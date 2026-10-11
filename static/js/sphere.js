/* Infosphere shared behaviour (every page loads this after sphere.css).

   Sphere.theme      light/dark toggle, remembered, follows the OS until chosen
   Sphere.Flap       split-flap text tiles (header clock, status, destination)
   Sphere.clock()    live flap clock + date + weather in the ink header
   Sphere.kinetic()  letters rise into place (destination titles, headings)
   Sphere.swap()     crossfade an element's text (language switches)
   Sphere.reveal()   scroll/entrance reveals for [data-reveal]
   plus: pointer spotlight + lit card edges (fine pointers only), button
   ripples, magnetic buttons, and the feedback tab + dialog.

   Everything checks prefers-reduced-motion and degrades to plain updates. */
(function (global) {
  'use strict';

  const root = document.documentElement;
  const mq = q => (global.matchMedia ? global.matchMedia(q) : { matches: false, addEventListener() {} });
  const reduceMQ = mq('(prefers-reduced-motion: reduce)');
  const reduced = () => reduceMQ.matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  const lang = () => (root.lang || 'id').slice(0, 2);

  /* ── Theme ──────────────────────────────────────────────────────────── */
  const darkMQ = mq('(prefers-color-scheme: dark)');
  const theme = {
    current() { return root.getAttribute('data-theme') || (darkMQ.matches ? 'dark' : 'light'); },
    set(t) {
      root.setAttribute('data-theme', t);
      store.set('sphere-theme', t);
      this.sync();
    },
    toggle() { this.set(this.current() === 'dark' ? 'light' : 'dark'); },
    sync() {
      const dark = this.current() === 'dark';
      root.classList.toggle('is-dark', dark);
      document.querySelectorAll('[data-theme-toggle]').forEach(b => {
        b.setAttribute('aria-pressed', dark ? 'true' : 'false');
        const L = THEME_TEXT[lang()] || THEME_TEXT.id;
        b.setAttribute('aria-label', dark ? L.toLight : L.toDark);
        b.title = b.getAttribute('aria-label');
      });
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = dark ? '#070b14' : '#0e1626';
      document.dispatchEvent(new CustomEvent('sphere:theme', { detail: { dark } }));
    },
  };
  const THEME_TEXT = {
    id: { toDark: 'Ganti ke mode gelap', toLight: 'Ganti ke mode terang' },
    en: { toDark: 'Switch to dark mode', toLight: 'Switch to light mode' },
    zh: { toDark: '切换到深色模式', toLight: '切换到浅色模式' },
  };
  darkMQ.addEventListener && darkMQ.addEventListener('change', () => { if (!store.get('sphere-theme')) theme.sync(); });

  /* ── Split-flap ─────────────────────────────────────────────────────── */
  const FLAP_GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  const FLAP_TILT = [{ transform: 'rotateX(0)' }, { transform: 'rotateX(-85deg)', opacity: 0.55, offset: 0.5 }, { transform: 'rotateX(0)' }];
  const FLAP_TIMING = { duration: 70, easing: 'cubic-bezier(0.77, 0, 0.175, 1)' };
  class Flap {
    /** el: container; opts.length pads/truncates to a fixed tile count */
    constructor(el, opts = {}) {
      this.el = el;
      this.length = opts.length || 0;
      this.upper = opts.upper !== false;
      this.cells = [];
      this.timers = [];
      el.classList.add('flap');
      el.textContent = '';
      // screen readers get the plain text; the tiles are decoration
      this.sr = document.createElement('span');
      this.sr.className = 'sr-only';
      el.appendChild(this.sr);
      this.value = '';
      if (opts.text != null) this.set(opts.text, { instant: true });
    }
    _chars(text) {
      let s = String(text == null ? '' : text);
      if (this.upper) s = s.toLocaleUpperCase();
      let chars = Array.from(s);
      if (this.length) chars = chars.slice(0, this.length).concat(Array(Math.max(0, this.length - chars.length)).fill(' '));
      return chars;
    }
    set(text, { instant = false } = {}) {
      const chars = this._chars(text);
      const joined = chars.join('');
      if (joined === this.value && this.cells.length === chars.length) return;
      this.value = joined;
      this.timers.forEach(clearTimeout);
      this.timers = [];
      this.sr.textContent = String(text == null ? '' : text).trim();
      // grow / shrink the row
      while (this.cells.length < chars.length) {
        const c = document.createElement('span');
        c.className = 'flap-cell';
        c.setAttribute('aria-hidden', 'true');
        const s = document.createElement('span');
        c.appendChild(s);
        this.el.appendChild(c);
        this.cells.push(c);
      }
      while (this.cells.length > chars.length) this.cells.pop().remove();
      this.el.style.setProperty('--n', chars.length);
      const animate = !instant && !reduced();
      chars.forEach((ch, i) => {
        const cell = this.cells[i];
        const span = cell.firstChild;
        cell.classList.toggle('space', ch === ' ');
        if (span.textContent === ch) return;
        if (!animate || ch === ' ') { span.textContent = ch === ' ' ? '' : ch; return; }
        // a few random glyphs, then the real one; staggered left to right
        const steps = 2 + ((i * 7) % 3);
        const start = i * 28;
        for (let k = 0; k <= steps; k++) {
          this.timers.push(setTimeout(() => {
            const g = k === steps ? ch : (/[㐀-鿿]/.test(ch) ? ch : FLAP_GLYPHS[(Math.random() * FLAP_GLYPHS.length) | 0]);
            span.textContent = g;
            if (span.animate) span.animate(FLAP_TILT, FLAP_TIMING);
          }, start + k * 70));
        }
      });
    }
  }

  /* ── Clock + date + weather in the header ──────────────────────────── */
  const LOCALE = { id: 'id-ID', en: 'en-GB', zh: 'zh-CN' };
  const WX = {
    id: { clear: 'Cerah', cloud: 'Berawan', rain: 'Hujan', storm: 'Badai', fog: 'Berkabut' },
    en: { clear: 'Clear', cloud: 'Cloudy', rain: 'Rain', storm: 'Storm', fog: 'Fog' },
    zh: { clear: '晴', cloud: '多云', rain: '雨', storm: '雷暴', fog: '雾' },
  };
  const wxKind = code => (code == null ? null : code <= 1 ? 'clear' : code <= 3 ? 'cloud' : code <= 48 ? 'fog' : code >= 95 ? 'storm' : 'rain');
  let wxData = null;

  function clock() {
    const timeEl = document.querySelector('[data-clock]');
    const dateEl = document.querySelector('[data-date]');
    if (!timeEl && !dateEl) return;
    const flap = timeEl && !timeEl.hasAttribute('data-plain') ? new Flap(timeEl, { length: 5 }) : null;
    let last = '';
    const tick = () => {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const t = `${hh}:${mm}`;
      if (t !== last) { if (flap) flap.set(t, { instant: !last }); else if (timeEl) timeEl.textContent = t; last = t; }
      if (dateEl) dateEl.textContent = now.toLocaleDateString(LOCALE[lang()] || 'id-ID', { weekday: 'long', day: 'numeric', month: 'long' });
    };
    tick();
    setInterval(tick, 1000);
    document.addEventListener('sphere:lang', () => { tick(); renderWeather(); });
    weather();
  }
  function renderWeather() {
    const el = document.querySelector('[data-weather]');
    if (!el) return;
    if (!wxData || wxData.temp_c == null) { el.hidden = true; return; }
    const kind = wxKind(wxData.code);
    const word = kind ? (WX[lang()] || WX.id)[kind] : '';
    el.querySelector('[data-weather-text]').textContent = `${wxData.temp_c}°C${word ? ' · ' + word : ''}`;
    el.hidden = false;
  }
  async function weather() {
    try {
      const r = await fetch('/api/weather', { cache: 'no-store' });
      wxData = r.ok ? await r.json() : null;
    } catch (e) { wxData = null; }
    renderWeather();
    setTimeout(weather, 15 * 60 * 1000);
  }

  /* ── Kinetic text: wrap words + letters, letters rise in sequence ──── */
  function kinetic(el, text) {
    el.textContent = '';
    el.classList.add('kinetic');
    el.setAttribute('aria-label', text);
    let k = 0;
    String(text).split(/(\s+)/).forEach(part => {
      if (/^\s+$/.test(part)) { el.appendChild(document.createTextNode(' ')); return; }
      if (!part) return;
      const w = document.createElement('span');
      w.className = 'kw';
      w.setAttribute('aria-hidden', 'true');
      Array.from(part).forEach(ch => {
        const c = document.createElement('span');
        c.className = 'kc';
        c.style.setProperty('--k', k++);
        c.textContent = ch;
        w.appendChild(c);
      });
      el.appendChild(w);
    });
  }

  /* ── Crossfade an element's text (or run a callback mid-fade) ──────── */
  function swap(el, textOrFn) {
    if (!el) return;
    const apply = () => (typeof textOrFn === 'function' ? textOrFn(el) : (el.textContent = textOrFn));
    if (reduced()) { apply(); return; }
    el.classList.add('swap', 'swap-out');
    setTimeout(() => { apply(); requestAnimationFrame(() => el.classList.remove('swap-out')); }, 160);
  }

  /* ── Reveals ───────────────────────────────────────────────────────── */
  let io = null;
  function reveal(scope = document) {
    const els = scope.querySelectorAll('[data-reveal]:not(.is-in)');
    if (!('IntersectionObserver' in global) || reduced()) { els.forEach(e => e.classList.add('is-in')); return; }
    io = io || new IntersectionObserver(entries => {
      entries.forEach(en => { if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    els.forEach(e => io.observe(e));
  }

  /* ── Pointer spotlight + magnetic buttons (fine pointers only) ─────── */
  function pointerFx() {
    const fine = mq('(pointer: fine)');
    if (!fine.matches || reduced()) return;
    const spot = document.createElement('div');
    spot.className = 'spot';
    spot.setAttribute('aria-hidden', 'true');
    document.body.appendChild(spot);
    // only these elements read --mx/--my; setting them on <html> would
    // restyle the whole document on every frame
    const targets = [...document.querySelectorAll('.lit')];
    let x = 0, y = 0, raf = 0;
    const paint = () => {
      raf = 0;
      spot.style.transform = `translate3d(${x - 520}px, ${y - 520}px, 0)`;   // compositor only
      targets.forEach(el => { el.style.setProperty('--mx', x + 'px'); el.style.setProperty('--my', y + 'px'); });
    };
    document.addEventListener('pointermove', e => {
      if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
      x = e.clientX; y = e.clientY;
      root.classList.add('has-spot');
      if (!raf) raf = requestAnimationFrame(paint);
    }, { passive: true });
    document.addEventListener('pointerleave', () => root.classList.remove('has-spot'));
    root.addEventListener('mouseleave', () => root.classList.remove('has-spot'));

    // magnetic: the element leans a few px toward the pointer
    document.querySelectorAll('[data-magnetic]').forEach(el => {
      const strength = Number(el.dataset.magnetic) || 6;
      el.addEventListener('pointermove', e => {
        const r = el.getBoundingClientRect();
        const dx = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
        const dy = (e.clientY - (r.top + r.height / 2)) / (r.height / 2);
        el.style.translate = `${(dx * strength).toFixed(1)}px ${(dy * strength).toFixed(1)}px`;
      });
      el.addEventListener('pointerleave', () => { el.style.translate = ''; });
      el.style.transition += ', translate .35s var(--ease-out)';
    });
  }

  /* ── Ripple on press ───────────────────────────────────────────────── */
  function ripples() {
    document.addEventListener('pointerdown', e => {
      if (reduced() || root.dataset.sphereRipple === 'off') return;   // pages with their own ripple
      const el = e.target.closest('.btn, .chip, .seg button, [data-ripple]');
      if (!el || el.disabled) return;
      const r = el.getBoundingClientRect();
      const s = document.createElement('span');
      s.className = 'ripple';
      s.style.left = (e.clientX - r.left) + 'px';
      s.style.top = (e.clientY - r.top) + 'px';
      s.style.setProperty('--rs', Math.ceil(Math.hypot(r.width, r.height) / 6));
      el.appendChild(s);
      setTimeout(() => s.remove(), 600);
    }, { passive: true });
  }

  /* ── Segmented switch: slide the pill to the pressed option ─────────── */
  function segSync(seg) {
    const btns = [...seg.querySelectorAll('button')];
    const i = Math.max(0, btns.findIndex(b => b.getAttribute('aria-pressed') === 'true'));
    seg.style.setProperty('--n', btns.length);
    seg.style.setProperty('--i', i);
  }

  /* ── Feedback dialog ───────────────────────────────────────────────── */
  const FB_TEXT = {
    id: { title: 'Bagaimana pengalaman Anda?', sub: 'Beri nilai, lalu ceritakan bila ada yang perlu kami perbaiki.', rate: 'Nilai', star: n => `${n} dari 5`,
          comment: 'Komentar (opsional)', ph: 'Apa yang bisa lebih baik?', send: 'Kirim', cancel: 'Batal', close: 'Tutup', sending: 'Mengirim…',
          need: 'Pilih nilai atau tulis komentar dulu.', ok: 'Terima kasih. Masukan Anda sudah kami terima.', fail: 'Gagal mengirim. Periksa koneksi lalu coba lagi.',
          busy: 'Terlalu banyak kiriman dari perangkat ini. Coba lagi beberapa menit lagi.' },
    en: { title: 'How was your visit?', sub: 'Rate it, then tell us anything we should fix.', rate: 'Rating', star: n => `${n} of 5`,
          comment: 'Comment (optional)', ph: 'What could be better?', send: 'Send', cancel: 'Cancel', close: 'Close', sending: 'Sending…',
          need: 'Pick a rating or write a comment first.', ok: 'Thank you. We received your feedback.', fail: "Couldn't send. Check the connection and try again.",
          busy: 'Too many messages from this device. Try again in a few minutes.' },
    zh: { title: '您的体验如何？', sub: '请评分，并告诉我们需要改进的地方。', rate: '评分', star: n => `${n} 星（共 5 星）`,
          comment: '留言（可选）', ph: '哪里可以做得更好？', send: '发送', cancel: '取消', close: '关闭', sending: '正在发送…',
          need: '请先选择评分或填写留言。', ok: '谢谢，我们已收到您的反馈。', fail: '发送失败，请检查网络后重试。',
          busy: '此设备提交次数过多，请几分钟后再试。' },
  };
  const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.3L12 17.1 6.3 20.2l1.2-6.3L2.8 9.5l6.4-.8z"/></svg>';

  /* A chosen rating: the stars up to it hop one after another. */
  function starHop() {
    document.addEventListener('change', e => {
      const input = e.target.closest && e.target.closest('.fb-stars input[type="radio"]');
      if (!input) return;
      const labels = [...input.closest('.fb-stars').querySelectorAll('label')];
      const upTo = Number(input.value) || 0;
      labels.forEach((l, i) => {
        l.classList.remove('hop');
        if (i >= upTo) return;
        l.style.setProperty('--k', i);
        void l.offsetWidth;                       // restart the animation on a repeat pick
        l.classList.add('hop');
        l.addEventListener('animationend', () => l.classList.remove('hop'), { once: true });
      });
    });
  }

  function feedback() {
    const openers = document.querySelectorAll('[data-feedback-open]');
    if (!openers.length) return;
    let dlg = null;
    const build = () => {
      const T = FB_TEXT[lang()] || FB_TEXT.id;
      dlg = document.createElement('dialog');
      dlg.className = 'fb-dialog';
      dlg.setAttribute('aria-labelledby', 'fb-title');
      const stars = [1, 2, 3, 4, 5].map(n =>
        `<input type="radio" name="rating" id="fb-r${n}" value="${n}"><label for="fb-r${n}" title="${T.star(n)}"><span class="sr-only">${T.star(n)}</span>${STAR}</label>`).join('');
      dlg.innerHTML = `
        <form method="dialog" novalidate>
          <div><h2 id="fb-title">${T.title}</h2><p class="fb-sub">${T.sub}</p></div>
          <fieldset class="fb-stars"><legend class="label">${T.rate}</legend>${stars}</fieldset>
          <div class="fb-field"><label class="label" for="fb-comment">${T.comment}</label>
            <textarea id="fb-comment" name="message" maxlength="1000" placeholder="${T.ph}"></textarea></div>
          <input class="fb-hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
          <p class="fb-msg" role="status" aria-live="polite"></p>
          <div class="fb-actions">
            <button type="button" class="btn btn-quiet" data-fb-cancel>${T.cancel}</button>
            <button type="submit" class="btn btn-amber" data-fb-send>${T.send}</button>
          </div>
        </form>`;
      document.body.appendChild(dlg);
      const form = dlg.querySelector('form');
      const labels = [...dlg.querySelectorAll('.fb-stars label')];
      const paint = v => labels.forEach((l, i) => l.classList.toggle('on', i < v));
      dlg.querySelectorAll('.fb-stars input').forEach(inp => inp.addEventListener('change', () => paint(Number(inp.value))));
      labels.forEach((l, i) => {
        l.addEventListener('pointerenter', () => paint(i + 1));
        l.addEventListener('pointerleave', () => paint(Number((form.rating && form.rating.value) || 0)));
      });
      dlg.querySelector('[data-fb-cancel]').addEventListener('click', () => dlg.close());
      dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });   // backdrop
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const T2 = FB_TEXT[lang()] || FB_TEXT.id;
        const msg = dlg.querySelector('.fb-msg');
        const rating = form.rating.value ? Number(form.rating.value) : null;
        const message = form.message.value.trim();
        if (!rating && message.length < 3) { msg.className = 'fb-msg err'; msg.textContent = T2.need; return; }
        const send = dlg.querySelector('[data-fb-send]');
        send.disabled = true; send.textContent = T2.sending;
        const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
        const category = rating == null ? 'Other' : rating >= 4 ? 'Compliment' : rating <= 2 ? 'Complaint' : 'Suggestion';
        try {
          const r = await fetch('/feedback/submit', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify({ rating, message, category, page: location.pathname, anonymous: true, website: form.website.value }),
          });
          if (r.status === 429) throw Object.assign(new Error('busy'), { busy: true });
          const data = await r.json().catch(() => ({}));
          if (!r.ok || data.status !== 'ok') throw new Error(data.message || 'failed');
          msg.className = 'fb-msg ok'; msg.textContent = T2.ok;
          form.reset(); paint(0);
          setTimeout(() => dlg.close(), 1600);
        } catch (err) {
          msg.className = 'fb-msg err';
          msg.textContent = err.busy ? T2.busy : (err.message && err.message !== 'failed' && err.message !== 'Failed to fetch' ? err.message : T2.fail);
        } finally {
          send.disabled = false; send.textContent = T2.send;
        }
      });
    };
    openers.forEach(b => b.addEventListener('click', e => {
      e.preventDefault();
      if (!dlg || dlg.dataset.lang !== lang()) { if (dlg) dlg.remove(); build(); dlg.dataset.lang = lang(); }
      dlg.querySelector('.fb-msg').textContent = '';
      if (dlg.showModal) dlg.showModal(); else location.href = '/feedback';
      const first = dlg.querySelector('#fb-r5');
      if (first) setTimeout(() => dlg.querySelector('.fb-stars input').focus(), 30);
    }));
  }

  /* ── Character art: the PNG-less JPEGs have black backgrounds; key them
     out once into a canvas (at most maxW px wide, so it stays cheap) ──── */
  function keyedImage(canvas, src, maxW = 800, threshold = 40) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => {
        const k = Math.min(1, maxW / img.naturalWidth);
        canvas.width = Math.round(img.naturalWidth * k);
        canvas.height = Math.round(img.naturalHeight * k);
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const im = ctx.getImageData(0, 0, canvas.width, canvas.height), d = im.data;
        for (let i = 0; i < d.length; i += 4) {
          const br = Math.max(d[i], d[i + 1], d[i + 2]);
          if (br < threshold) d[i + 3] = 0;
          else if (br < threshold * 2) d[i + 3] = Math.round(255 * (br - threshold) / threshold);
        }
        ctx.putImageData(im, 0, 0);
        resolve(canvas);
      };
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  /* ── Live numbers from /api/facts on [data-fact] elements, as flaps
     that roll in when they scroll into view ─────────────────────────── */
  async function facts() {
    const els = document.querySelectorAll('[data-fact]');
    if (!els.length) return;
    let data = {};
    try { const r = await fetch('/api/facts'); if (r.ok) data = await r.json(); } catch (e) { /* offline */ }
    els.forEach(el => {
      const v = data[el.dataset.fact];
      const wrap = el.closest('[data-fact-wrap]');
      if (v == null) { if (wrap) wrap.hidden = true; return; }
      const f = new Flap(el, { text: ''.padStart(String(v).length, ' ') });
      const show = () => f.set(String(v));
      if (!('IntersectionObserver' in global) || reduced()) { show(); return; }
      const o = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { show(); o.disconnect(); } }, { threshold: 0.4 });
      o.observe(el);
    });
  }

  /* ── Boot ──────────────────────────────────────────────────────────── */
  function boot() {
    theme.sync();
    document.querySelectorAll('[data-theme-toggle]').forEach(b => b.addEventListener('click', () => theme.toggle()));
    document.querySelectorAll('.seg').forEach(segSync);
    ripples();
    pointerFx();
    feedback();
    starHop();
    clock();
    reveal();
    facts();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  global.Sphere = { theme, Flap, kinetic, swap, reveal, segSync, reduced, lang, store, keyedImage };
})(window);
