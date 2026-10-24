// KURAMA UI controller. Talks to the KURAMA backend ONLY through the HTTP API (api.js).
import { Api } from "./api.js";
import { loadSettings, saveSettings } from "./config.js";
import { Dust } from "./dust.js";
import { Orb } from "./orb.js";
import { Conversation, Mic, Player, Recorder, SentenceSplitter, audioCtx, audioSleepSoon, insertAtCursor } from "./voice.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = loadSettings();
let botName = "KURAMA"; // the assistant's name (/api/v1/identity)
const lowPowerOn = () => (S.lowPower === null ? reducedMotion : !!S.lowPower);
const api = new Api(() => S);
if (params.get("wallpaper") === "1") document.body.classList.add("wallpaper");
const MINI = params.get("mini") === "1"; // the small chat panel of mini KURAMA (no orb, stats or workspace)
document.body.classList.toggle("mini", MINI);
let minimized = false; // the dashboard is minimized to the floating button (window.kuramaMinimized)

// ---------- orb ----------
const orb = new Orb($("orb-canvas"), { halo: document.querySelector("#orb .halo"), lowPower: lowPowerOn(), reducedMotion });
document.body.classList.toggle("low-power", lowPowerOn());
const dust = new Dust($("bg-dust"), { orbEl: $("orb"), lowPower: lowPowerOn() });
if (params.get("dust") !== "0" && !MINI) orb.attach(dust); // one loop drives the orb and the background field (?dust=0: off)
if (!MINI) orb.start();

// ---------- voice plumbing ----------
const mic = new Mic();
const recorder = new Recorder(mic);
const player = new Player(api, { onStart: () => updateState(), onIdle: () => { updateState(); maybeResume(); } });
const conv = new Conversation(mic, player, {
  onUtterance: (blob) => handleUtterance(blob),
  onState: () => updateState(),
  onBargeCheck: (blob) => bargeCheck(blob), // words spoken while KURAMA talks: "stop", yes/no, or a new request
  onAutoOff: () => { // 2 minutes of silence: back to sleep (wake word) or, without the wake word, off
    if (S.wakeListen) { goSleep(true); return; }
    conv.stop(); mic.stop(); setMode("text"); toast("Conversation turned off after 2 minutes of silence.");
  },
});
orb.levelFn = () => (player.playing ? player.level() : mic.open ? mic.level() : 0);
orb.bandsFn = (n) => (player.playing ? player.bands(n) : mic.open ? mic.bands(n) : null);
orb.waveFn = (n) => (mic.open ? mic.wave(n) : null);

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
let asleep = false; // talk mode, waiting for "wake up KURAMA" (only talk mode sleeps and wakes)
let openConfirm = null; // a yes/no card is waiting: typed or spoken "yes"/"no" answers it (never aborts the turn)
const bubbles = new Map(); // confirm id -> bubble
const FORCE_ORB = params.get("debug") === "1" ? params.get("orb") : null; // ?debug=1&orb=thinking (visual checks)
const FORCE_MODE = params.get("debug") === "1" ? { text: "text", mic: "mic", chat: "conv", conv: "conv" }[params.get("mode")] || null : null; // &mode=text|mic|chat
let dictLang = null; // language of text dictated into the box (mic mode), used when it is sent
let caretKnown = false; // the user has placed the caret in the box (else dictation appends)
const alive = () => !MINI && !lowPowerOn() && !reducedMotion && !paused && !document.hidden; // small CSS flourishes allowed
// restart a one-shot CSS animation by alternating two classes that use identical keyframes
function retrigger(node, a, b) {
  if (!node || !alive()) return;
  const on = node.classList.contains(a);
  node.classList.remove(on ? a : b);
  node.classList.add(on ? b : a);
}

function orbState() {
  if (player.playing) return "speaking";
  if (asleep || conv.state === "sleeping") return "idle";
  if (recording || conv.state === "listening" || conv.state === "capturing") return "listening";
  if (busy || sttBusy) return "thinking";
  return "idle";
}

function stateText(st) {
  if (online === false) return "Offline — check the API in settings";
  if (online === null) return "Connecting…";
  if (asleep || conv.state === "sleeping") return `Talk mode — say “hey ${botName}” to start`;
  if (st === "speaking") return mode === "conv" ? "Speaking — say “stop” to interrupt" : "Speaking — click the orb to stop";
  if (st === "listening") {
    if (recording) return `Recording ${recSecs}s — click the mic to stop · Esc cancels`;
    return conv.state === "capturing" ? "Hearing you…" : "Listening — speak anytime";
  }
  if (st === "thinking") return sttBusy ? "Transcribing…" : "Thinking…";
  if (mode === "mic") return "Mic ready — click the mic to dictate into the box";
  return "Voice off — type below";
}

const CHIP = { idle: "Ready", listening: "Listening", thinking: "Thinking…", speaking: "Speaking" };

function updateState() {
  const st = orbState();
  orb.setState(FORCE_ORB || st);
  const om = FORCE_MODE || (mode === "conv" && (conv.on || asleep) ? "conv" : mode === "mic" ? "mic" : "text"); // asleep = still talk mode
  orb.setMode(om);
  if (document.body.dataset.mode !== om) { document.body.dataset.mode = om; $("composer").querySelector(".modes").dataset.mode = om; }
  document.body.dataset.state = performance.now() < errUntil ? "error" : FORCE_ORB || st;
  const vs = $("voice-state"), txt = stateText(st);
  if (vs.textContent !== txt) { vs.textContent = txt; retrigger(vs, "fl-a", "fl-b"); }
  const chip = $("chat-state");
  chip.className = "chat-state " + (online === false ? "bad" : st === "thinking" ? "busy" : st === "idle" ? (online ? "ok" : "") : "live");
  chip.lastElementChild.textContent = online === false ? "Offline" : online === null ? "Connecting" : CHIP[st];
  $("send").classList.toggle("stop", busy);
  $("send").setAttribute("aria-label", busy ? "Stop" : "Send");
  $("m-mic").classList.toggle("rec", recording);
  $("m-conv").classList.toggle("live", mode === "conv" && conv.on);
  if (!mic.open && !player.active && !recording) audioSleepSoon(); // free the audio thread when idle (asleep = API listens)
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
  if (m !== "conv" && asleep) { asleep = false; api.wakeAwake().catch(() => {}); } // sleep/wake is talk mode only
  if (mode === "conv" && m !== "conv" && conv.on) { conv.stop(); player.stop(); mic.stop(); }
  if (mode === "mic" && m !== "mic" && recording) { recording = false; recorder.cancel(); mic.stop(); clearInterval(recTimer); }
  mode = m;
  for (const [id, v] of [["m-text", "text"], ["m-mic", "mic"], ["m-conv", "conv"]]) $(id).setAttribute("aria-pressed", String(mode === v));
  $("input").placeholder = mode === "conv" && conv.on ? "Just talk — or type here…" : mode === "mic" ? "Click the mic to talk, or type…" : `Ask ${botName.toUpperCase()}${MINI ? "" : " anything"}…`;
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
  // stop -> transcribe -> insert into the box at the caret; never auto-send (the user may add a pasted path)
  recording = false;
  clearInterval(recTimer);
  const blob = await recorder.stop();
  mic.stop();
  setMode("mic");
  if (!blob || blob.size < 1200) { toast("Didn't catch anything."); return; }
  const composer = $("composer");
  composer.classList.add("transcribing");
  input.placeholder = "Transcribing…";
  let r = null;
  try { r = await transcribe(blob); } finally { composer.classList.remove("transcribing"); setMode(mode); }
  if (r?.text) dictate(r.text, r.lang);
}

function cancelRecording() {
  if (!recording) return;
  recording = false;
  clearInterval(recTimer);
  recorder.cancel();
  mic.stop();
  updateState();
  toast("Recording cancelled.");
}

function dictate(text, lang) {
  const { value, caret } = insertAtCursor(input.value, caretKnown ? input.selectionStart : null, caretKnown ? input.selectionEnd : null, text);
  input.value = value;
  autosize();
  input.focus();
  input.setSelectionRange(caret, caret);
  caretKnown = true;
  dictLang = lang || dictLang;
  orb.poke(0.8);
}

async function toggleConv() {
  audioCtx();
  if (mode === "conv" && (conv.on || asleep)) { setMode("text"); return; } // talk button again: leave talk mode
  if (recording) setMode("text");
  if (!MINI && S.wakeListen) { startListening(); return; } // talk mode starts asleep: "hey KURAMA" starts it
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
  if (conv.asleep) { // fallback (the API can't listen): the page's own asleep mode // only the wake phrase counts; everything else (TV, other people, noise) is ignored silently
    let t = "";
    try { t = ((await api.stt(blob, S.lang)).text || "").trim(); } catch { /* ignore */ }
    const rest = t ? wakeRest(t) : null;
    const own = !!t && (player.said || []).join(" ").toLowerCase().includes(t.toLowerCase().replace(/[.!?,]+$/, "")); // its own voice
    if (rest === null || own) { conv.listen(); return; }
    wakeUp(rest);
    return;
  }
  conv.waiting();
  const r = await transcribe(blob);
  if (!r || !r.text) { maybeResume(); return; }
  if (isEcho(r.text)) { maybeResume(); return; } // the mic heard KURAMA's own voice
  if (SLEEP_RE.test(r.text.trim())) { addUser(r.text, true); goSleep(); return; }
  if (pendingConfirm) {
    const t = r.text.replace(/^[\s,.!?"']+/, "");
    const yes = NO.test(t) ? false : YES.test(t) ? true : null;
    if (yes === null) { player.enqueue("Please say yes or no.", r.lang); return; }
    addUser(r.text, true);
    answerConfirm(pendingConfirm, yes);
    return;
  }
  sendChat(r.text, { voice: true, lang: r.lang, speak: !S.mute });
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
    this.who = el("div", "who", `${botName.toUpperCase()} · ${hhmm()}`);
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
  if (openConfirm === id) openConfirm = null;
  bubbles.get(id)?.settle(id, yes ? "Approved" : "Declined");
  try { await api.confirm(id, yes); } catch (e) { toast("Confirmation failed: " + e.message); }
}

async function sendChat(text, { voice = false, lang = null, speak = false } = {}) {
  text = (text || "").trim();
  if (!text) return;
  if (SLEEP_RE.test(text) && mode === "conv" && S.wakeListen) { addUser(text, voice); goSleep(); return; } // talk mode sleeps
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
          openConfirm = ev.id;
          if (mode === "conv" && conv.on) pendingConfirm = ev.id; // any spoken yes/no answers it
          if (speak) player.enqueue(ev.prompt + (pendingConfirm ? " Please say yes or no." : ""), hint, gen);
          setTimeout(maybeResume, 400); // listen even if the spoken question failed to play
          break;
        case "confirm_timeout":
          bot.settle(ev.id, "No answer in time, so I declined.");
          if (pendingConfirm === ev.id) pendingConfirm = null;
          if (openConfirm === ev.id) openConfirm = null;
          break;
        case "error": bot.error(ev.text); flashError(); break;
        case "done":
          openConfirm = null;
          if (split) { const rest = split.flush(); if (rest) player.enqueue(rest, hint || ev.lang, gen); }
          bot.done(ev);
          wsFromReply(text, bot.text);
          if (ev.jobs?.length) watchJobs(ev.jobs); // background work: tell the user when it's done
          setTimeout(loadOutputs, 800); // a tool may have just saved a file (long results go to the workspace)
          setTimeout(loadWall, 1500);
          if (/\bname\b/i.test(text)) setTimeout(loadName, 500); // "change your name to ..."
          break;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") bot.note("Stopped.");
    else {
      bot.error(e.status === 401 ? "The API needs a token (open settings)." : "Can't reach KURAMA: " + e.message);
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
input.addEventListener("input", () => { autosize(); caretKnown = true; orb.poke(0.3); });
for (const ev of ["focus", "mouseup", "keyup", "select"]) input.addEventListener(ev, () => { caretKnown = true; });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); }
});
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = input.value.trim();
  if (openConfirm) { // typed answer to the yes/no card
    const yes = NO.test(t) ? false : YES.test(t) ? true : null;
    if (yes !== null) { input.value = ""; autosize(); addUser(t); answerConfirm(openConfirm, yes); }
    else toast("Answer the question first: type yes or no (or click a button).");
    return;
  }
  if (busy) { abortChat(); player.stop(); return; }
  if (!t) return;
  input.value = "";
  autosize();
  const dictated = dictLang !== null;
  const lang = (mode === "mic" && dictLang) || S.lang;
  dictLang = null;
  caretKnown = false;
  const speak = !S.mute; // voice on (speaker button) = KURAMA answers out loud in every mode
  if (speak) audioCtx();
  orb.poke(1);
  sendChat(t, { voice: speak || dictated, lang, speak });
});
$("m-text").onclick = () => { setMode("text"); input.focus(); };
$("m-mic").onclick = () => toggleMic();
$("m-conv").onclick = () => toggleConv();
$("btn-clear").onclick = () => { log.innerHTML = ""; log.append(welcome()); };
$("orb").onclick = () => {
  if (minimized) { hostSay("restore"); return; }
  if (player.active) player.stop(); else if (busy) abortChat();
  updateState();
};
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && recording) { e.preventDefault(); cancelRecording(); return; } // cancel, insert nothing
  if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
    if (player.active) player.stop();
    else if (busy) abortChat();
    else if (conv.on) setMode("text");
    else if (MINI) hostSay("hide");
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
  for (const s of ["Summarize today", "Latest news", "What can you do?", "Generate an image of a misty Himalayan sunrise"]) {
    const b = el("button", "chip sug");
    b.type = "button";
    b.textContent = s;
    b.onclick = () => { if (!S.mute) audioCtx(); sendChat(s, { lang: S.lang, speak: !S.mute }); };
    row.append(b);
  }
  w.append(row);
  return w;
}
log.append(welcome());

// ---------- numbers: set only when the shown text changes (no per-frame tweening: every animated frame
// costs real CPU in WebKitGTK, and this page runs all day) ----------
// Numbers ease to the new value in a few coarse steps (6 text updates, only when the value changed) and
// flash softly; low power / reduced motion / paused set the text directly.
function tweenTo(id, value, decimals = 0) {
  const node = $(id);
  const t = value == null || Number.isNaN(value) ? "–" : Number(value).toFixed(decimals);
  if (node.textContent === t && !node._tw) return;
  clearTimeout(node._tw); node._tw = 0;
  const from = parseFloat(node.textContent);
  if (!alive() || t === "–" || Number.isNaN(from)) { node.textContent = t; return; }
  if (Math.abs(Number(value) - from) >= 5) retrigger(node, "nf-a", "nf-b"); // flash only on real jumps (CPU)
  const to = Number(value);
  let i = 0;
  const stepFn = () => {
    i++;
    const e = 1 - Math.pow(1 - i / 6, 3);
    node.textContent = i >= 6 ? t : (from + (to - from) * e).toFixed(decimals);
    node._tw = i >= 6 ? 0 : setTimeout(stepFn, 70);
  };
  stepFn();
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
    if (this.c.clientWidth) this.c.style.setProperty("--step", (this.c.clientWidth / (this.points - 1)).toFixed(1) + "px");
    // no per-sample slide: each CSS animation forces full-window repaints in WebKitGTK (no GPU)
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
      const [lx, ly] = pts[pts.length - 1]; // live dot with a soft glow
      const hg = ctx.createRadialGradient(lx - 2, ly, 0, lx - 2, ly, 9);
      hg.addColorStop(0, s.fill.replace(/[\d.]+\)$/, "0.9)")); hg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = hg;
      ctx.beginPath(); ctx.arc(lx - 2, ly, 9, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.beginPath(); ctx.arc(lx - 2, ly, 1.3, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = s.color; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(lx - 2, ly, 3.2, 0, Math.PI * 2); ctx.stroke();
    }
  }
}
const cpuSpark = new Spark($("cpu-spark"), [{ color: "#ff8a2b", fill: "rgba(255,122,26,0.26)" }]);
const netSpark = new Spark($("net-spark"),
  [{ color: "#ffb347", fill: "rgba(255,179,71,0.20)" }, { color: "#6fb7ff", fill: "rgba(111,183,255,0.12)" }],
  (series) => Math.max(65536, ...series.flatMap((s) => s.data)) * 1.15);
addEventListener("resize", () => { cpuSpark.draw(); netSpark.draw(); });

// ---------- status ----------
let es = null, pollTimer = 0, retryTimer = 0, procSort = "rss", lastStatus = null, lastJobsKey = "", procGlitchAt = 0;

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
  $("cpu-metric").style.setProperty("--glow", (0.12 + Math.min(1, (cpu.percent || 0) / 100) * 0.7).toFixed(2));
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
    setBar("battery-bar", bat.percent, !bat.plugged && bat.percent <= 20 ? "low" : bat.plugged && bat.percent < 99 ? "chg" : "");
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
  loadOutputs(); // a job finished or started: its output may be new
  loadWall(); // ...or it set a new wallpaper
  if (!items.length) return;
  for (const x of items) {
    const li = el("li");
    li.innerHTML = '<span class="p"></span><span class="q"></span><span class="s"></span>';
    li.querySelector(".p").textContent = `#${x.id}`;
    li.querySelector(".q").textContent = x.title || x.kind || "job";
    li.querySelector(".s").textContent = x.progress || x.status;
    li.classList.add("run");
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
  const before = (ul.dataset.order || "").split(",");
  const pids = list.map((p) => String(p.pid));
  const moved = procSort === ul.dataset.sort && pids.join(",") !== before.join(",") && alive() && Date.now() - procGlitchAt > 10000;
  if (moved) procGlitchAt = Date.now();
  ul.dataset.order = pids.join(",");
  ul.dataset.sort = procSort;
  const gl = (procGlitchAt & 1) ? "gl-a" : "gl-b"; // alternate names so the one-shot replays
  ul.innerHTML = list.map((p, i) => {
    const v = procSort === "cpu" ? p.cpu : p.rss_mb;
    const mem = p.rss_mb >= 1024 ? `${(p.rss_mb / 1024).toFixed(1)} GB` : `${Math.round(p.rss_mb)} MB`;
    const cls = moved && before[i] !== pids[i] ? ` class="${gl}"` : "";
    return `<li${cls} title="pid ${p.pid}"><span class="n">${esc(p.name)}</span><span class="c">${p.cpu.toFixed(1)}%</span><span class="m">${mem}</span><i class="w" style="transform:scaleX(${(v / max).toFixed(3)})"></i></li>`;
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
  if (document.hidden || paused || MINI || minimized) return;
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

// ---------- weather card (Nepalgunj; fetched on load, then every 10 min) ----------
const WX_SVG = {
  sun: '<svg viewBox="0 0 32 32"><g class="wx-rays"><path d="M16 3v4M16 25v4M3 16h4M25 16h4M6.8 6.8l2.8 2.8M22.4 22.4l2.8 2.8M6.8 25.2l2.8-2.8M22.4 9.6l2.8-2.8"/></g><circle cx="16" cy="16" r="5.5"/></svg>',
  moon: '<svg viewBox="0 0 32 32"><circle class="wx-glow" cx="16" cy="16" r="11"/><path d="M20.5 22.5A8.5 8.5 0 0 1 13 8a8.5 8.5 0 1 0 10.5 13.2 8.4 8.4 0 0 1-3 1.3z"/></svg>',
  cloud: '<svg viewBox="0 0 32 32"><path class="wx-cloud" d="M9 23h14a5 5 0 0 0 .4-10A7 7 0 0 0 10 13.5 4.8 4.8 0 0 0 9 23z"/></svg>',
  rain: '<svg viewBox="0 0 32 32"><path d="M9 19h14a5 5 0 0 0 .4-10A7 7 0 0 0 10 9.5 4.8 4.8 0 0 0 9 19z"/><path class="wx-drop" d="M11 22l-1 3"/><path class="wx-drop d2" d="M16 22l-1 3"/><path class="wx-drop d3" d="M21 22l-1 3"/></svg>',
};
function wxKind(it) {
  const c = Number(it.code);
  if (c >= 51 && c <= 67 || c >= 80 && c <= 82 || c >= 95) return "rain";
  if (c <= 1) return it.is_day === false ? "moon" : "sun";
  return "cloud";
}
async function loadWeather() {
  if (MINI) return;
  let it = null;
  try { it = (await api.fetchWeather()).items?.[0] || null; } catch { it = null; }
  const ok = !!it && !it.error && it.temp_c != null;
  $("wx-place").textContent = (it?.place || "Nepalgunj").toUpperCase();
  if (ok) tweenTo("wx-temp", it.temp_c, 0); else $("wx-temp").textContent = "--";
  $("wx-desc").textContent = ok ? it.desc || "" : "unavailable";
  $("wx-sub").textContent = ok ? `Feels ${Math.round(it.feels_c)}° · ${Math.round(it.humidity)}% · ${Math.round(it.wind_kmh)} km/h` : "";
  const k = ok ? wxKind(it) : "cloud", ic = $("wx-icon");
  if (alive() || ic.dataset.k !== k) { ic.dataset.k = k; ic.innerHTML = WX_SVG[k]; } // re-insert = replay the one-shot animation
}
loadWeather();

// ---------- this laptop: Wi-Fi, volume, brightness, battery health, next reminder (every 30 s, only while visible) ----------
let devTimer = 0;
async function loadDevice() {
  clearTimeout(devTimer); devTimer = 0;
  if (MINI || paused || minimized || document.hidden) return; // applyActivity starts it again
  try {
    const d = await api.device();
    const w = d.wifi, v = d.volume, b = d.battery;
    tweenTo("d-wifi", w ? w.signal : null);
    setBar("d-wifi-bar", w?.signal ?? 0);
    $("d-ssid").textContent = w ? w.ssid : d.ip ? "wired" : "offline";
    $("d-ssid").title = w ? `Wi-Fi: ${w.ssid}` : "";
    tweenTo("d-vol", v ? v.percent : null);
    setBar("d-vol-bar", v && !v.muted ? v.percent : 0);
    $("d-vol-sub").textContent = v ? (v.muted ? "muted" : "speaker") : "–";
    tweenTo("d-bri", d.brightness);
    setBar("d-bri-bar", d.brightness ?? 0);
    $("d-bat").textContent = b ? `${b.health}%${b.cycles ? ` · ${b.cycles} cycles` : ""}` : "–";
    $("d-ip").textContent = d.ip || "offline";
    $("d-sys").textContent = [d.model, d.os].filter(Boolean).join(" · ") || d.host || "–";
    $("d-sys").title = `${d.host} · ${d.model} · ${d.os} · Linux ${d.kernel}`;
    const n = d.next, nb = $("d-next");
    nb.textContent = n ? `${new Date(n.at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${n.text}` : "nothing scheduled";
    nb.classList.toggle("dim", !n);
    nb.title = n ? n.text : "";
    $("dev-up").textContent = "up " + fmtDur(d.uptime_s);
  } catch { /* API still starting: try again next round */ }
  devTimer = setTimeout(loadDevice, 30000);
}

// ---------- workspace: the newest picture / poem / essay, shown big (outputs from /api/v1/outputs + long replies) ----------
const ws = { items: [], cur: -1, seen: new Set(), loaded: false };
const wsTitle = (name) => name.replace(/^.*\//, "").replace(/^\d{8}-\d{4,6}-?/, "").replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || name;
const LONG_REPLY = (t) => t && (t.split("\n").filter((l) => l.trim()).length >= 4 || t.length > 420);

const WS_MAX = 8; // the workspace keeps the last 8 results; swipe / arrows / wheel to go through them

function wsAdd(item, show) {
  if (ws.seen.has(item.key)) return;
  ws.seen.add(item.key);
  ws.items.unshift(item);
  if (ws.items.length > WS_MAX) ws.items.length = WS_MAX;
  if (show || ws.cur < 0) wsShow(0); else { ws.cur = Math.min(ws.cur + 1, ws.items.length - 1); wsTabs(); }
}

function wsTabs() { // footer: name + dots, and the arrows
  const n = ws.items.length, it = ws.items[ws.cur];
  $("ws-name").textContent = it ? it.title : "";
  const dots = $("ws-dots");
  dots.innerHTML = "";
  ws.items.forEach((x, i) => {
    const d = el("button", "ws-dot" + (i === ws.cur ? " on" : "") + (x.kind === "image" ? " img" : ""));
    d.type = "button"; d.title = x.title; d.setAttribute("aria-label", `Result ${i + 1} of ${n}: ${x.title}`);
    d.onclick = () => wsShow(i);
    dots.append(d);
  });
  $("ws-prev").hidden = ws.cur <= 0;
  $("ws-next").hidden = ws.cur >= n - 1;
}

function wsStep(d) {
  const i = ws.cur + d;
  if (i < 0 || i >= ws.items.length) return;
  ws.dir = d;
  wsShow(i);
}

async function wsBody(it, box) {
  const tok = (box._tok = Symbol("render")); // a newer render wins (startup loads several items at once)
  box.innerHTML = "";
  if (it.kind === "image") {
    const img = el("img", "ws-img");
    img.alt = it.title; img.src = it.src; img.decoding = "async";
    img.draggable = false;
    img.onclick = () => { if (!ws.dragged) wsBig(); };
    box.append(img);
    return;
  }
  if (it.text == null && it.src) {
    try { const r = await fetch(it.src); it.text = r.ok ? await r.text() : "(couldn't load this file)"; }
    catch { it.text = "(couldn't load this file)"; }
    if (box._tok !== tok) return;
  }
  const doc = el("div", "ws-text");
  doc.innerHTML = renderMarkdown(it.text || "");
  box.append(doc);
}

async function wsShow(i) {
  const it = ws.items[i];
  if (!it) return;
  ws.cur = i;
  wsTabs();
  const view = $("ws-view");
  await wsBody(it, view);
  view.scrollTop = 0;
  view.dataset.dir = ws.dir > 0 ? "next" : ws.dir < 0 ? "prev" : "";
  ws.dir = 0;
  retrigger(view, "ws-in-a", "ws-in-b"); // one short slide/fade in
  if ($("ws-big").open) wsBig();
}

function wsBig() {
  const it = ws.items[ws.cur];
  if (!it) return;
  $("ws-big-title").textContent = it.title;
  const a = $("ws-open");
  a.hidden = !it.src; if (it.src) a.href = it.src;
  wsBody(it, $("ws-big-view"));
  if (!$("ws-big").open) $("ws-big").showModal();
}

function wsFromReply(request, reply) {
  if (!LONG_REPLY(reply)) return;
  wsAdd({ key: "r" + Date.now(), kind: "text", title: request.slice(0, 48), text: reply }, true);
}

let outputsBusy = false;
async function loadOutputs() {
  if (MINI) return;
  if (outputsBusy) return;
  outputsBusy = true;
  try {
    const items = (await api.outputs(WS_MAX)).items || [];
    const fresh = items.filter((x) => !ws.seen.has("o" + x.name + x.mtime)).reverse(); // oldest first
    for (const x of fresh) {
      wsAdd({ key: "o" + x.name + x.mtime, kind: x.kind, title: wsTitle(x.name), src: api.outputUrl(x.name) },
        ws.loaded && x === fresh[fresh.length - 1]); // jump to a NEW result; at startup just list them
    }
    if (!ws.loaded && fresh.length) wsShow(0); // startup: open on the newest
    ws.loaded = true;
  } catch { /* API down: keep what we have */ }
  finally { outputsBusy = false; }
}
loadOutputs();
$("ws-expand").onclick = () => wsBig();
$("ws-prev").onclick = () => wsStep(-1);
$("ws-next").onclick = () => wsStep(1);
{ // swipe (touch / mouse drag) and horizontal wheel / two-finger trackpad swipe
  const v = $("ws-view");
  let x0 = null, wheelAt = 0;
  v.addEventListener("pointerdown", (e) => { x0 = e.clientX; });
  v.addEventListener("pointerup", (e) => {
    if (x0 === null) return;
    const dx = e.clientX - x0; x0 = null;
    ws.dragged = Math.abs(dx) > 50;
    if (ws.dragged) { wsStep(dx < 0 ? 1 : -1); setTimeout(() => { ws.dragged = false; }, 0); }
  });
  v.addEventListener("pointercancel", () => { x0 = null; });
  v.addEventListener("wheel", (e) => {
    if (Math.abs(e.deltaX) < 30 || Math.abs(e.deltaX) < Math.abs(e.deltaY)) return;
    e.preventDefault();
    const now = performance.now();
    if (now - wheelAt < 450) return;
    wheelAt = now;
    wsStep(e.deltaX > 0 ? 1 : -1);
  }, { passive: false });
  $("ws").addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") wsStep(-1);
    if (e.key === "ArrowRight") wsStep(1);
  });
}
document.addEventListener("keydown", (e) => {
  if (!$("ws-big").open) return;
  if (e.key === "ArrowLeft") wsStep(-1);
  if (e.key === "ArrowRight") wsStep(1);
});

// ---------- a wallpaper KURAMA made is drawn behind the dashboard (this window covers the real desktop) ----------
let wallMtime = -1;
async function loadWall() {
  if (MINI) return;
  try {
    const w = await api.wallpaperInfo();
    const m = w.kurama ? w.mtime : 0;
    if (m === wallMtime) return;
    wallMtime = m;
    const box = $("wall");
    if (!m) { box.classList.remove("on"); return; }
    const img = new Image();
    img.onload = () => { box.style.backgroundImage = `url("${img.src}")`; box.classList.add("on"); };
    img.src = api.wallpaperUrl(m);
  } catch { /* keep the current background */ }
}
loadWall();
setInterval(loadWall, 60000);
$("ws-close").onclick = () => $("ws-big").close();
$("ws-big").addEventListener("click", (e) => { if (e.target === $("ws-big")) $("ws-big").close(); });

// ---------- tool finder: search every KURAMA tool by what you want to do (Ctrl+K) ----------
const finder = { tools: null };
const EXAMPLE = {
  generate_image: "generate an image of ", scaffold_project: "create a new python project called ", send_file_telegram: "send this file to Telegram: ",
  web_search: "search for ", weather: "weather in ", get_time: "time in ", open_url: "open ", open_app: "open ",
  remember: "remember ", add_reminder: "remind me to  at ", news_headlines: "latest news about ", calculate: "what is ",
  convert_currency: "convert 100 dollars to rupees", focus_timer: "start a 25 minute focus session", cleanup_scan: "what is using my disk space",
  gesture_control: "enable hand gesture control", daily_digest: "summarize today", write_document: "write an essay about ",
  set_wallpaper: "change my wallpaper", screenshot: "take a screenshot", volume: "set volume to 50", find_files: "find file ",
};
const words = (t) => (t.toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => w.length > 1);
async function finderLoad() {
  if (finder.tools) return finder.tools;
  const d = await api.tools();
  finder.tools = d.groups.flatMap((g) => g.tools.map((t) => ({ ...t, group: g.group, nice: t.name.replace(/_/g, " "),
    hay: `${t.name.replace(/_/g, " ")} ${t.description} ${g.group}`.toLowerCase() })));
  return finder.tools;
}
function finderRender() {
  const q = $("finder-q").value.trim();
  const ws_ = words(q);
  let list = finder.tools || [];
  if (ws_.length) {
    list = list.map((t) => ({ t, s: ws_.reduce((a, w) => a + (t.nice.includes(w) ? 3 : t.hay.includes(w) ? 1 : 0), 0) }))
      .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.t);
  }
  $("finder-count").textContent = `${list.length} tool${list.length === 1 ? "" : "s"}`;
  const ul = $("finder-list");
  ul.innerHTML = "";
  if (!list.length) {
    ul.innerHTML = `<li class="finder-none">No tool for that yet — just ask ${esc(botName)}; it can search the web or build a small tool for you.</li>`;
    return;
  }
  for (const t of list.slice(0, 40)) {
    const li = el("li", "finder-item");
    li.setAttribute("role", "option");
    li.innerHTML = `<div class="fi-main"><b>${esc(t.nice)}</b><span class="chip ${esc(t.safety)}">${esc(t.safety)}</span><small>${esc(t.group)}</small></div><p>${esc(t.description)}</p>`;
    li.onclick = () => finderTry(t);
    ul.append(li);
  }
}
function finderTry(t) {
  $("finder").close();
  setMode("text");
  input.value = EXAMPLE[t.name] || `${t.nice} `;
  autosize();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}
async function openFinder() {
  if (!$("finder").open) $("finder").showModal();
  $("finder-q").focus();
  try { await finderLoad(); finderRender(); }
  catch { $("finder-list").innerHTML = '<li class="finder-none">Can\'t reach the API.</li>'; }
}
$("btn-find").onclick = () => openFinder();
$("finder-q").addEventListener("input", () => finderRender());
$("finder-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); const first = $("finder-list").querySelector(".finder-item"); if (first) first.click(); }
});
$("finder").addEventListener("click", (e) => { if (e.target === $("finder")) $("finder").close(); });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); openFinder(); }
});

// ---------- assistant name (default KURAMA; Settings or "change your name to ...") ----------
// botName is declared at the top (used by early UI code)
function setBotName(n) {
  if (!n) return;
  botName = n;
  document.querySelector("h1.name").textContent = n.toUpperCase();
  document.title = n.toUpperCase();
  input.placeholder = `Ask ${n.toUpperCase()}${MINI ? "" : " anything"}…`;
  if (MINI) $("chat-title").textContent = n.toUpperCase();
}
function loadName() { api.identity().then((r) => setBotName(r.name)).catch(() => {}); }
loadName();

// ---------- voice on/off (speaker button) ----------
function renderMute() {
  const b = $("btn-voice");
  b.classList.toggle("muted", !!S.mute);
  b.setAttribute("aria-pressed", String(!S.mute));
  b.title = S.mute ? "Voice off · click to let KURAMA speak" : "Voice on · click to mute";
  b.setAttribute("aria-label", S.mute ? "KURAMA voice off (click to unmute)" : "KURAMA voice on (click to mute)");
}
$("btn-voice").onclick = () => {
  S.mute = !S.mute;
  saveSettings(S);
  if (S.mute) player.stop();
  renderMute();
  toast(S.mute ? "Voice off: KURAMA will reply in text only." : "Voice on.");
};
renderMute();
setInterval(loadWeather, 600000);

// ---------- clock (ticks every second, aligned to the second) ----------
let clockTimer = 0;
function tick() {
  if (MINI) return;
  const now = new Date();
  const parts = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }).split(" ");
  const [hh, mm] = parts[0].split(":");
  $("clock-h").textContent = hh;
  $("clock-m").textContent = mm ?? "";
  $("clock-colon").classList.toggle("off", alive() && now.getSeconds() % 2 === 1);
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
  orb.pause(paused || MINI);
  if (idle || minimized) { stopStatus(); stopClock(); clearTimeout(devTimer); devTimer = 0; }
  else { if (!clockTimer) tick(); if (!es && !pollTimer) startStatus(); if (!devTimer) loadDevice(); }
  syncAmbient();
}

// ---------- ambient flourishes: one rare one-shot CSS effect every ~7-13 s (nothing runs in between) ----------
let ambTimer = 0;
function ambient() {
  ambTimer = 0;
  if (!alive()) return;
  const cards = [...document.querySelectorAll(".layout .card")];
  if (Math.random() < 0.75 && cards.length) pulseClass(cards[Math.floor(Math.random() * cards.length)], "shine", 2000);
  else pulseClass(document.querySelector(".name"), "flick", 800);
  ambTimer = setTimeout(ambient, 7000 + Math.random() * 6000);
}
function pulseClass(node, cls, ms) { if (!node) return; node.classList.add(cls); setTimeout(() => node.classList.remove(cls), ms); }
function syncAmbient() { clearTimeout(ambTimer); ambTimer = alive() ? setTimeout(ambient, 3000) : 0; }
window.kuramaPause = (on) => { paused = !!on; applyActivity(); return paused; };
document.addEventListener("visibilitychange", applyActivity);

// ---------- mini KURAMA: the floating button + small chat panel over every app (scripts/kurama_wallpaper.py) ----------
const host = window.webkit?.messageHandlers?.kurama; // only inside the KURAMA GTK windows
function hostSay(msg) { if (!host) return false; host.postMessage(msg); return true; }
$("btn-mini").onclick = () => { if (!hostSay("minimize")) window.open("?mini=1", "kurama-mini", "width=400,height=600"); };
$("btn-full").onclick = () => { if (!hostSay("restore")) window.close(); };
$("btn-hide").onclick = () => { if (!hostSay("hide")) window.close(); };
window.kuramaMinimized = (on) => { // dashboard: hide the panels, keep the orb (click it to restore)
  minimized = !!on;
  document.body.classList.toggle("minimized", minimized);
  $("orb").title = minimized ? "Click to restore KURAMA" : "Click to stop talking";
  if (minimized && !asleep) setMode("text"); // one mic user at a time; the wake word (asleep) keeps listening
  applyActivity();
};
window.kuramaMiniShown = (on) => { // mini panel opened / hidden
  document.body.classList.toggle("paused", !on); // freeze CSS animations while hidden
  if (on) { input.focus(); return; }
  if (recording) cancelRecording();
  if (conv.on) setMode("text"); // never keep listening while the panel is hidden
  saveMiniLog();
};
// The hidden panel is closed after a few minutes to free its memory; its chat comes back from here.
const MINI_LOG = "kurama.mini.log";
function saveMiniLog() {
  try {
    if (log.querySelector(".msg")) localStorage.setItem(MINI_LOG, JSON.stringify({ t: Date.now(), html: log.innerHTML }));
    else localStorage.removeItem(MINI_LOG);
  } catch { /* storage off: the chat just starts fresh */ }
}
function restoreMiniLog() {
  try {
    const s = JSON.parse(localStorage.getItem(MINI_LOG) || "null");
    if (!s || Date.now() - s.t > 12 * 3600e3) return;
    log.innerHTML = s.html;
    log.querySelectorAll("#welcome, .dots").forEach((n) => n.remove()); // no stale "thinking" dots
    log.querySelectorAll("button").forEach((b) => { b.disabled = true; }); // old confirm buttons are stale
    if (!log.children.length) log.append(welcome());
    scrollDown(true);
  } catch { /* ignore */ }
}

// ---------- background jobs started by a turn: a chat line (+ voice) when each one finishes ----------
const watched = new Set();
let jobsTimer = 0;
function watchJobs(ids) {
  for (const id of ids) watched.add(Number(id));
  if (!jobsTimer) jobsTimer = setTimeout(pollJobs, 3000);
}
async function pollJobs() {
  jobsTimer = 0;
  try {
    for (const r of (await api.jobs()).jobs || []) {
      if (!watched.has(r.id) || r.status === "queued" || r.status === "running") continue;
      watched.delete(r.id);
      if (r.status !== "cancelled") announceJob(r);
    }
  } catch { /* API busy: try again */ }
  if (watched.size) jobsTimer = setTimeout(pollJobs, 4000);
}
function announceJob(r) {
  const ok = r.status === "done";
  const title = r.title || "your task";
  const msg = ok ? `Done: ${title}.${r.output_path ? (MINI ? " It's in the workspace on your desktop." : " It's in your workspace.") : ""}`
    : `Sorry, ${title} failed${r.error ? `: ${r.error.slice(0, 120)}` : "."}`;
  const b = new BotBubble();
  b.append(msg);
  b.finish();
  scrollDown(true);
  if (!S.mute) { audioCtx(); player.enqueue(msg, S.lang === "auto" ? null : S.lang); }
  if (ok) loadOutputs();
}

// ---------- wake word + sleep: talk mode is on by default and asleep; "wake up KURAMA" wakes it,
// "sleep now" (or 2 quiet minutes) puts it back to sleep. Asleep, only short phrases are transcribed.
const SLEEP_RE = /^(?:ok(?:ay)?[,\s]+)?(?:(?:now\s+)?(?:go\s+to\s+)?sleep(?:\s+now)?|(?:kurama[,\s]+)?(?:go\s+)?(?:to\s+)?sleep(?:\s+kurama)?|good\s*night(?:\s+kurama)?|so\s+jao|सो\s*जाओ|सुत\S*)[\s.!।]*$/i;
const WAKE_NAMES = ["kurama", "karama", "corama", "kuruma", "kurma", "koorama", "kurrama", "jarvis", "करामा", "कुरामा"];
function wakeRest(text) { // null = no wake phrase; else what came after it ("wake up kurama, open youtube" -> "open youtube")
  const names = [...WAKE_NAMES, botName.toLowerCase()].map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const lead = "(?:(?:wake|woke|wakey|awake)(?:\\s*(?:up|off|of|now|please)){0,3}|hey|hello|hi|ok(?:ay)?|utho?|उठ\\S*)";
  const m = text.match(new RegExp(`${lead}?[\\s,]*(?:${names})\\b[\\s,!.]*(?:(?:wake|woke)(?:\\s*(?:up|off|now)){0,2})?[\\s,!.]*`, "i"));
  if (!m) return null;
  const said = m[0].toLowerCase();
  if (!/wake|hey|hello|hi\b|ok|uth|उठ/.test(said) && text.trim().split(/\s+/).length > 3) return null; // "...kurama..." mid-sentence
  return text.slice(m.index + m[0].length).replace(/^[\s,.!?]+/, "");
}
let wakeES = null, serverWake = true; // the API listens while asleep (cheap); false = it can't (no mic there)
function wakeEvents() {
  if (wakeES) return;
  wakeES = api.wakeEvents();
  wakeES.onopen = () => { if (asleep && serverWake) api.wakeSleep().catch(() => {}); }; // API restarted: listen again
  wakeES.onmessage = (e) => {
    let ev = null;
    try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.type === "wake" && asleep) wakeUp(ev.command && !isEcho(ev.command) ? ev.command : "");
    if (ev.type === "error" && asleep) { serverWake = false; sleepListen(); } // fall back to the page's mic
  };
}
function isEcho(text) { // mostly the words KURAMA itself just said (greeting, reply, question)
  const words = (text || "").toLowerCase().match(/\p{L}+/gu) || [];
  const said = (player.said || []).join(" ").toLowerCase();
  return words.length > 0 && !!said && words.filter((w) => said.includes(w)).length / words.length >= 0.6;
}
async function sleepListen() { // asleep: the API's cheap listener, or (fallback) the page's own asleep mode
  if (!asleep) return;
  for (let quiet = 0, i = 0; quiet < 6 && i < 240; i++) { // 1.5 s of real silence first: never hear our own voice
    await new Promise((r) => setTimeout(r, 250));
    quiet = player.active || player.playing ? 0 : quiet + 1;
  }
  if (!asleep) return;
  if (serverWake) {
    if (conv.on) { conv.stop(); mic.stop(); }
    mode = "conv"; setMode("conv"); // talk mode stays selected while asleep
    wakeEvents();
    try { await api.wakeSleep(); updateState(); return; } catch { serverWake = false; }
  }
  try { if (!conv.on) { mode = "conv"; await mic.start({ plain: true }); await conv.start(); } conv.sleep(true); setMode("conv"); }
  catch (e) { toast(micError(e)); }
}
function goSleep(quiet = false) {
  if (asleep) return;
  asleep = true;
  if (conv.on) conv.sleep(true); // from now on only the wake phrase counts, even before the API takes over
  abortChat();
  player.stop();
  if (!quiet && !S.mute) player.enqueue(`Okay, going to sleep. Say wake up ${botName} when you need me.`);
  updateState();
  sleepListen();
}
async function wakeUp(rest) {
  asleep = false;
  api.wakeAwake().catch(() => {});
  try { // talk mode with echo cancellation
    audioCtx();
    if (conv.on) { conv.sleep(false); await mic.restart({ plain: false }); }
    else { mode = "conv"; await mic.start(); await conv.start(); }
    setMode("conv");
  } catch (e) { toast(micError(e)); setMode("text"); }
  updateState();
  if (rest && rest.split(/\s+/).length >= 2) { sendChat(rest, { voice: true, speak: !S.mute }); return; }
  if (!S.mute) player.enqueue("Yes? I'm listening."); else conv.listen();
}
function startListening() { // boot: asleep, waiting for the wake word
  if (MINI || !S.wakeListen || asleep || conv.on) return;
  asleep = true;
  mode = "conv"; setMode("conv"); // talk mode is the default
  sleepListen();
}
const STOP_RE = /\b(?:stop|wait|enough|quiet|shut\s*up|pause|cancel|hold\s+on|be\s+quiet|ruk\S*|bas|chup|band\s+karo|pugyo|rok\S*)\b|रुक\S*|बस|चुप|पुग्यो|रोक\S*/i;
async function bargeCheck(blob) { // something was said while KURAMA was talking
  if (!blob) return;
  let r = null;
  try { r = await api.stt(blob, S.lang); } catch { return; }
  const t = (r?.text || "").trim();
  if (!t) return;
  if (pendingConfirm && (YES.test(t) || NO.test(t))) { player.stop(); addUser(t, true); answerConfirm(pendingConfirm, !NO.test(t) && YES.test(t)); return; }
  if (openConfirm) return; // a question is waiting: anything but yes/no must not cancel it
  if (STOP_RE.test(t) && t.split(/\s+/).length <= 4) { player.stop(); if (!openConfirm) abortChat(); updateState(); maybeResume(); return; }
  const words = t.toLowerCase().match(/\p{L}+/gu) || [];
  const said = (player.said || []).join(" ").toLowerCase();
  const echo = words.length && words.filter((w) => said.includes(w)).length / words.length >= 0.5;
  if (words.length >= 3 && !echo) { player.stop(); if (!openConfirm) abortChat(); sendChat(t, { voice: true, lang: r.lang, speak: !S.mute }); }
  // else: noise, KURAMA's own echo or a short aside: keep talking
}

// ---------- power switch: first click arms it (3 s), second click turns every KURAMA process off ----------
let powerArmed = 0;
function powerClick(btn) {
  if (!powerArmed) {
    btn.classList.add("armed");
    toast("Click again to turn KURAMA off completely (Super+K turns it back on).");
    powerArmed = setTimeout(() => { powerArmed = 0; btn.classList.remove("armed"); }, 3000);
    return;
  }
  clearTimeout(powerArmed); powerArmed = 0;
  setMode("text");
  player.stop();
  api.powerOff().then((r) => toast(r.message)).catch(() => toast("Couldn't reach KURAMA to turn it off."));
}
$("btn-power").onclick = (e) => powerClick(e.currentTarget);
$("btn-power-mini").onclick = (e) => powerClick(e.currentTarget);

// ---------- settings drawer ----------
const dlg = $("settings");
function openSettings(msg) {
  $("set-name").value = botName;
  $("set-api").value = S.apiBase || "";
  $("set-token").value = S.token || "";
  $("set-wake").checked = !!S.wakeListen;
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
  const wakeWas = S.wakeListen;
  S.wakeListen = $("set-wake").checked;
  if (S.wakeListen && !wakeWas) setTimeout(startListening, 0);
  if (!S.wakeListen && wakeWas && asleep) { asleep = false; api.wakeAwake().catch(() => {}); if (conv.on) { conv.stop(); mic.stop(); setMode("text"); } updateState(); }
  S.lowPower = $("set-low").checked;
  S.lang = $("set-lang").value;
  saveSettings(S);
  const nm = $("set-name").value.trim();
  if (nm && nm !== botName) api.setName(nm).then((r) => { setBotName(r.name); toast(`My name is ${r.name} now.`); })
    .catch(() => toast("That name didn't work: use 2-24 letters."));
  orb.setLowPower(S.lowPower);
  dust.setLowPower(S.lowPower);
  document.body.classList.toggle("low-power", S.lowPower);
  syncAmbient();
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
if (MINI) { $("chat-title").textContent = botName; restoreMiniLog(); input.focus(); }
tick();
if (params.get("paused") === "1") window.kuramaPause(true); // start paused (testing)
checkHealth().then(() => { startStatus(); loadDevice(); bootVoice(); });
async function bootVoice() { // first load after KURAMA starts: say hello, then wait (asleep) for the wake word
  if (MINI || params.get("debug") === "1") return;
  if (S.wakeListen) { mode = "conv"; setMode("conv"); } // talk mode is the default
  let g = "";
  try { g = (await api.greeting()).text || ""; } catch { /* no greeting */ }
  if (!g) { startListening(); return; }
  const b = new BotBubble();
  b.append(g);
  b.finish();
  if (!S.mute) { audioCtx(); player.enqueue(g); }
  startListening(); // waits until the greeting has been spoken
}
if (FORCE_ORB) { // fake audio for visual checks
  orb.levelFn = () => 0.35 + 0.3 * Math.sin(performance.now() / 180);
  const fb = new Float32Array(24), fw = new Float32Array(64);
  orb.bandsFn = (n) => { const t = performance.now() / 1000; for (let i = 0; i < n; i++) fb[i] = Math.max(0, 0.75 - i / n * 0.6 + 0.25 * Math.sin(t * 7 + i * 1.3)); return fb; };
  orb.waveFn = (n) => { const t = performance.now() / 1000; for (let i = 0; i < n; i++) fw[i] = 0.25 * Math.sin(i * 0.9 + t * 11) * Math.sin(i * 0.23 + t * 3); return fw; };
}
syncAmbient();
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
