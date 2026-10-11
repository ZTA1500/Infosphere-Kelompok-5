/* ═══════════════════════════════════════════════════════════════════════
   Shared constellation canvas — depth-layered particles connected by thin
   lines when close enough to read as a network ("a web that moves"), plus
   an optional set of slowly rotating "galaxy" rings as a brand nod to the
   Infosphere name. One implementation, reused wherever the site wants this
   living background (currently about.html and landing.html), each page
   tuning it through options rather than forking the canvas logic.

   Usage:
     const canvas = document.getElementById('myCanvas');
     initConstellation(canvas, { galaxy: true });
   ═══════════════════════════════════════════════════════════════════════ */
function initConstellation(canvas, opts) {
  const options = Object.assign({
    galaxy: false,
    layers: [
      { count: 24, size: [1, 1.6],   speed: 0.06, alpha: [.14, .26], connect: 90 },
      { count: 16, size: [1.6, 2.3], speed: 0.13, alpha: [.30, .46], connect: 120 },
      { count: 9,  size: [2.4, 3.2], speed: 0.22, alpha: [.55, .8],  connect: 150 },
    ],
    accent: [120, 184, 239],
    ink: [238, 243, 248],
    mouseRadius: 130,
    anchorY: 0.42,
  }, opts || {});

  const ctx = canvas.getContext('2d');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let w, h, dpr, particles = [];

  const rings = options.galaxy ? [
    { r: 0.16, n: 1,  speed: 0.00006,  dot: 3.2, alpha: .9  },
    { r: 0.24, n: 10, speed: -0.00010, dot: 2.2, alpha: .5  },
    { r: 0.33, n: 16, speed: 0.00007,  dot: 1.8, alpha: .34 },
    { r: 0.43, n: 22, speed: -0.00005, dot: 1.4, alpha: .2  },
  ] : [];

  function seed() {
    particles = [];
    options.layers.forEach((layer, li) => {
      for (let i = 0; i < layer.count; i++) {
        particles.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * layer.speed * dpr,
          vy: (Math.random() - 0.5) * layer.speed * dpr,
          r: (layer.size[0] + Math.random() * (layer.size[1] - layer.size[0])) * dpr,
          a: layer.alpha[0] + Math.random() * (layer.alpha[1] - layer.alpha[0]),
          layer: li,
          top: li === options.layers.length - 1,
          connect: layer.connect * dpr,
        });
      }
    });
  }

  function resize() {
    dpr = 1;   // a soft background: 1x is plenty and a quarter of the pixels
    w = canvas.width = window.innerWidth * dpr;
    h = canvas.height = window.innerHeight * dpr;
    canvas.style.width = window.innerWidth + 'px';
    canvas.style.height = window.innerHeight + 'px';
    seed();
  }
  resize();
  window.addEventListener('resize', resize);

  let scrollY = 0;
  window.addEventListener('scroll', () => { scrollY = window.scrollY; }, { passive: true });

  let mx = -9999, my = -9999, mxTarget = -9999, myTarget = -9999;
  window.addEventListener('pointermove', (e) => {
    mxTarget = e.clientX * dpr;
    myTarget = e.clientY * dpr;
  }, { passive: true });
  window.addEventListener('pointerleave', () => { mxTarget = -9999; myTarget = -9999; });
  const mouseRadiusPx = options.mouseRadius * dpr;

  const ACCENT = options.accent, INK = options.ink;

  function drawGalaxy(t) {
    const base = Math.min(w, h);
    const cx = w / 2;
    const cy = h * options.anchorY - scrollY * 0.05 * dpr;
    const drift = reduceMotion ? 0 : scrollY * 0.06 * dpr;

    rings.forEach((ring, ri) => {
      const radius = base * ring.r;
      const rot = reduceMotion ? 0 : t * ring.speed;
      for (let i = 0; i < ring.n; i++) {
        const a = (i / ring.n) * Math.PI * 2 + rot;
        const x = cx + Math.cos(a) * radius;
        const y = (cy - drift) + Math.sin(a) * radius * 0.72;
        const col = ri === 0 ? ACCENT : INK;
        ctx.beginPath();
        ctx.arc(x, y, ring.dot * dpr, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${ring.alpha})`;
        ctx.fill();
      }
      if (ri > 0) {
        ctx.beginPath();
        ctx.ellipse(cx, cy - drift, radius, radius * 0.72, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${INK[0]},${INK[1]},${INK[2]},${0.05 + ri * 0.015})`;
        ctx.lineWidth = 1 * dpr;
        ctx.stroke();
      }
    });
  }

  function drawFrame(t) {
    ctx.clearRect(0, 0, w, h);

    if (options.galaxy) drawGalaxy(t);

    const buckets = [[], [], [], [], []];
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      for (let j = i + 1; j < particles.length; j++) {
        const q = particles[j];
        const dx = p.x - q.x, dy = p.y - q.y;
        const maxDist = Math.min(p.connect, q.connect);
        if (Math.abs(dx) > maxDist || Math.abs(dy) > maxDist) continue;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < maxDist) buckets[Math.min(4, ((1 - dist / maxDist) * 5) | 0)].push(p.x, p.y, q.x, q.y);
      }
      if (mx > -1000) {
        const dx = p.x - mx, dy = p.y - my;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < mouseRadiusPx) {
          const lt = 1 - dist / mouseRadiusPx;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(mx, my);
          ctx.strokeStyle = `rgba(${ACCENT[0]},${ACCENT[1]},${ACCENT[2]},${lt * 0.35})`;
          ctx.lineWidth = 1 * dpr;
          ctx.stroke();
        }
      }
    }

    ctx.lineWidth = 1;
    buckets.forEach((seg, b) => {
      if (!seg.length) return;
      ctx.beginPath();
      for (let k = 0; k < seg.length; k += 4) { ctx.moveTo(seg[k], seg[k + 1]); ctx.lineTo(seg[k + 2], seg[k + 3]); }
      ctx.strokeStyle = `rgba(${INK[0]},${INK[1]},${INK[2]},${((b + 0.5) / 5) * 0.16})`;
      ctx.stroke();
    });

    particles.forEach((p) => {
      const col = p.top ? ACCENT : INK;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${col[0]},${col[1]},${col[2]},${p.a})`;
      ctx.fill();
    });
  }

  let last = 0;
  function step(t) {
    // off-screen (the page decides via isActive) or between 30fps ticks: skip the work
    if (t - last < 32 || (options.isActive && !options.isActive())) { if (!document.hidden) requestAnimationFrame(step); return; }
    last = t;
    mx += (mxTarget - mx) * 0.08;
    my += (myTarget - my) * 0.08;

    particles.forEach((p) => {
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < -20) p.x = w + 20; else if (p.x > w + 20) p.x = -20;
      if (p.y < -20) p.y = h + 20; else if (p.y > h + 20) p.y = -20;

      if (mx > -1000) {
        const dx = mx - p.x, dy = my - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < mouseRadiusPx && dist > 1) {
          const pull = (1 - dist / mouseRadiusPx) * 0.02 * (p.layer + 1);
          p.x += (dx / dist) * pull * mouseRadiusPx * 0.01;
          p.y += (dy / dist) * pull * mouseRadiusPx * 0.01;
        }
      }
    });

    drawFrame(t);
    if (!document.hidden) requestAnimationFrame(step);
  }

  if (reduceMotion) {
    drawFrame(0); // one static, fully-composed frame — no loop
  } else {
    requestAnimationFrame(step);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) requestAnimationFrame(step);
    });
  }
}
