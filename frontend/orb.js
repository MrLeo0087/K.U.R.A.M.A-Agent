// KURAMA orb v3: a layered hologram core on Canvas 2D, budgeted for an always-on 8 GB laptop.
//  Layers: two STATIC canvases (amber + cyan dial, tracks, glass, scanlines, chromatic fringe; painted once
//  per size, cross-faded with CSS opacity) under one DYNAMIC canvas (plasma core = pre-rendered sprites
//  rotated with "lighter", counter-rotating segmented / tick rings, satellites, particles, scan sweep,
//  rare glitch). Behaviour per mode and state (all eased, no jumps):
//   text (mic off)  calm amber, slow rotation, gentle breathing; typing pokes -> ripple + sparks
//   mic             cyan accents; recording -> ring segments light with the mic level, radial waveform
//   conv            pulsing listening halo + radial spectrum crown from the mic; speaking -> crown follows
//                   the voice output and the core pulses
//   thinking        rings speed up, a third satellite orbits, particles spiral inward
//   error           brief red glitch
// Loop: setTimeout -> requestAnimationFrame, 10 fps idle / 30 fps active, stops when hidden or paused
// (wallpaper covered); low power draws a single static frame and leaves the pulse to CSS.

const TAU = Math.PI * 2;
const AMBER = [255, 122, 26];
const GOLD = [255, 179, 71];
const CYAN = [56, 196, 255];
const ICE = [150, 228, 255];
const RED = [255, 64, 64];
const ROSE = [255, 140, 130];
const FRINGE = [255, 60, 40];
const NB = 24; // spectrum bands (mirrored -> 48 bars)
const NWAVE = 64; // waveform points
const SEG = 36; // segments of the middle ring
const MAX_PARTS = 40;
const SPEED = { idle: 1, listening: 1.6, thinking: 7, speaking: 2.2 };
const MODE_COOL = { text: 0, mic: 1, conv: 1 };
const RING_SPEED = [0.12, -0.08, 0.05, 0.3]; // rad/s at idle: outer arcs, segments, ticks, inner arc
const SAT_SPEED = [0.45, 0.7, -1.6];
const R1_ARCS = [[0, 1.1], [2.3, 0.5], [Math.PI + 0.6, 0.9]];
const R4_ARCS = [[0, 2.2], [3.3, 0.35]];
const TILT = -0.45;

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${clamp01(a).toFixed(3)})`;
const lerp = (a, b, t) => a + (b - a) * t;
const mix3 = (a, b, r, cool, err) => [0, 1, 2].map((i) => lerp(lerp(a[i], b[i], cool), r[i], err));

export class Orb {
  constructor(canvas, { halo = null, lowPower = false, reducedMotion = false } = {}) {
    this.c = canvas;
    this.halo = halo;
    this.ctx = canvas.getContext("2d");
    this.lowPower = lowPower || reducedMotion;
    this.reducedMotion = reducedMotion;
    this.levelFn = () => 0; // 0..1 audio level (mic or voice output)
    this.bandsFn = null; // (n) -> Float32Array(n) 0..1 spectrum, or null
    this.waveFn = null; // (n) -> Float32Array(n) -1..1 mic waveform, or null
    this.state = "idle";
    this.mode = "text";
    this.paused = false;
    this.running = false;
    this.e = { speed: 1, think: 0, level: 0, cool: 0, err: 0, conv: 0, bars: 0, rec: 0, speak: 0 }; // eased
    this.bars = new Float32Array(NB);
    this.wave = new Float32Array(NWAVE);
    this.ang = [0, 1.3, 2.6, 3.9];
    this.sat = [0.4, 2.2, 4.0];
    this.plasma = 0;
    this.ph = 0; // breathing phase
    this.parts = [];
    this.ripples = [];
    this.fast = false; // sparks / spiral particles alive
    const now = performance.now();
    this.lastRipple = 0;
    this.lastPoke = 0;
    this.errUntil = 0;
    this.glitchUntil = 0;
    this.nextGlitch = now + 7000 + Math.random() * 9000;
    this.scanAt = -1e9;
    this.scanNext = now + 1800;
    this.last = now;
    this.stats = { fps: 0, ms: 0, frames: 0, busy: 0, t0: now };
    this.st = ["amber", "cool"].map((k) => {
      const s = document.createElement("canvas");
      s.className = "orb-static " + k;
      s.setAttribute("aria-hidden", "true");
      canvas.parentNode?.insertBefore(s, canvas);
      return s;
    });
    this._mixStatic();
    this._tick = this._tick.bind(this);
    this._resize();
    if ("ResizeObserver" in window) new ResizeObserver(() => { this._resize(); if (!this.running || this.lowPower) this._static(); }).observe(canvas);
    document.addEventListener("visibilitychange", () => this._sync());
  }

  _resize() {
    const dpr = 1; // 1x canvas: big CPU saving in the always-on wallpaper
    const w = Math.max(1, Math.round(this.c.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.c.clientHeight * dpr));
    const changed = this.c.width !== w || this.c.height !== h || !this._painted;
    if (this.c.width !== w || this.c.height !== h) { this.c.width = w; this.c.height = h; }
    this.dpr = dpr;
    this.cx = w / 2; this.cy = h / 2;
    this.S = Math.min(w, h) / 1.44; // the orb box; the canvas overhangs it by 22% each side
    if (changed && w > 1) { this._paintStatic(w, h); this._painted = true; }
  }

  // ----- public -----
  start() { this._sync(); }
  setState(s) { if (s !== this.state) { this.state = s; this._sync(); } }
  setMode(m) {
    if (m === this.mode || !(m in MODE_COOL)) return;
    this.mode = m;
    this._mixStatic();
    this.halo?.classList.toggle("cool", MODE_COOL[m] > 0);
    this._sync();
  }
  setLowPower(on) { this.lowPower = !!on || this.reducedMotion; this._sync(); }
  pause(on) { this.paused = !!on; this._sync(); }
  flash() {
    const now = performance.now();
    this.errUntil = now + 750;
    this.glitchUntil = now + 220;
    if (this.lowPower || !this.running) { this._static(); setTimeout(() => (this.running && !this.lowPower) || this._static(), 780); }
    this._sync();
  }
  // typing / send reaction: a ripple and a few sparks from the core (0..1 strength)
  poke(strength = 0.4) {
    const now = performance.now();
    if (!this.running || this.lowPower || now - this.lastPoke < 90) return;
    this.lastPoke = now;
    const S = this.S;
    if (this.ripples.length < 8) this.ripples.push({ r: S * 0.17, v: S * (0.35 + 0.35 * strength), a: 0.22 + 0.4 * strength });
    const n = 2 + Math.round(5 * strength);
    for (let i = 0; i < n && this.parts.length < MAX_PARTS; i++) {
      const a = Math.random() * TAU;
      this.parts.push({ k: 1, r: S * 0.16, a, v: S * (0.3 + Math.random() * 0.45), life: 0, ttl: 0.45 + Math.random() * 0.45, sz: 0.8 + Math.random() * 0.6 });
    }
    this.fast = true;
  }

  // click on the orb: a shockwave (3 rings) + a spray of sparks from the core; the background dust bursts out
  // and is pulled back in (dust.burst). Rate-limited; low power gets a flash only.
  burst() {
    const now = performance.now();
    if (now - (this.lastBurst || 0) < 350) return;
    this.lastBurst = now;
    if (!this.running || this.lowPower) { this.flash(); return; }
    const S = this.S;
    for (let i = 0; i < 3 && this.ripples.length < 8; i++) {
      this.ripples.push({ r: S * 0.17, v: S * (0.95 - i * 0.22), a: 0.7 - i * 0.16 });
    }
    for (let i = 0; i < 24 && this.parts.length < MAX_PARTS; i++) {
      const a = Math.random() * TAU;
      this.parts.push({ k: 1, r: S * 0.16, a, v: S * (0.55 + Math.random() * 0.75), life: 0, ttl: 0.6 + Math.random() * 0.7, sz: 0.9 + Math.random() * 0.8 });
    }
    this.fast = true;
    if (this.fx && this.fx.burst) this.fx.burst(now);
    this._sync();
  }

  _mixStatic() {
    const c = MODE_COOL[this.mode] || 0;
    this.st[0].style.opacity = String(1 - 0.85 * c);
    this.st[1].style.opacity = String(c);
  }

  // the shared background field (dust.js) rides on this loop: one timer for the whole page
  attach(fx) { this.fx = fx; if (this.reducedMotion || !this.running) fx.still(); this._sync(); }

  _sync() {
    const vis = !this.paused && !document.hidden;
    const want = vis && !this.lowPower; // low power: static orb + static background, no loop at all
    if (this.lowPower) { this._static(); this.fx?.still(); } // one static frame in low power; CSS does the pulse
    if (want && !this.running) {
      this.running = true;
      this.last = performance.now();
      this._raf = requestAnimationFrame(this._tick);
    } else if (!want && this.running) {
      this.running = false;
      clearTimeout(this._to);
      cancelAnimationFrame(this._raf);
    }
  }

  _fps(now) {
    const E = this.e;
    const active = this.state !== "idle" || this.ripples.length || this.fast || now < this.glitchUntil || E.err > 0.01 ||
      E.think > 0.02 || E.level > 0.02 || E.conv > 0.01 || E.bars > 0.01 || E.rec > 0.01 ||
      Math.abs(E.cool - (MODE_COOL[this.mode] || 0)) > 0.01;
    return active ? 15 : 6;
  }

  _tick(now) {
    if (!this.running) return;
    const t0 = performance.now();
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    if (!this.lowPower) { this._step(now, dt); this._draw(now); }
    if (this.fx && now - (this._fxAt || 0) >= 95) { this.fx.frame(now, Math.min(0.2, (now - (this._fxAt || now)) / 1000), this); this._fxAt = now; } // field <= ~10 fps
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
  _targets(now) {
    const st = this.state, m = this.mode;
    return {
      speed: SPEED[st] || 1,
      think: st === "thinking" ? 1 : 0,
      cool: MODE_COOL[m] || 0,
      err: now < this.errUntil ? 1 : 0,
      conv: m === "conv" && st === "listening" ? 1 : 0,
      bars: (m === "conv" && st === "listening") || st === "speaking" ? 1 : 0,
      rec: m !== "conv" && st === "listening" ? 1 : 0,
      speak: st === "speaking" ? 1 : 0,
    };
  }

  _step(now, dt) {
    const S = this.S, E = this.e, T = this._targets(now);
    const k = 1 - Math.exp(-dt * 3.5);
    for (const key of ["speed", "think", "conv", "bars", "rec", "speak"]) E[key] += (T[key] - E[key]) * k;
    E.cool += (T.cool - E.cool) * (1 - Math.exp(-dt * 2.5));
    E.err += (T.err - E.err) * (1 - Math.exp(-dt * 12));
    const live = this.state === "listening" || this.state === "speaking";
    const raw = live ? clamp01(this.levelFn() || 0) : 0;
    E.level = lerp(E.level, raw, raw > E.level ? 0.55 : 0.12);

    if (E.bars > 0.01 || E.rec > 0.01) { // spectrum bands (eased: fast attack, slow release)
      const b = live && this.bandsFn ? this.bandsFn(NB) : null;
      for (let i = 0; i < NB; i++) {
        const tg = live ? (b ? b[i] : E.level * (0.45 + 0.55 * Math.abs(Math.sin(i * 1.9 + now / 170)))) : 0;
        const cur = this.bars[i];
        this.bars[i] = cur + (tg - cur) * (tg > cur ? 0.6 : 0.18);
      }
    }
    if (E.rec > 0.01) {
      const w = live && this.waveFn ? this.waveFn(NWAVE) : null;
      for (let i = 0; i < NWAVE; i++) {
        const tg = live ? (w ? w[i] : E.level * Math.sin(i * 0.7 + now / 90)) : 0;
        this.wave[i] = lerp(this.wave[i], tg, 0.5);
      }
    }

    const sp = E.speed;
    for (let i = 0; i < 4; i++) this.ang[i] = (this.ang[i] + RING_SPEED[i] * sp * dt) % TAU;
    for (let i = 0; i < 3; i++) this.sat[i] = (this.sat[i] + SAT_SPEED[i] * (0.6 + 0.4 * sp) * dt) % TAU;
    this.plasma = (this.plasma + dt * (0.22 + 0.5 * E.think + 0.7 * E.level)) % (TAU * 10);
    const period = this.state === "thinking" ? 1.4 : this.mode === "conv" ? 3.6 : this.mode === "mic" ? 4.5 : 6;
    this.ph = (this.ph + (dt * TAU) / period) % TAU;

    // rare hologram glitch; bursts while in error
    if (now > this.nextGlitch) { this.glitchUntil = now + 110 + Math.random() * 150; this.nextGlitch = now + 9000 + Math.random() * 17000; }
    if (now < this.errUntil && Math.random() < dt * 10) this.glitchUntil = now + 60 + Math.random() * 90;
    if (now >= this.scanNext) { this.scanAt = now; this.scanNext = now + (E.think > 0.5 ? 1700 : 7000 + Math.random() * 6000); }

    // ripples: voice peaks while speaking, loud mic moments while recording
    const gap = this.state === "speaking" && E.level > 0.12 ? Math.max(240, 700 - E.level * 600)
      : E.rec > 0.5 && E.level > 0.3 ? 420 : Infinity;
    if (now - this.lastRipple > gap && this.ripples.length < 8) {
      this.ripples.push({ r: S * 0.17, v: S * (0.3 + E.level * 0.45), a: 0.2 + E.level * 0.45 });
      this.lastRipple = now;
    }
    for (const p of this.ripples) p.r += p.v * dt;
    this.ripples = this.ripples.filter((p) => p.r < S * 0.7);

    // particles: k0 embers rise, k1 sparks fly out, k2 spiral inward (thinking)
    let embers = 0;
    for (const p of this.parts) if (p.k === 0) embers++;
    if (embers < (this.state === "idle" ? 8 : 14) && this.parts.length < MAX_PARTS && Math.random() < dt * 2.5) {
      const a = Math.random() * TAU, rad = S * (0.12 + Math.random() * 0.28);
      this.parts.push({ k: 0, x: Math.cos(a) * rad, y: Math.abs(Math.sin(a)) * rad * 0.8 + S * 0.05, vy: -S * (0.035 + Math.random() * 0.06),
        sway: Math.random() * TAU, sz: 0.7 + Math.random() * 0.8, life: 0, ttl: 3 + Math.random() * 4 });
    }
    if (E.think > 0.1 && this.parts.length < MAX_PARTS && Math.random() < dt * 16 * E.think) {
      this.parts.push({ k: 2, r: S * (0.6 + Math.random() * 0.08), a: Math.random() * TAU, life: 0, ttl: 9, sz: 0.7 + Math.random() * 0.7 });
    }
    const lift = this.state === "thinking" ? 1.8 : this.state === "speaking" ? 1.3 + E.level : 1;
    const r0 = S * 0.68;
    let fast = false;
    for (const p of this.parts) {
      p.life += dt;
      if (p.k === 0) { p.y += p.vy * dt * lift; p.sway += dt * 1.3; p.x += Math.sin(p.sway) * S * 0.012 * dt; }
      else if (p.k === 1) { p.r += p.v * dt; p.v *= 1 - dt * 2.2; fast = true; }
      else { const f = 1 - p.r / r0; p.r -= S * (0.1 + 0.4 * f) * dt; p.a += (0.8 + 3.4 * f) * dt; fast = true; }
    }
    this.parts = this.parts.filter((p) => p.life < p.ttl && (p.k !== 0 || p.y > -S * 0.7) && (p.k !== 2 || p.r > S * 0.16));
    this.fast = fast;
  }

  // ----- drawing -----
  _dot(sp, x, y, r, a) {
    const ctx = this.ctx, E = this.e;
    const wa = (1 - E.cool) * (1 - E.err), wc = E.cool * (1 - E.err);
    if (wa > 0.02) { ctx.globalAlpha = clamp01(a * wa); ctx.drawImage(sp.dotA, x - r, y - r, r * 2, r * 2); }
    if (wc > 0.02) { ctx.globalAlpha = clamp01(a * wc); ctx.drawImage(sp.dotC, x - r, y - r, r * 2, r * 2); }
    if (E.err > 0.02) { ctx.globalAlpha = clamp01(a * E.err); ctx.drawImage(sp.dotR, x - r, y - r, r * 2, r * 2); }
  }

  _rot(img, x, y, ang, r, alpha) {
    const ctx = this.ctx, c = Math.cos(ang), s = Math.sin(ang);
    ctx.globalAlpha = clamp01(alpha);
    ctx.setTransform(c, s, -s, c, x, y);
    ctx.drawImage(img, -r, -r, r * 2, r * 2);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  _chroma(path, d, a) { // chromatic edge: cyan / red copies of a path, offset sideways
    const ctx = this.ctx;
    ctx.strokeStyle = rgba(CYAN, a); ctx.setTransform(1, 0, 0, 1, d, 0); ctx.stroke(path);
    ctx.strokeStyle = rgba(FRINGE, a * 0.8); ctx.setTransform(1, 0, 0, 1, -d, 0); ctx.stroke(path);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  _draw(now, still = false) {
    const { ctx, S, dpr } = this;
    const E = this.e;
    const t = now / 1000;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, this.c.width, this.c.height);
    if (S < 4) return;
    const glitch = !still && now < this.glitchUntil;
    const ox = glitch ? (Math.random() - 0.5) * 7 * dpr : 0;
    const cx = this.cx + ox, cy = this.cy;
    const flick = glitch ? (Math.random() < 0.5 ? 0.55 : 1) : 1;
    const chroma = (glitch ? 3.5 : 1.1) * dpr;
    const sp = this._sprites();
    const main = mix3(AMBER, CYAN, RED, E.cool, E.err);
    const hi = mix3(GOLD, ICE, ROSE, E.cool, E.err);
    const warm = mix3(GOLD, GOLD, ROSE, 0, E.err);
    const breath = still ? 0.5 : (Math.sin(this.ph) + 1) / 2;
    const lv = E.level;

    // the big soft glow is the CSS halo behind the canvas: only its transform/opacity change (composited)
    const calm = still || (this.state === "idle" && E.err < 0.02 && lv < 0.02 && E.think < 0.02);
    this._halo(calm ? null : 0.93 + 0.07 * breath + 0.3 * lv + 0.05 * E.think, Math.min(1, (0.72 + 0.18 * breath + 0.4 * lv) * flick), E.err > 0.5);

    // spectrum crown (conversation listening / speaking): 48 mirrored bars outside the main ring
    if (E.bars > 0.01) {
      const p = new Path2D(), n = 48, rb = 0.525 * S;
      for (let i = 0; i < n; i++) {
        const a = -Math.PI / 2 + (i / n) * TAU, d = i <= n / 2 ? i : n - i;
        const v = this.bars[Math.min(NB - 1, Math.floor((d / (n / 2)) * NB))];
        const L = S * (0.008 + 0.115 * v) * E.bars;
        const c = Math.cos(a), s = Math.sin(a);
        p.moveTo(cx + c * rb, cy + s * rb); p.lineTo(cx + c * (rb + L), cy + s * (rb + L));
      }
      ctx.lineCap = "butt"; ctx.lineWidth = 2.4 * dpr;
      ctx.strokeStyle = rgba(warm, 0.85 * E.bars * flick); ctx.stroke(p);
      this._chroma(p, chroma * 1.3, 0.2 * E.bars);
    }

    // listening halo: a soft wide glow on the main ring that breathes, plus a thin ring drifting out
    if (E.conv > 0.01) {
      const pu = (Math.sin(t * TAU / 3) + 1) / 2;
      ctx.lineWidth = (4 + 7 * pu) * dpr; ctx.strokeStyle = rgba(hi, (0.05 + 0.11 * pu) * E.conv);
      ctx.beginPath(); ctx.arc(cx, cy, 0.5 * S, 0, TAU); ctx.stroke();
      ctx.lineWidth = dpr; ctx.strokeStyle = rgba(hi, (0.4 - 0.35 * ((t / 3) % 1)) * E.conv);
      ctx.beginPath(); ctx.arc(cx, cy, S * (0.5 + 0.09 * ((t / 3) % 1)), 0, TAU); ctx.stroke();
    }

    // ripples
    ctx.lineWidth = 1.4 * dpr;
    for (const p of this.ripples) {
      const fade = 1 - (p.r - S * 0.17) / (S * 0.53);
      ctx.strokeStyle = rgba(hi, p.a * fade * fade);
      ctx.beginPath(); ctx.arc(cx, cy, p.r, 0, TAU); ctx.stroke();
    }

    const boost = (1 + lv * 0.5 + E.think * 0.25) * flick;
    // R1: outer bright arcs + chromatic edge
    ctx.lineCap = "round";
    {
      const R = 0.5 * S, a1 = this.ang[0], ext = 1 + 0.35 * E.think, p = new Path2D();
      for (const [s0, len] of R1_ARCS) {
        const a = a1 + s0;
        p.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); p.arc(cx, cy, R, a, a + len * ext);
      }
      ctx.lineWidth = 1.7 * dpr * (1 + 0.3 * E.think);
      ctx.strokeStyle = rgba(main, 0.92 * boost); ctx.stroke(p);
      this._chroma(p, chroma, 0.26 * flick);
    }
    // R2: segmented ring; lit segments = idle chase, mic level meter + spectrum (anchored to the top)
    {
      const R = 0.43 * S, a2 = this.ang[1], step = TAU / SEG, segLen = step * 0.62;
      const base = new Path2D(), lit = [new Path2D(), new Path2D(), new Path2D()];
      let used = 0;
      const chase = ((t * (0.8 + 2.2 * E.think)) % SEG + SEG) % SEG;
      const meter = Math.max(E.rec, E.conv) * Math.min(1, lv * 1.6);
      for (let i = 0; i < SEG; i++) {
        const a = a2 + i * step;
        base.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); base.arc(cx, cy, R, a, a + segLen);
        let d = Math.abs(i - chase); d = Math.min(d, SEG - d);
        let v = d < 3 ? (1 - d / 3) * (0.55 + 0.45 * E.think) : 0;
        if (meter > 0.01 || E.rec > 0.01) {
          let u = (((a + segLen / 2 + Math.PI / 2) % TAU) + TAU) % TAU; // distance from the top, 0..PI
          if (u > Math.PI) u = TAU - u;
          const f = u / Math.PI;
          if (f < meter) v = Math.max(v, 1 - 0.5 * (f / Math.max(meter, 0.01)));
          v = Math.max(v, this.bars[Math.min(NB - 1, Math.floor(f * NB))] * E.rec);
        }
        if (v > 0.08) { const b = v > 0.66 ? 2 : v > 0.33 ? 1 : 0; lit[b].moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); lit[b].arc(cx, cy, R, a, a + segLen); used |= 1 << b; }
      }
      ctx.lineCap = "butt"; ctx.lineWidth = 3.2 * dpr;
      ctx.strokeStyle = rgba(main, 0.2 * flick); ctx.stroke(base);
      [0.38, 0.62, 0.95].forEach((al, b) => { if (used & (1 << b)) { ctx.strokeStyle = rgba(hi, al * flick); ctx.stroke(lit[b]); } });
    }
    // R3: rotating tick ring + one bright arc
    {
      const a3 = this.ang[2], p = new Path2D(), ri = 0.348 * S, ro = 0.372 * S;
      for (let i = 0; i < 60; i++) {
        const a = a3 + (i / 60) * TAU, c = Math.cos(a), s = Math.sin(a);
        p.moveTo(cx + c * ri, cy + s * ri); p.lineTo(cx + c * ro, cy + s * ro);
      }
      ctx.lineWidth = dpr; ctx.strokeStyle = rgba(main, 0.32 * flick); ctx.stroke(p);
      ctx.lineCap = "round"; ctx.lineWidth = 2 * dpr; ctx.strokeStyle = rgba(main, 0.75 * boost);
      ctx.beginPath(); ctx.arc(cx, cy, 0.36 * S, -a3 * 2, -a3 * 2 + 0.9 + 0.6 * E.think); ctx.stroke();
    }
    // R4: inner warm arcs (fast)
    {
      const R = 0.27 * S, a4 = this.ang[3], p = new Path2D();
      for (const [s0, len] of R4_ARCS) { const a = a4 + s0; p.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); p.arc(cx, cy, R, a, a + len); }
      ctx.lineWidth = 1.6 * dpr; ctx.strokeStyle = rgba(warm, 0.85 * boost); ctx.stroke(p);
    }

    // radial waveform around the core while recording (mic mode)
    if (E.rec > 0.01) {
      const p = new Path2D(), rw = 0.205 * S;
      for (let i = 0; i <= NWAVE; i++) {
        const j = i % NWAVE, w = this.wave[j <= NWAVE / 2 ? j : NWAVE - j];
        const a = -Math.PI / 2 + (i / NWAVE) * TAU, r = rw + S * 0.06 * Math.max(-1, Math.min(1, w * 2.2)) * E.rec;
        if (i) p.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r); else p.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      }
      ctx.lineJoin = "round"; ctx.lineWidth = 1.5 * dpr; ctx.strokeStyle = rgba(ICE, 0.9 * E.rec * flick); ctx.stroke(p);
      this._chroma(p, chroma * 1.5, 0.22 * E.rec);
    }

    // core: sprite + two counter-rotating plasma sprites ("lighter") + spinning hologram meridians
    const rc = S * 0.15 * (1 + 0.05 * breath + 0.24 * lv * E.speak + 0.08 * lv * E.rec + 0.04 * E.think * Math.sin(t * 9));
    ctx.globalAlpha = 0.82 + 0.18 * flick;
    ctx.drawImage(sp.core, cx - rc, cy - rc, rc * 2, rc * 2);
    if (E.err > 0.02) { ctx.globalAlpha = E.err; ctx.drawImage(sp.coreR, cx - rc, cy - rc, rc * 2, rc * 2); }
    ctx.globalCompositeOperation = "lighter";
    const pr = rc * 1.22;
    this._rot(sp.plasmaA, cx, cy, this.plasma, pr, (0.5 + 0.35 * lv) * (1 - E.err));
    this._rot(sp.plasmaA, cx, cy, 1 - this.plasma * 1.7, pr * 0.78, 0.36 * (1 - E.err));
    if (E.cool > 0.02) this._rot(sp.plasmaC, cx, cy, 2 + this.plasma * 1.3, pr * 0.96, 0.42 * E.cool * (1 - E.err));
    ctx.globalAlpha = 1;
    {
      const p = new Path2D(), rm = rc * 0.9;
      for (const k of [0, Math.PI / 3, (2 * Math.PI) / 3]) {
        const rx = Math.max(0.5, rm * Math.abs(Math.cos(this.plasma * 0.8 + k)));
        p.moveTo(cx + rx, cy); p.ellipse(cx, cy, rx, rm, 0, 0, TAU);
      }
      p.moveTo(cx + rm, cy); p.ellipse(cx, cy, rm, rm * 0.28, 0, 0, TAU);
      ctx.lineWidth = dpr; ctx.strokeStyle = `rgba(255,236,210,${(0.13 * flick).toFixed(3)})`; ctx.stroke(p);
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.lineWidth = dpr;
    ctx.strokeStyle = rgba(hi, (0.35 + 0.35 * lv) * flick);
    ctx.beginPath(); ctx.arc(cx, cy, rc * 1.16, 0, TAU); ctx.stroke();

    // satellites: one on the main ring (with a trail), one on a tilted orbit (dims behind the core),
    // a third, fast one on the tick ring while thinking
    ctx.lineWidth = dpr; ctx.strokeStyle = rgba(hi, 0.08 + 0.06 * E.think);
    ctx.beginPath(); ctx.ellipse(cx, cy, 0.47 * S, 0.15 * S, TILT, 0, TAU); ctx.stroke();
    {
      const R = 0.5 * S, trail = 0.05 * (1 + 2 * E.think) * Math.sign(SAT_SPEED[0]);
      for (let j = 5; j >= 0; j--) {
        const a = this.sat[0] - j * trail;
        this._dot(sp, cx + Math.cos(a) * R, cy + Math.sin(a) * R, (7 - j * 0.8) * dpr, (1 - j / 6) * 0.95 * flick);
      }
      const e = this.sat[1], x = Math.cos(e) * 0.47 * S, y = Math.sin(e) * 0.15 * S;
      const X = x * Math.cos(TILT) - y * Math.sin(TILT), Y = x * Math.sin(TILT) + y * Math.cos(TILT);
      const front = Math.sin(e) > 0;
      this._dot(sp, cx + X, cy + Y, (front ? 8 : 5.5) * dpr, front ? 1 : 0.35);
      if (E.think > 0.02) {
        const R3 = 0.36 * S;
        for (let j = 3; j >= 0; j--) {
          const a = this.sat[2] + j * 0.12;
          this._dot(sp, cx + Math.cos(a) * R3, cy + Math.sin(a) * R3, (6 - j) * dpr, E.think * (1 - j / 4));
        }
      }
    }

    // particles
    if (!still) {
      for (const p of this.parts) {
        const tt = p.life / p.ttl;
        if (p.k === 0) this._dot(sp, cx + p.x, cy + p.y, 3 * p.sz * dpr, Math.sin(Math.PI * tt) * 0.7);
        else if (p.k === 1) this._dot(sp, cx + Math.cos(p.a) * p.r, cy + Math.sin(p.a) * p.r, 3.5 * p.sz * dpr, 1 - tt);
        else {
          const a = Math.min(1, p.life * 3) * clamp01((p.r - S * 0.16) / (S * 0.08)) * E.think;
          this._dot(sp, cx + Math.cos(p.a) * p.r, cy + Math.sin(p.a) * p.r, 3.2 * p.sz * dpr, a);
        }
      }
    }

    // scan sweep: a soft band gliding down through the orb (chord-sized, so no clipping needed)
    const sc = (now - this.scanAt) / 2600;
    if (!still && sc >= 0 && sc < 1) {
      const y = (-0.52 + 1.04 * sc) * S, R = 0.5 * S, half = Math.sqrt(Math.max(0, R * R - y * y)), h = 0.1 * S;
      if (half > 2) { ctx.globalAlpha = 0.55 * Math.sin(Math.PI * sc); ctx.drawImage(E.cool > 0.5 ? sp.scanC : sp.scanA, cx - half, cy + y - h / 2, half * 2, h); }
    }

    // glitch: displaced slices
    if (glitch) {
      for (let i = 0; i < 3; i++) {
        const y = cy + (Math.random() - 0.5) * S, w = S * (0.25 + Math.random() * 0.5), x = cx - w / 2 + (Math.random() - 0.5) * S * 0.2;
        ctx.globalAlpha = 0.5;
        ctx.fillStyle = rgba(i === 1 ? CYAN : hi, 0.6);
        ctx.fillRect(x, y, w, Math.max(1, Math.round((1 + Math.random() * 2) * dpr)));
      }
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
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

  // Static layers: painted once per size (two palettes, cross-faded by CSS opacity on a mode change).
  _paintStatic(w, h) {
    const { cx, cy, S, dpr } = this;
    const R = S * 0.5;
    [[AMBER, GOLD], [CYAN, ICE]].forEach(([main, hi], idx) => {
      const cv = this.st[idx];
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      const g = cv.getContext("2d");
      g.clearRect(0, 0, w, h);
      // glass + hologram scanlines inside the orb
      g.save();
      g.beginPath(); g.arc(cx, cy, R, 0, TAU); g.clip();
      const gl = g.createRadialGradient(cx, cy, S * 0.12, cx, cy, R);
      gl.addColorStop(0, rgba(main, 0.07)); gl.addColorStop(0.65, rgba(main, 0.015)); gl.addColorStop(1, rgba(main, 0.1));
      g.fillStyle = gl; g.fillRect(cx - R, cy - R, R * 2, R * 2);
      g.fillStyle = rgba(hi, 0.05);
      const step = Math.max(2, Math.round(3 * dpr));
      for (let y = Math.floor(cy - R); y < cy + R; y += step) g.fillRect(cx - R, y, R * 2, Math.max(1, Math.round(dpr * 0.7)));
      g.restore();
      // tracks
      g.lineWidth = dpr;
      for (const [r, a] of [[0.5, 0.14], [0.43, 0.07], [0.36, 0.1], [0.27, 0.1], [0.205, 0.08]]) {
        g.strokeStyle = rgba(main, a); g.beginPath(); g.arc(cx, cy, r * S, 0, TAU); g.stroke();
      }
      // chromatic fringe on the main ring
      g.lineWidth = 1.2 * dpr;
      g.strokeStyle = rgba(CYAN, 0.2); g.beginPath(); g.arc(cx + 1.3 * dpr, cy, R, 0, TAU); g.stroke();
      g.strokeStyle = rgba(FRINGE, 0.18); g.beginPath(); g.arc(cx - 1.3 * dpr, cy, R, 0, TAU); g.stroke();
      // outer dial
      const tick = (from, to, every, skip) => {
        g.beginPath();
        for (let i = 0; i < 120; i++) {
          if ((i % every === 0) === skip) continue;
          const a = (i / 120) * TAU, c = Math.cos(a), s = Math.sin(a);
          g.moveTo(cx + c * from * S, cy + s * from * S); g.lineTo(cx + c * to * S, cy + s * to * S);
        }
        g.stroke();
      };
      g.lineWidth = dpr; g.strokeStyle = rgba(hi, 0.2); tick(0.662, 0.674, 10, true);
      g.lineWidth = 1.4 * dpr; g.strokeStyle = rgba(hi, 0.45); tick(0.645, 0.68, 10, false);
      // corner brackets
      g.lineWidth = 1.6 * dpr; g.strokeStyle = rgba(main, 0.35); g.lineCap = "round";
      for (let k = 0; k < 4; k++) { const a = Math.PI / 4 + (k * Math.PI) / 2; g.beginPath(); g.arc(cx, cy, 0.7 * S, a - 0.16, a + 0.16); g.stroke(); }
    });
  }

  // Gradients are rendered once per size into small offscreen canvases and then only scaled + blitted.
  _sprites() {
    const key = Math.round(this.S);
    if (this._sp && this._sp.key === key) return this._sp;
    const mk = (wd, ht, paint) => {
      const c = document.createElement("canvas");
      c.width = Math.max(2, Math.ceil(wd)); c.height = Math.max(2, Math.ceil(ht));
      paint(c.getContext("2d"), c.width, c.height);
      return c;
    };
    const rc = this.S * 0.15 * 1.3; // headroom for the speaking pulse
    const core = (hot, mid, deep) => mk(rc * 2, rc * 2, (g, W) => {
      const R = W / 2;
      const gr = g.createRadialGradient(R * 0.78, R * 0.72, R * 0.06, R, R, R);
      gr.addColorStop(0, "#fff4e2"); gr.addColorStop(0.28, rgba(hot, 1)); gr.addColorStop(0.62, rgba(mid, 1)); gr.addColorStop(1, rgba(deep, 1));
      g.fillStyle = gr; g.beginPath(); g.arc(R, R, R, 0, TAU); g.fill();
      g.strokeStyle = "rgba(255,230,200,0.35)"; g.lineWidth = Math.max(1, R * 0.035);
      g.beginPath(); g.arc(R, R, R * 0.95, 0, TAU); g.stroke();
    });
    const plasma = (col, strand) => mk(rc * 2, rc * 2, (g, W) => {
      const R = W / 2;
      for (let i = 0; i < 3; i++) {
        const a = (i * TAU) / 3 + 0.4, bx = R + Math.cos(a) * R * 0.34, by = R + Math.sin(a) * R * 0.34;
        const gr = g.createRadialGradient(bx, by, 0, bx, by, R * 0.55);
        gr.addColorStop(0, rgba(col, 0.55)); gr.addColorStop(1, rgba(col, 0));
        g.fillStyle = gr; g.fillRect(0, 0, W, W);
      }
      g.strokeStyle = strand; g.lineWidth = Math.max(1, R * 0.035); g.lineCap = "round";
      for (let i = 0; i < 2; i++) {
        const a = i * Math.PI;
        g.beginPath(); g.arc(R + Math.cos(a) * R * 0.3, R + Math.sin(a) * R * 0.3, R * 0.55, a + 2.2, a + 3.6); g.stroke();
      }
    });
    const dot = (col, hiC) => mk(24, 24, (g) => {
      const gr = g.createRadialGradient(12, 12, 0, 12, 12, 12);
      gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.22, rgba(hiC, 0.95)); gr.addColorStop(0.55, rgba(col, 0.3)); gr.addColorStop(1, rgba(col, 0));
      g.fillStyle = gr; g.fillRect(0, 0, 24, 24);
    });
    const scan = (col) => mk(256, Math.max(8, this.S * 0.1), (g, W, H) => {
      const v = g.createLinearGradient(0, 0, 0, H);
      v.addColorStop(0, rgba(col, 0)); v.addColorStop(0.47, rgba(col, 0.22)); v.addColorStop(0.5, rgba(col, 0.75)); v.addColorStop(0.53, rgba(col, 0.22)); v.addColorStop(1, rgba(col, 0));
      g.fillStyle = v; g.fillRect(0, 0, W, H);
      g.globalCompositeOperation = "destination-in";
      const hz = g.createLinearGradient(0, 0, W, 0);
      hz.addColorStop(0, "rgba(0,0,0,0)"); hz.addColorStop(0.2, "rgba(0,0,0,1)"); hz.addColorStop(0.8, "rgba(0,0,0,1)"); hz.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = hz; g.fillRect(0, 0, W, H);
    });
    this._sp = {
      key,
      core: core(GOLD, AMBER, [150, 46, 0]),
      coreR: core(ROSE, RED, [110, 12, 12]),
      plasmaA: plasma([255, 200, 120], "rgba(255,236,200,0.35)"),
      plasmaC: plasma(CYAN, "rgba(190,240,255,0.35)"),
      dotA: dot(AMBER, GOLD), dotC: dot(CYAN, ICE), dotR: dot(RED, ROSE),
      scanA: scan([255, 200, 140]), scanC: scan([160, 225, 255]),
    };
    return this._sp;
  }

  _static() {
    this._resize();
    this.parts = [];
    this.ripples = [];
    this.fast = false;
    const now = performance.now(), T = this._targets(now);
    Object.assign(this.e, T, { level: 0, conv: 0, bars: 0, rec: 0 });
    this.bars.fill(0);
    this._draw(now, true);
  }
}
