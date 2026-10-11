/* Language switch flourish: LangFx.play('id' | 'en' | 'zh', { within }).
   Styles and the three scenes are described in static/css/lang-fx.css.
   It plays inside `within` (the language button that was pressed) and the
   button is back to normal afterwards; without it, over the whole page. A new switch replaces the scene still playing. */
(function (global) {
  'use strict';

  const HOLD_MS = 520, OUT_MS = 460;
  const TEXT = {
    id: ['Halo!', 'Bahasa Indonesia'],
    en: ['Hello!', 'English'],
    zh: ['你好！', '中文'],
  };

  // Union Jack, each arm drawn from the centre outward (pathLength=1 for the dash trick).
  const arms = (d, stroke, w, clip) => d.map(p =>
    `<path class="lfx-x" pathLength="1" d="${p}" stroke="${stroke}" stroke-width="${w}"${clip ? ' clip-path="url(#lfx-uj-clip)"' : ''}/>`).join('');
  const DIAG = ['M30 15L0 0', 'M30 15L60 30', 'M30 15L60 0', 'M30 15L0 30'];
  const CROSS = ['M30 15V0', 'M30 15V30', 'M30 15H0', 'M30 15H60'];
  const FLAG = `<svg class="lfx-flag" viewBox="0 0 60 30" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <clipPath id="lfx-uj-clip"><path d="M30 15h30v15zv15h-30zh-30v-15zv-15h30z"/></clipPath>
      <rect width="60" height="30" fill="#012169"/>
      <g fill="none">${arms(DIAG, '#fff', 6)}${arms(DIAG, '#c8102e', 4, true)}${arms(CROSS, '#fff', 10)}${arms(CROSS, '#c8102e', 6)}</g>
    </svg>`;

  const LANTERN = `<svg viewBox="0 0 70 190" aria-hidden="true">
      <path d="M35 0v62" stroke="#f6ead2" stroke-width="1.6"/>
      <ellipse cx="35" cy="98" rx="34" ry="34" fill="#ff8a5c" opacity=".28"/>
      <rect x="23" y="60" width="24" height="9" rx="2" fill="#4a0b0f"/>
      <ellipse cx="35" cy="98" rx="28" ry="28" fill="#e5383b" stroke="#f6ead2" stroke-opacity=".75" stroke-width="1.5"/>
      <path d="M35 70c-12 7-12 49 0 56M35 70c12 7 12 49 0 56M35 70c-23 7-23 49 0 56M35 70c23 7 23 49 0 56" stroke="#a51d24" stroke-width="1.5" fill="none"/>
      <ellipse cx="26" cy="86" rx="5" ry="10" fill="#fff" opacity=".2"/>
      <rect x="23" y="125" width="24" height="9" rx="2" fill="#4a0b0f"/>
      <path d="M35 134v10" stroke="#f6ead2" stroke-width="1.6"/>
      <path d="M29 144h12l-2 40h-8z" fill="#f6ead2"/>
    </svg>`;

  const SCENE = {
    id: '<div class="lfx-half lfx-top"></div><div class="lfx-half lfx-bot"></div>',
    en: FLAG,
    zh: `<div class="lfx-gate"></div><div class="lfx-lantern l">${LANTERN}</div><div class="lfx-lantern r">${LANTERN}</div>`,
  };

  let current = null;

  function play(lang, opts = {}) {
    if (!TEXT[lang]) return;
    if (current) { clearTimeout(current.t1); clearTimeout(current.t2); current.el.remove(); current = null; }
    const host = opts.within || document.body;
    const el = document.createElement('div');
    const mini = !!opts.within && opts.within.offsetHeight < 90;
    el.className = `lang-fx lfx-${lang}` + (opts.within ? ' is-local' : '') + (mini ? ' is-mini' : '') +
      (mini && opts.within.offsetWidth < 64 ? ' is-tiny' : '');
    el.setAttribute('aria-hidden', 'true');
    // In a thin strip a cropped flag shows only its centre (the red cross), so squeeze the whole flag in.
    el.innerHTML = (mini ? SCENE[lang].replace('xMidYMid slice', 'none') : SCENE[lang]) + `<div class="lfx-card"><span class="lfx-word" lang="${lang}">${TEXT[lang][0]}</span><span class="lfx-sub">${TEXT[lang][1]}</span></div>`;
    if (opts.within && getComputedStyle(host).position === 'static') host.style.position = 'relative';
    host.appendChild(el);
    void el.offsetWidth;                          // commit the start state so the transitions run
    el.classList.add('is-in');
    const state = { el };
    state.t1 = setTimeout(() => { el.classList.remove('is-in'); el.classList.add('is-out'); }, HOLD_MS + 380);
    state.t2 = setTimeout(() => { el.remove(); if (current === state) current = null; }, HOLD_MS + 380 + OUT_MS);
    current = state;
  }

  global.LangFx = { play };
})(window);
