/* Web portal scroll choreography (loaded after GSAP + ScrollTrigger).

   - the sky: three depths of clouds rise at different speeds as you scroll,
     so the page feels like climbing through them
   - cloud banks drift up and sideways as each section edge passes
   - the hero tilts back and fades as you leave it
   - campus photos wipe open from the bottom
   - feature squares lean toward the pointer (mouse/trackpad only)
   - a thin progress bar tracks the whole page

   Everything is transform/opacity/clip-path and scrubbed by ScrollTrigger.
   prefers-reduced-motion turns all of it off (clouds stay where they are). */
(function () {
  'use strict';
  if (!window.gsap || !window.ScrollTrigger) return;
  gsap.registerPlugin(ScrollTrigger);
  const mm = gsap.matchMedia();

  mm.add('(prefers-reduced-motion: no-preference)', () => {
    // progress bar
    gsap.to('#scrollProgress', {
      scaleX: 1, ease: 'none',
      scrollTrigger: { trigger: document.documentElement, start: 'top top', end: 'bottom bottom', scrub: 0.2 },
    });

    // sky depths: far clouds barely move, near clouds rush past
    const depth = { far: -12, mid: -26, near: -48 };
    document.querySelectorAll('.sky-layer').forEach(layer => {
      gsap.to(layer, {
        yPercent: depth[layer.dataset.depth] || -20, ease: 'none',
        scrollTrigger: { trigger: document.documentElement, start: 'top top', end: 'bottom bottom', scrub: 0.6 },
      });
    });

    // cloud banks: you pass through them at each section edge
    gsap.utils.toArray('.cloud-bank-inner').forEach((bank, i) => {
      gsap.fromTo(bank,
        { yPercent: 45, xPercent: i % 2 ? 3 : -3, opacity: 0.35 },
        { yPercent: -60, xPercent: i % 2 ? -3 : 3, opacity: 1, ease: 'none',
          scrollTrigger: { trigger: bank.parentElement, start: 'top bottom', end: 'top top', scrub: 0.8 } });
    });

    // hero leaves with depth: copy rises and fades, the carousel tips back
    gsap.timeline({ scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 0.5 } })
      .to('.hero-copy', { yPercent: -18, autoAlpha: 0.15, ease: 'none' }, 0)
      .to('.carousel', { scale: 0.9, rotationX: 10, yPercent: 8, transformOrigin: '50% 100%', ease: 'none' }, 0);

    // campus photos wipe open from the bottom edge
    gsap.utils.toArray('.campus-img').forEach((fig, i) => {
      gsap.fromTo(fig, { clipPath: 'inset(100% 0% 0% 0% round 18px)' }, {
        clipPath: 'inset(0% 0% 0% 0% round 18px)', duration: 1.1, delay: i * 0.08, ease: 'power3.out',
        scrollTrigger: { trigger: fig, start: 'top 88%', once: true },
      });
    });
  });

  // feature squares lean toward the pointer (fine pointers only)
  mm.add('(prefers-reduced-motion: no-preference) and (pointer: fine)', () => {
    const cleanups = [];
    document.querySelectorAll('.feature').forEach(card => {
      const rx = gsap.quickTo(card, 'rotationX', { duration: 0.4, ease: 'power3' });
      const ry = gsap.quickTo(card, 'rotationY', { duration: 0.4, ease: 'power3' });
      const move = e => {
        const r = card.getBoundingClientRect();
        ry(((e.clientX - r.left) / r.width - 0.5) * 12);
        rx(-((e.clientY - r.top) / r.height - 0.5) * 12);
      };
      const leave = () => { rx(0); ry(0); };
      card.addEventListener('pointermove', move);
      card.addEventListener('pointerleave', leave);
      cleanups.push(() => { card.removeEventListener('pointermove', move); card.removeEventListener('pointerleave', leave); });
    });
    return () => cleanups.forEach(f => f());
  });
})();

/* ── "How it works": an arrow lobs from 01 to 02 to 03 as you scroll.
      Each number lights up the moment the arrow lands on it. ───────────── */
(function lobbingArrow() {
  'use strict';
  const wrap = document.querySelector('.product .steps');
  if (!wrap) return;
  const steps = [...wrap.querySelectorAll('.step')];
  const nums = steps.map(s => s.querySelector('.step-num'));
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce || !window.gsap || !window.ScrollTrigger || window.matchMedia('(max-width: 720px)').matches) {
    steps.forEach(s => s.classList.add('lit'));
    return;
  }
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'lob');
  svg.setAttribute('aria-hidden', 'true');
  const ghost = document.createElementNS(NS, 'path'); ghost.setAttribute('class', 'lob-ghost');
  const trail = document.createElementNS(NS, 'path'); trail.setAttribute('class', 'lob-trail');
  const arrow = document.createElementNS(NS, 'g'); arrow.setAttribute('class', 'lob-arrow');
  const head = document.createElementNS(NS, 'path'); head.setAttribute('d', 'M-2 -7 L14 0 L-2 7 L3 0 Z');
  arrow.appendChild(head);
  svg.append(ghost, trail, arrow);
  wrap.appendChild(svg);

  let total = 0, landings = [], progress = 0;
  const measure = d => { const t = document.createElementNS(NS, 'path'); t.setAttribute('d', d); svg.appendChild(t); const l = t.getTotalLength(); t.remove(); return l; };

  function build() {
    const box = wrap.getBoundingClientRect();
    svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
    const pts = nums.map(n => { const r = n.getBoundingClientRect(); return [r.left - box.left + r.width / 2, r.top - box.top + 4]; });
    let prev = [pts[0][0] - 90, pts[0][1] + 6];
    let d = `M${prev[0].toFixed(1)} ${prev[1].toFixed(1)}`;
    landings = [];
    pts.forEach((p, i) => {
      // the short run-up into 01 is a low hop; the long hops between numbers arc high
      const lift = i === 0 ? 26 : Math.max(70, Math.abs(p[0] - prev[0]) * 0.22);
      const cx = (prev[0] + p[0]) / 2, cy = Math.min(prev[1], p[1]) - lift;
      d += ` Q${cx.toFixed(1)} ${cy.toFixed(1)} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`;
      landings.push(measure(d));
      prev = p;
    });
    ghost.setAttribute('d', d);
    trail.setAttribute('d', d);
    total = trail.getTotalLength();
    trail.style.strokeDasharray = `${total} ${total}`;
    render(progress);
  }

  function render(p) {
    progress = p;
    const L = Math.max(0.01, p * total);
    const pt = trail.getPointAtLength(L);
    const back = trail.getPointAtLength(Math.max(0, L - 2));
    const ang = Math.atan2(pt.y - back.y, pt.x - back.x) * 180 / Math.PI;
    arrow.setAttribute('transform', `translate(${pt.x.toFixed(1)} ${pt.y.toFixed(1)}) rotate(${ang.toFixed(1)})`);
    trail.style.strokeDashoffset = (total - L).toFixed(1);
    arrow.style.opacity = p > 0.995 ? 0 : 1;
    steps.forEach((s, i) => s.classList.toggle('lit', L >= landings[i] - 3));
  }

  build();
  const proxy = { p: 0 };
  gsap.to(proxy, {
    p: 1, ease: 'none',
    scrollTrigger: { trigger: wrap, start: 'top 82%', end: 'bottom 40%', scrub: 0.6 },
    onUpdate: () => render(proxy.p),
  });
  ScrollTrigger.addEventListener('refresh', build);
})();

/* ── Magnifier over the product heading: put the glass's three stops on
   the words' centres (layout-dependent, so re-measured on resize). ──── */
(function wordLens() {
  'use strict';
  const title = document.querySelector('.mg-title');
  const lens = title && title.querySelector('.mg-lens');
  if (!lens) return;
  const words = title.querySelectorAll('.mg-word');
  function measure() {
    // Layout boxes (offset*), so a word that is mid-grow doesn't skew the stop.
    const half = parseFloat(getComputedStyle(title).fontSize) * 1.9 * 0.4;   // lens is 1.9em; circle centre at 40%
    words.forEach((w, i) => {
      title.style.setProperty(`--x${i + 1}`, `${Math.round(w.offsetLeft + w.offsetWidth / 2 - half)}px`);
      title.style.setProperty(`--y${i + 1}`, `${Math.round(w.offsetTop + w.offsetHeight / 2 - half)}px`);
    });
    title.classList.add('mg-ready');
  }
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(measure);
  if ('ResizeObserver' in window) new ResizeObserver(measure).observe(title);
})();

/* ── Performance: anything off screen stops animating ─────────────────── */
(function pauseOffscreen() {
  'use strict';
  if (!('IntersectionObserver' in window)) return;
  const targets = document.querySelectorAll('.features, .floaters, .cloud-bank, .feature-art, .story-stage, .stats, .proof, .carousel-wrap, .mg-title');
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    e.target.classList.toggle('fx-paused', !e.isIntersecting);
    e.target.querySelectorAll('svg').forEach(svg => {
      if (!svg.pauseAnimations) return;
      if (e.isIntersecting) svg.unpauseAnimations(); else svg.pauseAnimations();
    });
  }), { rootMargin: '120px 0px' });
  targets.forEach(t => io.observe(t));
})();
