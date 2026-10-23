// KURAMA UI controller. Talks to the Jarvis backend ONLY through the HTTP API (api.js).
import { Api } from "./api.js";
import { loadSettings, saveSettings } from "./config.js";
import { Orb } from "./orb.js";
import { Conversation, Mic, Player, Recorder, SentenceSplitter, audioCtx } from "./voice.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = loadSettings();
const lowPowerOn = () => (S.lowPower === null ? reducedMotion : !!S.lowPower);
const api = new Api(() => S);
if (params.get("wallpaper") === "1") document.body.classList.add("wallpaper");

// ---------- orb ----------
const orb = new Orb($("orb-canvas"), { halo: document.querySelector("#orb .halo"), lowPower: lowPowerOn(), reducedMotion });
document.body.classList.toggle("low-power", lowPowerOn());
orb.start();

// ---------- voice plumbing ----------
const mic = new Mic();
const recorder = new Recorder(mic);
const player = new Player(api, { onStart: () => updateState(), onIdle: () => { updateState(); maybeResume(); } });
const conv = new Conversation(mic, player, {
  onUtterance: (blob) => handleUtterance(blob),
  onState: () => updateState(),
  onBargeIn: () => abortChat(),
  onAutoOff: () => { mic.stop(); setMode("text"); toast("Conversation turned off after 2 minutes of silence."); },
});
orb.levelFn = () => (player.playing ? player.level() : mic.open ? mic.level() : 0);

let mode = "text"; // text | mic | conv
let recording = false;
let recTimer = 0;
let recSecs = 0;
let busy = false; // a chat turn is streaming
let sttBusy = false;
let chatCtrl = null;
let online = null;
let errUntil = 0;
let paused = false; // wallpaper covered by a window (window.kuramaPause)
let pendingConfirm = null; // conversation mode: confirmation answered by voice
const bubbles = new Map(); // confirm id -> bubble
const FORCE_ORB = params.get("debug") === "1" ? params.get("orb") : null; // ?debug=1&orb=thinking (visual checks)

function orbState() {
  if (player.playing) return "speaking";
  if (recording || conv.state === "listening" || conv.state === "capturing") return "listening";
  if (busy || sttBusy) return "thinking";
  return "idle";
}

function stateText(st) {
  if (online === false) return "Offline — check the API in settings";
  if (online === null) return "Connecting…";
  if (st === "speaking") return mode === "conv" ? "Speaking — talk over me to interrupt" : "Speaking — click the orb to stop";
  if (st === "listening") {
    if (recording) return `Recording ${recSecs}s — click the mic to send`;
    return conv.state === "capturing" ? "Hearing you…" : "Listening — speak anytime";
  }
  if (st === "thinking") return sttBusy ? "Transcribing…" : "Thinking…";
  if (mode === "mic") return "Mic ready — click the mic to talk";
  return "Voice off — type below";
}

const CHIP = { idle: "Ready", listening: "Listening", thinking: "Thinking…", speaking: "Speaking" };

function updateState() {
  const st = orbState();
  orb.setState(FORCE_ORB || st);
  document.body.dataset.state = performance.now() < errUntil ? "error" : st;
  $("voice-state").textContent = stateText(st);
  const chip = $("chat-state");
  chip.className = "chat-state " + (online === false ? "bad" : st === "thinking" ? "busy" : st === "idle" ? (online ? "ok" : "") : "live");
  chip.lastElementChild.textContent = online === false ? "Offline" : online === null ? "Connecting" : CHIP[st];
  $("send").classList.toggle("stop", busy);
  $("send").setAttribute("aria-label", busy ? "Stop" : "Send");
  $("m-mic").classList.toggle("rec", recording);
  $("m-conv").classList.toggle("live", mode === "conv" && conv.on);
}

function flashError() {
  errUntil = performance.now() + 1400;
  orb.flash();
  updateState();
  setTimeout(updateState, 1450);
}

function maybeResume() {
  if (mode !== "conv" || !conv.on || player.active || sttBusy) return;
  if (busy && !pendingConfirm) return;
  if (conv.state === "listening" || conv.state === "capturing") return;
  conv.listen();
}

function abortChat() { chatCtrl?.abort(); }

// ---------- modes ----------
function setMode(m) {
  if (mode === "conv" && m !== "conv" && conv.on) { conv.stop(); player.stop(); mic.stop(); }
  if (mode === "mic" && m !== "mic" && recording) { recording = false; recorder.cancel(); mic.stop(); clearInterval(recTimer); }
  mode = m;
  for (const [id, v] of [["m-text", "text"], ["m-mic", "mic"], ["m-conv", "conv"]]) $(id).setAttribute("aria-pressed", String(mode === v));
  $("input").placeholder = mode === "conv" && conv.on ? "Just talk — or type here…" : mode === "mic" ? "Click the mic to talk, or type…" : "Ask KURAMA anything…";
  updateState();
}

async function toggleMic() {
  audioCtx();
  if (mode === "conv") setMode("text");
  if (!recording) {
    try { await mic.start(); } catch (e) { toast(micError(e)); flashError(); return; }
    player.stop();
    recorder.start();
    recording = true;
    recSecs = 0;
    const t0 = Date.now();
    recTimer = setInterval(() => {
      recSecs = Math.floor((Date.now() - t0) / 1000);
      updateState();
      if (recSecs >= 60) toggleMic(); // safety cap
    }, 500);
    setMode("mic");
    return;
  }
  recording = false;
  clearInterval(recTimer);
  const blob = await recorder.stop();
  mic.stop();
  setMode("mic");
  if (!blob || blob.size < 1200) { toast("Didn't catch anything."); return; }
  const r = await transcribe(blob);
  if (r?.text) sendChat(r.text, { voice: true, lang: r.lang, speak: S.voiceReplies });
}

async function toggleConv() {
  audioCtx();
  if (mode === "conv" && conv.on) { setMode("text"); return; }
  if (recording) setMode("text");
  mode = "conv";
  try { await conv.start(); } catch (e) { toast(micError(e)); flashError(); setMode("text"); return; }
  setMode("conv");
}

function micError(e) {
  if (e && e.name === "NotAllowedError") return "Microphone permission denied.";
  if (e && e.name === "NotFoundError") return "No microphone found.";
  return (e && e.message) || "Microphone unavailable.";
}

async function transcribe(blob) {
  sttBusy = true;
  updateState();
  try {
    const r = await api.stt(blob, S.lang);
    r.text = (r.text || "").trim();
    if (!r.text) toast("Didn't catch that.");
    return r;
  } catch (e) {
    toast("Speech-to-text failed: " + e.message);
    flashError();
    if (e.status === 401) openSettings("This API needs a token.");
    return null;
  } finally {
    sttBusy = false;
    updateState();
  }
}

const YES = /^(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|confirm|please do|haan|han|ha|ho|हो|हाँ|हां|हजुर|ठीक|गर)/i;
const NO = /^(no|nope|nah|don'?t|do not|cancel|stop|never|nahi|hoina|होइन|नाइ|नहीं|नही|नगर)/i;

async function handleUtterance(blob) {
  conv.waiting();
  const r = await transcribe(blob);
  if (!r || !r.text) { maybeResume(); return; }
  if (pendingConfirm) {
    const t = r.text.replace(/^[\s,.!?"']+/, "");
    const yes = NO.test(t) ? false : YES.test(t) ? true : null;
    if (yes === null) { player.enqueue("Please say yes or no.", r.lang); return; }
    addUser(r.text, true);
    answerConfirm(pendingConfirm, yes);
    return;
  }
  sendChat(r.text, { voice: true, lang: r.lang, speak: true });
}

// ---------- chat ----------
const log = $("log");
const MAX_MSGS = 60; // keeps the DOM small on an all-day page
const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 90;
const scrollDown = (force) => { if (force || nearBottom()) log.scrollTop = log.scrollHeight; };
const hhmm = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Minimal SAFE markdown: everything is escaped first; only `code`, **bold**, headings, bullets, links, ``` blocks.
function inlineMd(t) {
  let h = esc(t);
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*\n][^*]*?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/^#{1,6}\s+(.+)$/gm, "<strong>$1</strong>");
  h = h.replace(/^\s*[-*•]\s+/gm, "• ");
  h = h.replace(/(^|[\s(])(https?:\/\/[^\s<>"')]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  return h.replace(/\n/g, "<br>");
}

export function renderMarkdown(src) {
  return String(src).split("```").map((part, i) => {
    if (i % 2 === 0) return inlineMd(part);
    const code = part.replace(/^[\w+.-]*\n/, "");
    return `<pre><code>${esc(code)}</code></pre>`;
  }).join("");
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function trim() { while (log.children.length > MAX_MSGS) log.firstElementChild.remove(); }

function addUser(text, voice = false) {
  $("welcome")?.remove();
  const m = el("div", "msg user" + (voice ? " voice" : ""));
  const body = el("div", "body");
  body.append(el("div", "who", `You · ${hhmm()}`));
  const t = el("div", "text");
  t.textContent = text;
  body.append(t);
  m.append(body);
  log.append(m);
  trim();
  scrollDown(true);
}

class BotBubble {
  constructor() {
    $("welcome")?.remove();
    this.text = "";
    this.root = el("div", "msg bot");
    this.root.append(el("div", "avatar", "K"));
    this.body = el("div", "body");
    this.who = el("div", "who", `KURAMA · ${hhmm()}`);
    this.chips = el("div", "chips");
    this.bubble = el("div", "text", '<span class="dots" aria-label="thinking"><i></i><i></i><i></i></span>');
    this.content = el("div", "content");
    this.meta = el("div", "meta");
    this.body.append(this.who, this.chips, this.bubble, this.meta);
    this.root.append(this.body);
    log.append(this.root);
    trim();
    this.timer = 0;
    scrollDown(true);
  }
  _show() { if (!this.content.isConnected) { this.bubble.innerHTML = ""; this.bubble.append(this.content); } }
  append(t) {
    this.text += t;
    if (this.timer) return;
    this.timer = setTimeout(() => { this.timer = 0; this._render(); }, 50); // throttle re-renders
  }
  _render() { this._show(); this.content.innerHTML = renderMarkdown(this.text); scrollDown(); }
  tool(ev) {
    const c = el("span", "chip tool " + (ev.ok ? "ok" : "fail"));
    c.textContent = `${ev.name}${ev.ms != null ? " · " + ev.ms + " ms" : ""}`;
    c.title = ev.ok ? "tool ran" : "tool failed or was declined";
    this.chips.append(c);
    scrollDown();
  }
  confirm(ev) {
    const card = el("div", "confirm");
    card.append(el("div", "q", esc(ev.prompt)));
    const row = el("div", "row");
    const yes = el("button", "btn yes", "Yes"), no = el("button", "btn no", "No");
    yes.type = no.type = "button";
    yes.onclick = () => answerConfirm(ev.id, true);
    no.onclick = () => answerConfirm(ev.id, false);
    row.append(yes, no);
    card.append(row);
    this.body.insertBefore(card, this.meta);
    this.cards = this.cards || {};
    this.cards[ev.id] = card;
    bubbles.set(ev.id, this);
    yes.focus({ preventScroll: true });
    scrollDown(true);
  }
  settle(id, text) {
    const card = this.cards?.[id];
    if (!card) return;
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    card.classList.add("settled");
    card.append(el("div", "verdict", esc(text)));
    bubbles.delete(id);
  }
  error(t) { this._show(); this.content.append(el("div", "err", esc(t))); }
  note(t) { this._show(); this.content.append(el("div", "note", esc(t))); }
  done(ev) {
    clearTimeout(this.timer); this.timer = 0;
    if (ev.text) this.text = ev.text;
    if (this.text) this._render();
    const route = ev.route && typeof ev.route === "object" ? [].concat(ev.route.groups || []).join("+") || ev.route.method : ev.route;
    const bits = [route && ["route", route], ev.tier && ["tier", ev.tier], ["tok", ev.tokens ?? 0], ev.ms != null && ["ms", ev.ms], ev.lang && ["lang", ev.lang]];
    this.meta.innerHTML = bits.filter(Boolean).map(([k, v]) => `<span class="chip"><b>${esc(k)}</b> ${esc(v)}</span>`).join("");
  }
  finish() {
    clearTimeout(this.timer); this.timer = 0;
    if (this.text) this._render();
    else if (!this.content.isConnected) this.bubble.innerHTML = '<span class="note">(no reply)</span>';
    scrollDown();
  }
}

async function answerConfirm(id, yes) {
  if (pendingConfirm === id) pendingConfirm = null;
  bubbles.get(id)?.settle(id, yes ? "Approved" : "Declined");
  try { await api.confirm(id, yes); } catch (e) { toast("Confirmation failed: " + e.message); }
}

async function sendChat(text, { voice = false, lang = null, speak = false } = {}) {
  text = (text || "").trim();
  if (!text) return;
  if (busy) { // e.g. a barge-in utterance while the previous turn is still closing
    abortChat();
    for (let i = 0; busy && i < 40; i++) await new Promise((r) => setTimeout(r, 50));
    if (busy) return;
  }
  busy = true;
  addUser(text, voice);
  const bot = new BotBubble();
  const ctrl = new AbortController();
  chatCtrl = ctrl;
  if (speak) player.stop(); // a new turn replaces anything still being said
  const gen = player.gen;
  const split = speak ? new SentenceSplitter() : null;
  const hint = lang && lang !== "auto" ? lang : S.lang !== "auto" ? S.lang : null;
  updateState();
  try {
    for await (const ev of api.chat(text, { mode: voice ? "voice" : "text", lang: hint, signal: ctrl.signal })) {
      switch (ev.type) {
        case "delta":
          bot.append(ev.text);
          if (split) split.feed(ev.text).forEach((s) => player.enqueue(s, hint, gen));
          break;
        case "tool": bot.tool(ev); break;
        case "confirm":
          bot.confirm(ev);
          if (speak) {
            if (mode === "conv" && conv.on) pendingConfirm = ev.id;
            player.enqueue(ev.prompt + (pendingConfirm ? " Please say yes or no." : ""), hint, gen);
          }
          break;
        case "confirm_timeout":
          bot.settle(ev.id, "No answer in time, so I declined.");
          if (pendingConfirm === ev.id) pendingConfirm = null;
          break;
        case "error": bot.error(ev.text); flashError(); break;
        case "done":
          if (split) { const rest = split.flush(); if (rest) player.enqueue(rest, hint || ev.lang, gen); }
          bot.done(ev);
          break;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") bot.note("Stopped.");
    else {
      bot.error(e.status === 401 ? "The API needs a token (open settings)." : "Can't reach Jarvis: " + e.message);
      flashError();
      if (e.status === 401) openSettings("This API needs a token.");
      setConn(false);
    }
  } finally {
    busy = false;
    chatCtrl = null;
    pendingConfirm = null;
    bot.finish();
    updateState();
    maybeResume();
  }
}

// composer
const input = $("input");
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight + 2, 140) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); }
});
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if (busy) { abortChat(); player.stop(); return; }
  const t = input.value.trim();
  if (!t) return;
  input.value = "";
  autosize();
  const speak = mode === "conv" ? conv.on : mode === "mic" && S.voiceReplies;
  if (speak) audioCtx();
  sendChat(t, { voice: speak, lang: S.lang, speak });
});
$("m-text").onclick = () => { setMode("text"); input.focus(); };
$("m-mic").onclick = () => toggleMic();
$("m-conv").onclick = () => toggleConv();
$("btn-clear").onclick = () => { log.innerHTML = ""; log.append(welcome()); };
$("orb").onclick = () => { if (player.active) player.stop(); else if (busy) abortChat(); updateState(); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
    if (player.active) player.stop();
    else if (busy) abortChat();
    else if (conv.on) setMode("text");
    updateState();
  }
  if (e.altKey && (e.key === "m" || e.key === "M")) { e.preventDefault(); toggleMic(); }
  if (e.altKey && (e.key === "c" || e.key === "C")) { e.preventDefault(); toggleConv(); }
});

function welcome() {
  const w = el("div", "welcome");
  w.id = "welcome";
  w.innerHTML = "<p>Type, tap the mic, or start a hands-free conversation.</p>";
  const row = el("div", "suggest");
  for (const s of ["What time is it?", "What's using my RAM?", "Weather in Kathmandu", "What do you remember about me?"]) {
    const b = el("button", "chip sug");
    b.type = "button";
    b.textContent = s;
    b.onclick = () => sendChat(s, { lang: S.lang });
    row.append(b);
  }
  w.append(row);
  return w;
}
log.append(welcome());

// ---------- numbers: set only when the shown text changes (no per-frame tweening: every animated frame
// costs real CPU in WebKitGTK, and this page runs all day) ----------
function tweenTo(id, value, decimals = 0) {
  const node = $(id);
  const t = value == null || Number.isNaN(value) ? "–" : Number(value).toFixed(decimals);
  if (node.textContent !== t) node.textContent = t;
}

// ---------- sparklines (redrawn once per sample) ----------
class Spark {
  constructor(canvas, series, max = 100, points = 60) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.series = series.map((s) => ({ ...s, data: Array(points).fill(0) }));
    this.max = max;
    this.points = points;
  }
  push(values) {
    values.forEach((v, i) => { const d = this.series[i].data; d.push(v || 0); d.shift(); });
    this.draw();
  }
  draw() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = this.c.clientWidth, h = this.c.clientHeight;
    if (!w || !h) return;
    if (this.c.width !== Math.round(w * dpr)) { this.c.width = Math.round(w * dpr); this.c.height = Math.round(h * dpr); }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const step = w / (this.points - 1);
    const max = typeof this.max === "function" ? this.max(this.series) : this.max;
    for (const s of this.series) {
      const pts = s.data.map((v, i) => [i * step, h - 2 - (Math.min(v, max) / max) * (h - 6)]);
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length - 1; i++) {
        ctx.quadraticCurveTo(pts[i][0], pts[i][1], (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2);
      }
      ctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
      ctx.strokeStyle = s.color; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, s.fill); g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g; ctx.fill();
      const [lx, ly] = pts[pts.length - 1]; // live dot
      ctx.fillStyle = s.color;
      ctx.beginPath(); ctx.arc(lx - 1.5, ly, 2, 0, Math.PI * 2); ctx.fill();
    }
  }
}
const cpuSpark = new Spark($("cpu-spark"), [{ color: "#ff8a2b", fill: "rgba(255,122,26,0.26)" }]);
const netSpark = new Spark($("net-spark"),
  [{ color: "#ffb347", fill: "rgba(255,179,71,0.20)" }, { color: "#6fb7ff", fill: "rgba(111,183,255,0.12)" }],
  (series) => Math.max(65536, ...series.flatMap((s) => s.data)) * 1.15);
addEventListener("resize", () => { cpuSpark.draw(); netSpark.draw(); });

// ---------- status ----------
let es = null, pollTimer = 0, retryTimer = 0, procSort = "rss", lastStatus = null, lastJobsKey = "";

function setConn(ok) {
  if (online === ok) return;
  online = ok;
  $("offline").hidden = ok;
  $("composer").classList.toggle("offline-mode", !ok);
  updateState();
}

const fmtGb = (g) => (g == null ? "–" : g >= 100 ? g.toFixed(0) : g.toFixed(1));
const fmtRate = (bps) => (bps >= 1048576 ? `${(bps / 1048576).toFixed(1)} MB/s` : bps >= 1024 ? `${(bps / 1024).toFixed(0)} KB/s` : `${Math.round(bps || 0)} B/s`);
function fmtDur(s) {
  if (s == null) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
const fmtK = (n) => (n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? (n / 1e3).toFixed(1) + "k" : String(n));

function setBar(id, pct, cls = "") {
  // transition only on a visible (>= 1 %) change, so bars don't animate every 2 s for nothing
  const b = $(id);
  const v = Math.round(Math.max(0, Math.min(100, pct || 0)));
  if (b.dataset.v !== String(v)) { b.dataset.v = String(v); b.style.transform = `scaleX(${v / 100})`; }
  if (b.className !== cls) b.className = cls;
}

function renderStatus(s) {
  lastStatus = s;
  setConn(true);
  const cpu = s.cpu || {};
  tweenTo("cpu", cpu.percent ?? 0);
  cpuSpark.push([cpu.percent ?? 0]);
  $("cpu-freq").textContent = cpu.freq_ghz ? `${cpu.freq_ghz.toFixed(2)} GHz` : `${cpu.count ?? "?"} cores`;
  $("cpu-temp").textContent = cpu.temp_c != null ? `${Math.round(cpu.temp_c)} °C` : "– °C";
  $("cpu-load").textContent = cpu.load?.length ? `load ${cpu.load[0].toFixed(2)}` : "";

  const ram = s.ram || {};
  tweenTo("ram-used", ram.used_gb ?? 0, 1);
  $("ram-total").textContent = fmtGb(ram.total_gb);
  tweenTo("ram", ram.percent ?? 0);
  tweenTo("swap", s.swap?.percent ?? 0);
  setBar("ram-bar", ram.percent, ram.percent >= 85 ? "hot" : "");

  const disk = s.disk || {};
  tweenTo("disk-used", disk.used_gb ?? 0);
  $("disk-total").textContent = disk.total_gb != null ? Math.round(disk.total_gb) : "–";
  setBar("disk-bar", disk.percent, disk.percent >= 90 ? "hot" : "");

  const bat = s.battery;
  $("bat-row").hidden = !bat;
  if (bat) {
    tweenTo("battery", bat.percent);
    setBar("battery-bar", bat.percent, !bat.plugged && bat.percent <= 20 ? "low" : "");
    $("charging").hidden = !bat.plugged;
    $("battery-time").textContent = bat.plugged ? (bat.percent >= 99 ? "Full · plugged in" : "Charging")
      : bat.secs_left != null ? `${fmtDur(bat.secs_left)} left` : "On battery";
  }

  const net = s.net || {};
  $("down").textContent = fmtRate(net.rx_bps);
  $("up").textContent = fmtRate(net.tx_bps);
  netSpark.push([net.rx_bps || 0, net.tx_bps || 0]);
  $("uptime").textContent = "up " + fmtDur(s.uptime?.system_s);

  const j = s.jarvis || {};
  $("t-rss").textContent = j.rss_mb != null ? Math.round(j.rss_mb) : "–";
  $("core-up").textContent = (j.agent_ready ? "agent ready" : j.agent_loaded ? "agent loading" : "agent idle") + " · " + fmtDur(j.uptime_s);
  const tk = s.tokens || {};
  $("t-tokens").textContent = fmtK(tk.today);
  $("t-calls").textContent = `${tk.calls ?? 0} calls`;
  const al = s.alerts || {};
  $("t-alerts").textContent = String(al.unread ?? 0);
  $("tile-alerts").classList.toggle("hot", (al.unread || 0) > 0);
  $("t-alerts-sub").textContent = al.recent?.[0] && al.unread ? al.recent[0].title : "all clear";

  renderJobs(s.jobs || {});
  renderProcs();
}

function renderJobs(jb) {
  const items = jb.items || [];
  const key = JSON.stringify(items);
  $("jobs-count").textContent = items.length ? `${jb.running || 0} running · ${jb.queued || 0} queued` : "";
  if (key === lastJobsKey) return; // only touch the DOM on change
  lastJobsKey = key;
  const ul = $("jobs");
  ul.innerHTML = "";
  if (!items.length) { ul.innerHTML = '<li class="empty">Nothing running</li>'; return; }
  for (const x of items) {
    const li = el("li");
    li.innerHTML = '<span class="p"></span><span class="q"></span><span class="s"></span>';
    li.querySelector(".p").textContent = `#${x.id}`;
    li.querySelector(".q").textContent = x.title || x.kind || "job";
    li.querySelector(".s").textContent = x.progress || x.status;
    li.title = "Open background jobs";
    li.onclick = () => openInfo("jobs");
    ul.append(li);
  }
}

function renderProcs() {
  const s = lastStatus;
  if (!s) return;
  const list = (procSort === "cpu" ? s.processes?.by_cpu : s.processes?.by_rss) || [];
  if (!list.length) return;
  const max = Math.max(0.1, ...list.map((p) => (procSort === "cpu" ? p.cpu : p.rss_mb)));
  const ul = $("procs");
  ul.dataset.sort = procSort;
  ul.innerHTML = list.map((p) => {
    const v = procSort === "cpu" ? p.cpu : p.rss_mb;
    const mem = p.rss_mb >= 1024 ? `${(p.rss_mb / 1024).toFixed(1)} GB` : `${Math.round(p.rss_mb)} MB`;
    return `<li title="pid ${p.pid}"><span class="n">${esc(p.name)}</span><span class="c">${p.cpu.toFixed(1)}%</span><span class="m">${mem}</span><i class="w" style="transform:scaleX(${(v / max).toFixed(3)})"></i></li>`;
  }).join("");
  $("procs-count").textContent = s.processes?.count ? `${s.processes.count} total` : "";
}

for (const b of document.querySelectorAll("[data-sort]")) {
  b.onclick = () => {
    procSort = b.dataset.sort;
    document.querySelectorAll("[data-sort]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderProcs();
  };
}

function stopStatus() {
  if (es) { es.close(); es = null; }
  clearInterval(pollTimer); pollTimer = 0;
  clearTimeout(retryTimer); retryTimer = 0;
}

async function pollOnce() {
  try { renderStatus(await api.status()); } catch (e) { setConn(false); if (e.status === 401) openSettings("This API needs a token."); }
}

function startStatus() {
  stopStatus();
  if (document.hidden || paused) return;
  try {
    es = api.statusStream();
    es.onmessage = (e) => { try { renderStatus(JSON.parse(e.data)); } catch { /* ignore */ } };
    es.onerror = () => {
      if (es) { es.close(); es = null; } // fall back to polling, retry the stream later
      if (!pollTimer) { pollOnce(); pollTimer = setInterval(pollOnce, 5000); }
      clearTimeout(retryTimer);
      retryTimer = setTimeout(startStatus, 30000);
    };
  } catch {
    pollTimer = setInterval(pollOnce, 5000);
  }
}

// ---------- clock (ticks every second, aligned to the second) ----------
let clockTimer = 0;
function tick() {
  const now = new Date();
  const parts = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }).split(" ");
  $("clock-hm").textContent = parts[0];
  $("clock-ap").textContent = parts[1] || "";
  $("clock-s").textContent = String(now.getSeconds()).padStart(2, "0");
  $("date").textContent = now.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  clockTimer = setTimeout(tick, 1000 - (Date.now() % 1000) + 5);
}
function stopClock() { clearTimeout(clockTimer); clockTimer = 0; }

// ---------- pause / visibility (wallpaper covered, tab hidden) ----------
function applyActivity() {
  const idle = paused || document.hidden;
  document.body.classList.toggle("paused", idle);
  orb.pause(paused);
  if (idle) { stopStatus(); stopClock(); } else { if (!clockTimer) tick(); if (!es && !pollTimer) startStatus(); }
}
window.kuramaPause = (on) => { paused = !!on; applyActivity(); return paused; };
document.addEventListener("visibilitychange", applyActivity);

// ---------- settings drawer ----------
const dlg = $("settings");
function openSettings(msg) {
  $("set-api").value = S.apiBase || "";
  $("set-token").value = S.token || "";
  $("set-voice").checked = !!S.voiceReplies;
  $("set-low").checked = lowPowerOn();
  $("set-lang").value = S.lang || "auto";
  $("set-msg").textContent = msg || "";
  if (!dlg.open) dlg.showModal();
}
$("btn-settings").onclick = () => openSettings();
$("set-test").onclick = async () => {
  const probe = new Api(() => ({ apiBase: $("set-api").value, token: $("set-token").value }));
  $("set-msg").textContent = "Testing…";
  try {
    const h = await probe.health();
    await probe.status(); // checks the token too
    $("set-msg").textContent = `Connected · API v${h.version}${h.auth ? " · token OK" : ""}`;
  } catch (e) {
    $("set-msg").textContent = "Failed: " + (e.status === 401 ? "wrong or missing token" : e.message);
  }
};
$("set-form").addEventListener("submit", (e) => {
  if (e.submitter?.value !== "save") return;
  S.apiBase = $("set-api").value.trim().replace(/\/+$/, "");
  S.token = $("set-token").value.trim();
  S.voiceReplies = $("set-voice").checked;
  S.lowPower = $("set-low").checked;
  S.lang = $("set-lang").value;
  saveSettings(S);
  orb.setLowPower(S.lowPower);
  document.body.classList.toggle("low-power", S.lowPower);
  online = null;
  startStatus();
  checkHealth();
});
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); }); // click the backdrop to close

// ---------- info (tools / memory / jobs / alerts) ----------
const info = $("info");
function openInfo(tab) { if (!info.open) info.showModal(); showInfo(tab); }
info.addEventListener("click", (e) => { if (e.target === info) info.close(); });
async function showInfo(tab) {
  document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  const body = $("info-body");
  body.innerHTML = '<p class="note">Loading…</p>';
  try {
    if (tab === "tools") {
      const d = await api.tools();
      body.innerHTML = `<p class="note">${d.count} tools. <span class="chip safe">safe</span> runs directly, <span class="chip confirm">confirm</span> asks you first.</p>` +
        d.groups.map((g) => `<details><summary>${esc(g.group)} <small>${g.tools.length}</small></summary><ul class="tools">${
          g.tools.map((t) => `<li><span class="chip ${esc(t.safety)}">${esc(t.safety)}</span><b>${esc(t.name)}</b><small>${esc(t.description)}</small></li>`).join("")
        }</ul></details>`).join("");
    } else if (tab === "memory") {
      const d = await api.profile();
      body.innerHTML = d.facts.length ? `<ul class="facts">${d.facts.map((f) => `<li><b>${esc(f.key)}</b><span>${esc(f.value)}</span></li>`).join("")}</ul>`
        : '<p class="note">Nothing remembered yet. Try “remember that my name is …”.</p>';
    } else if (tab === "jobs") {
      const d = await api.jobs();
      body.innerHTML = d.jobs.length ? `<ul class="facts">${d.jobs.map((j) => `<li><b>#${j.id} ${esc(j.title || "")}</b><span>${esc(j.status)}${j.progress ? " · " + esc(j.progress) : ""}${j.output_path ? " · " + esc(j.output_path) : ""}${j.error ? " · " + esc(j.error) : ""}</span>${
        j.status === "running" || j.status === "queued" ? `<button type="button" class="btn" data-cancel="${Number(j.id)}">Cancel</button>` : ""}</li>`).join("")}</ul>`
        : '<p class="note">No background jobs yet.</p>';
      body.querySelectorAll("[data-cancel]").forEach((b) => (b.onclick = async () => {
        b.disabled = true;
        try { await api.cancelJob(b.dataset.cancel); } catch (e) { toast("Cancel failed: " + e.message); }
        showInfo("jobs");
      }));
    } else if (tab === "alerts") {
      const d = await api.alerts();
      body.innerHTML = (d.unread ? '<p><button type="button" class="btn" id="mark-read">Mark all read</button></p>' : "") +
        (d.alerts.length ? `<ul class="facts">${d.alerts.map((a) => `<li class="lvl-${esc(a.level)}"><b>${esc(a.title)}</b><span>${esc(a.text)} · ${new Date(a.ts * 1000).toLocaleString()}</span></li>`).join("")}</ul>`
          : '<p class="note">No alerts.</p>');
      const mr = $("mark-read");
      if (mr) mr.onclick = async () => { await api.alertsRead(); showInfo("alerts"); pollOnce(); };
    }
  } catch (e) {
    body.innerHTML = `<p class="err">${esc(e.message)}</p>`;
  }
}
$("btn-info").onclick = () => openInfo("tools");
document.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => showInfo(b.dataset.tab)));
$("tile-alerts").onclick = () => openInfo("alerts");

// ---------- toast ----------
let toastTimer = 0;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 4200);
}

// ---------- debug overlay (?debug=1): orb fps + ms per frame ----------
if (params.get("debug") === "1") {
  const d = $("debug");
  d.hidden = false;
  setInterval(() => { d.textContent = `orb ${orb.running ? orb.stats.fps + " fps · " + orb.stats.ms + " ms/frame" : "stopped"} · ${orb.state}`; }, 1000);
}

// ---------- boot ----------
async function checkHealth() {
  try {
    const h = await api.health();
    setConn(true);
    if (h.auth && !S.token) openSettings("This API needs a token.");
  } catch {
    setConn(false);
  }
}
setMode("text");
tick();
if (params.get("paused") === "1") window.kuramaPause(true); // start paused (testing)
checkHealth().then(startStatus);
if (FORCE_ORB) orb.levelFn = () => 0.35 + 0.3 * Math.sin(performance.now() / 180); // fake audio level for visual checks
if (params.get("debug") === "1" && params.get("demo") === "1") { // static sample conversation (visual checks only)
  addUser("open youtube and write a 1000-word essay about Nepal");
  const b = new BotBubble();
  b.tool({ name: "open_url", ok: true, ms: 84 });
  b.tool({ name: "start_job", ok: true, ms: 12 });
  b.append("Opened **YouTube**. The essay is running as background job `#14`; I'll tell you when it's saved under `data/outputs/`.");
  b.done({ route: { groups: ["web", "jobs"] }, tier: "8b", tokens: 412, ms: 930, lang: "en" });
  addUser("delete the old screenshots folder", true);
  const c = new BotBubble();
  c.tool({ name: "delete_path", ok: false, ms: 3 });
  c.append("That needs your OK.");
  c.confirm({ id: "demo", prompt: "Delete ~/Pictures/old-screens (42 files)?" });
  c.finish();
}
