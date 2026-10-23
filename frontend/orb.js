// KURAMA orb: one Canvas 2D loop, budgeted for an always-on 8 GB laptop.
//  - idle: slow breathing nucleus, slowly rotating partial/dashed arcs, a few rising embers (~10 fps)
//  - listening: ripples that react to the mic level           (30 fps)
//  - thinking: arcs speed up, bright dots orbit the rings      (30 fps)
//  - speaking: nucleus + glow pulse with the output level      (30 fps)
//  - error: brief red flicker
// The loop is scheduled with setTimeout -> requestAnimationFrame (no 60 Hz wake-ups when idle), stops
// completely when the page is hidden or paused (wallpaper covered), and in low-power mode it draws a
// single static frame and leaves the gentle pulse to CSS.

const TAU = Math.PI * 2;
const AMBER = [255, 122, 26];
const GOLD = [255, 179, 71];
const RED = [255, 93, 93];
const MAX_EMBERS = 36; // budget: <= 40
const MAX_RIPPLES = 8;

const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a < 0 ? 0 : a > 1 ? 1 : a})`;
const lerp = (a, b, t) => a + (b - a) * t;

// rings: radius (x S), width, speed (rad/s at idle), partial arcs [start, length] or dashed full circle
const RINGS = [
  { r: 0.5, w: 1.5, speed: 0.12, arcs: [[0, 1.25], [Math.PI, 0.45]], color: AMBER, a: 0.95, track: 0.16 },
  { r: 0.395, w: 1.1, speed: -0.07, dash: [3, 7], color: GOLD, a: 0.38, track: 0 },
  { r: 0.29, w: 1.7, speed: 0.2, arcs: [[0, 2.3]], color: GOLD, a: 0.9, track: 0.12 },
  { r: 0.6, w: 1, speed: -0.04, arcs: [[0, 0.22], [2.09, 0.22], [4.19, 0.22]], color: AMBER, a: 0.45, track: 0 },
];
const SPEED = { idle: 1, listening: 1.8, thinking: 9, speaking: 2.6 };

export class Orb {
  constructor(canvas, { halo = null, lowPower = false, reducedMotion = false } = {}) {
    this.c = canvas;
    this.halo = halo;
    this.ctx = canvas.getContext("2d");
    this.lowPower = lowPower || reducedMotion;
    this.reducedMotion = reducedMotion;
    this.levelFn = () => 0;
    this.state = "idle";
    this.paused = false;
    this.running = false;
    this.speed = 1; // eased multiplier
    this.think = 0; // 0..1 eased "thinking" amount (orbit dots)
    this.level = 0; // eased audio level
    this.angles = RINGS.map((_, i) => i * 1.3);
    this.embers = [];
    this.ripples = [];
    this.lastRipple = 0;
    this.errUntil = 0;
    this.last = 0;
    this.stats = { fps: 0, ms: 0, frames: 0, busy: 0, t0: performance.now() };
    this._tick = this._tick.bind(this);
    this._resize();
    if ("ResizeObserver" in window) new ResizeObserver(() => { this._resize(); if (!this.running) this._static(); }).observe(canvas);
    document.addEventListener("visibilitychange", () => this._sync());
  }

  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = Math.max(1, Math.round(this.c.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.c.clientHeight * dpr));
    if (this.c.width !== w || this.c.height !== h) { this.c.width = w; this.c.height = h; }
    this.dpr = dpr;
    this.cx = w / 2; this.cy = h / 2;
    this.S = Math.min(w, h) / 1.44; // the orb box; the canvas overhangs it by 22% each side
  }

  // ----- public -----
  start() { this._sync(); }
  setState(s) { if (s !== this.state) { this.state = s; this._sync(); } }
  setLowPower(on) { this.lowPower = !!on || this.reducedMotion; this._sync(); }
  pause(on) { this.paused = !!on; this._sync(); }
  flash() {
    this.errUntil = performance.now() + 750;
    if (this.lowPower || !this.running) { this._static(); setTimeout(() => this.running || this._static(), 780); }
    this._sync();
  }

  _sync() {
    const want = !this.paused && !document.hidden && !this.lowPower;
    if (want && !this.running) {
      this.running = true;
      this.last = performance.now();
      this._raf = requestAnimationFrame(this._tick);
    } else if (!want && this.running) {
      this.running = false;
      clearTimeout(this._to);
      cancelAnimationFrame(this._raf);
      if (this.lowPower) this._static();
    } else if (!want && this.lowPower) {
      this._static();
    }
  }

  _fps(now) {
    const active = this.state !== "idle" || this.ripples.length || now < this.errUntil || this.think > 0.02 || this.level > 0.02;
    return active ? 30 : 10;
  }

  _tick(now) {
    if (!this.running) return;
    const t0 = performance.now();
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    this._step(now, dt);
    this._draw(now);
    const spent = performance.now() - t0;
    const st = this.stats;
    st.frames++; st.busy += spent;
    if (now - st.t0 >= 2000) {
      st.fps = Math.round((st.frames * 1000) / (now - st.t0));
      st.ms = +(st.busy / st.frames).toFixed(2);
      st.frames = 0; st.busy = 0; st.t0 = now;
    }
    const delay = Math.max(0, 1000 / this._fps(now) - spent - 8); // rAF adds up to one vsync
    this._to = setTimeout(() => { if (this.running) this._raf = requestAnimationFrame(this._tick); }, delay);
  }

  // ----- simulation -----
  _step(now, dt) {
    const S = this.S;
    const k = 1 - Math.exp(-dt * 4); // easing per second
    this.speed = lerp(this.speed, SPEED[this.state] || 1, k);
    this.think = lerp(this.think, this.state === "thinking" ? 1 : 0, k);
    const raw = this.state === "listening" || this.state === "speaking" ? Math.max(0, Math.min(1, this.levelFn() || 0)) : 0;
    this.level = lerp(this.level, raw, raw > this.level ? 0.55 : 0.12);
    RINGS.forEach((r, i) => { this.angles[i] = (this.angles[i] + r.speed * this.speed * dt) % TAU; });

    // ripples: mic level while listening (plus a slow heartbeat so the state is visible), voice peaks while speaking
    const gap = this.state === "listening" ? Math.max(130, 1500 - this.level * 1900)
      : this.state === "speaking" && this.level > 0.12 ? Math.max(220, 700 - this.level * 600) : Infinity;
    if (now - this.lastRipple > gap && this.ripples.length < MAX_RIPPLES) {
      this.ripples.push({ r: S * 0.2, v: S * (0.32 + this.level * 0.5), a: 0.28 + this.level * 0.5, red: now < this.errUntil });
      this.lastRipple = now;
    }
    for (const p of this.ripples) { p.r += p.v * dt; }
    this.ripples = this.ripples.filter((p) => p.r < S * 0.72);

    // embers drift upward out of the orb's lower half
    const target = this.state === "idle" ? 20 : MAX_EMBERS;
    if (this.embers.length < target && Math.random() < dt * 6) {
      const ang = Math.random() * TAU;
      const rad = S * (0.12 + Math.random() * 0.3);
      this.embers.push({
        x: Math.cos(ang) * rad, y: Math.abs(Math.sin(ang)) * rad * 0.8 + S * 0.05,
        vy: -S * (0.035 + Math.random() * 0.06), sway: Math.random() * TAU, sz: 0.6 + Math.random() * 1.3,
        life: 0, ttl: 3 + Math.random() * 4,
      });
    }
    const lift = this.state === "thinking" ? 1.8 : this.state === "speaking" ? 1.3 + this.level : 1;
    for (const e of this.embers) {
      e.life += dt;
      e.y += e.vy * dt * lift;
      e.sway += dt * 1.3;
      e.x += Math.sin(e.sway) * S * 0.012 * dt;
    }
    this.embers = this.embers.filter((e) => e.life < e.ttl && e.y > -S * 0.7);
  }

  // ----- drawing -----
  _draw(now, still = false) {
    const { ctx, cx, cy, S, dpr } = this;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.c.width, this.c.height);
    const err = now < this.errUntil;
    const flick = err ? (Math.sin(now / 38) > 0 ? 1 : 0.45) : 1;
    const main = err ? RED : AMBER;
    const gold = err ? RED : GOLD;
    const breath = still ? 0.5 : (Math.sin(now / 1000 * (TAU / (this.state === "thinking" ? 1.4 : 5))) + 1) / 2;
    const lv = this.level;

    // the big soft glow is the CSS halo behind the canvas: only its transform/opacity change (composited)
    const rn = S * 0.17 * (1 + 0.05 * breath + 0.22 * lv);
    const sp = this._sprites(err);
    // idle: the halo stays a static CSS layer (per-frame style changes cost real CPU in WebKitGTK)
    const calm = still || (this.state === "idle" && !err && lv < 0.02);
    this._halo(calm ? null : 0.93 + 0.07 * breath + 0.3 * lv, Math.min(1, (0.72 + 0.18 * breath + 0.4 * lv) * flick), err);

    // ripples
    for (const p of this.ripples) {
      const fade = 1 - (p.r - S * 0.2) / (S * 0.52);
      ctx.strokeStyle = rgba(p.red ? RED : gold, p.a * fade * fade);
      ctx.lineWidth = 1.4 * dpr;
      ctx.beginPath(); ctx.arc(cx, cy, p.r, 0, TAU); ctx.stroke();
    }

    // rings: faint track + bright partial arcs (or a dashed circle)
    const boost = 1 + lv * 0.6 + this.think * 0.25;
    ctx.lineCap = "round";
    RINGS.forEach((ring, i) => {
      const R = ring.r * S;
      const a0 = this.angles[i];
      const col = i % 2 ? gold : main;
      if (ring.track) {
        ctx.strokeStyle = rgba(col, ring.track * flick);
        ctx.lineWidth = ring.w * dpr;
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.stroke();
      }
      ctx.strokeStyle = rgba(col, ring.a * boost * flick);
      ctx.lineWidth = ring.w * dpr * (1 + this.think * 0.3);
      if (ring.dash) {
        ctx.setLineDash(ring.dash.map((d) => d * dpr));
        ctx.beginPath(); ctx.arc(cx, cy, R, a0, a0 + TAU); ctx.stroke();
        ctx.setLineDash([]);
      } else {
        for (const [s, len] of ring.arcs) {
          ctx.beginPath(); ctx.arc(cx, cy, R, a0 + s, a0 + s + len * (1 + this.think * 0.35)); ctx.stroke();
        }
      }
    });

    // thinking: bright dots orbiting the outer and inner rings
    if (this.think > 0.02) {
      ctx.fillStyle = rgba(gold, this.think * flick);
      for (const [ri, n, mul] of [[0, 2, 1.6], [2, 3, -2.2]]) {
        const R = RINGS[ri].r * S;
        for (let j = 0; j < n; j++) {
          const a = this.angles[ri] * mul + (j * TAU) / n;
          ctx.beginPath(); ctx.arc(cx + Math.cos(a) * R, cy + Math.sin(a) * R, 2.2 * dpr, 0, TAU); ctx.fill();
        }
      }
    }

    // nucleus
    ctx.globalAlpha = 0.75 + 0.25 * flick;
    ctx.drawImage(sp.core, cx - rn, cy - rn, rn * 2, rn * 2);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = rgba(gold, 0.35 + 0.3 * lv);
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath(); ctx.arc(cx, cy, rn * 1.18, 0, TAU); ctx.stroke();

    // embers
    if (this.embers.length) {
      ctx.globalCompositeOperation = "lighter";
      for (const e of this.embers) {
        const t = e.life / e.ttl;
        const a = Math.sin(Math.PI * t) * 0.8;
        ctx.fillStyle = rgba(t < 0.5 ? gold : main, a);
        ctx.beginPath(); ctx.arc(cx + e.x, cy + e.y, e.sz * dpr, 0, TAU); ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
    }
  }

  _halo(scale, opacity, err) {
    const h = this.halo;
    if (!h) return;
    if (scale === null) {
      if (this._hq !== "static") { this._hq = "static"; h.style.transform = ""; h.style.opacity = ""; h.classList.remove("err"); }
      return;
    }
    const q = `${scale.toFixed(3)}|${opacity.toFixed(2)}|${err}`;
    if (q === this._hq) return; // untouched style = no compositor work
    this._hq = q;
    h.style.transform = `scale(${scale.toFixed(3)})`;
    h.style.opacity = opacity.toFixed(2);
    h.classList.toggle("err", err);
  }

  // Gradients are rendered once per size into small offscreen canvases and then only scaled + blitted.
  _sprites(err) {
    const key = `${Math.round(this.S)}:${err ? 1 : 0}`;
    if (this._sp && this._sp.key === key) return this._sp;
    const main = err ? RED : AMBER;
    const mk = (r, paint) => {
      const c = document.createElement("canvas");
      c.width = c.height = Math.max(2, Math.ceil(r * 2));
      paint(c.getContext("2d"), c.width / 2);
      return c;
    };
    const base = this.S * 0.17;
    const core = mk(base * 1.3, (g, R) => {
      const gr = g.createRadialGradient(R * 0.75, R * 0.7, R * 0.08, R, R, R);
      gr.addColorStop(0, err ? "#ffd0d0" : "#ffd29a");
      gr.addColorStop(0.45, rgba(main, 1));
      gr.addColorStop(1, err ? "#7a1010" : "#a33a00");
      g.fillStyle = gr; g.beginPath(); g.arc(R, R, R, 0, TAU); g.fill();
    });
    this._sp = { key, core };
    return this._sp;
  }

  _static() {
    this._resize();
    this.embers = [];
    this.ripples = [];
    this.level = 0;
    this.think = this.state === "thinking" ? 1 : 0;
    this._draw(performance.now(), true);
  }
}
