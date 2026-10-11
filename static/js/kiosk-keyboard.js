/* On-screen keyboard for the lobby touch screen.

   Only active on a large touch screen (coarse pointer, no hover, >= 1024px
   wide) or when the page was opened with ?kiosk=1 (remembered for the
   session; ?kiosk=0 turns it off). Never on phones or mouse-driven desktops.

   Inputs opt in with data-osk. While active they get inputmode="none" so the
   operating system's own touch keyboard stays closed, and ours slides up
   from the bottom when one of them is focused. It types at the caret and
   fires real 'input' / 'keydown' events, so the page's handlers just work. */
(function (global) {
  'use strict';

  const params = new URLSearchParams(location.search);
  try {
    if (params.get('kiosk') === '1') sessionStorage.setItem('sphere-kiosk', '1');
    if (params.get('kiosk') === '0') sessionStorage.removeItem('sphere-kiosk');
  } catch (e) { /* storage blocked */ }
  let forced = false;
  try { forced = sessionStorage.getItem('sphere-kiosk') === '1'; } catch (e) { /* ignore */ }
  const touchKiosk = global.matchMedia && matchMedia('(pointer: coarse) and (hover: none) and (min-width: 1024px)').matches;
  if (!forced && !touchKiosk) { global.KioskKeyboard = { active: false }; return; }

  const TEXT = {
    id: { label: 'Papan ketik layar', space: 'spasi', enter: 'Cari', close: 'Tutup papan ketik', back: 'Hapus', zh: 'Untuk 中文, gunakan tombol suara' },
    en: { label: 'On-screen keyboard', space: 'space', enter: 'Go', close: 'Hide keyboard', back: 'Delete', zh: 'For 中文, use the voice button' },
    zh: { label: '屏幕键盘', space: '空格', enter: '确定', close: '隐藏键盘', back: '删除', zh: '中文请使用语音按钮' },
  };
  const ROWS = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', '?'],
    ['z', 'x', 'c', 'v', 'b', 'n', 'm', '-', '.', 'BACK'],
  ];
  const lang = () => (document.documentElement.lang || 'id').slice(0, 2);
  const T = () => TEXT[lang()] || TEXT.id;

  const kb = document.createElement('div');
  kb.className = 'osk';
  kb.setAttribute('role', 'group');
  kb.hidden = true;
  document.body.appendChild(kb);
  let target = null;

  const ICON_BACK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 5H9l-6 7 6 7h12z"/><path d="M17 9l-6 6M11 9l6 6"/></svg>';
  const ICON_DOWN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';

  function render() {
    const t = T();
    kb.setAttribute('aria-label', t.label);
    kb.innerHTML = '';
    const head = document.createElement('div');
    head.className = 'osk-head';
    const note = document.createElement('span');
    note.className = 'osk-note';
    note.textContent = lang() === 'zh' ? t.zh : '';
    const close = document.createElement('button');
    close.type = 'button'; close.className = 'osk-close'; close.dataset.k = 'CLOSE';
    close.setAttribute('aria-label', t.close); close.innerHTML = ICON_DOWN;
    head.append(note, close);
    kb.appendChild(head);
    ROWS.forEach(row => {
      const r = document.createElement('div');
      r.className = 'osk-row';
      row.forEach(k => {
        const b = document.createElement('button');
        b.type = 'button'; b.dataset.k = k;
        if (k === 'BACK') { b.className = 'osk-key osk-wide'; b.setAttribute('aria-label', t.back); b.innerHTML = ICON_BACK; }
        else { b.className = 'osk-key'; b.textContent = k; }
        r.appendChild(b);
      });
      kb.appendChild(r);
    });
    const last = document.createElement('div');
    last.className = 'osk-row';
    last.innerHTML = `<button type="button" class="osk-key osk-space" data-k=" ">${t.space}</button>`
                   + `<button type="button" class="osk-key osk-enter" data-k="ENTER">${t.enter}</button>`;
    kb.appendChild(last);
  }

  function type(k) {
    if (!target) return;
    const el = target;
    if (k === 'ENTER') {
      el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
      hide();
      return;
    }
    const s = el.selectionStart ?? el.value.length, e = el.selectionEnd ?? el.value.length;
    if (k === 'BACK') {
      if (s === e && s > 0) el.setRangeText('', s - 1, e, 'end');
      else el.setRangeText('', s, e, 'end');
    } else {
      if (el.maxLength > 0 && el.value.length >= el.maxLength) return;
      el.setRangeText(k, s, e, 'end');
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // pointerdown + preventDefault keeps focus (and the caret) in the input
  let repeat = null;
  kb.addEventListener('pointerdown', e => {
    const b = e.target.closest('button[data-k]');
    if (!b) return;
    e.preventDefault();
    const k = b.dataset.k;
    b.classList.add('down');
    if (k === 'CLOSE') { hide(); return; }
    type(k);
    if (k === 'BACK') repeat = setTimeout(function again() { type('BACK'); repeat = setTimeout(again, 70); }, 450);
  });
  const release = () => { clearTimeout(repeat); repeat = null; kb.querySelectorAll('.down').forEach(b => b.classList.remove('down')); };
  kb.addEventListener('pointerup', release);
  kb.addEventListener('pointerleave', release);
  kb.addEventListener('pointercancel', release);

  function show(el) {
    target = el;
    if (kb.hidden) { render(); kb.hidden = false; }
    requestAnimationFrame(() => {
      document.body.classList.add('osk-open');
      document.documentElement.style.setProperty('--osk-h', kb.offsetHeight + 'px');
    });
  }
  function hide() {
    document.body.classList.remove('osk-open');
    document.documentElement.style.setProperty('--osk-h', '0px');
    const done = () => { if (!document.body.classList.contains('osk-open')) kb.hidden = true; };
    setTimeout(done, 320);
    target = null;
  }

  function wire(el) {
    if (el.dataset.oskWired) return;
    el.dataset.oskWired = '1';
    el.setAttribute('inputmode', 'none');
    el.addEventListener('focus', () => show(el));
    el.addEventListener('blur', () => setTimeout(() => {
      if (document.activeElement && document.activeElement.matches('[data-osk]')) return;
      hide();
    }, 120));
  }
  document.querySelectorAll('[data-osk]').forEach(wire);
  document.addEventListener('sphere:lang', () => { if (!kb.hidden) render(); });
  document.documentElement.classList.add('has-osk');

  global.KioskKeyboard = { active: true, wire, show, hide };
})(window);
