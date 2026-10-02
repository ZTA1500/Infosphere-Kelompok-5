/* Route finding on a floor map — no dependencies.

   Each floor is sampled into a grid. Blocked cells come from the floor's
   traced grid file (static/maps/lantai-N.grid.json: walls, outside, voids) or,
   for floors without one, from the floor's `walkable` box; every room except
   the start and the destination is blocked on top, so routes follow corridors.
   A* finds the cells, then line-of-sight smoothing turns them into a few
   straight segments.

   Closed / under-construction areas are deliberately NOT blocked: the route
   still shows the way, and the page warns about the closure instead.
*/
(function (global) {
  'use strict';

  // Rough walking-distance scale; floors can override it with metres_per_unit.
  const DEFAULT_M_PER_UNIT = 0.07;
  const mPerUnit = floor => floor.metres_per_unit || DEFAULT_M_PER_UNIT;
  const gridCache = new Map();         // floor -> Promise<grid|null>

  function roomBounds(poly) {
    const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  function roomCentre(room) {
    const [x0, y0, x1, y1] = roomBounds(room.poly);
    return [(x0 + x1) / 2, (y0 + y1) / 2];
  }

  function pointInPoly(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) inside = !inside;
    }
    return inside;
  }

  /** Load (once) the traced grid for a floor, or null when it has none. */
  function loadGrid(floor) {
    if (floor.walkable) return Promise.resolve(null);
    if (!gridCache.has(floor.floor)) {
      gridCache.set(floor.floor, fetch(`/static/maps/${floor.image}.grid.json`)
        .then(r => (r.ok ? r.json() : null))
        .then(g => {
          if (!g) return null;
          const bytes = Uint8Array.from(atob(g.blocked), c => c.charCodeAt(0));
          const cells = new Uint8Array(g.cols * g.rows);
          for (let i = 0; i < cells.length; i++) cells[i] = (bytes[i >> 3] >> (7 - (i & 7))) & 1;
          return { step: g.step, cols: g.cols, rows: g.rows, blocked: cells };
        })
        .catch(() => null));
    }
    return gridCache.get(floor.floor);
  }

  function buildGrid(floor, base, rooms, keepIds) {
    const step = base ? base.step : 6;
    const cols = base ? base.cols : Math.ceil(floor.width / step);
    const rows = base ? base.rows : Math.ceil(floor.height / step);
    const blocked = base ? base.blocked.slice() : new Uint8Array(cols * rows);
    if (!base && floor.walkable) {
      const [x0, y0, x1, y1] = floor.walkable;
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const x = c * step + step / 2, y = r * step + step / 2;
        if (x < x0 || x > x1 || y < y0 || y > y1) blocked[r * cols + c] = 1;
      }
    }
    for (const room of rooms) {
      if (room.floor !== floor.floor || !room.poly || keepIds.has(room.id)) continue;
      const [bx0, by0, bx1, by1] = roomBounds(room.poly);
      const m = 3;                                               // keep paths off the walls
      for (let r = Math.max(0, Math.floor((by0 - m) / step)); r <= Math.min(rows - 1, Math.floor((by1 + m) / step)); r++) {
        for (let c = Math.max(0, Math.floor((bx0 - m) / step)); c <= Math.min(cols - 1, Math.floor((bx1 + m) / step)); c++) {
          const x = c * step + step / 2, y = r * step + step / 2;
          if (pointInPoly(x, y, room.poly) || (x >= bx0 - m && x <= bx1 + m && y >= by0 - m && y <= by1 + m)) {
            blocked[r * cols + c] = 1;
          }
        }
      }
    }
    return { step, cols, rows, blocked };
  }

  function nearestFree(g, x, y) {
    let c0 = Math.max(0, Math.min(g.cols - 1, Math.floor(x / g.step)));
    let r0 = Math.max(0, Math.min(g.rows - 1, Math.floor(y / g.step)));
    if (!g.blocked[r0 * g.cols + c0]) return [c0, r0];
    for (let rad = 1; rad < Math.max(g.cols, g.rows); rad++) {
      for (let dr = -rad; dr <= rad; dr++) for (let dc = -rad; dc <= rad; dc++) {
        if (Math.abs(dr) !== rad && Math.abs(dc) !== rad) continue;
        const r = r0 + dr, c = c0 + dc;
        if (r >= 0 && r < g.rows && c >= 0 && c < g.cols && !g.blocked[r * g.cols + c]) return [c, r];
      }
    }
    return null;
  }

  /* Binary min-heap keyed on f-score. */
  class Heap {
    constructor() { this.a = []; }
    get size() { return this.a.length; }
    push(item) {
      const a = this.a; a.push(item);
      let i = a.length - 1;
      while (i > 0) { const p = (i - 1) >> 1; if (a[p].f <= a[i].f) break; [a[p], a[i]] = [a[i], a[p]]; i = p; }
    }
    pop() {
      const a = this.a, top = a[0], last = a.pop();
      if (a.length) {
        a[0] = last; let i = 0;
        for (;;) {
          const l = 2 * i + 1, r = l + 1; let m = i;
          if (l < a.length && a[l].f < a[m].f) m = l;
          if (r < a.length && a[r].f < a[m].f) m = r;
          if (m === i) break;
          [a[m], a[i]] = [a[i], a[m]]; i = m;
        }
      }
      return top;
    }
  }

  function astar(g, start, goal) {
    const { cols, rows, blocked } = g;
    const N = cols * rows;
    const gScore = new Float32Array(N).fill(Infinity);
    const came = new Int32Array(N).fill(-1);
    const closed = new Uint8Array(N);
    const si = start[1] * cols + start[0], gi = goal[1] * cols + goal[0];
    const h = (c, r) => Math.hypot(c - goal[0], r - goal[1]);
    const open = new Heap();
    gScore[si] = 0;
    open.push({ i: si, f: h(start[0], start[1]) });
    // If the goal is sealed off in the drawing (a door the plan doesn't show),
    // walk to the reachable cell closest to it instead.
    let best = si, bestH = h(start[0], start[1]);
    const pathTo = k => { const p = []; for (; k !== -1; k = came[k]) p.push([k % cols, Math.floor(k / cols)]); return p.reverse(); };
    const dirs = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, 1.4142], [1, -1, 1.4142], [-1, 1, 1.4142], [-1, -1, 1.4142]];
    while (open.size) {
      const { i } = open.pop();
      if (closed[i]) continue;
      if (i === gi) return pathTo(i);
      closed[i] = 1;
      const c = i % cols, r = Math.floor(i / cols);
      const hi = h(c, r);
      if (hi < bestH) { bestH = hi; best = i; }
      for (const [dc, dr, cost] of dirs) {
        const nc = c + dc, nr = r + dr;
        if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
        const ni = nr * cols + nc;
        if (blocked[ni] || closed[ni]) continue;
        if (dc && dr && (blocked[r * cols + nc] || blocked[nr * cols + c])) continue;   // no corner cutting
        const ng = gScore[i] + cost;
        if (ng < gScore[ni]) { gScore[ni] = ng; came[ni] = i; open.push({ i: ni, f: ng + h(nc, nr) }); }
      }
    }
    return best !== si ? pathTo(best) : null;
  }

  function lineClear(g, a, b) {
    let [c0, r0] = a; const [c1, r1] = b;
    const dc = Math.abs(c1 - c0), dr = Math.abs(r1 - r0);
    const sc = c0 < c1 ? 1 : -1, sr = r0 < r1 ? 1 : -1;
    let err = dc - dr;
    for (;;) {
      if (g.blocked[r0 * g.cols + c0]) return false;
      if (c0 === c1 && r0 === r1) return true;
      const e2 = 2 * err;
      if (e2 > -dr) { err -= dr; c0 += sc; }
      if (e2 < dc) { err += dc; r0 += sr; }
    }
  }

  function smooth(g, cells) {
    if (cells.length <= 2) return cells;
    const out = [cells[0]];
    let i = 0;
    while (i < cells.length - 1) {
      let j = cells.length - 1;
      while (j > i + 1 && !lineClear(g, cells[i], cells[j])) j--;
      out.push(cells[j]); i = j;
    }
    return out;
  }

  /**
   * Route between two points on one floor. `keepIds` = rooms that must stay
   * enterable (start and destination). Returns [[x,y], ...] in map units;
   * falls back to a straight line when no corridor path exists.
   */
  async function route(floor, rooms, from, to, keepIds = []) {
    const g = buildGrid(floor, await loadGrid(floor), rooms, new Set(keepIds));
    const s = nearestFree(g, from[0], from[1]);
    const t = nearestFree(g, to[0], to[1]);
    const cells = s && t ? astar(g, s, t) : null;
    if (!cells) return [from, to];
    const pts = smooth(g, cells).map(([c, r]) => [c * g.step + g.step / 2, r * g.step + g.step / 2]);
    const all = [from, ...pts, to];
    return all.filter((p, i) => i === 0 || Math.hypot(p[0] - all[i - 1][0], p[1] - all[i - 1][1]) > 4);
  }

  function nearestRoomName(rooms, floorNum, x, y) {
    let best = null, bestD = Infinity;
    for (const r of rooms) {
      if (r.floor !== floorNum || !r.poly) continue;
      const [cx, cy] = roomCentre(r);
      const d = Math.hypot(cx - x, cy - y);
      if (d < bestD) { bestD = d; best = r; }
    }
    return best && bestD < 180 ? best.name : null;
  }

  /** Turn a polyline into short Indonesian/English walking steps (plain text). */
  function steps(pts, rooms, floor, destName, t) {
    if (!pts || pts.length < 2) return [];
    const k = mPerUnit(floor);
    const keep = [pts[0]];
    for (let i = 1; i < pts.length - 1; i++) {
      const a = keep[keep.length - 1], b = pts[i], c = pts[i + 1];
      const v1 = [b[0] - a[0], b[1] - a[1]], v2 = [c[0] - b[0], c[1] - b[1]];
      const ang = Math.abs(Math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]));
      if (ang > 0.35) keep.push(b);
    }
    keep.push(pts[pts.length - 1]);
    const out = [];
    let run = 0;
    for (let i = 0; i < keep.length - 1; i++) {
      const a = keep[i], b = keep[i + 1];
      run += Math.hypot(b[0] - a[0], b[1] - a[1]) * k;
      if (i < keep.length - 2) {
        const c = keep[i + 2];
        const v1 = [b[0] - a[0], b[1] - a[1]], v2 = [c[0] - b[0], c[1] - b[1]];
        const cross = v1[0] * v2[1] - v1[1] * v2[0];
        if (Math.abs(Math.atan2(cross, v1[0] * v2[0] + v1[1] * v2[1])) > 0.35) {
          const near = nearestRoomName(rooms, floor.floor, b[0], b[1]);
          out.push(t.straight(Math.max(1, Math.round(run))));
          out.push(t.turn(cross > 0 ? 'right' : 'left', near));
          run = 0;
        }
      }
    }
    if (run > 0.5) out.push(t.straight(Math.max(1, Math.round(run))));
    out.push(t.arrive(destName));
    return out;
  }

  /** Does segment p-q cross (or touch) the polygon? */
  function segmentTouchesPoly(p, q, poly) {
    if (pointInPoly(p[0], p[1], poly) || pointInPoly(q[0], q[1], poly)) return true;
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const a = poly[j], b = poly[i];
      const d1 = cross(a, b, p), d2 = cross(a, b, q), d3 = cross(p, q, a), d4 = cross(p, q, b);
      if (((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0))) return true;
    }
    return false;
  }

  function pathTouchesPoly(pts, poly) {
    for (let i = 1; i < pts.length; i++) if (segmentTouchesPoly(pts[i - 1], pts[i], poly)) return true;
    return false;
  }

  function metres(pts, floor) {
    let d = 0;
    for (let i = 1; i < pts.length; i++) d += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    return Math.max(1, Math.round(d * mPerUnit(floor)));
  }

  global.Routing = { route, steps, metres, roomCentre, roomBounds, pointInPoly, pathTouchesPoly, loadGrid };
})(window);
