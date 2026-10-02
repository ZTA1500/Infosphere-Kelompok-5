/* Pan & zoom for one element inside a viewport — no dependencies.

   - drag to pan (mouse, pen, touch) via Pointer Events
   - wheel / trackpad zoom anchored at the cursor
   - pinch to zoom, double-click / double-tap to zoom in
   - zoom clamped to [minZoom, maxZoom] x the "fit to screen" scale, and
     panning clamped so the content can never be lost off-screen
   - one CSS transform (translate + scale) written per animation frame

   Everything drawn inside `content` (image, SVG overlay, labels) shares the
   transform, so overlays stay aligned at every zoom level. Content is laid out
   at its natural size (map units = CSS px) with transform-origin 0 0.

   new PanZoom(viewport, content, { width, height, onChange })
*/
(function (global) {
  'use strict';

  const DRAG_THRESHOLD = 5;        // px before a press becomes a pan, not a tap
  const DOUBLE_TAP_MS  = 300;
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clampNum = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  class PanZoom {
    constructor(viewport, content, opts = {}) {
      this.vp = viewport;
      this.el = content;
      this.minZoom = opts.minZoom ?? 0.5;
      this.maxZoom = opts.maxZoom ?? 4;
      this.onChange = opts.onChange || (() => {});
      this.enabled = true;
      this.w = opts.width || 1;
      this.h = opts.height || 1;
      this.x = 0; this.y = 0; this.s = 1;
      this._pointers = new Map();
      this._frame = 0;
      this._anim = 0;
      this._lastTap = null;
      this._userMoved = false;

      this.el.style.transformOrigin = '0 0';
      this.el.style.willChange = 'transform';
      this.vp.style.touchAction = 'none';         // we handle every gesture ourselves

      this._onDown   = this._onDown.bind(this);
      this._onMove   = this._onMove.bind(this);
      this._onUp     = this._onUp.bind(this);
      this._onWheel  = this._onWheel.bind(this);
      this._onClickCapture = this._onClickCapture.bind(this);
      this._onKey    = this._onKey.bind(this);

      this.vp.addEventListener('pointerdown', this._onDown);
      this.vp.addEventListener('pointermove', this._onMove);
      this.vp.addEventListener('pointerup', this._onUp);
      this.vp.addEventListener('pointercancel', this._onUp);
      // Capture can move from the touched child to the viewport when a drag
      // starts; only a capture lost by the viewport itself ends the gesture.
      this.vp.addEventListener('lostpointercapture', e => { if (e.target === this.vp) this._onUp(e); });
      // passive:false so preventDefault() stops the PAGE from scrolling while
      // the pointer is over the map. Outside the map the page scrolls normally.
      this.vp.addEventListener('wheel', this._onWheel, { passive: false });
      this.vp.addEventListener('click', this._onClickCapture, true);
      this.vp.addEventListener('keydown', this._onKey);

      if ('ResizeObserver' in window) {
        this._ro = new ResizeObserver(() => this._onResize());
        this._ro.observe(this.vp);
      }
      this.fit(false);
    }

    /* ── public API ─────────────────────────────────────────────────────── */

    setContentSize(w, h) {
      this.w = w; this.h = h;
      this._userMoved = false;
      this.fit(false);
    }

    fitScale() {
      const r = this.vp.getBoundingClientRect();
      if (!r.width || !r.height) return 1;
      return Math.min(r.width / this.w, r.height / this.h);
    }

    /** Current zoom relative to fit-to-screen (1 = whole map visible). */
    zoomLevel() { return this.s / this.fitScale(); }

    fit(animate = true) {
      const r = this.vp.getBoundingClientRect();
      const s = this.fitScale();
      this._userMoved = false;
      this._go((r.width - this.w * s) / 2, (r.height - this.h * s) / 2, s, animate);
    }

    zoomBy(factor, cx, cy, animate = true) {
      const r = this.vp.getBoundingClientRect();
      if (cx == null) { cx = r.width / 2; cy = r.height / 2; }
      const s = this._clampScale(this.s * factor);
      const k = s / this.s;
      this._userMoved = true;
      this._go(cx - (cx - this.x) * k, cy - (cy - this.y) * k, s, animate);
    }

    /** Zoom/pan so the map-unit rectangle is visible (used for routes). */
    focusRect(x0, y0, x1, y1, padding = 40, animate = true) {
      const r = this.vp.getBoundingClientRect();
      const bw = Math.max(1, x1 - x0), bh = Math.max(1, y1 - y0);
      let s = Math.min((r.width - padding * 2) / bw, (r.height - padding * 2) / bh);
      s = this._clampScale(Math.min(s, this.fitScale() * 2.5));
      const x = r.width / 2 - ((x0 + x1) / 2) * s;
      const y = r.height / 2 - ((y0 + y1) / 2) * s;
      this._userMoved = true;
      this._go(x, y, s, animate);
    }

    /** Viewport pixel -> map units. */
    toMap(clientX, clientY) {
      const r = this.vp.getBoundingClientRect();
      return [(clientX - r.left - this.x) / this.s, (clientY - r.top - this.y) / this.s];
    }

    destroy() {
      this._ro && this._ro.disconnect();
      cancelAnimationFrame(this._frame); cancelAnimationFrame(this._anim);
    }

    /* ── internals ──────────────────────────────────────────────────────── */

    _clampScale(s) {
      const f = this.fitScale();
      return clampNum(s, f * this.minZoom, f * this.maxZoom);
    }

    /** Keep the map on screen: centred when smaller than the viewport,
        otherwise no gap may open between its edge and the viewport edge. */
    _clampPos(x, y, s) {
      const r = this.vp.getBoundingClientRect();
      const cw = this.w * s, ch = this.h * s;
      x = cw <= r.width  ? (r.width - cw) / 2  : clampNum(x, r.width - cw, 0);
      y = ch <= r.height ? (r.height - ch) / 2 : clampNum(y, r.height - ch, 0);
      return [x, y];
    }

    _set(x, y, s) {
      s = this._clampScale(s);
      [x, y] = this._clampPos(x, y, s);
      const changed = s !== this.s;
      this.x = x; this.y = y; this.s = s;
      if (!this._frame) {
        this._frame = requestAnimationFrame(() => {
          this._frame = 0;
          this.el.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.s})`;
          this.el.style.setProperty('--pz-scale', this.s);
          this.onChange(this.s, changed);
        });
      }
    }

    _go(x, y, s, animate) {
      cancelAnimationFrame(this._anim);
      if (!animate || reduceMotion()) { this._set(x, y, s); return; }
      const from = { x: this.x, y: this.y, s: this.s };
      // animate towards the clamped target so the motion doesn't bounce at the end
      const ts = this._clampScale(s);
      const [tx, ty] = this._clampPos(x, y, ts);
      const t0 = performance.now(), dur = 260;
      const step = (now) => {
        const t = Math.min(1, (now - t0) / dur);
        const e = 1 - Math.pow(1 - t, 3);                        // ease-out cubic
        this._set(from.x + (tx - from.x) * e, from.y + (ty - from.y) * e, from.s + (ts - from.s) * e);
        if (t < 1) this._anim = requestAnimationFrame(step);
      };
      this._anim = requestAnimationFrame(step);
    }

    _onResize() {
      if (!this._userMoved) { this.fit(false); return; }
      this._set(this.x, this.y, this.s);                            // re-clamp
    }

    _local(e) {
      const r = this.vp.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    }

    _onDown(e) {
      if (!this.enabled || (e.pointerType === 'mouse' && e.button !== 0)) return;
      cancelAnimationFrame(this._anim);
      const [lx, ly] = this._local(e);
      this._pointers.set(e.pointerId, { x: lx, y: ly, startX: lx, startY: ly });
      if (this._pointers.size === 1) {
        this._drag = { x: this.x, y: this.y, px: lx, py: ly, moved: false };
      } else if (this._pointers.size === 2) {
        this._startPinch();
      }
    }

    _startPinch() {
      const [a, b] = [...this._pointers.values()];
      this._pinch = {
        dist: Math.hypot(b.x - a.x, b.y - a.y) || 1,
        mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2,
        x: this.x, y: this.y, s: this.s,
      };
      if (this._drag) this._drag.moved = true;     // a pinch is never a tap
    }

    _onMove(e) {
      const p = this._pointers.get(e.pointerId);
      if (!p || !this.enabled) return;
      [p.x, p.y] = this._local(e);

      if (this._pointers.size >= 2 && this._pinch) {
        const [a, b] = [...this._pointers.values()];
        const dist = Math.hypot(b.x - a.x, b.y - a.y) || 1;
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const pz = this._pinch;
        const s = this._clampScale(pz.s * dist / pz.dist);
        const k = s / pz.s;
        // the map point under the starting midpoint follows the fingers
        this._userMoved = true;
        this._set(mx - (pz.mx - pz.x) * k, my - (pz.my - pz.y) * k, s);
        return;
      }

      const d = this._drag;
      if (!d) return;
      if (!d.moved && Math.hypot(p.x - d.px, p.y - d.py) < DRAG_THRESHOLD) return;
      if (!d.moved) {
        d.moved = true;
        this.vp.classList.add('is-panning');
        try { this.vp.setPointerCapture(e.pointerId); } catch (_) { /* pointer already gone */ }
      }
      this._userMoved = true;
      this._set(d.x + (p.x - d.px), d.y + (p.y - d.py), this.s);
    }

    _onUp(e) {
      const p = this._pointers.get(e.pointerId);
      if (!p) return;
      this._pointers.delete(e.pointerId);
      const wasDrag = this._drag && this._drag.moved;
      if (this._pointers.size < 2) this._pinch = null;
      if (this._pointers.size === 1) {
        // one finger left after a pinch: continue as a pan from here
        const rest = [...this._pointers.values()][0];
        this._drag = { x: this.x, y: this.y, px: rest.x, py: rest.y, moved: true };
        return;
      }
      if (this._pointers.size === 0) {
        this._suppressClick = wasDrag;
        this._drag = null;
        this.vp.classList.remove('is-panning');
        if (!wasDrag && e.type === 'pointerup') this._maybeDoubleTap(p);
      }
    }

    _maybeDoubleTap(p) {
      const now = performance.now();
      const last = this._lastTap;
      if (last && now - last.t < DOUBLE_TAP_MS && Math.hypot(p.x - last.x, p.y - last.y) < 30) {
        this._lastTap = null;
        this.zoomBy(2, p.x, p.y);
      } else {
        this._lastTap = { t: now, x: p.x, y: p.y };
      }
    }

    /* A drag that ends over a room must not also "click" that room. */
    _onClickCapture(e) {
      if (this._suppressClick) {
        this._suppressClick = false;
        e.stopPropagation();
        e.preventDefault();
      }
    }

    _onWheel(e) {
      if (!this.enabled) return;
      e.preventDefault();
      let dy = e.deltaY;
      if (e.deltaMode === 1) dy *= 16;                 // lines -> px
      else if (e.deltaMode === 2) dy *= 400;           // pages -> px
      // trackpad pinch arrives as ctrl+wheel with small deltas: zoom faster
      const speed = e.ctrlKey ? 0.01 : 0.0018;
      const factor = Math.exp(-clampNum(dy, -120, 120) * speed);
      const [lx, ly] = this._local(e);
      cancelAnimationFrame(this._anim);
      const s = this._clampScale(this.s * factor);
      const k = s / this.s;
      this._userMoved = true;
      this._set(lx - (lx - this.x) * k, ly - (ly - this.y) * k, s);
    }

    _onKey(e) {
      if (!this.enabled || e.target !== this.vp) return;
      const step = 60;
      const keys = {
        '+': () => this.zoomBy(1.4), '=': () => this.zoomBy(1.4),
        '-': () => this.zoomBy(1 / 1.4), '_': () => this.zoomBy(1 / 1.4),
        '0': () => this.fit(),
        ArrowLeft:  () => this._go(this.x + step, this.y, this.s, true),
        ArrowRight: () => this._go(this.x - step, this.y, this.s, true),
        ArrowUp:    () => this._go(this.x, this.y + step, this.s, true),
        ArrowDown:  () => this._go(this.x, this.y - step, this.s, true),
      };
      if (keys[e.key]) { e.preventDefault(); this._userMoved = true; keys[e.key](); }
    }
  }

  global.PanZoom = PanZoom;
})(window);
