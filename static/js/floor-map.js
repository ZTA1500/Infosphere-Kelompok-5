/* Interactive floor map used by the kiosk page and the admin "Area Status" page.

   new FloorMap(rootElement, {
     data,                 // parsed /rooms.json
     mode: 'user'|'admin',
     text: {...},          // UI strings (see DEFAULT_TEXT)
     onRoomClick(room), onFloorChange(floorNum), onAreaClick(closure)
   })

   Layers inside one transformed element (so they stay aligned at any zoom):
     <picture>  floor image — only the floor on screen is ever downloaded
     <svg>      rooms, closures (dark + hatched), highlight, route line
     .fm-pins   HTML pins/labels, counter-scaled to stay readable
*/
(function (global) {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const DEFAULT_TEXT = {
    floorsLabel: 'Floor',
    zoomIn: 'Zoom in', zoomOut: 'Zoom out', fit: 'Fit map to screen',
    loading: 'Loading map…',
    unavailable: 'Map not available',
    unavailableSub: 'The floor plan for this floor hasn\'t been added yet.',
    mapLabel: 'Floor map. Drag to move, scroll or pinch to zoom, double-click to zoom in.',
    closed: 'Currently closed',
    under_construction: 'Currently under construction',
    you: 'You are here',
  };

  function svg(tag, attrs = {}, parent) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }

  function h(tag, cls, parent, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    if (parent) parent.appendChild(el);
    return el;
  }

  const polyPoints = poly => poly.map(p => p.join(',')).join(' ');

  function centre(poly) {
    const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
  }

  class FloorMap {
    constructor(root, opts) {
      this.root = root;
      this.data = opts.data;
      this.mode = opts.mode || 'user';
      this.text = { ...DEFAULT_TEXT, ...(opts.text || {}) };
      this.onRoomClick = opts.onRoomClick || (() => {});
      this.onFloorChange = opts.onFloorChange || (() => {});
      this.onAreaClick = opts.onAreaClick || null;
      this.floors = [...this.data.floors].sort((a, b) => a.floor - b.floor);
      this.rooms = this.data.rooms;
      this.closures = [];
      this.legs = {};             // floorNum -> { points, start, end }
      this.highlightId = null;
      this.selection = null;      // admin: { roomId } or { polygon }
      this.uid = 'fm' + Math.random().toString(36).slice(2, 8);
      this._build();
      this.current = null;
      this.showFloor(opts.initialFloor || this.floors[0].floor);
      this._ready = true;          // onFloorChange only fires for later switches
    }

    /* ── structure ──────────────────────────────────────────────────────── */

    _build() {
      const t = this.text;
      this.root.classList.add('fm', 'fm-' + this.mode);
      this.root.innerHTML = '';

      this.floorBar = h('div', 'fm-floors', this.root);
      this.floorBar.setAttribute('role', 'group');
      this.floorBar.setAttribute('aria-label', t.floorsLabel);
      this.floorButtons = {};
      for (const f of this.floors) {
        const b = h('button', 'fm-floor-btn', this.floorBar, f.label);
        b.type = 'button';
        b.addEventListener('click', () => this.showFloor(f.floor));
        this.floorButtons[f.floor] = b;
      }

      this.vp = h('div', 'fm-viewport', this.root);
      this.vp.tabIndex = 0;
      this.vp.setAttribute('role', 'application');
      this.vp.setAttribute('aria-label', t.mapLabel);
      this.content = h('div', 'fm-content', this.vp);

      this.picture = h('picture', 'fm-picture', this.content);
      this.source = h('source', null, this.picture);
      this.source.type = 'image/webp';
      this.img = h('img', 'fm-img', this.picture);
      this.img.decoding = 'async';
      this.img.draggable = false;
      this.img.addEventListener('load', () => this._setState('ready'));
      this.img.addEventListener('error', () => this._setState('missing'));

      this.svg = svg('svg', { class: 'fm-svg' }, this.content);
      const defs = svg('defs', {}, this.svg);
      for (const [kind, stripe] of [['closed', 'rgba(255,255,255,.55)'], ['under_construction', 'rgba(255,196,0,.85)']]) {
        const p = svg('pattern', {
          id: `${this.uid}-hatch-${kind}`, width: 12, height: 12,
          patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)',
        }, defs);
        svg('rect', { width: 12, height: 12, fill: 'rgba(15,23,42,.62)' }, p);
        svg('rect', { width: 4, height: 12, fill: stripe }, p);
      }
      this.gRooms = svg('g', { class: 'fm-rooms' }, this.svg);
      this.gClosures = svg('g', { class: 'fm-closures' }, this.svg);
      this.gHighlight = svg('g', { class: 'fm-highlight' }, this.svg);
      this.gRoute = svg('g', { class: 'fm-route' }, this.svg);
      this.gDraft = svg('g', { class: 'fm-draft' }, this.svg);
      this.pins = h('div', 'fm-pins', this.content);

      this.stateBox = h('div', 'fm-state', this.vp);
      this.stateBox.setAttribute('role', 'status');

      const ctr = h('div', 'fm-controls', this.root);
      const mk = (label, sym, fn) => {
        const b = h('button', 'fm-ctrl', ctr);
        b.type = 'button';
        b.title = label;
        b.setAttribute('aria-label', label);
        b.innerHTML = sym;
        b.addEventListener('click', fn);
        return b;
      };
      mk(t.zoomIn, '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>', () => this.pz.zoomBy(1.5));
      mk(t.zoomOut, '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/></svg>', () => this.pz.zoomBy(1 / 1.5));
      mk(t.fit, '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>', () => this.pz.fit());

      // Small notes would cover the plan when the whole floor is on screen:
      // show them once the visitor zooms in.
      this.pz = new PanZoom(this.vp, this.content, {
        minZoom: 0.5, maxZoom: 4,
        onChange: () => this.root.classList.toggle('fm-far', this.pz.zoomLevel() < 1.6),
      });
    }

    _setState(state) {
      const t = this.text;
      this.root.dataset.state = state;
      this.stateBox.innerHTML = '';
      if (state === 'loading') {
        h('div', 'fm-spinner', this.stateBox);
        h('div', 'fm-state-title', this.stateBox, t.loading);
      } else if (state === 'missing') {
        h('div', 'fm-state-title', this.stateBox, `${t.unavailable} — ${this.floor ? this.floor.label : ''}`);
        h('div', 'fm-state-sub', this.stateBox, t.unavailableSub);
      }
      this.stateBox.hidden = state === 'ready';
    }

    /** Switch UI language without rebuilding the map. */
    setText(text) {
      this.text = { ...DEFAULT_TEXT, ...text };
      const t = this.text;
      this.floorBar.setAttribute('aria-label', t.floorsLabel);
      this.vp.setAttribute('aria-label', t.mapLabel);
      const [zin, zout, fit] = this.root.querySelectorAll('.fm-ctrl');
      [[zin, t.zoomIn], [zout, t.zoomOut], [fit, t.fit]].forEach(([b, l]) => { b.title = l; b.setAttribute('aria-label', l); });
      this._drawClosures();
      this._drawRoute();
      if (this.root.dataset.state !== 'ready') this._setState(this.root.dataset.state);
    }

    /* ── floors ─────────────────────────────────────────────────────────── */

    floorDef(n) { return this.floors.find(f => f.floor === n); }

    showFloor(n) {
      const f = this.floorDef(n);
      if (!f) return;
      const changed = this.current !== n;
      this.current = n;
      this.floor = f;
      for (const [num, b] of Object.entries(this.floorButtons)) {
        const on = Number(num) === n;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.classList.toggle('has-route', !!this.legs[num]);
      }
      if (changed) {
        this.content.style.width = f.width + 'px';
        this.content.style.height = f.height + 'px';
        this.svg.setAttribute('viewBox', `0 0 ${f.width} ${f.height}`);
        this.svg.setAttribute('width', f.width);
        this.svg.setAttribute('height', f.height);
        this.img.width = f.width;
        this.img.height = f.height;
        this.img.alt = f.alt || f.label;
        this._setState('loading');
        // only this floor's image is requested; other floors load when opened
        this.source.srcset = `/static/maps/${f.image}.webp`;
        this.img.src = `/static/maps/${f.image}.png`;
        if (this.img.complete && this.img.naturalWidth) this._setState('ready');
        this.pz.setContentSize(f.width, f.height);
      }
      this._drawRooms();
      this._drawClosures();
      this._drawHighlight();
      this._drawRoute();
      this._drawSelection();
      if (changed && this._ready) this.onFloorChange(n);
    }

    /* ── rooms ──────────────────────────────────────────────────────────── */

    _drawRooms() {
      this.gRooms.innerHTML = '';
      for (const room of this.rooms) {
        if (room.floor !== this.current || !room.poly) continue;
        const el = svg('polygon', { points: polyPoints(room.poly), class: 'fm-room', tabindex: 0, role: 'button' }, this.gRooms);
        el.setAttribute('aria-label', room.name);
        svg('title', {}, el).textContent = room.name;
        el.dataset.id = room.id;
        if (this.selection && this.selection.roomId === room.id) el.classList.add('selected');
        const go = () => this.onRoomClick(room);
        el.addEventListener('click', go);
        el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
      }
    }

    roomById(id) { return this.rooms.find(r => r.id === id); }

    highlightRoom(room) {
      this.highlightId = room ? room.id : null;
      this._drawHighlight();
    }

    _drawHighlight() {
      this.gHighlight.innerHTML = '';
      const room = this.highlightId && this.roomById(this.highlightId);
      if (room && room.floor === this.current && room.poly) {
        svg('polygon', { points: polyPoints(room.poly), class: 'fm-hl' }, this.gHighlight);
      }
    }

    /* ── closures ───────────────────────────────────────────────────────── */

    closurePoly(c) {
      if (c.polygon) return c.polygon;
      const room = c.roomId && this.roomById(c.roomId);
      return room && room.poly ? room.poly : null;
    }

    setClosures(list) {
      this.closures = list || [];
      this._drawClosures();
    }

    _drawClosures() {
      this.gClosures.innerHTML = '';
      this.pins.querySelectorAll('.fm-tag').forEach(e => e.remove());
      for (const c of this.closures) {
        if (c.floor !== this.current) continue;
        const poly = this.closurePoly(c);
        if (!poly) continue;
        const label = this.text[c.status] || c.status;
        const room = c.roomId && this.roomById(c.roomId);
        const el = svg('polygon', {
          points: polyPoints(poly),
          class: `fm-closure fm-closure-${c.status}`,
          fill: `url(#${this.uid}-hatch-${c.status})`,
        }, this.gClosures);
        svg('title', {}, el).textContent = [room ? room.name : null, label, c.note].filter(Boolean).join(' — ');
        if (this.onAreaClick) {
          el.classList.add('clickable');
          el.addEventListener('click', e => { e.stopPropagation(); this.onAreaClick(c); });
        } else if (room) {
          el.addEventListener('click', () => this.onRoomClick(room));
        }
        // label sits on the area's top edge, so a route pin in the middle stays visible
        const [cx] = centre(poly);
        const top = Math.min(...poly.map(p => p[1]));
        const tag = this._pin(cx, top, `fm-tag fm-tag-${c.status}`);
        h('span', 'fm-tag-status', tag, (c.status === 'closed' ? '⛔ ' : '🚧 ') + label);
        if (c.note) h('span', 'fm-tag-note', tag, c.note);
        tag.title = [room ? room.name : null, label, c.note].filter(Boolean).join(' — ');
      }
    }

    /* ── route ──────────────────────────────────────────────────────────── */

    /** legs: { [floor]: { points:[[x,y]...], start:{label,kind}, end:{label,kind} } } */
    setRoute(legs, { focus = true } = {}) {
      this.legs = legs || {};
      this.showFloor(this.current);
      if (focus) this.focusLeg();
    }

    clearRoute() {
      this.legs = {};
      this.highlightId = null;
      this.showFloor(this.current);
    }

    focusLeg() {
      const leg = this.legs[this.current];
      const pts = leg ? leg.points : null;
      const room = this.highlightId && this.roomById(this.highlightId);
      const all = [...(pts || []), ...(room && room.floor === this.current ? room.poly : [])];
      if (!all.length) return;
      const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
      // generous padding keeps pins clear of the zoom buttons on the right
      this.pz.focusRect(Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys), 64);
    }

    _drawRoute() {
      this.gRoute.innerHTML = '';
      this.pins.querySelectorAll('.fm-pin').forEach(e => e.remove());
      const leg = this.legs[this.current];
      if (this.kiosk && this.kiosk.floor === this.current && !(leg && leg.start && leg.start.kind === 'you')) {
        this._marker(this.kiosk.xy, 'you', this.text.you);
      }
      if (!leg || !leg.points || leg.points.length < 2) return;
      const pts = leg.points.map(p => p.join(',')).join(' ');
      svg('polyline', { points: pts, class: 'fm-route-casing' }, this.gRoute);
      svg('polyline', { points: pts, class: 'fm-route-line' }, this.gRoute);
      if (leg.start) this._marker(leg.points[0], leg.start.kind, leg.start.label);
      if (leg.end) this._marker(leg.points[leg.points.length - 1], leg.end.kind, leg.end.label);
    }

    setKiosk(floor, xy) { this.kiosk = { floor, xy }; this._drawRoute(); }

    _marker(xy, kind, label) {
      const pin = this._pin(xy[0], xy[1], `fm-pin fm-pin-${kind}`);
      h('span', 'fm-dot', pin);
      if (label) h('span', 'fm-pin-label', pin, label);
    }

    _pin(x, y, cls) {
      const el = h('div', cls, this.pins);
      el.style.left = (x / this.floor.width * 100) + '%';
      el.style.top = (y / this.floor.height * 100) + '%';
      return el;
    }

    /* ── admin: selection & rectangle drawing ───────────────────────────── */

    /** sel = { floor, roomId } or { floor, polygon } or null */
    setSelection(sel) {
      this.selection = sel;
      this._drawSelection();
    }

    _drawSelection() {
      const sel = this.selection;
      this.gDraft.innerHTML = '';
      this.gRooms.querySelectorAll('.fm-room').forEach(el =>
        el.classList.toggle('selected', !!(sel && sel.roomId === el.dataset.id)));
      if (sel && sel.polygon && sel.floor === this.current) {
        svg('polygon', { points: polyPoints(sel.polygon), class: 'fm-draft-rect' }, this.gDraft);
      }
    }

    /** Next drag on the map draws a rectangle; resolves with its polygon. */
    drawRect() {
      this.cancelDraw();
      this.pz.enabled = false;
      this.root.classList.add('drawing');
      return new Promise(resolve => {
        let start = null, rect = null;
        const clampPt = ([x, y]) => [Math.round(Math.max(0, Math.min(this.floor.width, x))),
                                     Math.round(Math.max(0, Math.min(this.floor.height, y)))];
        const down = e => {
          if (e.button !== undefined && e.button !== 0) return;
          e.preventDefault();
          start = clampPt(this.pz.toMap(e.clientX, e.clientY));
          this.vp.setPointerCapture(e.pointerId);
          this.gDraft.innerHTML = '';
          rect = svg('polygon', { class: 'fm-draft-rect' }, this.gDraft);
        };
        const move = e => {
          if (!start) return;
          const [x, y] = clampPt(this.pz.toMap(e.clientX, e.clientY));
          rect.setAttribute('points', polyPoints([[start[0], start[1]], [x, start[1]], [x, y], [start[0], y]]));
        };
        const up = e => {
          if (!start) return;
          const [x, y] = clampPt(this.pz.toMap(e.clientX, e.clientY));
          const x0 = Math.min(start[0], x), x1 = Math.max(start[0], x);
          const y0 = Math.min(start[1], y), y1 = Math.max(start[1], y);
          start = null;
          if (x1 - x0 < 8 || y1 - y0 < 8) { this.gDraft.innerHTML = ''; return; }   // too small: keep drawing
          finish([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]);
        };
        const finish = poly => {
          this.vp.removeEventListener('pointerdown', down, true);
          this.vp.removeEventListener('pointermove', move, true);
          this.vp.removeEventListener('pointerup', up, true);
          this.pz.enabled = true;
          this.root.classList.remove('drawing');
          this._cancelDraw = null;
          resolve(poly);
        };
        this.vp.addEventListener('pointerdown', down, true);
        this.vp.addEventListener('pointermove', move, true);
        this.vp.addEventListener('pointerup', up, true);
        this._cancelDraw = () => { this.gDraft.innerHTML = ''; finish(null); };
      });
    }

    cancelDraw() { if (this._cancelDraw) this._cancelDraw(); }
  }

  global.FloorMap = FloorMap;
})(window);
