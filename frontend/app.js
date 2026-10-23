// KURAMA UI controller. Talks to the Jarvis backend ONLY through the HTTP API (api.js).
import { Api } from "./api.js";
import { loadSettings, saveSettings } from "./config.js";
import { Hologram } from "./holo.js";
import { Conversation, Mic, Player, Recorder, SentenceSplitter, audioCtx } from "./voice.js";

const $ = (id) => document.getElementById(id);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = loadSettings();
const lowPowerOn = () => (S.lowPower === null ? reducedMotion : !!S.lowPower);
const api = new Api(() => S);

// ---------- hologram ----------
const holo = new Hologram($("holo"), { lowPower: lowPowerOn(), reducedMotion });
document.body.classList.toggle("low-power", lowPowerOn());
holo.start();

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
holo.levelFn = () => (player.playing ? player.level() : mic.open ? mic.level() : 0);

let mode = "text"; // text | mic | conv
let recording = false;
let recTimer = 0;
let busy = false; // a chat turn is streaming
let sttBusy = false;
let chatCtrl = null;
let pendingConfirm = null; // conversation mode: confirmation answered by voice
const bubbles = new Map(); // confirm id -> bubble

const STATE_TEXT = { idle: "STANDING BY", listening: "LISTENING", thinking: "THINKING", speaking: "SPEAKING" };

function holoState() {
  if (player.playing) return "speaking";
  if (recording || conv.state === "listening" || conv.state === "capturing") return "listening";
  if (busy || sttBusy) return "thinking";
  return "idle";
}

function updateState() {
  const st = holoState();
  holo.setState(st);
  document.body.dataset.state = st;
  let label = STATE_TEXT[st];
  if (mode === "conv" && conv.on && st === "listening") label = conv.state === "capturing" ? "HEARING YOU" : "LISTENING · SPEAK ANYTIME";
  if (mode === "mic" && recording) label = "RECORDING · CLICK MIC TO SEND";
  $("state-label").textContent = label;
  $("send").classList.toggle("stop", busy);
  $("send").setAttribute("aria-label", busy ? "Stop" : "Send");
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
  for (const [id, v] of [["m-text", "text"], ["m-mic", "mic"], ["m-conv", "conv"]]) {
    $(id).setAttribute("aria-pressed", String(mode === v));
  }
  $("m-mic").classList.toggle("rec", recording);
  $("m-conv").classList.toggle("live", mode === "conv" && conv.on);
  const hints = {
    text: "Text mode · Enter to send, Shift+Enter for a new line",
    mic: recording ? "Recording… click the mic again to send" : "Mic mode · click the mic to record, click again to send",
    conv: conv.on ? "Conversation on · just talk; speak over me to interrupt · click the wave to stop" : "Conversation mode",
  };
  $("voice-hint").textContent = hints[mode];
  updateState();
}

async function toggleMic() {
  audioCtx();
  if (mode === "conv") setMode("text");
  if (!recording) {
    try { await mic.start(); } catch (e) { toast(micError(e)); return; }
    player.stop();
    recorder.start();
    recording = true;
    const t0 = Date.now();
    recTimer = setInterval(() => {
      const s = Math.floor((Date.now() - t0) / 1000);
      $("voice-hint").textContent = `Recording ${s}s… click the mic again to send`;
      if (s >= 60) toggleMic(); // safety cap
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
  try { await conv.start(); } catch (e) { toast(micError(e)); setMode("text"); return; }
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
const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 90;
const scrollDown = (force) => { if (force || nearBottom()) log.scrollTop = log.scrollHeight; };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

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

function addUser(text, small = false) {
  $("welcome")?.remove();
  const m = el("div", "msg user" + (small ? " small" : ""));
  const b = el("div", "bubble");
  b.textContent = text;
  m.append(b);
  log.append(m);
  scrollDown(true);
}

class BotBubble {
  constructor() {
    $("welcome")?.remove();
    this.text = "";
    this.root = el("div", "msg bot");
    this.chips = el("div", "chips");
    this.bubble = el("div", "bubble", '<span class="dots" aria-label="thinking"><i></i><i></i><i></i></span>');
    this.content = el("div", "content");
    this.meta = el("div", "meta");
    this.root.append(this.chips, this.bubble, this.meta);
    log.append(this.root);
    this.timer = 0;
    scrollDown(true);
  }
  _show() { if (!this.content.isConnected) { this.bubble.innerHTML = ""; this.bubble.append(this.content); } }
  append(t) {
    this.text += t;
    if (this.timer) return;
    this.timer = setTimeout(() => { this.timer = 0; this._render(); }, 40); // throttle re-renders
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
    this.root.insertBefore(card, this.meta);
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
  }
  error(t) { this._show(); this.content.append(el("div", "err", esc(t))); }
  note(t) { this._show(); this.content.append(el("div", "note", esc(t))); }
  done(ev) {
    clearTimeout(this.timer); this.timer = 0;
    if (ev.text) this.text = ev.text;
    if (this.text) this._render();
    const route = ev.route && typeof ev.route === "object" ? [].concat(ev.route.groups || []).join("+") || ev.route.method : ev.route;
    const bits = [route && ["route", route], ev.tier && ["tier", ev.tier], ["tokens", ev.tokens ?? 0], ["ms", ev.ms], ev.lang && ["lang", ev.lang]];
    this.meta.innerHTML = bits.filter(Boolean).map(([k, v]) => `<span class="chip meta"><b>${esc(k)}</b> ${esc(v)}</span>`).join("");
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
  addUser(text);
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
        case "error": bot.error(ev.text); break;
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
      if (e.status === 401) openSettings("This API needs a token.");
      setConn(false, e.status === 401 ? "auth needed" : "offline");
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
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; }
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
  w.innerHTML = `<div class="w-title">KURAMA online</div>
    <p>Type, tap the mic, or start a hands-free conversation.</p>`;
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

// ---------- status ----------
let es = null, pollTimer = 0, retryTimer = 0, procSort = "rss";
const CIRC = 2 * Math.PI * 42;

function setConn(ok, text) {
  const c = $("conn");
  c.textContent = text || (ok ? "online" : "offline");
  c.className = "pill " + (ok ? "ok" : "bad");
}

const fmtGb = (g) => (g == null ? "–" : g >= 10 ? g.toFixed(0) : g.toFixed(1));
const level = (p) => (p >= 85 ? "hot" : p >= 60 ? "warm" : "");
function fmtUp(s) {
  if (s == null) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

function bar(id, pct, text, invert = false) {
  const b = $(id);
  if (!b) return;
  b.querySelector("i").style.width = Math.max(0, Math.min(100, pct || 0)) + "%";
  // usage bars: high = bad; battery (invert): low = bad
  b.className = "bar " + level(invert ? 100 - (pct || 0) : pct || 0);
  b.querySelector("span").textContent = text;
}

let lastStatus = null;
function renderStatus(s) {
  lastStatus = s;
  setConn(true);
  const cpu = s.cpu?.percent ?? 0;
  const ring = $("cpu-ring");
  ring.style.strokeDashoffset = String(CIRC * (1 - cpu / 100));
  ring.setAttribute("class", "ring-fg " + level(cpu));
  $("cpu-val").textContent = Math.round(cpu) + "%";
  $("cpu-sub").textContent = `${s.cpu?.count ?? "?"} cores · load ${(s.cpu?.load || []).slice(0, 1).map((x) => x.toFixed(2)).join("") || "–"}`;
  bar("ram-bar", s.ram?.percent, `${fmtGb(s.ram?.used_gb)} / ${fmtGb(s.ram?.total_gb)} GB`);
  bar("swap-bar", s.swap?.percent, s.swap?.total_gb ? `${fmtGb(s.swap.used_gb)} / ${fmtGb(s.swap.total_gb)} GB` : "none");
  bar("disk-bar", s.disk?.percent, s.disk?.total_gb ? `${fmtGb(s.disk.free_gb)} GB free` : "–");
  const bat = s.battery;
  $("bat-row").hidden = !bat;
  if (bat) bar("bat-bar", bat.percent, `${Math.round(bat.percent)}%${bat.plugged ? " · charging" : ""}`, true);
  $("sys-up").textContent = "up " + fmtUp(s.uptime?.system_s);

  const j = s.jarvis || {};
  $("t-rss").textContent = j.rss_mb != null ? Math.round(j.rss_mb) : "–";
  $("t-rss-sub").textContent = `${j.agent_ready ? "agent ready" : j.agent_loaded ? "agent loading" : "agent idle"} · up ${fmtUp(j.uptime_s)}`;
  const tk = s.tokens || {};
  $("t-tokens").textContent = tk.today != null ? Number(tk.today).toLocaleString() : "–";
  $("t-tokens-sub").textContent = `${tk.calls ?? 0} calls · ${tk.fastpath_hits ?? 0} fast`;
  const jb = s.jobs || {};
  $("t-jobs").textContent = String((jb.running || 0) + (jb.queued || 0));
  $("t-jobs-sub").textContent = jb.items?.length ? jb.items.slice(0, 2).map((x) => `${x.title}${x.progress ? " · " + x.progress : ""}`).join(" | ") : `${jb.running || 0} running · ${jb.queued || 0} queued`;
  const al = s.alerts || {};
  $("t-alerts").textContent = String(al.unread ?? 0);
  $("tile-alerts").classList.toggle("hot", (al.unread || 0) > 0);
  $("t-alerts-sub").textContent = al.recent?.[0] ? al.recent[0].title : "all clear";
  renderProcs();
}

function renderProcs() {
  const s = lastStatus;
  if (!s) return;
  const list = (procSort === "cpu" ? s.processes?.by_cpu : s.processes?.by_rss) || [];
  const max = Math.max(1, ...list.map((p) => (procSort === "cpu" ? p.cpu : p.rss_mb)));
  $("procs").innerHTML = list.map((p) => {
    const v = procSort === "cpu" ? p.cpu : p.rss_mb;
    const label = procSort === "cpu" ? `${v.toFixed(1)}%` : v >= 1024 ? `${(v / 1024).toFixed(2)} GB` : `${Math.round(v)} MB`;
    return `<li><span class="pn" title="pid ${p.pid}">${esc(p.name)}</span><span class="pv">${label}</span><i style="width:${(v / max) * 100}%"></i></li>`;
  }).join("") || '<li class="empty">–</li>';
  $("procs-count").textContent = s.processes?.count ? `${s.processes.count} running` : "";
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
  try { renderStatus(await api.status()); } catch (e) { setConn(false, e.status === 401 ? "auth needed" : "offline"); }
}

function startStatus() {
  stopStatus();
  if (document.hidden) return;
  try {
    es = api.statusStream();
    es.onmessage = (e) => { try { renderStatus(JSON.parse(e.data)); } catch { /* ignore */ } };
    es.onerror = () => {
      // fall back to polling, retry the stream later
      if (es) { es.close(); es = null; }
      if (!pollTimer) { pollOnce(); pollTimer = setInterval(pollOnce, 5000); }
      clearTimeout(retryTimer);
      retryTimer = setTimeout(startStatus, 30000);
    };
  } catch {
    pollTimer = setInterval(pollOnce, 5000);
  }
}
document.addEventListener("visibilitychange", () => (document.hidden ? stopStatus() : startStatus()));

// clock (minute precision is enough)
function tick() { $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
tick();
setInterval(tick, 15000);

// ---------- settings ----------
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
  if (e.submitter?.value === "cancel") return;
  S.apiBase = $("set-api").value.trim().replace(/\/+$/, "");
  S.token = $("set-token").value.trim();
  S.voiceReplies = $("set-voice").checked;
  S.lowPower = $("set-low").checked;
  S.lang = $("set-lang").value;
  saveSettings(S);
  holo.setLowPower(S.lowPower);
  document.body.classList.toggle("low-power", S.lowPower);
  startStatus();
  checkHealth();
});

// ---------- info (tools / memory / jobs / alerts) ----------
const info = $("info");
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
      body.innerHTML = d.jobs.length ? `<ul class="facts">${d.jobs.map((j) => `<li><b>#${j.id} ${esc(j.title || "")}</b><span>${esc(j.status)}${j.progress ? " · " + esc(j.progress) : ""}${j.output_path ? " · " + esc(j.output_path) : ""}</span></li>`).join("")}</ul>`
        : '<p class="note">No background jobs yet.</p>';
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
$("btn-info").onclick = () => { info.showModal(); showInfo("tools"); };
document.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => showInfo(b.dataset.tab)));
$("tile-jobs").onclick = () => { info.showModal(); showInfo("jobs"); };
$("tile-alerts").onclick = () => { info.showModal(); showInfo("alerts"); };

// ---------- toast ----------
let toastTimer = 0;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 4200);
}

// ---------- boot ----------
async function checkHealth() {
  try {
    const h = await api.health();
    setConn(true);
    if (h.auth && !S.token) openSettings("This API needs a token.");
  } catch (e) {
    setConn(false, "offline");
    toast(`Can't reach the Jarvis API at ${api.base() || location.origin}. Check settings.`);
  }
}
setMode("text");
checkHealth().then(startStatus);
