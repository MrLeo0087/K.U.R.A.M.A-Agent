// Browser-side voice: microphone (with the browser's echo cancellation), recorder, sentence splitter,
// a sentence-by-sentence TTS player (fetches /tts, decodes, plays gaplessly through an AnalyserNode so
// the orb can pulse with the voice), and the Conversation-mode VAD loop with barge-in.

let _ctx = null;
export function audioCtx() {
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (_ctx.state === "suspended") _ctx.resume().catch(() => {});
  return _ctx;
}

function rmsOf(analyser, buf) {
  analyser.getFloatTimeDomainData(buf);
  let s = 0;
  for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
  return Math.sqrt(s / buf.length);
}

// ---------- WAV encoding (pure; unit-tested with Node in tests/test_frontend_js.py) ----------
// Downsample Float32 PCM to `outRate` mono (box filter: averages the samples of each output step) and
// encode it as 16-bit PCM WAV. /api/v1/stt accepts audio/wav, so no MediaRecorder is needed anywhere
// (WebKitGTK, used by the wallpaper window, has none).
export function downsample(pcm, inRate, outRate = 16000) {
  if (outRate >= inRate) return pcm;
  const ratio = inRate / outRate;
  const out = new Float32Array(Math.floor(pcm.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(i * ratio), b = Math.min(pcm.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = a; j < b; j++) s += pcm[j];
    out[i] = b > a ? s / (b - a) : 0;
  }
  return out;
}

export function encodeWav(pcm, inRate, outRate = 16000) {
  const data = downsample(pcm, inRate, outRate);
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
let _tapModule = null;

export class Mic {
  constructor() { this.stream = null; this.sinks = new Set(); }
  get open() { return !!this.stream; }

  async start() {
    if (this.stream) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(window.isSecureContext === false
        ? "Microphone needs a secure page: open http://127.0.0.1:8000 (or https)."
        : "Microphone not available in this window — open http://127.0.0.1:8000 in a browser, or update the wallpaper app.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    const ctx = audioCtx();
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
      if (!_tapModule) {
        const url = URL.createObjectURL(new Blob([TAP_WORKLET], { type: "application/javascript" }));
        _tapModule = ctx.audioWorklet.addModule(url).finally(() => URL.revokeObjectURL(url));
      }
      await _tapModule;
      this.tap = new AudioWorkletNode(ctx, "kurama-tap", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
      this.tap.port.onmessage = (e) => feed(e.data);
    } catch {
      _tapModule = null;
      this.tap = ctx.createScriptProcessor(4096, 1, 1);
      this.tap.onaudioprocess = (e) => { if (this.sinks.size) feed(new Float32Array(e.inputBuffer.getChannelData(0))); };
    }
    this.src.connect(this.tap);
    this.tap.connect(this.mute);
    this.rate = ctx.sampleRate;
    this.stream = stream;
  }

  stop() {
    if (!this.stream) return;
    this.stream.getTracks().forEach((t) => t.stop());
    for (const n of [this.src, this.tap, this.mute]) { try { n.disconnect(); } catch { /* ignore */ } }
    if (this.tap?.port) this.tap.port.onmessage = null;
    this.tap = null;
    this.stream = null;
  }

  rms() { return this.stream ? rmsOf(this.analyser, this.buf) : 0; }
  level() { return Math.min(1, this.rms() * 9); }
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
    if (!this.analyser) {
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

  enqueue(text, lang, gen = this.gen) {
    if (gen !== this.gen || !text || !text.trim()) return;
    this.items.push({ text, lang, ctrl: null, p: null });
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
  constructor(mic, player, { onUtterance, onState, onBargeIn, onAutoOff }) {
    this.mic = mic;
    this.player = player;
    this.rec = new Recorder(mic);
    this.cb = { onUtterance, onState, onBargeIn, onAutoOff };
    this.on = false;
    this.state = "off";
    this.timer = 0;
    this.floor = 0.006;
    this.MIN_SPEECH_MS = 160;
    this.END_SILENCE_MS = 900;
    this.MAX_UTTERANCE_MS = 30000;
    this.RESTART_IDLE_MS = 8000; // restart the recorder during long silences (keeps uploads small)
    this.AUTO_OFF_MS = 120000;
  }

  _set(s) { this.state = s; this.cb.onState?.(s); }

  async start() {
    await this.mic.start();
    this.on = true;
    this.lastSpeech = performance.now();
    this.timer = setInterval(() => this._tick(), 50);
    this.listen();
  }

  stop() {
    this.on = false;
    clearInterval(this.timer);
    this.rec.cancel();
    this._set("off");
  }

  listen() {
    if (!this.on) return;
    this.rec.cancel();
    this.rec.start();
    this.speechMs = 0; this.silenceMs = 0; this.started = false; this.bargeMs = 0;
    this._set("listening");
  }

  waiting() { if (this.on) this._set("thinking"); } // app is busy (stt / chat / speaking)

  async _end() {
    this._set("thinking");
    const blob = await this.rec.stop();
    if (!this.on) return;
    if (!blob || blob.size < 1500) { this.listen(); return; }
    this.cb.onUtterance?.(blob);
  }

  _tick() {
    if (!this.on) return;
    const now = performance.now(), dt = 50;
    const rms = this.mic.rms();
    if (this.state === "listening" || this.state === "capturing") {
      const thr = Math.max(this.floor * 3, 0.012);
      if (!this.started && rms < thr) this.floor = this.floor * 0.97 + rms * 0.03; // adaptive noise floor
      if (rms > thr) {
        this.speechMs += dt; this.silenceMs = 0;
        if (!this.started && this.speechMs >= this.MIN_SPEECH_MS) { this.started = true; this.capT0 = now; this._set("capturing"); }
        if (this.started) this.lastSpeech = now;
      } else {
        if (this.started) this.silenceMs += dt;
        else this.speechMs = Math.max(0, this.speechMs - dt);
      }
      if (this.started && (this.silenceMs >= this.END_SILENCE_MS || now - this.capT0 > this.MAX_UTTERANCE_MS)) {
        this._end();
      } else if (!this.started && now - this.rec.t0 > this.RESTART_IDLE_MS) {
        this.rec.cancel(); this.rec.start();
      }
      if (!this.started && now - this.lastSpeech > this.AUTO_OFF_MS) { this.stop(); this.cb.onAutoOff?.(); }
    } else if (this.player.playing) {
      // barge-in: louder than the noise floor by a wide margin (echo cancellation removes most of
      // Jarvis's own voice) for ~280 ms -> stop talking and listen.
      const thr = Math.max(this.floor * 6, 0.045);
      this.bargeMs = rms > thr ? this.bargeMs + dt : Math.max(0, this.bargeMs - dt);
      if (this.bargeMs >= 280) {
        this.bargeMs = 0;
        this.player.stop();
        this.cb.onBargeIn?.();
        this.lastSpeech = now;
        this.listen();
      }
    }
  }
}
