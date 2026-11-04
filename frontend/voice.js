// Browser-side voice: microphone (with the browser's echo cancellation), recorder, sentence splitter,
// a sentence-by-sentence TTS player (fetches /tts, decodes, plays gaplessly through an AnalyserNode so
// the orb can pulse with the voice), and the Conversation-mode VAD loop with barge-in.

let _ctx = null;
let _sleep = 0;
export function audioCtx() {
  clearTimeout(_sleep); _sleep = 0;
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (_ctx.state === "suspended") _ctx.resume().catch(() => {});
  return _ctx;
}

// set by the page: before = the mic is about to record (await), after = it stopped
export const micHooks = { before: null, after: null };

// Nothing playing or listening for 20 s: close the context. An open AudioContext keeps WebKit's audio thread
// rendering silence all day (~12% of a core, measured); the next mic / voice reply opens a fresh one.
export function audioSleepSoon(ms = 20000) {
  if (!_ctx || _sleep) return;
  _sleep = setTimeout(() => {
    _sleep = 0;
    const c = _ctx;
    _ctx = null;
    c.close().catch(() => {});
  }, ms);
}

function rmsOf(analyser, buf) {
  analyser.getFloatTimeDomainData(buf);
  let s = 0;
  for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
  return Math.sqrt(s / buf.length);
}

// Spectrum for the orb: max of log-spaced FFT bins up to ~5 kHz (speech), 0..1, into a reused array.
function bandsOf(analyser, bytes, out) {
  analyser.getByteFrequencyData(bytes);
  const hz = analyser.context.sampleRate / analyser.fftSize;
  const lo = 2, hi = Math.max(lo + out.length, Math.min(bytes.length, Math.round(5000 / hz)));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(lo * Math.pow(hi / lo, i / out.length));
    const b = Math.max(a + 1, Math.floor(lo * Math.pow(hi / lo, (i + 1) / out.length)));
    let m = 0;
    for (let j = a; j < b && j < bytes.length; j++) if (bytes[j] > m) m = bytes[j];
    out[i] = Math.max(0, (m / 255 - 0.25) / 0.75);
  }
  return out;
}

// ---------- dictation: put transcribed text into the message box without sending ----------
// Pure (unit-tested in tests/test_frontend_js.py): insert `text` at the selection [selStart, selEnd)
// (replacing any selected text; null = append at the end), adding a separating space where it would
// otherwise glue onto neighbouring words. Returns the new value and the caret (end of inserted text).
export function insertAtCursor(value, selStart, selEnd, text) {
  value = value || "";
  text = (text || "").trim();
  const n = value.length;
  const s = Math.max(0, Math.min(n, selStart ?? n));
  const e = Math.max(s, Math.min(n, selEnd ?? s));
  if (!text) return { value, caret: e };
  const before = value.slice(0, s), after = value.slice(e);
  const pre = before && !/\s$/.test(before) ? " " : "";
  const post = after && !/^\s/.test(after) ? " " : "";
  return { value: before + pre + text + post + after, caret: before.length + pre.length + text.length };
}

// ---------- WAV encoding (pure; unit-tested with Node in tests/test_frontend_js.py) ----------
// Downsample Float32 PCM to `outRate` mono (box filter: averages the samples of each output step) and
// encode it as 16-bit PCM WAV. /api/v1/stt accepts audio/wav, so no MediaRecorder is needed anywhere
// (WebKitGTK, used by the wallpaper window, has none).
// A windowed-sinc low-pass before decimating: the old box filter let 8-24 kHz hiss fold back into the speech
// band, which blurred "s", "f" and "sh" for Whisper ("Spotify" heard as "so fast").
export function downsample(pcm, inRate, outRate = 16000) {
  if (outRate >= inRate) return pcm;
  const ratio = inRate / outRate, half = Math.ceil(4 * ratio), cut = 0.45 / ratio;
  const taps = new Float32Array(2 * half + 1);
  let sum = 0;
  for (let k = -half; k <= half; k++) {
    const sinc = k === 0 ? 2 * cut : Math.sin(2 * Math.PI * cut * k) / (Math.PI * k);
    sum += taps[k + half] = sinc * (0.5 + 0.5 * Math.cos(Math.PI * k / (half + 1))); // Hann window
  }
  for (let k = 0; k < taps.length; k++) taps[k] /= sum;
  const out = new Float32Array(Math.floor(pcm.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const c = Math.round(i * ratio);
    let s = 0;
    for (let k = -half; k <= half; k++) { const j = c + k; if (j >= 0 && j < pcm.length) s += pcm[j] * taps[k + half]; }
    out[i] = s;
  }
  return out;
}

// Quiet recordings (mic far away, low input gain) are lifted to a normal level: Whisper calls very quiet
// speech "no speech" and drops it. Loud ones are left alone.
export function normalize(pcm, target = 0.7, maxGain = 8) {
  let peak = 0;
  for (let i = 0; i < pcm.length; i++) { const a = Math.abs(pcm[i]); if (a > peak) peak = a; }
  if (!peak || peak >= target / 2) return pcm;
  const g = Math.min(maxGain, target / peak);
  for (let i = 0; i < pcm.length; i++) pcm[i] *= g;
  return pcm;
}

export function encodeWav(pcm, inRate, outRate = 16000) {
  let data = downsample(pcm, inRate, outRate);
  data = normalize(data === pcm ? Float32Array.from(pcm) : data);
  const rate = Math.min(inRate, outRate);
  const buf = new ArrayBuffer(44 + data.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + data.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, data.length * 2, true);
  for (let i = 0, o = 44; i < data.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, data[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

// ---------- microphone ----------
// One getUserMedia stream feeds an AnalyserNode (levels / VAD) and a PCM tap (AudioWorklet, or a
// ScriptProcessorNode where worklets are missing). The tap only keeps samples while a Recorder listens.
const TAP_WORKLET = `class KuramaTap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(4096); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i];
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
    }
    return true;
  }
}
registerProcessor("kurama-tap", KuramaTap);`;

export class Mic {
  constructor() {
    this.stream = null; this.sinks = new Set(); this.muted = false; this.hearDevice = false;
    this.proc = { ns: true, ec: true, agc: true }; // Settings -> Voice: the browser's noise / echo / volume cleaning
  }
  get open() { return !!this.stream; }

  // muted: the track delivers silence (nothing is heard, recorded or sent) until unmuted
  setMuted(on) {
    this.muted = !!on;
    this.stream?.getAudioTracks().forEach((t) => { t.enabled = !this.muted; });
  }

  // plain = no echo cancellation / noise suppression / gain control: much cheaper (the sleeping wake-word
  // listener never talks, so it needs no echo cancellation)
  // system=false (hold-to-talk, the mic button): no system echo canceller. KURAMA is silent while you hold the key,
  // so there is no echo to cancel, and loading it first cost ~1-2 s: the first holds after start-up recorded
  // silence ('' x3 at 20:06, 11-04). Hands-free talk keeps it (KURAMA speaks while it listens).
  async start({ plain = false, system = true } = {}) {
    if (this.stream) return;
    this.plain = plain; this.system = !plain && system;
    if (this.system) await micHooks.before?.(); // the system echo canceller starts only while KURAMA really listens
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(window.isSecureContext === false
        ? "Microphone needs a secure page: open http://127.0.0.1:8000 (or https)."
        : "Microphone not available in this window — open http://127.0.0.1:8000 in a browser, or update the wallpaper app.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      // hearDevice: the user wants KURAMA to hear the laptop's sound too, so the page doesn't cancel it either
      // browser echo cancellation only cleans KURAMA's own mic capture (it never touches speaker volume), so keep
      // it on regardless of the system "hear device sound" setting
      audio: { echoCancellation: !plain && this.proc.ec, noiseSuppression: !plain && this.proc.ns,
               autoGainControl: !plain && this.proc.agc, channelCount: 1 },
    });
    stream.getAudioTracks().forEach((t) => { t.enabled = !this.muted; });
    const ctx = audioCtx(); // full rate: a 16 kHz context made speech recognition noticeably worse
    this.src = ctx.createMediaStreamSource(stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.buf = new Float32Array(this.analyser.fftSize);
    this.src.connect(this.analyser);
    this.mute = ctx.createGain();
    this.mute.gain.value = 0; // taps must reach the destination to be pulled; silently
    this.mute.connect(ctx.destination);
    const feed = (chunk) => { for (const s of this.sinks) s(chunk); };
    try {
      if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") throw new Error("no worklet");
      if (!ctx.kuramaTap) { // the worklet module is loaded once per context
        const url = URL.createObjectURL(new Blob([TAP_WORKLET], { type: "application/javascript" }));
        ctx.kuramaTap = ctx.audioWorklet.addModule(url).finally(() => URL.revokeObjectURL(url));
      }
      await ctx.kuramaTap;
      this.tap = new AudioWorkletNode(ctx, "kurama-tap", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
      this.tap.port.onmessage = (e) => feed(e.data);
    } catch {
      ctx.kuramaTap = null;
      this.tap = ctx.createScriptProcessor(4096, 1, 1);
      this.tap.onaudioprocess = (e) => { if (this.sinks.size) feed(new Float32Array(e.inputBuffer.getChannelData(0))); };
    }
    this.src.connect(this.tap);
    this.tap.connect(this.mute);
    this.rate = ctx.sampleRate;
    this.stream = stream;
  }

  async restart(opts) { // switch processing (sleep <-> awake) without losing recorders listening on this mic
    if (this.stream && !!opts?.plain === !!this.plain && !opts?.force) return;
    this.stop();
    await this.start(opts);
  }

  stop() {
    if (!this.stream) return;
    if (this.system) micHooks.after?.();
    this.stream.getTracks().forEach((t) => t.stop());
    for (const n of [this.src, this.tap, this.mute]) { try { n.disconnect(); } catch { /* ignore */ } }
    if (this.tap?.port) this.tap.port.onmessage = null;
    this.tap = null;
    this.stream = null;
  }

  rms() { return this.stream ? rmsOf(this.analyser, this.buf) : 0; }
  level() { return Math.min(1, this.rms() * 9); }
  bands(n) {
    if (!this.stream) return null;
    if (!this._bands || this._bands.length !== n) { this._bands = new Float32Array(n); this._bytes = new Uint8Array(this.analyser.frequencyBinCount); }
    return bandsOf(this.analyser, this._bytes, this._bands);
  }
  wave(n) { // n evenly spaced samples of the current time-domain buffer
    if (!this.stream) return null;
    if (!this._wave || this._wave.length !== n) this._wave = new Float32Array(n);
    this.analyser.getFloatTimeDomainData(this.buf);
    const step = this.buf.length / n;
    for (let i = 0; i < n; i++) this._wave[i] = this.buf[Math.floor(i * step)];
    return this._wave;
  }
}

// ---------- recorder (PCM -> 16 kHz mono WAV) ----------
export class Recorder {
  constructor(mic) { this.mic = mic; this.on = false; this.t0 = 0; this.chunks = []; this.sink = (c) => this.chunks.push(c); }
  get active() { return this.on; }

  start() {
    this.chunks = [];
    this.on = true;
    this.mic.sinks.add(this.sink);
    this.t0 = performance.now();
  }

  stop() {
    if (!this.on) return Promise.resolve(null);
    this.on = false;
    this.mic.sinks.delete(this.sink);
    const n = this.chunks.reduce((a, c) => a + c.length, 0);
    if (!n) return Promise.resolve(null);
    const pcm = new Float32Array(n);
    let o = 0;
    for (const c of this.chunks) { pcm.set(c, o); o += c.length; }
    this.chunks = [];
    return Promise.resolve(new Blob([encodeWav(pcm, this.mic.rate || 48000)], { type: "audio/wav" }));
  }

  cancel() {
    this.on = false;
    this.mic.sinks.delete(this.sink);
    this.chunks = [];
  }
}

// ---------- sentence splitter (mirrors jarvis.core.tts.SentenceSplitter) ----------
const letters = (s) => (s.match(/\p{L}/gu) || []).length;

export class SentenceSplitter {
  constructor() { this.buf = ""; this.n = 0; }
  feed(delta) {
    this.buf += delta;
    const out = [];
    if ((this.buf.match(/```/g) || []).length % 2) return out; // inside a code block: wait
    this.buf = this.buf.replace(/```[\s\S]*?```/g, " ");
    const re = /[.!?]+["')\]]*\s+|[।॥]+["')\]]*\s*|\n+/g;
    let m, start = 0;
    while ((m = re.exec(this.buf))) {
      const end = m.index + m[0].length;
      const cand = this.buf.slice(start, end).trim();
      if (letters(cand) >= 2) { out.push(cand); start = end; }
    }
    this.buf = this.buf.slice(start);
    const limit = this.n === 0 && out.length === 0 ? 60 : 220; // first chunk: cut early at a clause
    if (this.buf.length > limit) {
      const cut = Math.max(...[", ", "; ", ": ", " - "].map((p) => this.buf.lastIndexOf(p)));
      if (cut >= limit / 2) { out.push(this.buf.slice(0, cut + 1).trim()); this.buf = this.buf.slice(cut + 1); }
    }
    this.n += out.length;
    return out;
  }
  flush() {
    const rest = this.buf.trim();
    this.buf = "";
    return letters(rest) >= 1 ? rest : null;
  }
}

// ---------- TTS player ----------
// Only real words are spoken: file paths, links, emoji and long numbers stay on screen (the server cleans the rest).
const UNSPOKEN = /https?:\/\/\S+|(?:~|\.{1,2})?\/[\w.@+-]+(?:\/[\w.@+-]*)+|#\d{4,}\b|\b\d{7,}\b|[\u{1F000}-\u{1FAFF}\u2600-\u27BF\uFE0F\u200D]/gu;
export function speakable(text) {
  return letters((text || "").replace(UNSPOKEN, " ")) >= 2;
}

export class Player {
  constructor(api, { onStart, onIdle } = {}) {
    this.api = api;
    this.onStart = onStart || (() => {});
    this.onIdle = onIdle || (() => {});
    this.gen = 0;
    this.items = [];
    this.src = null;
    this.analyser = null;
  }
  get active() { return !!this.src || this.items.length > 0; }
  get playing() { return !!this.src; }

  _ensure() {
    const ctx = audioCtx();
    if (!this.analyser || this.analyser.context !== ctx) {
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.buf = new Float32Array(this.analyser.fftSize);
      this.analyser.connect(ctx.destination);
    }
    return ctx;
  }

  level() {
    if (this.src?.el) return 0.35 + 0.25 * Math.sin(performance.now() / 160); // <audio> fallback: no analyser
    return this.src && this.analyser ? Math.min(1, rmsOf(this.analyser, this.buf) * 5) : 0;
  }

  bands(n) { // null for the <audio> fallback (the orb then derives bars from level())
    if (!this.src || this.src.el || !this.analyser) return null;
    if (!this._bands || this._bands.length !== n) { this._bands = new Float32Array(n); this._bytes = new Uint8Array(this.analyser.frequencyBinCount); }
    return bandsOf(this.analyser, this._bytes, this._bands);
  }

  enqueue(text, lang, gen = this.gen) {
    if (gen !== this.gen || !speakable(text)) return;
    this.items.push({ text, lang, ctrl: null, p: null });
    // what KURAMA said in the last 90 s: the mic hearing it back (speaker -> mic) is never taken as a request
    const now = Date.now(), keep = (this.saidAt || []).map((t, i) => (now - t < 90000 ? i : -1)).filter((i) => i >= 0).slice(-40);
    this.said = [...keep.map((i) => this.said[i]), text];
    this.saidAt = [...keep.map((i) => this.saidAt[i]), now];
    this._pump();
  }

  _fetch(item) {
    item.ctrl = new AbortController();
    const ctx = this._ensure();
    const asBlob = (ab) => ({ blob: new Blob([ab], { type: "audio/mpeg" }) });
    item.p = this.api.tts(item.text, item.lang, item.ctrl.signal)
      .then((ab) => {
        if (this.noDecode) return asBlob(ab);
        const copy = ab.slice(0); // decodeAudioData detaches its input
        // Web Audio decode (gapless + analyser); if this engine can't decode mp3 (some WebKitGTK builds),
        // fall back to a plain <audio> element per sentence from then on.
        return new Promise((res, rej) => {
          const p = ctx.decodeAudioData(ab, res, rej);
          if (p && p.then) p.then(res, rej);
        }).then((buffer) => ({ buffer }), () => { this.noDecode = true; return asBlob(copy); });
      })
      .catch((e) => { if (e.name !== "AbortError") console.warn("tts failed:", e.message); return null; });
  }

  async _pump() {
    this.items.slice(0, 2).forEach((it) => it.p || this._fetch(it)); // prefetch the next sentence
    if (this.src || this._starting || !this.items.length) return;
    this._starting = true;
    const gen = this.gen;
    const item = this.items[0];
    const got = await item.p;
    this._starting = false;
    if (gen !== this.gen) return;
    this.items.shift();
    if (!got) { if (this.items.length) this._pump(); else this.onIdle(); return; }
    if (got.blob) { this._playElement(got.blob); return; }
    const buffer = got.buffer;
    const ctx = this._ensure();
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.analyser);
    src.onended = () => {
      if (this.src !== src) return;
      this.src = null;
      if (this.items.length) this._pump(); else this.onIdle();
    };
    this.src = src;
    src.start();
    // watchdog: if the audio engine never reports the end (suspended device), don't stay "Speaking" forever
    setTimeout(() => { if (this.src === src) { try { src.stop(); } catch { /* ended */ } src.onended?.(); } },
      (buffer.duration + 2) * 1000);
    this.onStart();
  }

  _playElement(blob) {
    const url = URL.createObjectURL(blob);
    const el = new Audio(url);
    const handle = { el, stop: () => { el.pause(); done(); } };
    const done = () => {
      el.onended = el.onerror = null;
      URL.revokeObjectURL(url);
      if (this.src !== handle) return;
      this.src = null;
      if (this.items.length) this._pump(); else this.onIdle();
    };
    el.onended = el.onerror = done;
    this.src = handle;
    el.play().then(() => this.onStart(), done);
  }

  stop() {
    this.gen++;
    this.items.forEach((it) => it.ctrl?.abort());
    this.items = [];
    this._starting = false;
    const s = this.src;
    this.src = null;
    if (s) { try { s.stop(); } catch { /* already stopped */ } }
  }
}

// ---------- Conversation loop (VAD + barge-in) ----------
// States: off -> listening -> capturing -> (app: thinking/speaking) -> listening ...
export class Conversation {
  constructor(mic, player, { onUtterance, onState, onBargeCheck, onAutoOff }) {
    this.mic = mic;
    this.player = player;
    this.rec = new Recorder(mic);
    this.cb = { onUtterance, onState, onBargeCheck, onAutoOff };
    this.on = false;
    this.muted = false; // the user muted the mic: nothing is detected or recorded
    this.asleep = false; // only listening for "wake up KURAMA": short phrases only, no auto-off
    this.state = "off";
    this.timer = 0;
    this.floor = 0.006;
    this.MIN_SPEECH_MS = 300; // shorter bursts are clicks/bumps/noise, not words
    this.END_SILENCE_MS = 1000; // a short pause mid-sentence ("open ... Spotify") doesn't end the request
    this.MAX_UTTERANCE_MS = 30000;
    this.RESTART_IDLE_MS = 8000; // restart the recorder during long silences (keeps uploads small)
    this.AUTO_OFF_MS = 120000;
    this.thrMult = 3; this.thrMin = 0.016; // speech must be this much louder than the room (sensitivity 5)
  }

  // Settings -> Voice: sens 1 (noisy room: only clear speech) .. 10 (quiet voice), pause before sending (s),
  // the shortest sound that counts as speech (ms)
  applyVoice(v) {
    const s = Math.max(1, Math.min(10, Number(v.sens) || 5));
    this.thrMult = 3 * Math.pow(1.18, 5 - s);
    this.thrMin = 0.016 * Math.pow(1.25, 5 - s);
    this.END_SILENCE_MS = Math.round(Math.max(0.5, Math.min(3, Number(v.pause) || 1)) * 1000);
    this.MIN_SPEECH_MS = Math.max(100, Math.min(800, Number(v.minMs) || 300));
  }
  threshold() { return Math.max(this.floor * this.thrMult, this.thrMin); }

  _set(s) { this.state = s; this.cb.onState?.(s); }

  async start() {
    await this.mic.start();
    this.mic.setMuted(this.muted);
    this.on = true;
    this.lastSpeech = performance.now();
    this.lastTick = 0;
    this.timer = setInterval(() => this._tick(), 50);
    this.listen();
  }

  stop() {
    this.on = false;
    this.mic.setMuted(false);
    clearInterval(this.timer);
    this.rec.cancel();
    this._set("off");
  }

  listen() {
    if (!this.on) return;
    this.rec.cancel();
    this.rec.start();
    this.speechMs = 0; this.silenceMs = 0; this.started = false;
    this.bRec = false; this.bSpeech = 0; this.bSil = 0; this.bOn = false;
    this._set(this.asleep ? "sleeping" : "listening");
  }

  mute(on) {
    this.muted = !!on;
    if (this.on) this.mic.setMuted(this.muted); // (the mic itself stays usable for dictation when talk mode is off)
    if (this.muted) { this.rec.cancel(); this.bRec = false; if (this.on) this._set(this.asleep ? "sleeping" : "listening"); }
    else if (this.on && this.state !== "thinking") this.listen();
  }

  sleep(on) { this.asleep = !!on; this.lastSpeech = performance.now(); if (this.on && this.state !== "thinking") this.listen(); }

  waiting() { if (this.on) this._set("thinking"); } // app is busy (stt / chat / speaking)

  async _end() {
    this._set("thinking");
    const blob = await this.rec.stop();
    if (!this.on) return;
    if (!blob || blob.size < 1500) { this.listen(); return; }
    this.cb.onUtterance?.(blob);
  }

  _tick() {
    if (!this.on || this.muted) return;
    // real elapsed time: when the page is busy drawing, ticks come late, and counting each as 50 ms made
    // speech look too short (ignored) and pauses too long (cut off)
    const now = performance.now(), dt = this.lastTick ? Math.min(250, now - this.lastTick) : 50;
    this.lastTick = now;
    const rms = this.mic.rms();
    if (this.state === "listening" || this.state === "capturing" || this.state === "sleeping") {
      const thr = this.threshold();
      if (!this.started && rms < thr) this.floor = this.floor * 0.97 + rms * 0.03; // adaptive noise floor
      if (rms > thr) {
        this.speechMs += dt; this.silenceMs = 0;
        if (!this.started && this.speechMs >= this.MIN_SPEECH_MS) { this.started = true; this.capT0 = now; if (!this.asleep) this._set("capturing"); }
        if (this.started) this.lastSpeech = now;
      } else {
        if (this.started) this.silenceMs += dt;
        else this.speechMs = Math.max(0, this.speechMs - dt);
      }
      if (this.asleep && this.started && now - this.capT0 > 5000) { this.listen(); return; } // long talk: not a wake phrase
      if (this.started && (this.silenceMs >= this.END_SILENCE_MS || now - this.capT0 > this.MAX_UTTERANCE_MS)) {
        this._end();
      } else if (!this.started && !this.speechMs && now - this.rec.t0 > this.RESTART_IDLE_MS) {
        this.rec.cancel(); this.rec.start(); // only in real silence: never cut off the start of a word
      }
      if (!this.asleep && !this.started && now - this.lastSpeech > this.AUTO_OFF_MS) { this.lastSpeech = now; this.cb.onAutoOff?.(); }
    } else if (this.player.playing && !this.asleep) {
      // While KURAMA speaks it is NOT cut off by noise or echo: a loud stretch is recorded and checked as words
      // (onBargeCheck): "stop" stops it, a real new request takes over, anything else is ignored.
      if (!this.bRec) { this.rec.cancel(); this.rec.start(); this.bRec = true; this.bSpeech = 0; this.bSil = 0; this.bOn = false; }
      const thr = Math.max(this.floor * 6, 0.045);
      if (rms > thr) { this.bSpeech += dt; this.bSil = 0; if (!this.bOn && this.bSpeech >= 200) this.bOn = true; }
      else if (this.bOn) this.bSil += dt;
      else { this.bSpeech = Math.max(0, this.bSpeech - dt); if (now - this.rec.t0 > 6000) { this.rec.cancel(); this.rec.start(); } }
      if (this.bOn && (this.bSil >= 600 || this.bSpeech > 6000)) {
        this.bOn = false; this.bSpeech = 0; this.bSil = 0;
        this.rec.stop().then((blob) => { if (this.on && this.player.playing) { this.rec.start(); } this.cb.onBargeCheck?.(blob); });
      }
    } else if (this.bRec) { this.bRec = false; this.rec.cancel(); }
  }
}
