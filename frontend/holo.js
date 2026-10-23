// KURAMA hologram: a nine-tailed fox drawn with Canvas 2D (no libraries).
// Light by design for an all-day laptop UI: <= 30 fps (20 fps when idle), stops while the tab is
// hidden, DPR capped at 1.5, no shadowBlur (glows are pre-rendered sprites), particles batched into
// a few fill() calls. Low-power mode draws one static frame and only redraws on state changes.

const TAU = Math.PI * 2;
const CYAN = [62, 242, 255];
const TEAL = [20, 224, 192];
const AMBER = [255, 179, 71];
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

// Left half of the head outline, snout tip -> top centre (model units, y down). Mirrored for the right.
const HALF = [
  [0, 0.8], [-0.14, 0.62], [-0.32, 0.5], [-0.58, 0.4], [-0.98, 0.22], [-0.76, 0.1], [-0.96, -0.06],
  [-0.74, -0.3], [-0.8, -0.52], [-0.7, -1.1], [-0.36, -0.58], [-0.16, -0.5], [0, -0.46],
];
const mirror = (pts) => pts.map(([x, y]) => [-x, y]);
const OUTLINE = HALF.concat(mirror(HALF.slice(1, -1)).reverse());
const EAR_L = [[-0.68, -0.98], [-0.74, -0.56], [-0.44, -0.6]];
const EYE_L = [[-0.18, 0.02], [-0.36, -0.15], [-0.56, -0.17], [-0.36, 0.01]];
const WHISKERS_L = [[[-0.48, 0.22], [-0.8, 0.15]], [[-0.47, 0.3], [-0.8, 0.3]], [[-0.45, 0.38], [-0.74, 0.45]]];
const MUZZLE_L = [[-0.12, 0.08], [-0.09, 0.58]];
const NOSE = [[-0.08, 0.6], [0.08, 0.6], [0, 0.7]];

function depth(x, y) { // rough convex head + forward snout
  return 0.32 * Math.sqrt(Math.max(0, 1 - x * x * 0.9 - y * y * 0.45)) + 0.18 * Math.max(0, y) * Math.max(0, 1 - Math.abs(x) * 2.2);
}

function sampleLine(out, a, b, step, kind) {
  const n = Math.max(1, Math.round(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
  for (let i = 0; i < n; i++) {
    const t = i / n, x = a[0] + (b[0] - a[0]) * t, y = a[1] + (b[1] - a[1]) * t;
    out.push({ x, y, z: depth(x, y) + 0.02, p: Math.random() * TAU, k: kind });
  }
}

function inside(poly, x, y) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

function buildParticles() {
  const pts = [];
  const closed = (poly, step, kind) => poly.forEach((p, i) => sampleLine(pts, p, poly[(i + 1) % poly.length], step, kind));
  closed(OUTLINE, 0.034, 0);
  for (const side of [1, -1]) {
    const m = (poly) => poly.map(([x, y]) => [x * side, y]);
    closed(m(EAR_L), 0.05, 1);
    for (const [a, b] of WHISKERS_L) sampleLine(pts, [a[0] * side, a[1]], [b[0] * side, b[1]], 0.045, 1);
    sampleLine(pts, ...m(MUZZLE_L), 0.06, 1);
  }
  let guard = 0, fill = 0;
  while (fill < 130 && guard++ < 4000) { // dim interior "volume" particles
    const x = (Math.random() * 2 - 1) * 0.95, y = Math.random() * 1.9 - 1.1;
    if (inside(OUTLINE, x, y)) { pts.push({ x, y, z: depth(x, y), p: Math.random() * TAU, k: 2 }); fill++; }
  }
  return pts;
}

function sprite(c, size = 128) {
  const cv = document.createElement("canvas");
  cv.width = cv.height = size;
  const x = cv.getContext("2d");
  const g = x.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, rgba(c, 0.85));
  g.addColorStop(0.22, rgba(c, 0.32));
  g.addColorStop(0.55, rgba(c, 0.08));
  g.addColorStop(1, rgba(c, 0));
  x.fillStyle = g;
  x.fillRect(0, 0, size, size);
  return cv;
}

export class Hologram {
  constructor(canvas, { lowPower = false, reducedMotion = false } = {}) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d", { alpha: true });
    this.state = "idle";
    this.levelFn = () => 0;
    this.level = 0;
    this.t = 7.3; // a pleasant static pose for low-power frames
    this.last = 0;
    this.raf = 0;
    this.lowPower = lowPower;
    this.reduced = reducedMotion;
    this.parts = buildParticles();
    this.embers = [];
    this.glowC = sprite(CYAN, 256);
    this.glowA = sprite(AMBER, 128);
    this.w = this.h = 0;
    this._loop = this._loop.bind(this);
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    document.addEventListener("visibilitychange", () => (document.hidden ? this.stop() : this.start()));
    this.resize();
  }

  setState(s) {
    if (s === this.state) return;
    this.state = s;
    if (this.lowPower) this.drawStatic();
  }
  setLowPower(on) {
    this.lowPower = !!on;
    if (this.lowPower) { this.stop(); this.drawStatic(); } else this.start();
  }
  start() {
    if (this.lowPower || document.hidden || this.raf) return;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this._loop);
  }
  stop() { cancelAnimationFrame(this.raf); this.raf = 0; }

  resize() {
    const p = this.cv.parentElement;
    const w = Math.max(50, p.clientWidth), h = Math.max(50, p.clientHeight);
    let dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    if (w * h * dpr * dpr > 1.3e6) dpr = Math.sqrt(1.3e6 / (w * h)); // pixel budget for weak GPUs
    this.cv.width = Math.round(w * dpr);
    this.cv.height = Math.round(h * dpr);
    this.cv.style.width = w + "px";
    this.cv.style.height = h + "px";
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w; this.h = h;
    this.R = Math.min(w * 0.2, h * 0.21);
    this.cx = w / 2; this.cy = h * 0.43;
    this._cone = null;
    if (this.lowPower || !this.raf) this.drawStatic();
  }

  drawStatic() { this.level = 0; this.draw(0); }

  _loop(now) {
    this.raf = requestAnimationFrame(this._loop);
    const minDt = 1000 / (this.state === "idle" ? 20 : 30);
    if (now - this.last < minDt - 1) return;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    this.t += dt * (this.reduced ? 0.45 : 1);
    const target = Math.max(0, Math.min(1, this.levelFn() || 0));
    this.level += (target - this.level) * (target > this.level ? 0.55 : 0.12);
    this.draw(dt);
  }

  // --- drawing ---
  draw(dt) {
    const { ctx, w, h, R, cx, cy, t, state } = this;
    if (!w) return;
    const lv = this.level;
    const thinking = state === "thinking", listening = state === "listening", speaking = state === "speaking";
    const breath = 1 + 0.018 * Math.sin(t * 1.1) + (speaking ? lv * 0.05 : 0);
    const yaw = (thinking ? 0.3 * Math.sin(t * 0.9) : 0.22 * Math.sin(t * 0.25)) + 0.04 * Math.sin(t * 1.7);
    const cosY = Math.cos(yaw), sinY = Math.sin(yaw);
    const S = R * breath;
    const proj = (x, y, z) => {
      const X = x * cosY + z * sinY, Z = -x * sinY + z * cosY, k = 1 + Z * 0.09;
      return [cx + X * S * k, cy + y * S * k, Z];
    };
    const flick = Math.random() < 0.025 ? 0.7 : 1;

    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";

    // aura + projector cone
    ctx.globalAlpha = (0.28 + (speaking ? lv * 0.35 : 0) + (listening ? lv * 0.2 : 0)) * flick;
    const aura = R * 4.4 * (1 + lv * 0.15);
    ctx.drawImage(this.glowC, cx - aura / 2, cy - aura / 2, aura, aura);
    ctx.globalAlpha = 0.9 * flick;
    this._drawCone(ctx);

    // rings
    const spin = thinking ? 4 : listening ? 1.8 : 1;
    this._ring(ctx, cx, cy + R * 0.15, R * 1.62 * (1 + (listening ? lv * 0.12 : 0)), R * 0.36, -0.06 + yaw * 0.15, [2, 9], -t * 24 * spin, rgba(CYAN, 0.55));
    this._ring(ctx, cx, cy + R * 0.15, R * 1.95, R * 0.45, 0.05 - yaw * 0.1, [26, 14, 4, 14], t * 14 * spin, rgba(TEAL, 0.3));
    this._ring(ctx, cx, cy + R * 1.78, R * 1.15, R * 0.2, 0, [3, 6], -t * 10 * spin, rgba(CYAN, 0.45));
    this._ring(ctx, cx, cy + R * 1.78, R * 0.75 * (1 + lv * 0.2), R * 0.13 * (1 + lv * 0.2), 0, [], 0, rgba(AMBER, 0.35 + lv * 0.4));

    // nine tails (behind the head)
    const tips = this._tails(ctx, proj, t, lv, state);
    ctx.globalAlpha = flick;

    // head occluder, then glowing edges and particles
    ctx.globalCompositeOperation = "source-over";
    ctx.beginPath();
    OUTLINE.forEach(([x, y], i) => { const [X, Y] = proj(x, y, depth(x, y)); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.closePath();
    ctx.fillStyle = "rgba(2,10,24,0.78)";
    ctx.fill();
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = rgba(CYAN, 0.35);
    ctx.lineWidth = 1.2;
    ctx.stroke();
    this._particles(ctx, proj, t, lv, listening);
    this._face(ctx, proj, t, lv, state);
    if (thinking) this._swirl(ctx, proj, t);
    this._embers(ctx, tips, dt, state, lv);

    // scan band
    const sy = cy - R * 1.3 + ((t * 0.35) % 1) * R * 3.2;
    const g = ctx.createLinearGradient(0, sy - R * 0.12, 0, sy + R * 0.12);
    g.addColorStop(0, rgba(CYAN, 0)); g.addColorStop(0.5, rgba(CYAN, 0.10)); g.addColorStop(1, rgba(CYAN, 0));
    ctx.fillStyle = g;
    ctx.fillRect(cx - R * 2.2, sy - R * 0.12, R * 4.4, R * 0.24);

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  _drawCone(ctx) {
    const { cx, cy, R } = this;
    if (!this._cone) {
      const g = ctx.createLinearGradient(0, cy + R * 1.8, 0, cy - R * 1.3);
      g.addColorStop(0, rgba(CYAN, 0.16)); g.addColorStop(0.6, rgba(CYAN, 0.04)); g.addColorStop(1, rgba(CYAN, 0));
      this._cone = g;
    }
    ctx.fillStyle = this._cone;
    ctx.beginPath();
    ctx.moveTo(cx - R * 1.1, cy + R * 1.78);
    ctx.lineTo(cx + R * 1.1, cy + R * 1.78);
    ctx.lineTo(cx + R * 2.3, cy - R * 1.3);
    ctx.lineTo(cx - R * 2.3, cy - R * 1.3);
    ctx.closePath();
    ctx.fill();
  }

  _ring(ctx, x, y, rx, ry, rot, dash, off, color) {
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, rot, 0, TAU);
    ctx.setLineDash(dash);
    ctx.lineDashOffset = off;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.stroke();
    ctx.setLineDash([]);
  }

  _tails(ctx, proj, t, lv, state) {
    const N = 20, tips = [];
    const lift = state === "listening" ? lv * 0.12 : 0;
    const speed = state === "thinking" ? 2.2 : state === "speaking" ? 1.4 : 1;
    const widthK = 1 + (state === "speaking" ? lv * 0.3 : 0);
    const base = [0, 0.42, -0.25];
    for (let i = 0; i < 9; i++) {
      const u = i / 8; // 0 = far left, 1 = far right
      let dir = Math.PI * (0.93 + u * 1.14) - lift * (u - 0.5);
      const curl = (u - 0.5) * 1.6; // outer tails curl outward at the tips
      const len = 2.05 + 0.12 * Math.sin(i * 1.7), step = len / N;
      let x = base[0], y = base[1];
      const L = [], Rr = [];
      const grad = [];
      for (let s = 0; s <= N; s++) {
        const f = s / N;
        const z = base[2] - f * 0.45 - Math.abs(u - 0.5) * 0.2 * f;
        const P = proj(x, y, z);
        const wv = 0.17 * widthK * Math.pow(Math.sin(Math.PI * Math.pow(Math.max(f, 0.02), 0.65)), 0.9) * (1 - 0.25 * f);
        const nx = -Math.sin(dir), ny = Math.cos(dir);
        L.push(proj(x + nx * wv, y + ny * wv, z)); Rr.push(proj(x - nx * wv, y - ny * wv, z));
        if (s === 0) grad.push(P);
        if (s === N) { grad.push(P); tips.push(P); }
        dir += (curl + 0.9 * Math.sin(t * 0.9 * speed + i * 0.8 + f * 3.2) * (0.35 + f)) * (1 / N);
        x += Math.cos(dir) * step; y += Math.sin(dir) * step;
      }
      const g = ctx.createLinearGradient(grad[0][0], grad[0][1], grad[1][0], grad[1][1]);
      g.addColorStop(0, rgba(CYAN, 0.02)); g.addColorStop(0.45, rgba(TEAL, 0.14)); g.addColorStop(1, rgba(AMBER, 0.22));
      ctx.beginPath();
      L.forEach(([X, Y], k) => (k ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y)));
      for (let k = Rr.length - 1; k >= 0; k--) ctx.lineTo(Rr[k][0], Rr[k][1]);
      ctx.closePath();
      ctx.fillStyle = g;
      ctx.fill();
      ctx.strokeStyle = rgba(i % 2 ? TEAL : CYAN, 0.38);
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    return tips;
  }

  _particles(ctx, proj, t, lv, listening) {
    const jit = listening ? 0.004 + lv * 0.05 : 0.004;
    const scanY = -1.3 + ((t * 0.35) % 1) * 3.2;
    const buckets = [[], [], [], []];
    for (const q of this.parts) {
      const j = jit * Math.sin(t * 6 + q.p * 5);
      const [X, Y] = proj(q.x + j, q.y + jit * Math.cos(t * 5 + q.p * 3), q.z);
      const fl = 0.5 + 0.5 * Math.sin(t * 3.2 + q.p * 7);
      let b = q.k === 2 ? 0 : fl > 0.55 ? 2 : 1;
      if (Math.abs(q.y - scanY) < 0.07) b = 3;
      buckets[b].push(X, Y, q.k === 2 ? 1.1 : 1.7);
    }
    const styles = [rgba(CYAN, 0.28), rgba(CYAN, 0.55), rgba(CYAN, 0.95), "rgba(235,255,255,1)"];
    buckets.forEach((arr, b) => {
      if (!arr.length) return;
      ctx.fillStyle = styles[b];
      ctx.beginPath();
      for (let i = 0; i < arr.length; i += 3) ctx.rect(arr[i] - arr[i + 2] / 2, arr[i + 1] - arr[i + 2] / 2, arr[i + 2], arr[i + 2]);
      ctx.fill();
    });
  }

  _face(ctx, proj, t, lv, state) {
    const eyeK = state === "speaking" ? 1 + lv * 1.6 : state === "listening" ? 1.2 + lv * 0.8 : 0.9 + 0.1 * Math.sin(t * 2);
    for (const side of [1, -1]) {
      const pts = EYE_L.map(([x, y]) => proj(x * side, y, depth(x, y) + 0.03));
      const [ex, ey] = proj(-0.37 * side, -0.08, depth(0.37, -0.08) + 0.03);
      const gs = this.R * 0.55 * eyeK;
      ctx.globalAlpha = 0.75;
      ctx.drawImage(this.glowA, ex - gs / 2, ey - gs / 2, gs, gs);
      ctx.globalAlpha = 1;
      ctx.beginPath();
      pts.forEach(([X, Y], i) => (i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y)));
      ctx.closePath();
      ctx.fillStyle = rgba(AMBER, 0.85);
      ctx.fill();
      const [p1x, p1y] = proj(-0.37 * side, -0.15, 0.33), [p2x, p2y] = proj(-0.36 * side, 0.0, 0.33);
      ctx.strokeStyle = "rgba(60,10,0,0.9)";
      ctx.lineWidth = 1.6;
      ctx.globalCompositeOperation = "source-over";
      ctx.beginPath(); ctx.moveTo(p1x, p1y); ctx.lineTo(p2x, p2y); ctx.stroke();
      ctx.globalCompositeOperation = "lighter";
    }
    ctx.beginPath();
    NOSE.forEach(([x, y], i) => { const [X, Y] = proj(x, y, depth(x, y) + 0.04); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
    ctx.closePath();
    ctx.fillStyle = rgba(CYAN, 0.7);
    ctx.fill();
    const [fx, fy] = proj(0, -0.3, 0.34), d = this.R * 0.05;
    ctx.beginPath(); ctx.moveTo(fx, fy - d); ctx.lineTo(fx + d * 0.6, fy); ctx.lineTo(fx, fy + d); ctx.lineTo(fx - d * 0.6, fy); ctx.closePath();
    ctx.fillStyle = rgba(AMBER, 0.6 + 0.3 * Math.sin(t * 2.4));
    ctx.fill();
  }

  _swirl(ctx, proj, t) {
    ctx.fillStyle = rgba(AMBER, 0.9);
    ctx.beginPath();
    for (let k = 0; k < 28; k++) {
      const a = t * 3 + (k * TAU) / 28, r = 1.3 + 0.12 * Math.sin(t * 2 + k);
      const [X, Y] = proj(Math.cos(a) * r, 0.1 + Math.sin(a) * r * 0.28 + Math.sin(t * 1.5 + k) * 0.05, Math.sin(a) * r * 0.5);
      const s = 1.2 + (k % 4 === 0 ? 1.2 : 0);
      ctx.rect(X - s / 2, Y - s / 2, s, s);
    }
    ctx.fill();
  }

  _embers(ctx, tips, dt, state, lv) {
    const rate = state === "speaking" ? 18 + lv * 30 : state === "thinking" ? 14 : 5;
    if (dt > 0 && !this.reduced) {
      let n = rate * dt;
      while (n > 0 && this.embers.length < 70) {
        if (Math.random() < n) {
          const [x, y] = tips[(Math.random() * tips.length) | 0];
          this.embers.push({ x, y, vx: (Math.random() - 0.5) * 14, vy: -12 - Math.random() * 22, life: 1 });
        }
        n -= 1;
      }
    }
    const buckets = [[], []];
    this.embers = this.embers.filter((e) => {
      e.x += e.vx * dt; e.y += e.vy * dt; e.life -= dt * 0.8;
      if (e.life <= 0) return false;
      buckets[e.life > 0.5 ? 1 : 0].push(e);
      return true;
    });
    [rgba(AMBER, 0.35), rgba(AMBER, 0.8)].forEach((style, b) => {
      if (!buckets[b].length) return;
      ctx.fillStyle = style;
      ctx.beginPath();
      for (const e of buckets[b]) ctx.rect(e.x - 1, e.y - 1, 2, 2);
      ctx.fill();
    });
  }
}
