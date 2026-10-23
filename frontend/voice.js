// Browser-side voice: microphone (with the browser's echo cancellation), recorder, sentence splitter,
// a sentence-by-sentence TTS player (fetches /tts, decodes, plays gaplessly through an AnalyserNode so
// the hologram can pulse with the voice), and the Conversation-mode VAD loop with barge-in.

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

// ---------- microphone ----------
export class Mic {
  constructor() { this.stream = null; }
  get open() { return !!this.stream; }

  async start() {
    if (this.stream) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone needs a secure page (https or localhost).");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    const ctx = audioCtx();
    this.src = ctx.createMediaStreamSource(this.stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.buf = new Float32Array(this.analyser.fftSize);
    this.src.connect(this.analyser);
  }

  stop() {
    if (!this.stream) return;
    this.stream.getTracks().forEach((t) => t.stop());
    try { this.src.disconnect(); } catch { /* ignore */ }
    this.stream = null;
  }

  rms() { return this.stream ? rmsOf(this.analyser, this.buf) : 0; }
  level() { return Math.min(1, this.rms() * 9); }
}

// ---------- recorder ----------
const MIME = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/mp4"];

export class Recorder {
  constructor(mic) { this.mic = mic; this.mr = null; this.t0 = 0; }
  get active() { return !!this.mr && this.mr.state === "recording"; }

  start() {
    const mime = MIME.find((m) => window.MediaRecorder?.isTypeSupported?.(m));
    this.chunks = [];
    this.mr = new MediaRecorder(this.mic.stream, mime ? { mimeType: mime } : undefined);
    this.mr.ondataavailable = (e) => { if (e.data && e.data.size) this.chunks.push(e.data); };
    this.mr.start(250);
    this.t0 = performance.now();
  }

  stop() {
    return new Promise((resolve) => {
      const mr = this.mr;
      if (!mr || mr.state === "inactive") return resolve(null);
      mr.onstop = () => resolve(new Blob(this.chunks, { type: (mr.mimeType || "audio/webm").split(";")[0] }));
      mr.stop();
      this.mr = null;
    });
  }

  cancel() {
    if (this.mr && this.mr.state !== "inactive") { this.mr.onstop = null; this.mr.stop(); }
    this.mr = null;
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

  level() { return this.src && this.analyser ? Math.min(1, rmsOf(this.analyser, this.buf) * 5) : 0; }

  enqueue(text, lang, gen = this.gen) {
    if (gen !== this.gen || !text || !text.trim()) return;
    this.items.push({ text, lang, ctrl: null, p: null });
    this._pump();
  }

  _fetch(item) {
    item.ctrl = new AbortController();
    const ctx = this._ensure();
    item.p = this.api.tts(item.text, item.lang, item.ctrl.signal)
      .then((ab) => ctx.decodeAudioData(ab))
      .catch((e) => { if (e.name !== "AbortError") console.warn("tts failed:", e.message); return null; });
  }

  async _pump() {
    this.items.slice(0, 2).forEach((it) => it.p || this._fetch(it)); // prefetch the next sentence
    if (this.src || this._starting || !this.items.length) return;
    this._starting = true;
    const gen = this.gen;
    const item = this.items[0];
    const buffer = await item.p;
    this._starting = false;
    if (gen !== this.gen) return;
    this.items.shift();
    if (!buffer) { if (this.items.length) this._pump(); else this.onIdle(); return; }
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
