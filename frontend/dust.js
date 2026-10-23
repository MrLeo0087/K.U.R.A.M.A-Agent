// KURAMA background field: ONE shared, half-resolution canvas behind the panels. It has no loop of its
// own: the orb's single setTimeout -> rAF loop calls frame() (10 fps idle, 30 fps active, ~5 fps in low
// power, stopped when hidden / paused). Layout is read only on resize and every few seconds.
//  - 72 drifting amber dust motes, faint lines between near ones (low power: 25 motes, no lines)
//  - listening: motes are pulled toward the orb (with a slight swirl); speaking: they pulse outward
//  - a soft glow behind every panel border that slowly breathes (painted once, blitted with alpha)
//  - a rare, faint scan line sweeping down the screen

const TAU = Math.PI * 2;
const COL = ["255,150,60", "255,196,120"]; // one accent: amber + its light tint
const LINK = 110; // css px: max distance for a connecting line

export class Dust {
  constructor(canvas, { orbEl = null, lowPower = false } = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.orbEl = orbEl;
    this.k = 0.5; // render scale (css px -> canvas px); the browser upscales the soft layer for free
    this.lowPower = !!lowPower;
    this.ps = [];
    this.glow = document.createElement("canvas");
    this.glowKey = "";
    this.measuredAt = 0;
    this.sweepAt = -1e9;
    this.sweepNext = performance.now() + 5000;
    this.ph = 0;
    this.resize();
    addEventListener("resize", () => { this.resize(); this.still(); });
  }

  get count() { return this.lowPower ? 25 : 72; }
  setLowPower(on) { this.lowPower = !!on; this._fill(); }

  resize() {
    const w = Math.max(1, Math.round(innerWidth * this.k)), h = Math.max(1, Math.round(innerHeight * this.k));
    if (this.c.width !== w || this.c.height !== h) {
      this.c.width = w; this.c.height = h;
      for (const p of this.ps) { p.x = Math.random() * w; p.y = Math.random() * h; }
    }
    this.w = w; this.h = h;
    this._measure(true);
    this._fill();
  }

  _measure(force = false) {
    const k = this.k;
    const o = this.orbEl?.getBoundingClientRect();
    if (o && o.width) { this.ox = (o.left + o.width / 2) * k; this.oy = (o.top + o.height / 2) * k; this.or = (o.width / 2) * k; }
    else { this.ox = this.w / 2; this.oy = this.h * 0.35; this.or = 120 * k; }
    const rects = [...document.querySelectorAll(".card")].map((n) => n.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0);
    const key = rects.map((r) => `${r.left | 0},${r.top | 0},${r.width | 0},${r.height | 0}`).join(";") + `|${this.w}x${this.h}`;
    if (force || key !== this.glowKey) { this.glowKey = key; this._paintGlow(rects); }
    this.measuredAt = performance.now();
  }

  _paintGlow(rects) { // the panels' border glow, painted once (shadowBlur is too slow per frame)
    const g = this.glow, k = this.k;
    g.width = this.w; g.height = this.h;
    const x = g.getContext("2d");
    x.clearRect(0, 0, g.width, g.height);
    x.shadowColor = "rgba(255,122,26,0.9)";
    x.shadowBlur = 16 * k;
    x.strokeStyle = "rgba(255,140,50,0.55)";
    x.lineWidth = 1;
    for (const r of rects) {
      x.beginPath();
      if (x.roundRect) x.roundRect(r.left * k, r.top * k, r.width * k, r.height * k, 16 * k);
      else x.rect(r.left * k, r.top * k, r.width * k, r.height * k);
      x.stroke();
    }
  }

  _spawn(p = {}, edge = false) {
    const k = this.k, sp = (4 + Math.random() * 9) * k, a = Math.random() * TAU;
    if (edge) { // re-enter from a random screen edge
      const s = Math.floor(Math.random() * 4);
      p.x = s === 0 ? 0 : s === 1 ? this.w : Math.random() * this.w;
      p.y = s === 2 ? 0 : s === 3 ? this.h : Math.random() * this.h;
    } else { p.x = Math.random() * this.w; p.y = Math.random() * this.h; }
    p.bx = Math.cos(a) * sp; p.by = Math.sin(a) * sp * 0.6 - 2 * k; // slight upward bias
    p.vx = p.bx; p.vy = p.by;
    p.s = (0.8 + Math.random() * 1.4) * k * 2;
    p.c = Math.random() < 0.28 ? 1 : 0;
    p.tw = Math.random() * TAU; p.ts = 0.6 + Math.random() * 1.4;
    p.a = 0;
    return p;
  }

  _fill() {
    while (this.ps.length < this.count) this.ps.push(this._spawn());
    if (this.ps.length > this.count) this.ps.length = this.count;
  }

  still() { this.frame(performance.now(), 0, null); }

  // one step + draw; `orb` gives state / eased level (null = static frame)
  frame(now, dt, orb) {
    if (now - this.measuredAt > 4000) this._measure();
    const { ctx, w, h, k, ox, oy } = this;
    const st = orb ? orb.state : "idle", lv = orb ? orb.e.level : 0;
    const listen = st === "listening", speak = st === "speaking" && lv > 0.04, think = st === "thinking";
    const relax = Math.min(1, dt * 0.8), m = 6 * k;
    this.ph = (this.ph + dt * (TAU / 7)) % TAU;

    for (const p of this.ps) {
      p.vx += (p.bx - p.vx) * relax; p.vy += (p.by - p.vy) * relax;
      if (listen || speak || think) {
        const dx = p.x - ox, dy = p.y - oy, d = Math.hypot(dx, dy) + 0.001, ux = dx / d, uy = dy / d;
        if (listen) { // pulled in, with a gentle swirl
          p.vx += (-ux * 46 - uy * 14) * k * dt; p.vy += (-uy * 46 + ux * 14) * k * dt;
          if (d < this.or * 0.6) this._spawn(p, true);
        } else if (speak) { // pushed out with the voice
          const f = (lv * 140 * k * dt) / (1 + d / (320 * k));
          p.vx += ux * f; p.vy += uy * f;
        } else { p.vx += -uy * 10 * k * dt; p.vy += ux * 10 * k * dt; } // thinking: slow orbit
      }
      p.x += p.vx * dt; p.y += p.vy * dt;
      if (p.x < -m) p.x = w + m; else if (p.x > w + m) p.x = -m;
      if (p.y < -m) p.y = h + m; else if (p.y > h + m) p.y = -m;
      if (p.a < 1) p.a = Math.min(1, p.a + dt * 0.6 + (dt ? 0 : 1));
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, w, h);
    // breathing panel glow
    ctx.globalAlpha = this.lowPower ? 0.3 : 0.18 + 0.22 * ((Math.sin(this.ph) + 1) / 2);
    ctx.drawImage(this.glow, 0, 0);
    ctx.globalAlpha = 1;

    const ps = this.ps, n = ps.length;
    if (!this.lowPower) { // connecting lines, batched into 3 alpha buckets
      const L = LINK * k, L2 = L * L, buckets = [new Path2D(), new Path2D(), new Path2D()];
      for (let i = 0; i < n; i++) {
        const a = ps[i];
        for (let j = i + 1; j < n; j++) {
          const b = ps[j], dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
          if (d2 > L2) continue;
          const q = d2 / L2, bi = q < 0.25 ? 2 : q < 0.6 ? 1 : 0;
          buckets[bi].moveTo(a.x, a.y); buckets[bi].lineTo(b.x, b.y);
        }
      }
      ctx.lineWidth = 0.6;
      [0.05, 0.09, 0.15].forEach((al, i) => { ctx.strokeStyle = `rgba(${COL[0]},${al})`; ctx.stroke(buckets[i]); });
    }
    // motes: 2 colours x 2 twinkle buckets
    const t = now / 1000, dots = [new Path2D(), new Path2D(), new Path2D(), new Path2D()];
    for (const p of ps) {
      const tw = 0.5 + 0.5 * Math.sin(t * p.ts + p.tw);
      const bi = p.c * 2 + (tw * p.a > 0.6 ? 1 : 0);
      const s = p.s * (speak ? 1 + lv * 0.6 : 1);
      dots[bi].rect(p.x - s / 2, p.y - s / 2, s, s);
    }
    [0.32, 0.75, 0.3, 0.7].forEach((al, i) => { ctx.fillStyle = `rgba(${COL[i >> 1]},${al})`; ctx.fill(dots[i]); });

    // rare page scan line
    if (!this.lowPower && orb) {
      if (now >= this.sweepNext) { this.sweepAt = now; this.sweepNext = now + 12000 + Math.random() * 8000; }
      const q = (now - this.sweepAt) / 6000;
      if (q >= 0 && q < 1) {
        const y = q * h, a = Math.sin(Math.PI * q);
        const g = ctx.createLinearGradient(0, y - 30 * k, 0, y);
        g.addColorStop(0, "rgba(255,140,50,0)"); g.addColorStop(1, `rgba(255,140,50,${(0.05 * a).toFixed(3)})`);
        ctx.fillStyle = g; ctx.fillRect(0, y - 30 * k, w, 30 * k);
        ctx.fillStyle = `rgba(255,170,90,${(0.16 * a).toFixed(3)})`; ctx.fillRect(0, y, w, 1);
      }
    }
  }
}
