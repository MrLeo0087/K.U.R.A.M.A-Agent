// KURAMA UI controller. Talks to the KURAMA backend ONLY through the HTTP API (api.js).
import { Api } from "./api.js";
import { VOICE_DEFAULTS, loadSettings, saveSettings } from "./config.js";
import { Dust } from "./dust.js";
import { Orb } from "./orb.js";
import { attachSlash } from "./slash.js";
import { openMoney } from "./money.js";
import { Conversation, Mic, Player, Recorder, SentenceSplitter, audioCtx, audioSleepSoon, insertAtCursor, micHooks } from "./voice.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = loadSettings();
let botName = "KURAMA"; // the assistant's name (/api/v1/identity)
const lowPowerOn = () => (S.lowPower === null ? reducedMotion : !!S.lowPower);
const api = new Api(() => S);
if (params.get("wallpaper") === "1") document.body.classList.add("wallpaper");
const MINI = params.get("mini") === "1"; // the small chat panel of mini KURAMA (no orb, stats or workspace)
const WSONLY = MINI && params.get("ws") === "1"; // mini KURAMA's separate workspace window: just the workspace
document.body.classList.toggle("mini", MINI);
document.body.classList.toggle("wsonly", WSONLY);
let minimized = false; // the dashboard is minimized to the floating button (window.kuramaMinimized)
let miniGhost = false; // mini panel closed while in talk mode: it keeps listening, replies show beside the button

// ---------- orb ----------
// the big animated orb (owner: "like the previous circle"); its own capped loop, 10 fps idle / 30 active
const orb = new Orb($("orb-canvas"), { halo: document.querySelector("#orb .halo"), lowPower: false, reducedMotion });
document.body.classList.toggle("low-power", lowPowerOn());
const dust = new Dust($("bg-dust"), { orbEl: $("orb"), lowPower: lowPowerOn() });
// no background dust field (static wallpaper instead) // one loop drives the orb and the background field (?dust=0: off)
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
    if (openConfirm) return; // a yes/no is waiting: keep listening for it (the server times it out by itself)
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
  if (conv.muted && mode === "conv" && !busy && !sttBusy) return "idle";
  if (asleep || conv.state === "sleeping") return "idle";
  if (recording || conv.state === "listening" || conv.state === "capturing") return "listening";
  if (busy || sttBusy) return "thinking";
  return "idle";
}

function stateText(st) {
  if (st === "idle" && Date.now() < orbNoteUntil) return orbNoteText;
  if (online === false) return "Offline — check the API in settings";
  if (online === null) return "Connecting…";
  if (conv.muted && mode === "conv" && st !== "speaking" && st !== "thinking") return "Mic muted — click the mic button to unmute";
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
  markKick();
  const vs = $("voice-state"), txt = stateText(st);
  if (vs.textContent !== txt) { vs.textContent = txt; retrigger(vs, "fl-a", "fl-b"); }
  const chip = $("chat-state");
  chip.className = "chat-state " + (online === false ? "bad" : st === "thinking" ? "busy" : st === "idle" ? (online ? "ok" : "") : "live");
  chip.lastElementChild.textContent = online === false ? "Offline" : online === null ? "Connecting" : CHIP[st];
  chip.title = chip.lastElementChild.textContent; // the narrow panel shows only the dot
  $("send").classList.toggle("stop", busy);
  $("send").setAttribute("aria-label", busy ? "Stop" : "Send");
  $("m-mic").classList.toggle("rec", recording);
  if (MINI) miniReport(st);
  $("m-conv").classList.toggle("live", mode === "conv" && conv.on);
  $("m-mute").setAttribute("aria-pressed", String(conv.muted));
  if (!mic.open && !player.active && !recording) audioSleepSoon(); // free the audio thread when idle (asleep = API listens)
  // music down only while you actually speak (or the mic button records), KURAMA thinks or answers; back up 2 s
  // after (not while talk mode merely waits: that kept the music at a whisper and every state flip pumped it)
  // text mode: you type, so the music stays as it is (only voice / talk mode turns it down)
  const duck = recording || conv.state === "capturing" || (mode !== "text" && (busy || sttBusy || player.playing));
  clearTimeout(unduckTimer);
  if (duck && !ducked) { ducked = true; api.musicDuck(true).catch(() => {}); }
  else if (!duck && ducked) unduckTimer = setTimeout(() => { ducked = false; api.musicDuck(false).catch(() => {}); }, 2000);
}
let ducked = false, unduckTimer = 0;

// ---------- the KURAMA mark: glows and shifts colour with the voice (only while listening / speaking) ----------
let markRaf = 0, markAt = 0;
const MARK_HUE = { speaking: [28, 44], listening: [140, 160], capturing: [140, 160], thinking: [38, 46] };
function markLoop(now) {
  markRaf = 0;
  const st = document.body.dataset.state, hue = MARK_HUE[st];
  const el = $("orb");
  if (!hue || MINI || paused || minimized || document.hidden) { el.style.removeProperty("--lv"); el.style.removeProperty("--kh"); return; }
  if (now - markAt >= 66) { // ~15 fps: enough for a soft glow
    markAt = now;
    const lv = player.playing ? player.level() : mic.open ? mic.level() : st === "thinking" ? 0.25 + 0.2 * Math.sin(now / 260) : 0;
    el.style.setProperty("--lv", Math.min(1, lv).toFixed(2));
    el.style.setProperty("--kh", (hue[0] + (hue[1] - hue[0]) * Math.min(1, lv * 1.6)).toFixed(0));
  }
  markRaf = requestAnimationFrame(markLoop);
}
function markKick() { /* the orb itself reacts to the voice now; the small mark loop is off */ }

function flashError() {
  errUntil = performance.now() + 1400;
  orb.flash();
  updateState();
  setTimeout(updateState, 1450);
}

function maybeResume() {
  if (mode !== "conv" || !conv.on || player.active || sttBusy) return;
  if (busy && !pendingConfirm && !S.mute) return; // voice off: you can talk again while the answer is still coming
  if (conv.state === "listening" || conv.state === "capturing") return;
  conv.listen();
}

// a waiting yes/no question is never cancelled by a side effect (a new message, Esc, the orb, a chip): closing the
// turn used to make the server answer "no" for the user. Only an explicit no / sleep / reset closes it (force).
function abortChat(force = false) {
  if (openConfirm && !force) { toast("A yes/no question is waiting: answer it first (yes or no)."); return; }
  chatCtrl?.abort();
}

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
  // an explicit click on the talk button = "listen to me now", NOT "wait for the wake word" (that passive,
  // asleep-until-"hey KURAMA" state is only the boot default; clicking should start capturing right away)
  asleep = false;
  api.wakeAwake().catch(() => {}); // stop the server's asleep wake-listener so it hands the mic to the page
  mode = "conv";
  try { await conv.start(); } catch (e) { toast(micError(e)); flashError(); setMode("text"); return; }
  conv.sleep(false); // make sure the loop is awake (not only listening for the wake phrase)
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

// whole words only: "Now…" / "Nothing" are not a no, "How" / "Hold on" / "Hang on" are not a yes
const YES = /^(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|confirm|please do|haan|han|ha|ho|हो|हाँ|हां|हजुर|ठीक\S*|गर\S*)(?=$|[\s,.!?;:'"।])/i;
const NO = /^(no|nope|nah|don'?t|do not|cancel|stop|never|nahi|hoina|होइन|नाइ|नहीं|नही|नगर\S*)(?=$|[\s,.!?;:'"।])/i;

async function handleUtterance(blob) {
  if (conv.asleep) { // fallback (the API can't listen): the page's own asleep mode // only the wake phrase counts; everything else (TV, other people, noise) is ignored silently
    let t = "";
    try { t = ((await api.stt(blob, S.lang)).text || "").trim(); } catch { /* ignore */ }
    const rest = t ? wakeRest(t) : null;
    if (rest === null || isEcho(t)) { conv.listen(); return; } // not the wake phrase, or its own voice
    wakeUp(rest);
    return;
  }
  conv.waiting();
  const r = await transcribe(blob);
  if (!r || !r.text) { maybeResume(); return; }
  r.text = stripEcho(r.text); // the mic often catches the tail of KURAMA's own "Yes? I'm listening." before you speak
  if (!r.text) { maybeResume(); return; }
  if (isEcho(r.text)) { maybeResume(); return; } // the whole thing was KURAMA's own voice
  if (wantsSleep(r.text)) { addUser(r.text, true); goSleep(); return; }
  if (pendingConfirm) {
    const t = r.text.replace(/^[\s,.!?"']+/, "");
    const yes = NO.test(t) ? false : YES.test(t) ? true : null;
    if (yes === null) { player.enqueue("Please say yes or no.", r.lang); return; }
    addUser(r.text, true);
    answerConfirm(pendingConfirm, yes, "voice:" + t.slice(0, 40));
    return;
  }
  sendChat(r.text, { voice: true, lang: r.lang, speak: !S.mute, ambient: Date.now() - lastBotAt > FOLLOWUP_MS });
}

// ---------- chat ----------
const log = $("log");
const MAX_MSGS = 60; // keeps the DOM small on an all-day page
const nearBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 90;
let stick = true; // follow new messages until the user scrolls up to read something older
log.addEventListener("scroll", () => { stick = nearBottom(); }, { passive: true });
const scrollDown = (force) => {
  if (force) stick = true;
  if (stick || nearBottom()) { log.style.scrollBehavior = "auto"; log.scrollTop = log.scrollHeight; log.style.scrollBehavior = ""; }
};
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

// Workspace documents: a fuller (still SAFE: everything escaped first) Markdown renderer with real headings,
// lists, numbered lists, tables, quotes, rules, **bold**, *italic*, `code`, links and ``` code blocks.
function mdInline(t) {
  let h = esc(t);
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*\n][^*]*?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[\s(])\*([^*\s][^*\n]*?)\*(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
  h = h.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  h = h.replace(/(^|[\s(])(https?:\/\/[^\s<>"')]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  return h;
}
function mdBlocks(src) {
  const out = [], lines = src.split("\n");
  let i = 0;
  const isTable = (l) => /^\s*\|.*\|\s*$/.test(l);
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    let m;
    if ((m = l.match(/^\s*(#{1,6})\s+(.+)$/))) { const n = Math.min(4, m[1].length); out.push(`<h${n}>${mdInline(m[2])}</h${n}>`); i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
    if (isTable(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const row = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => mdInline(c.trim()));
      const head = row(l); i += 2;
      const body = [];
      while (i < lines.length && isTable(lines[i])) body.push(row(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (/^\s*>/.test(l)) {
      const q = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${mdInline(q.join(" "))}</blockquote>`); continue;
    }
    if (/^\s*([-*•+])\s+/.test(l) || /^\s*\d{1,3}[.)]\s+/.test(l)) {
      const ordered = /^\s*\d/.test(l), tag = ordered ? "ol" : "ul", items = [];
      while (i < lines.length && (ordered ? /^\s*\d{1,3}[.)]\s+/ : /^\s*([-*•+])\s+/).test(lines[i])) {
        items.push(mdInline(lines[i++].replace(/^\s*(?:[-*•+]|\d{1,3}[.)])\s+/, "")));
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*(?:[-*•+]|\d{1,3}[.)])\s+/.test(lines[i])) items[items.length - 1] += " " + mdInline(lines[i++].trim());
      }
      const start = ordered ? (l.match(/^\s*(\d+)/)[1]) : "";
      out.push(`<${tag}${start && start !== "1" ? ` start="${start}"` : ""}>${items.map((x) => `<li>${x}</li>`).join("")}</${tag}>`); continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(#{1,6}\s|>|([-*•+])\s|\d{1,3}[.)]\s)/.test(lines[i]) && !isTable(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    out.push(`<p>${para.map(mdInline).join("<br>")}</p>`);
  }
  return out.join("");
}
export function renderDoc(src) {
  return String(src).split("```").map((part, i) => {
    if (i % 2 === 0) return mdBlocks(part);
    const m = part.match(/^([\w+.-]*)\n/);
    const code = part.replace(/^[\w+.-]*\n/, "").replace(/\n$/, "");
    return `<pre class="doc-code">${m && m[1] ? `<span class="lang">${esc(m[1])}</span>` : ""}<code>${esc(code)}</code></pre>`;
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
  if (voice) miniCaption("you", text);
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
  return m;
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
  _render() { // a long answer is still arriving: the chat shows its start; the server moves it to the workspace
    this._show();
    const t = !this.final && CHAT_LONG(this.text) ? chatHead(this.text) : this.text;
    this.content.innerHTML = renderMarkdown(t);
    scrollDown();
  }
  tool(ev) {
    const c = el("span", "chip tool " + (ev.ok ? "ok" : "fail"));
    c.textContent = `${ev.name}${ev.ms != null ? " · " + ev.ms + " ms" : ""}`;
    c.title = ev.ok ? "tool ran" : "tool failed or was declined";
    this.chips.append(c);
    scrollDown();
    if (ev.name === "power_mode" && ev.ok) setTimeout(() => api.modes().then((m) => applyModeClient(m.current, true)).catch(() => {}), 300);
  }
  confirm(ev) {
    const card = el("div", "confirm");
    card.append(el("div", "q", esc(ev.prompt)));
    const row = el("div", "row");
    const yes = el("button", "btn yes", "Yes"), no = el("button", "btn no", "No");
    yes.type = no.type = "button";
    yes.onclick = () => answerConfirm(ev.id, true, "button");
    no.onclick = () => answerConfirm(ev.id, false, "button");
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
    this.final = true;
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

async function answerConfirm(id, yes, via = "") { // via: who answered (logged by the server)
  if (pendingConfirm === id) pendingConfirm = null;
  if (openConfirm === id) openConfirm = null;
  bubbles.get(id)?.settle(id, yes ? "Approved" : "Declined");
  try { await api.confirm(id, yes, via); } catch (e) { toast("Confirmation failed: " + e.message); }
}

let lastBotAt = 0; // talk mode: speech long after KURAMA last spoke is probably room talk (sent as "ambient")
const FOLLOWUP_MS = 120000; // talk mode: within 2 min of KURAMA's last reply anything said is for it

// a long answer is not read out in full: the first ~3 sentences, then "the rest is on the screen"
const SPEAK_MAX = 420;
const spoken = { chars: 0, cut: false };
function speakPart(sentence, lang, gen) {
  if (S.mute || spoken.cut || gen !== player.gen) return;
  if (spoken.chars + sentence.length > SPEAK_MAX && spoken.chars > 0) {
    spoken.cut = true;
    player.enqueue(lang === "ne" ? "बाँकी स्क्रिनमा छ।" : lang === "hi" ? "बाकी स्क्रीन पर है।" : "The rest is on the screen.", lang, gen);
    return;
  }
  spoken.chars += sentence.length;
  player.enqueue(sentence, lang, gen);
}

async function sendChat(text, { voice = false, lang = null, speak = false, ambient = false } = {}) {
  text = (text || "").trim();
  if (!text) return;
  if (wantsSleep(text) && mode === "conv") { addUser(text, voice); goSleep(); return; } // talk mode: "sleep" puts KURAMA to sleep, never the laptop
  if (busy) { // e.g. a barge-in utterance while the previous turn is still closing
    if (openConfirm) { abortChat(); return; } // the question first (abortChat says so)
    abortChat();
    for (let i = 0; busy && i < 40; i++) await new Promise((r) => setTimeout(r, 50));
    if (busy) return;
  }
  busy = true;
  const userBubble = addUser(text, voice);
  const bot = new BotBubble();
  const ctrl = new AbortController();
  chatCtrl = ctrl;
  if (speak) player.stop(); // a new turn replaces anything still being said
  spoken.chars = 0; spoken.cut = false;
  const gen = player.gen;
  const split = speak ? new SentenceSplitter() : null;
  const hint = lang && lang !== "auto" ? lang : S.lang !== "auto" ? S.lang : null;
  updateState();
  // a turn that goes silent (no event for 90 s, no yes/no card waiting) is stopped, never dots forever
  let lastEv = Date.now(), stalled = false;
  const watchdog = setInterval(() => {
    if (!openConfirm && Date.now() - lastEv > 90000) { stalled = true; ctrl.abort(); }
  }, 5000);
  const shown = new Set();
  function showConfirm(ev) { // from the stream, or found by asking (WebKit can hold a waiting stream's last bytes)
    if (shown.has(ev.id) || ctrl.signal.aborted) return;
    shown.add(ev.id);
    lastEv = Date.now();
    bot.confirm(ev);
    miniCaption("bot", ev.prompt);
    openConfirm = ev.id;
    if (mode === "conv" && conv.on) pendingConfirm = ev.id; // any spoken yes/no answers it
    if (speak) player.enqueue(ev.prompt + (pendingConfirm ? " Please say yes or no." : ""), hint, gen);
    setTimeout(maybeResume, 400); // listen even if the spoken question failed to play
  }
  const asker = setInterval(async () => { // a question the stream didn't deliver yet: ask the server directly
    if (openConfirm || Date.now() - lastEv < 800) return;
    try { for (const q of (await api.pendingConfirms()).pending || []) showConfirm(q); } catch { /* offline */ }
  }, 1000);
  try {
    for await (const ev of api.chat(text, { mode: voice ? "voice" : "text", lang: hint, signal: ctrl.signal, ambient })) {
      lastEv = Date.now();
      switch (ev.type) {
        case "delta":
          bot.append(ev.text);
          if (miniGhost) miniCaptionSoon(() => bot.text);
          if (split) split.feed(ev.text).forEach((s) => speakPart(s, hint, gen));
          break;
        case "tool": bot.tool(ev); break;
        case "confirm": showConfirm(ev); break;
        case "confirm_timeout":
          bot.settle(ev.id, "No answer in time, so I declined.");
          if (pendingConfirm === ev.id) pendingConfirm = null;
          if (openConfirm === ev.id) openConfirm = null;
          break;
        case "error": bot.error(ev.text); flashError(); miniCaption("bot", ev.text, true); break;
        case "done":
          openConfirm = null;
          if (ev.ignored) { // room talk / TV, not for KURAMA: keep it visible (faded) so the user knows why nothing happened
            bot.root.remove();
            if (userBubble) { userBubble.classList.add("ignored"); userBubble.title = "Not sent: it sounded like room talk. Start with 'KURAMA …'"; }
            toast("Heard you, but it sounded like room talk. Start with “KURAMA …” after a pause.");
            maybeResume(); break;
          }
          lastBotAt = Date.now();
          if (split) { const rest = split.flush(); if (rest) speakPart(rest, hint || ev.lang, gen); }
          bot.done(ev);
          miniCaption("bot", bot.text || ev.text || "Done.", true);
          wsFromReply(text, bot.text);
          if (ev.jobs?.length) watchJobs(ev.jobs); // background work: tell the user when it's done
          if (MINI && ev.workspace?.length) openWorkspace(false); // the long answer went there: show it (no focus steal)
          setTimeout(loadToday, 600); // a reminder / alarm / timer may have changed
          setTimeout(loadOutputs, 800); // a tool may have just saved a file (long results go to the workspace)
          setTimeout(loadDownloads, 1200); // a download may have just started: show its bar
          setTimeout(loadWall, 1500);
          if (/\bname\b/i.test(text)) setTimeout(loadName, 500); // "change your name to ..."
          break;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") bot.note(stalled ? "That took too long, so I stopped it. Please say it again." : "Stopped.");
    else {
      bot.error(e.status === 401 ? "The API needs a token (open settings)." : "Can't reach KURAMA: " + e.message);
      flashError();
      if (e.status === 401) openSettings("This API needs a token.");
      setConn(false);
    }
  } finally {
    clearInterval(watchdog);
    clearInterval(asker);
    busy = false;
    chatCtrl = null;
    pendingConfirm = null;
    bot.finish();
    updateState();
    maybeResume();
    fresh = true; setTimeout(() => { loadDash(); loadToday(); loadSuggest(true); }, 300); // a turn may have changed the list / goals / reminders: show it now
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
attachSlash(input, api, $("composer"), autosize);
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = input.value.trim();
  if (openConfirm) { // typed answer to the yes/no card
    const yes = NO.test(t) ? false : YES.test(t) ? true : null;
    if (yes !== null) { input.value = ""; autosize(); addUser(t); answerConfirm(openConfirm, yes, "typed:" + t.slice(0, 40)); }
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
$("m-text").onclick = () => { setMode("text"); input.focus(); tip($("m-text"), "Text mode: type and press Enter."); };
$("m-mic").onclick = () => { toggleMic(); tip($("m-mic"), "Mic: click again when you've finished speaking."); };
$("m-conv").onclick = () => { toggleConv(); setTimeout(() => tip($("m-conv"), conv.on ? "Talk mode: just speak." : "Talk mode off."), 150); };
// talk mode: mute / unmute the mic (KURAMA hears nothing, not even the wake word, until unmuted)
function setMicMuted(on) {
  conv.mute(on); // also silences the mic track
  S.micMuted = conv.muted; saveSettings(S);
  if (asleep && serverWake) (on ? api.wakeAwake() : api.wakeSleep()).catch(() => {});
  toast(on ? "Mic muted. I can't hear you until you unmute." : "Mic on. I'm listening again.");
  updateState();
}
$("m-mute").onclick = () => setMicMuted(!conv.muted);
$("btn-clear").onclick = () => { log.innerHTML = ""; log.append(welcome()); };
// the orb: click = a shockwave + the dust bursts and returns, and a one-line status under the name;
// double-click = talk to KURAMA now. While it speaks / works, a click still stops it; minimized = restore.
$("orb").onclick = () => {
  if (minimized) { hostSay("restore"); return; }
  orb.burst();
  if (player.active) { player.stop(); updateState(); return; }
  if (busy) { abortChat(); updateState(); return; }
  orbNote(quickStatus());
};
$("orb").ondblclick = (e) => {
  e.preventDefault();
  if (minimized || MINI || player.active || busy) return;
  orb.burst();
  wakeUp(""); // talk mode, listening right away ("Yes? I'm listening.")
};
let orbNoteText = "", orbNoteUntil = 0;
function orbNote(text, ms = 6000) {
  orbNoteText = text; orbNoteUntil = Date.now() + ms;
  updateState();
  retrigger($("voice-state"), "fl-a", "fl-b");
  setTimeout(updateState, ms + 50);
}
function quickStatus() { // what's going on, in one line (no API call: the panels already know)
  const parts = [], now = dash?.now || [];
  const tr = now.find((x) => x.kind === "train");
  if (tr) parts.push(`${tr.title}: ${tr.sub.split(",").slice(0, 2).join(",")}`);
  else if (now.length) parts.push(`${now.length} running`);
  if (lastStatus?.ram) parts.push(`RAM ${Math.round(lastStatus.ram.percent)}%`);
  if (lastStatus?.cpu) parts.push(`CPU ${Math.round(lastStatus.cpu.percent)}%`);
  const next = (dash?.today || []).find((c) => c.next);
  if (next) parts.push(`next ${next.text} ${next.time}`);
  return (parts.join(" · ") || "All quiet") + " — double-click to talk";
}
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
  const chips = (list) => {
    row.textContent = "";
    for (const s of list) {
      const b = el("button", "chip sug");
      b.type = "button";
      b.textContent = s;
      b.onclick = () => { if (!S.mute) audioCtx(); sendChat(s, { lang: S.lang, speak: !S.mute }); };
      row.append(b);
    }
  };
  chips(["What's on today?", "Latest news", "What can you do?", "Play lofi music"]); // until the random ones arrive
  api.suggest(4).then((r) => r.items?.length && chips(r.items)).catch(() => {});
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
    if (this.c.width !== Math.round(w * dpr) || this.c.height !== Math.round(h * dpr)) { this.c.width = Math.round(w * dpr); this.c.height = Math.round(h * dpr); }
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
const cpuSpark = new Spark($("cpu-spark"), [{ color: "#ff8a2b", fill: "rgba(255,122,26,0.22)" }, { color: "#f0c35e", fill: "rgba(240,195,94,0.08)" }]);
addEventListener("resize", () => cpuSpark.draw());

// ---------- status ----------
let es = null, pollTimer = 0, retryTimer = 0, lastStatus = null, lastJobsKey = "";

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

const RING = 2 * Math.PI * 27; // ring circumference (r = 27)
function setRing(id, pct) {
  const v = Math.max(0, Math.min(100, pct || 0)), fill = $(id).querySelector(".fill");
  if (fill) { // the System card's bars
    const w = Math.round(v) + "%";
    if (fill.style.width !== w) fill.style.width = w;
    $(id).classList.toggle("hot", v >= 85);
    return;
  }
  const arc = $(id).querySelector(".arc");
  const off = (RING * (1 - v / 100)).toFixed(1);
  if (arc.dataset.off !== off) { arc.dataset.off = off; arc.style.strokeDashoffset = off; }
  $(id).classList.toggle("hot", v >= 85);
}

function renderStatus(s) {
  lastStatus = s;
  setConn(true);
  const cpu = s.cpu || {};
  tweenTo("cpu", cpu.percent ?? 0);
  setRing("rg-cpu", cpu.percent);
  cpuSpark.push([cpu.percent ?? 0, s.ram?.percent ?? 0]); // CPU + RAM history (last 2 min)
  $("cpu-temp").textContent = cpu.temp_c != null ? `${Math.round(cpu.temp_c)} °C` : "– °C";
  const ram = s.ram || {};
  tweenTo("ram", ram.percent ?? 0);
  setRing("rg-ram", ram.percent);
  $("rg-ram").title = `${fmtGb(ram.used_gb)} / ${fmtGb(ram.total_gb)} GB · swap ${s.swap?.percent ?? 0}%`;
  const disk = s.disk || {};
  tweenTo("disk", disk.percent ?? 0);
  setRing("rg-disk", disk.percent);
  $("rg-disk").title = `${Math.round(disk.used_gb ?? 0)} / ${Math.round(disk.total_gb ?? 0)} GB`;
  const bat = s.battery; // the battery lives on the Laptop card
  if (bat) {
    tweenTo("d-batp", bat.percent);
    setBar("d-bat-bar", bat.percent, !bat.plugged && bat.percent <= 20 ? "low" : bat.plugged && bat.percent < 99 ? "chg" : "");
    $("d-bat").dataset.state = bat.plugged ? (bat.percent >= 99 ? "full" : "charging")
      : bat.secs_left != null ? `${fmtDur(bat.secs_left)} left` : "on battery";
    renderBatSub();
  }
  const net = s.net || {};
  $("down").textContent = fmtRate(net.rx_bps);
  $("up").textContent = fmtRate(net.tx_bps);
  $("uptime").textContent = "up " + fmtDur(s.uptime?.system_s);
  const j = s.jarvis || {};
  $("t-rss").textContent = j.rss_mb != null ? Math.round(j.rss_mb) : "–";
  const tk = s.tokens || {};
  $("t-tokens").textContent = fmtK(tk.today);
  const al = s.alerts || {};
  $("t-alerts").textContent = String(al.unread ?? 0);
  $("tile-alerts").classList.toggle("hot", (al.unread || 0) > 0);
  $("tile-alerts").title = al.recent?.[0] && al.unread ? al.recent[0].title : "No new alerts";
  renderJobs(s.jobs || {});
  renderAgent(s.agent);
}

// ---------- agents: General (default) or the coding agent; its news ("Crashed: ... fix it?") is said in the chat
let agentName = "general", agentSeen = null;
function renderAgent(a) {
  if (!a) return;
  agentName = a.name || "general";
  const sw = $("agent-switch");
  sw.dataset.on = agentName;
  $("agent-select").value = agentName;
  for (const b of sw.querySelectorAll("button")) b.setAttribute("aria-checked", String(b.dataset.agent === agentName));
  const evs = a.events || [];
  if (agentSeen === null) { agentSeen = Math.max(0, ...evs.map((e) => e.id)); return; } // never replay old news
  for (const e of evs) {
    if (e.id <= agentSeen || !e.text) continue;
    agentSeen = e.id;
    const bb = new BotBubble();
    bb.append(e.text);
    bb.finish();
    if (e.actions?.length) { // Fix it / Ask ChatGPT / Ask Gemini / Ask Claude
      const row = el("div", "suggest agent-acts");
      for (const a of e.actions) {
        const btn = el("button", "chip sug");
        btn.type = "button";
        btn.textContent = a.label;
        btn.onclick = () => { row.remove(); ask(a.say); };
        row.append(btn);
      }
      bb.body.insertBefore(row, bb.meta); // under the message, not beside it
    }
    scrollDown(true);
    miniCaption("bot", e.text, true);
    if (!S.mute) { audioCtx(); player.enqueue(e.text, null); }
  }
}
// the mini chat gets no status stream: it asks for the agent's news itself (a tiny request every 4 s)
if (MINI) setInterval(async () => { if (!document.hidden) { try { renderAgent(await api.agentState()); } catch { /* offline */ } } }, 4000);
$("agent-select").onchange = async (ev) => { // the mini chat's drop-down
  const name = ev.target.value;
  try {
    const r = await api.agent(name);
    renderAgent(r);
    tip($("agent-select"), name === "coding" ? "Coding agent on" : "Back to General");
  } catch (e) { ev.target.value = agentName; tip($("agent-select"), "Couldn't switch: " + e.message); }
};
for (const b of $("agent-switch").querySelectorAll("button")) {
  b.onclick = async () => {
    if (b.dataset.agent === agentName) return;
    try {
      const r = await api.agent(b.dataset.agent);
      renderAgent(r);
      tip($("agent-switch"), b.dataset.agent === "coding" ? "Coding agent on: crashes in the VS Code terminal → I offer the fix."
        : "Back to General.");
    } catch (e) { tip($("agent-switch"), "Couldn't switch: " + e.message); }
  };
}

function renderJobs(jb) {
  const items = jb.items || [];
  const key = JSON.stringify(items);
  $("jobs-count").textContent = items.length ? `${jb.running || 0} running` : "";
  if (key === lastJobsKey) return; // only on change
  lastJobsKey = key;
  loadOutputs(); // a job finished or started: its output may be new
  loadWall(); // ...or it set a new wallpaper
  loadDash(); // ...and Now & today lists it
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
  if (MINI || minimized) return;
  let it = null;
  try { it = (await api.fetchWeather()).items?.[0] || null; } catch { it = null; }
  const ok = !!it && !it.error && it.temp_c != null;
  $("wx-place").textContent = (it?.place || "Nepalgunj");
  if (ok) tweenTo("wx-temp", it.temp_c, 0); else $("wx-temp").textContent = "--";
  $("tb-wx-t").textContent = ok ? `${Math.round(it.temp_c)}°` : "--°";
  $("tb-wx").title = ok ? `${it.place || "Weather"}: ${it.desc || ""}` : "Weather";
  $("wx-desc").textContent = ok ? it.desc || "" : "unavailable";
  $("wx-sub").textContent = ok ? `Feels ${Math.round(it.feels_c)}° · ${Math.round(it.humidity)}% · ${Math.round(it.wind_kmh)} km/h` : "";
  const k = ok ? wxKind(it) : "cloud", ic = $("wx-icon");
  if (alive() || ic.dataset.k !== k) { ic.dataset.k = k; ic.innerHTML = WX_SVG[k]; } // re-insert = replay the one-shot animation
  try { wxFull = await api.weatherFull(); } catch { wxFull = null; }
  renderWxHours(ok ? it : null);
}
let wxFull = null;
function renderWxHours(now) {
  const box = $("wx-hours"), f = wxFull;
  if (!f || f.error || !f.hours?.length) { box.innerHTML = ""; return; }
  const d0 = f.days?.[0], d1 = f.days?.[1];
  if (now && d0) $("wx-sub").textContent = `${Math.round(d0.min)}° – ${Math.round(d0.max)}° · rain ${d0.rain ?? 0}%`;
  const picks = [1, 4, 7, 10].map((i) => f.hours[i]).filter(Boolean);
  const h12 = (t) => { const h = +t.slice(0, 2); return `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`; };
  box.innerHTML = picks.map((h) => `<div class="h"><small>${h12(h.t)}</small>${Math.round(h.temp)}°${h.rain >= 30 ? `<i>${h.rain}%</i>` : ""}</div>`).join("")
    + (d1 ? `<div class="h"><small>Tmrw</small>${Math.round(d1.min)}–${Math.round(d1.max)}°</div>` : "");
}
loadWeather();

// ---------- this laptop: Wi-Fi, volume, brightness, battery health, next reminder (every 30 s, only while visible) ----------
let devTimer = 0, devLast = null;
function renderBatSub() {
  const st = $("d-bat").dataset.state || "", h = devLast?.battery;
  $("d-bat").textContent = [st, h ? `health ${h.health}%` : ""].filter(Boolean).join(" · ") || "–";
}
async function loadDevice() {
  clearTimeout(devTimer); devTimer = 0;
  if (MINI || paused || minimized || document.hidden) return; // applyActivity starts it again
  try {
    const d = devLast = await api.device();
    const w = d.wifi, v = d.volume;
    tweenTo("d-wifi", w ? w.signal : null);
    setBar("d-wifi-bar", w?.signal ?? 0);
    $("d-ssid").textContent = w ? w.ssid : d.ip ? "wired" : "offline";
    $("d-ssid").title = w ? `Wi-Fi: ${w.ssid} · ${d.ip || ""}` : "";
    tweenTo("d-vol", v ? v.percent : null);
    setBar("d-vol-bar", v && !v.muted ? v.percent : 0);
    $("d-vol-sub").textContent = v ? (v.muted ? "muted" : `speaker · screen ${d.brightness ?? "–"}%`) : "–";
    renderBatSub();
    $("dev-up").textContent = "up " + fmtDur(d.uptime_s);
  } catch { /* API still starting: try again next round */ }
  devTimer = setTimeout(loadDevice, 30000);
}

// ---------- Today: reminders, alarms, timers + stopwatch (card + details dialog; live countdowns on the clock tick) ----------
const ICON = {
  alarm: '<svg viewBox="0 0 24 24"><circle cx="12" cy="13" r="7"/><path d="M12 9.5V13l2.5 1.5M5 4 2.5 6.5M19 4l2.5 2.5"/></svg>',
  timer: '<svg viewBox="0 0 24 24"><path d="M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9s8 4 8 9"/></svg>',
  reminder: '<svg viewBox="0 0 24 24"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0"/></svg>',
  command: '<svg viewBox="0 0 24 24"><path d="M5 7l5 5-5 5M12 17h7"/></svg>',
};
const sched = { items: [], sw: null, at: 0 };
let schedTimer = 0;
const hm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
function left(ts) { // "4:32" / "1:05:00" until ts
  const s = Math.max(0, Math.round(ts - Date.now() / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
function swNow() { const w = sched.sw; return w ? w.elapsed + (w.running_since ? Date.now() / 1000 - w.running_since : 0) : 0; }
function swFmt(s) { s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(x).padStart(2, "0")}`; }
function timeCell(it) { return it.kind === "timer" ? `${left(it.at)} left` : it.day === "today" ? hm(it.at) : it.day === "tomorrow" ? `tmrw ${hm(it.at)}` : new Date(it.at * 1000).toLocaleDateString([], { weekday: "short" }) + " " + hm(it.at); }
async function loadToday() {
  clearTimeout(schedTimer); schedTimer = 0;
  if (MINI) return;
  try {
    const r = await api.schedule();
    sched.items = r.items || []; sched.sw = r.stopwatch; sched.at = Date.now();
    renderToday();
    if (dash) renderNow(dash.now || [], dash.today || []);
    if ($("sched").open) renderSched();
  } catch { /* API busy */ }
  if (!paused && !minimized && !document.hidden) schedTimer = setTimeout(loadToday, 30000);
}
function renderToday() { // reminders/alarms/timers of today feed the chips via /dashboard; here: the stopwatch
  renderTodayLive();
}
function renderTodayLive() { // every second from tick(): timer countdowns + stopwatch
  for (const c of $("today-chips").querySelectorAll(".chip2.k-timer")) {
    const it = sched.items.find((x) => String(x.id) === c.dataset.id);
    if (it) c.querySelector("b").textContent = left(it.at);
  }
  const w = sched.sw, on = !!(w && (w.running_since || w.elapsed));
  $("today-sw").hidden = !on;
  if (on) {
    $("today-sw-time").textContent = swFmt(swNow());
    $("today-sw-state").textContent = w.running_since ? "running" : "paused";
    $("today-sw").classList.toggle("run", !!w.running_since);
  }
  if ($("sched").open) { $("sched-sw-time").textContent = swFmt(swNow()); for (const n of document.querySelectorAll(".sched-item.k-timer .t")) { const it = sched.items.find((x) => String(x.id) === n.dataset.id); if (it) n.textContent = timeCell(it); } }
}
function renderSched() {
  const box = $("sched-groups");
  box.innerHTML = "";
  const groups = [["Today", (i) => i.day === "today" && i.repeat === "none"], ["Tomorrow", (i) => i.day === "tomorrow" && i.repeat === "none"],
    ["Later", (i) => i.day === "later" && i.repeat === "none"], ["Repeating", (i) => i.repeat !== "none"]];
  let any = false;
  for (const [name, f] of groups) {
    const items = sched.items.filter(f);
    if (!items.length) continue;
    any = true;
    const g = el("section", "sched-group");
    g.append(el("h3", "", name));
    for (const it of items) {
      const row = el("div", `sched-item k-${it.kind}`);
      row.innerHTML = `<span class="ic">${ICON[it.kind] || ICON.reminder}</span><span class="t"></span><span class="x"></span>`;
      row.querySelector(".t").textContent = timeCell(it);
      row.querySelector(".t").dataset.id = it.id;
      row.querySelector(".x").innerHTML = `${esc(it.text)}<small>${esc(it.kind)} · ${esc(it.desc)}</small>`;
      const del = el("button", "icon-btn del", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>');
      del.type = "button";
      del.title = `Cancel this ${it.kind}`;
      del.onclick = async () => { try { await api.cancelSchedule(it.id); toast(`Cancelled: ${it.text}`); loadToday(); } catch (e) { toast(e.message); } };
      row.append(del);
      g.append(row);
    }
    box.append(g);
  }
  if (!any) box.append(el("p", "sched-empty", "Nothing scheduled yet."));
  const laps = sched.sw?.laps || [];
  $("sched-sw-laps").textContent = laps.length ? `Laps: ${laps.slice(-4).map(swFmt).join(" · ")}` : "";
  $("sched-sw-time").textContent = swFmt(swNow());
}
function openSched() { if (!$("sched").open) $("sched").showModal(); renderSched(); loadToday(); }
$("sched").addEventListener("click", (e) => { if (e.target === $("sched")) $("sched").close(); });
for (const b of document.querySelectorAll("[data-sw]")) {
  b.onclick = async () => { try { const r = await api.stopwatch(b.dataset.sw); toast(r.text); loadToday(); } catch (e) { toast(e.message); } };
}

// ---------- workspace: results (outputs from /api/v1/outputs + long replies) as a list with tabs, a preview and actions ----------
const ws = { items: [], cur: -1, seen: new Set(), loaded: false, tab: "all" };
const wsTitle = (name) => name.replace(/^.*\//, "").replace(/^\d{8}-\d{4,6}-?/, "").replace(/\.[a-z0-9]+$/i, "").replace(/[-_]+/g, " ").trim() || name;
// only a big answer goes to the Workspace too (simple ones stay in the chat)
// same rule as the server (config.CHAT_MAX_CHARS / CHAT_MAX_LINES): long answers belong in the workspace
const CHAT_LONG = (t) => !!t && (t.length > 380 || t.split("\n").filter((l) => l.trim()).length > 3 || t.includes("```"));
const chatHead = (t) => (t.split("\n").find((l) => l.trim()) || "").slice(0, 200).replace(/:\s*$/, "") + " … (putting it in the workspace)";
const LONG_REPLY = (t) => t && (t.split("\n").filter((l) => l.trim()).length >= 14 || t.length > 1500);
const WS_MAX = 100; // kept in the panel (the files themselves stay in data/outputs for good)
const WS_SHOW = 10; // listed per tab: the last 10 documents, 10 pictures, 10 code files...
const WS_TABS = [["all", "All"], ["doc", "Docs"], ["code", "Code"], ["image", "Images"], ["media", "Audio"], ["data", "Data"]];
function wsType(it) {
  if (it.kind === "image") return "image";
  if (it.kind === "audio" || it.kind === "video") return "media";
  const ext = (it.name || "").split(".").pop().toLowerCase();
  if (["py", "js", "sh", "html", "json", "ipynb", "ts", "css"].includes(ext)) return "code";
  if (["csv", "tsv", "jsonl"].includes(ext)) return "data";
  return "doc";
}
const fmtSize = (b) => (b == null ? "" : b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : b >= 1024 ? `${Math.round(b / 1024)} KB` : `${b} B`);
function fmtAgo(t) {
  if (!t) return "";
  const d = Date.now() / 1000 - t;
  return d < 60 ? "just now" : d < 3600 ? `${Math.floor(d / 60)} min ago` : d < 86400 ? `${Math.floor(d / 3600)} h ago`
    : d < 172800 ? "yesterday" : `${Math.floor(d / 86400)} days ago`;
}
function wsShown() { return ws.items.filter((x) => ws.tab === "all" || x.type === ws.tab); }

function wsAdd(item, show) {
  if (ws.seen.has(item.key)) return;
  if (show && ws.loaded) wsPanel(true); // minimal layout: a NEW result slides the workspace in
  ws.seen.add(item.key);
  item.type = wsType(item);
  ws.items.unshift(item);
  if (ws.items.length > WS_MAX) ws.items.length = WS_MAX;
  if (show || ws.cur < 0) wsShow(item); else wsList();
}

function wsClearAll() { // dashboard: after "clean workspace"
  ws.items = []; ws.cur = -1; // keep ws.seen: cleaned files never come back from a stale list
  $("ws-view").innerHTML = '<p class="ws-empty">Pictures, code and writing you ask for appear here.</p>';
  wsList();
}

function wsList() {
  const counts = {};
  for (const x of ws.items) counts[x.type] = (counts[x.type] || 0) + 1;
  $("ws-tabs").innerHTML = WS_TABS.filter(([k]) => k === "all" || counts[k])
    .map(([k, n]) => `<button type="button" role="tab" data-wstab="${k}" aria-selected="${ws.tab === k}">${n}${k !== "all" ? `<small>${counts[k]}</small>` : ""}</button>`).join("");
  const list = wsShown().slice(0, WS_SHOW);
  const ul = $("ws-list");
  ul.innerHTML = list.length ? "" : '<li class="empty">Nothing here yet.</li>';
  for (const it of list) {
    const li = el("li", it === ws.items[ws.cur] ? "sel" : "");
    const ext = (it.name || "").split(".").pop().toUpperCase();
    const badge = it.type === "image" && it.src ? `<img src="${esc(it.src)}" alt="" loading="lazy" decoding="async">`
      : esc(it.name ? ext.slice(0, 4) : "TXT");
    li.innerHTML = `<span class="ft t-${it.type}">${badge}</span>
      <div class="grow"><div class="n ell"></div><div class="d"></div></div><span class="z"></span>`;
    li.querySelector(".n").textContent = it.title;
    li.querySelector(".d").textContent = it.mtime ? fmtAgo(it.mtime) : "from the chat";
    li.querySelector(".z").textContent = fmtSize(it.size);
    li.title = it.name || it.title;
    li.onclick = () => wsShow(it);
    ul.append(li);
  }
  wsActs();
}

async function wsBody(it, box) {
  const tok = (box._tok = Symbol("render")); // a newer render wins (startup loads several items at once)
  box.innerHTML = "";
  if (it.kind === "audio" || it.kind === "video") { // MP3s (read aloud) and short videos KURAMA made
    const m = el(it.kind, "ws-media");
    m.controls = true; m.preload = "metadata"; m.src = it.src;
    box.append(m);
    return;
  }
  if (it.kind === "image") {
    const img = el("img", "ws-img");
    img.alt = it.title; img.src = it.src; img.decoding = "async"; img.draggable = false;
    img.onclick = () => wsBig();
    box.append(img);
    return;
  }
  if (it.text == null && it.src) {
    try { const r = await fetch(it.src); it.text = r.ok ? await r.text() : "(couldn't load this file)"; }
    catch { it.text = "(couldn't load this file)"; }
    if (box._tok !== tok) return;
  }
  const doc = el("div", "ws-text");
  if (it.type === "code" || it.type === "data") {
    const lines = (it.text || "").split("\n").slice(0, 400);
    doc.innerHTML = `<pre class="code">${lines.map((l, i) => `<span class="ln">${i + 1}</span>${esc(l)}`).join("\n")}</pre>`;
  } else doc.innerHTML = renderDoc(it.text || ""); // headings, lists, tables...: a readable document
  box.append(doc);
}

async function wsShow(it) {
  if (typeof it === "number") it = ws.items[it];
  if (!it) return;
  ws.cur = ws.items.indexOf(it);
  if (ws.tab !== "all" && it.type !== ws.tab) ws.tab = "all";
  wsList();
  const view = $("ws-view");
  await wsBody(it, view);
  wsActs(); // now the line count is known
  view.scrollTop = 0;
  retrigger(view, "ws-in-a", "ws-in-b"); // one short fade in
  if ($("ws-big").open) wsBig();
}

function wsActs() { // what you can do with the selected result
  const it = ws.items[ws.cur], box = $("ws-acts");
  if (!it) { box.innerHTML = ""; return; }
  const file = !!it.name;
  const kind = { image: "image", code: "code", data: "data", doc: "doc", media: it.kind }[it.type] || it.type;
  const lines = it.text ? ` · ${(it.text.match(/\n/g) || []).length + 1} lines` : "";
  box.innerHTML = `<span class="tiny grow ell">${esc(kind + lines + (it.size ? ` · ${fmtSize(it.size)}` : ""))}</span>`
    + (file && it.type !== "image" && it.type !== "media" ? '<button type="button" class="act" data-ws="open_vscode">VS Code</button>' : "")
    + (file && (it.type === "image" || it.type === "media") ? '<button type="button" class="act" data-ws="open">Open</button>' : "")
    + (it.type !== "image" && it.type !== "media" ? '<button type="button" class="act ghost" data-ws="copy">Copy</button>' : "")
    + (file ? '<button type="button" class="act ghost" data-ws="send_phone">Phone</button><button type="button" class="act ghost" data-ws="show_folder">Folder</button>' : "")
    + (file ? '<button type="button" class="act ghost danger" data-ws="delete" title="Delete this item (to the trash)">Delete</button>' : "");
}
async function wsDelete(it) { // dashboard: remove ONE workspace item
  if (!it?.name || !confirm(`Delete "${it.title}"? It goes to the trash.`)) return;
  try { await api.deleteOutput(it.name); } catch (e) { toast("Couldn't delete it: " + e.message); return; }
  const i = ws.items.indexOf(it);
  ws.items.splice(i, 1);
  const next = ws.items[Math.min(i, ws.items.length - 1)];
  if (next) wsShow(next); else wsClearAll();
  toast("Deleted (it's in the trash).");
}
async function wsAction(name) {
  const it = ws.items[ws.cur];
  if (!it) return;
  if (name === "copy") {
    try { await navigator.clipboard.writeText(it.text || ""); toast("Copied."); } catch { toast("Couldn't copy here."); }
    return;
  }
  if (name === "delete") { wsDelete(it); return; }
  doAction({ name, path: it.name });
}
$("ws-acts").addEventListener("click", (e) => { const b = e.target.closest("[data-ws]"); if (b) wsAction(b.dataset.ws); });
$("ws-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-wstab]");
  if (!b) return;
  ws.tab = b.dataset.wstab;
  const cur = ws.items[ws.cur], list = wsShown();
  if (list.length && !list.includes(cur)) wsShow(list[0]); else wsList(); // show this tab's newest
});

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
    const items = ((await api.outputs(100)).items || []) // small saved tool results (quick lists) are not Workspace material
      .filter((x) => !(String(x.name).startsWith("results/") && x.size < 4000));
    const fresh = items.filter((x) => !ws.seen.has("o" + x.name + x.mtime)).reverse(); // oldest first
    for (const x of fresh) {
      wsAdd({ key: "o" + x.name + x.mtime, kind: x.kind, title: wsTitle(x.name), name: x.name, mtime: x.mtime, size: x.size,
        src: api.outputUrl(x.name) }, ws.loaded && x === fresh[fresh.length - 1]); // jump to a NEW result; at startup just list
    }
    if (!ws.loaded && fresh.length) wsShow(0); // startup: open on the newest
    ws.loaded = true;
  } catch { /* API down: keep what we have */ }
  finally { outputsBusy = false; }
}
loadOutputs();
$("ws-expand").onclick = () => wsBig();
$("ws").addEventListener("keydown", (e) => {
  const list = wsShown(), i = list.indexOf(ws.items[ws.cur]);
  if (e.key === "ArrowUp" && i > 0) { e.preventDefault(); wsShow(list[i - 1]); }
  if (e.key === "ArrowDown" && i < list.length - 1) { e.preventDefault(); wsShow(list[i + 1]); }
});
document.addEventListener("keydown", (e) => {
  if (!$("ws-big").open) return;
  const list = wsShown(), i = list.indexOf(ws.items[ws.cur]);
  if (e.key === "ArrowLeft" && i > 0) wsShow(list[i - 1]);
  if (e.key === "ArrowRight" && i < list.length - 1) wsShow(list[i + 1]);
});

// ---------- live panels: memory by app, coding, now & today, switches, KURAMA (one /dashboard call, every 10 s) ----------
let dash = null, dashTimer = 0, dashBusy = false, fresh = false;
const gbOf = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);
async function loadDash() {
  clearTimeout(dashTimer); dashTimer = 0;
  if (MINI || paused || minimized || document.hidden || dashBusy) return; // applyActivity starts it again
  dashBusy = true;
  try { dash = await api.dashboard(fresh); fresh = false; renderDash(); } catch { /* API busy: next round */ }
  finally { dashBusy = false; }
  dashTimer = setTimeout(loadDash, 10000);
}
function renderDash() {
  if (!dash) return;
  renderCoding(dash.coding || {});
  renderWork(dash.work || {});
  renderNow(dash.now || [], dash.today || []);
  renderSwitches(dash.switches || {});
  renderTracker(dash.tracker || {});
  const k = dash.kurama || {};
  $("t-free").textContent = k.free_pct == null ? "–" : `${k.free_pct}%`;
  $("t-calls").textContent = k.calls_today ? `${k.calls_today} calls` : "";
  const [run, tot] = k.workers || [0, 0];
  $("k-workers").innerHTML = Array.from({ length: tot }, (_, i) => `<i class="${i < run ? "" : "off"}"></i>`).join("");
  $("k-workers").title = `${run} of ${tot} background workers running`;
  renderSuggest();
}
// Work card: long goals (countdown / project day N of M) + my list, above the coding block
const hm12 = (hm) => { const [h, m] = (hm || "0:0").split(":").map(Number); return `${h % 12 || 12}${m ? ":" + String(m).padStart(2, "0") : ""} ${h < 12 ? "AM" : "PM"}`; };
function goalRight(g) {
  if (g.kind === "project" && g.total) return `day ${Math.min(g.day, g.total)}/${g.total}`;
  if (g.left == null) return `day ${g.day}`;
  return g.left > 1 ? `${g.left} days` : g.left === 1 ? "tomorrow" : g.left === 0 ? "today" : "ended";
}
function goalSub(g, full) {
  const bits = [];
  if (g.status === "paused") bits.push("paused");
  if (g.today.length) bits.push(`<span class="ok">✓ today:</span> ${esc(g.today.join(" · "))}`);
  else if (g.ask) bits.push(`check-in ${hm12(g.ask_at)}`);
  if (full || !g.today.length) {
    if (g.end_nice) bits.push(`ends ${esc(g.end_nice)}`);
    if (full && g.remind) bits.push(`reminders ${g.remind.split(",").map((x) => hm12(x.trim())).join(", ")}`);
    if (full && g.notes) bits.push(`${g.notes} notes`);
  }
  return bits.join(" · ");
}
const goalHtml = (g, full = false) => `<div class="goal${g.status === "paused" ? " paused" : ""}"><div class="gh"><b title="${esc(g.name)}">${g.kind === "project" ? "📂" : "📅"} ${esc(g.name)}</b>
  <span class="${g.kind !== "project" && g.left != null && g.left <= 7 ? "soon" : ""}">${goalRight(g)}</span></div>
  ${g.progress != null ? `<div class="gbar"><i style="width:${Math.max(2, Math.round(g.progress * 100))}%"></i></div>` : ""}
  <div class="gs">${goalSub(g, full)}</div></div>`;
function renderWork(w) {
  const gs = w.goals || [], l = w.list || {};
  $("goal-body").innerHTML = gs.slice(0, 3).map((g) => goalHtml(g)).join("") + (gs.length > 3 ? `<div class="gs">+${gs.length - 3} more</div>` : "");
  const parts = [l.todo && `<b>${l.todo}</b> to-do${l.today ? ` (${l.today} today${l.overdue ? `, <span class="late">${l.overdue} overdue</span>` : ""})` : ""}`,
    l.reminders && `<b>${l.reminders}</b> reminder${l.reminders > 1 ? "s" : ""}`, l.read && `<b>${l.read}</b> to read`].filter(Boolean);
  $("list-line").innerHTML = parts.length ? parts.join(" · ") : (gs.length ? "" : 'Nothing yet: say “add finish the report to my to-do, due Friday”.');
  $("todo-items").innerHTML = (w.items || []).map((r) => todoLi(r)).join("");
  $("tb-todo-n").textContent = l.todo || "";
  $("tb-todo").classList.toggle("hot", !!(l.overdue || l.today));
  $("tb-todo").title = l.todo ? `To-do: ${l.todo}${l.today ? `, ${l.today} today` : ""}${l.overdue ? `, ${l.overdue} overdue` : ""}` : "To-do list";
  $("tb-rem-n").textContent = l.reminders || "";
  $("work-pill").textContent = gs.length ? `${gs.length} long task${gs.length > 1 ? "s" : ""}` : "";
}
function todoLi(r) { // one to-do: ❗ for high priority, due/overdue, 🔔 when it has a linked reminder, ✓ done, ✕ delete
  return `<li${r.late ? ' class="late"' : ""}><span class="ell" title="${esc(r.title)}">${r.priority === 1 ? "❗" : "✅"} ${esc(r.title)}${r.tag ? ` <small>#${esc(r.tag)}</small>` : ""}${r.bell ? " 🔔" : ""}</span>
    <small>${esc(r.due || "")}</small><button type="button" class="tb ok" data-todo="done" data-id="${r.id}" data-type="todo" title="Done" aria-label="Done">✓</button>
    <button type="button" class="tb" data-todo="remove" data-id="${r.id}" data-type="todo" title="Delete" aria-label="Delete">✕</button></li>`;
}
document.addEventListener("click", async (e) => { // ✓ done / ✕ delete a to-do, ✕ cancel a reminder, ✓ read a link (no chat, 0 tokens)
  const b = e.target.closest("[data-todo]");
  if (!b) return;
  e.stopPropagation();
  b.disabled = true;
  try { const r = await api.todo(b.dataset.todo, b.dataset.type, Number(b.dataset.id || 0), b.dataset.title || ""); toast(r.text); }
  catch { toast("Couldn't change it right now."); }
  fresh = true; loadDash(); loadToday();
  if ($("sheet")?.open && b.closest("#sheet")) openSheet("work");
}, true);
function fmtDue(due) { // '2026-10-27 17:00' -> 'tomorrow 5 PM'
  if (!due) return "";
  const [d, t] = due.split(" "), today = new Date(), tm = new Date(today.getTime() + 864e5);
  const iso = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  const day = d === iso(today) ? "today" : d === iso(tm) ? "tomorrow" : new Date(d + "T12:00").toLocaleDateString([], { month: "short", day: "numeric" });
  return t ? `${day} ${hm12(t)}` : day;
}
function renderCoding(c) {
  const box = $("code-body");
  if (!c.project) { box.innerHTML = '<p class="empty">No project watched: say “watch the project at /path” (or open it in VS Code and say “watch this project”).</p>'; $("code-snap").textContent = ""; return; }
  $("code-snap").textContent = c.snapshot ? `snapshot ${c.snapshot === "now" ? "just now" : c.snapshot + " ago"}` : "";
  const e = c.error;
  box.innerHTML = `<div class="proj"><b class="ell">${esc(c.project)}</b>${c.branch ? `<span class="branch">${esc(c.branch)}</span>` : ""}</div>
    <div class="trio"><div><span>CHANGED</span><b class="${c.changed ? "warn" : ""}">${c.changed ?? "–"}</b></div>
      <div><span>LINES</span><b><span class="ok">+${c.ins ?? 0}</span> <span class="bad">−${c.dels ?? 0}</span></b></div>
      <div><span>COMMIT</span><b>${c.last_commit ? esc(c.last_commit) : "–"}</b></div></div>
    ${(c.files || []).length ? `<ul class="cfiles">${c.files.map((f) => `<li><button type="button" class="link ell" data-act="open_vscode" data-path="${esc(c.path + "/" + f.file)}" title="Open in VS Code">${esc(f.file)}</button><span>${f.ins === "new" ? '<i class="ok">new</i>' : `<i class="ok">+${esc(f.ins)}</i> <i class="bad">−${esc(f.dels)}</i>`}</span></li>`).join("")}</ul>` : ""}
    ${e ? `<div class="code-err ell" title="${esc(e.text)}">● <code>${esc(e.text)}</code>${e.where ? ` · ${esc(e.where)}` : ""}</div>` : ""}
    <div class="btns"><button type="button" class="act" data-act="open_vscode" data-path="${esc(c.path)}">VS Code</button>
      <button type="button" class="act ghost" data-ask="where was I">Where was I?</button>
      <button type="button" class="act ghost" data-ask="what did I change in the last hour">Changes</button></div>`;
}
const NOW_IC = { train: "◐", download: "⇣", web: "◉", job: "✍", record: "●", guard: "⛨" };
function renderNow(items, classes) {
  const ul = $("now-list");
  ul.innerHTML = items.slice(0, 3).map((x) => `<li class="k-${x.kind}"><span class="ic">${NOW_IC[x.kind] || "•"}</span>
    <div class="grow"><div class="ell">${esc(x.title)}</div><div class="s ell">${esc(x.sub || "")}</div>
    ${x.progress != null ? `<div class="mini"><i style="width:${Math.round(x.progress * 100)}%"></i></div>` : ""}</div>
    <span class="r">${esc(x.right || "")}</span></li>`).join("");
  // today: classes (timetable) + reminders/alarms/timers (live countdowns, from /schedule)
  const now = Date.now() / 1000;
  const sch = sched.items.filter((i) => i.day === "today" && i.at > now).map((i) => ({ time: i.kind === "timer" ? null : hm(i.at),
    text: i.text, kind: i.kind, id: i.id, at: i.at }));
  const chips = [...classes.map((c) => ({ ...c, at: null })), ...sch].sort((a, b) => (a.at || 0) - (b.at || 0) || String(a.time).localeCompare(String(b.time)));
  let nextDone = false;
  $("today-chips").innerHTML = chips.slice(0, 5).map((c) => {
    const next = !nextDone && (c.next || c.at); if (next) nextDone = true;
    return `<span class="chip2 k-${c.kind}${next ? " next" : ""}" data-id="${c.id ?? ""}"><b>${c.kind === "timer" ? left(c.at) : esc(c.time || "")}</b>${esc(c.text)}</span>`;
  }).join("");
  const n = items.length, first = items[0], nextChip = chips.find((c) => c.next || c.at) || chips[0];
  $("today-count").textContent = n ? `${n} running` : chips.length ? `${chips.length} today` : "all quiet";
  if (!n && !chips.length) ul.innerHTML = '<li class="empty">Nothing running right now.</li>';
  $("today").classList.toggle("quiet", !n && !chips.length); // nothing to show: just the title line (room for the other cards)
}
// Money & habits card: today / month (+ budget), 7-day bars, top categories, habits with their week and a ✓ button
function renderTracker(t) {
  const m = t.money || {}, hs = t.habits || [], cur = m.currency || "Rs";
  const amt = (v) => `${cur} ${Math.round(v || 0).toLocaleString("en-IN")}`;
  $("m-today").textContent = amt(m.today);
  $("m-month").textContent = amt(m.month);
  const w = m.last7 || [], top = Math.max(1, ...w);
  $("m-bars").innerHTML = w.map((v, i) => `<i style="height:${Math.max(6, Math.round(v / top * 100))}%" class="${i === w.length - 1 ? "now" : ""}${v ? "" : " zero"}" title="${amt(v)}"></i>`).join("");
  const used = m.budget_used;
  $("m-budget-row").hidden = used == null;
  if (used != null) {
    const bar = $("m-budget-bar");
    bar.style.transform = `scaleX(${Math.min(1, used)})`;
    bar.classList.toggle("low", used >= 1);
    bar.classList.toggle("hot", used >= 0.8 && used < 1);
    $("m-budget").textContent = `${Math.round(used * 100)}% of ${amt(m.budget)} budget`;
  }
  const bills = (m.bills_due || []).map((b) => `<span class="mchip due">💸 ${esc(b)} due</span>`).join("");
  $("m-top").innerHTML = bills + (m.top || []).slice(0, 3).map((c) => `<span class="mchip">${esc(c.cat)} ${amt(c.amount)}</span>`).join("");
  const done = hs.filter((h) => h.done).length;
  $("track-pill").textContent = hs.length ? `habits ${done}/${hs.length}` : "";
  const ul = $("habit-list");
  $("track").classList.toggle("empty-track", !hs.length && !m.month && !(m.recent || []).length);
  if (!hs.length && !m.month) {
    ul.innerHTML = `<li class="empty">Say “spent 500 on food” or “add a habit: drink water 8 glasses a day”.</li>`;
    return;
  }
  ul.innerHTML = hs.slice(0, 4).map((h) => `<li class="${h.done ? "done" : ""}">
    <span class="hn ell" title="${esc(h.name)}">${esc(h.name)}${h.target > 1 ? ` <small>${h.today}/${h.target}</small>` : ""}</span>
    <span class="hw">${h.week.map((d) => `<i class="${d ? "on" : ""}"></i>`).join("")}</span>
    <span class="hs" title="best ${h.best}">${h.streak ? `🔥${h.streak}` : ""}</span>
    <button type="button" class="tb ${h.done ? "" : "ok"}" data-habit="${h.done ? "habit_undo" : "habit_done"}" data-ref="${esc(h.name)}"
      title="${h.done ? "Undo today" : "Done today"}" aria-label="${h.done ? "Undo" : "Done"}">${h.done ? "↺" : "✓"}</button></li>`).join("");
}
$("track").addEventListener("click", (e) => { // the card itself opens the Money window (date range, category, rows)
  if (e.target.closest("button")) return;
  openMoney(api, { esc, toast, onChange: () => { fresh = true; loadDash(); } });
});
document.addEventListener("click", async (e) => { // Money & habits card: ✓ habit done / ↺ undo (no chat, 0 tokens)
  const b = e.target.closest("[data-habit]");
  if (!b) return;
  e.stopPropagation();
  b.disabled = true;
  try { const r = await api.tracker(b.dataset.habit, b.dataset.ref); toast(r.text); } catch { toast("Couldn't change it right now."); }
  fresh = true; loadDash();
}, true);
function renderSwitches(sw) {
  for (const b of document.querySelectorAll("[data-switch]")) {
    const on = !!sw[b.dataset.switch];
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
    b.title = `${b.textContent} is ${on ? "on" : "off"}: click to turn it ${on ? "off" : "on"}`;
  }
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-switch]");
  if (!b) return;
  e.stopPropagation(); // a switch is not "open the card"
  const want = b.classList.contains("on") ? "off" : "on";
  b.classList.toggle("on", want === "on"); // optimistic, corrected by the reply
  try { const r = await api.action({ name: "toggle", setting: b.dataset.switch, state: want }); toast(r.text); }
  catch (err) { b.classList.toggle("on", want !== "on"); toast(err.message || "Couldn't switch it."); }
  loadDash();
});

// buttons that DO something: data-act -> a direct, safe action; data-ask -> a normal request (same tools + confirmations)
async function doAction(body) {
  try { const r = await api.action(body); toast(r.text); } catch (e) { toast(e.message || "That didn't work."); }
}
function ask(text) {
  if ($("sheet").open) $("sheet").close();
  const speak = !S.mute;
  if (speak) audioCtx();
  sendChat(text, { voice: speak, speak, lang: S.lang });
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act], [data-ask]");
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  if (b.dataset.ask) ask(b.dataset.ask);
  else doAction({ name: b.dataset.act, path: b.dataset.path || "" });
}, true);

// click a card -> a big sheet with everything about it
const SHEETS = { modes: "KURAMA modes", weather: "Weather", apps: "Memory & processes", coding: "Coding", work: "Work · goals, to-do & coding", laptop: "This laptop", system: "System", now: "Now & today" };
function cardOpen(card) { if (card?.dataset.sheet) openSheet(card.dataset.sheet); }
for (const c of document.querySelectorAll("[data-sheet]")) {
  c.addEventListener("click", (e) => { if (!e.target.closest("button, a, input")) cardOpen(c); });
  c.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === c) { e.preventDefault(); cardOpen(c); } });
}
$("sheet-close").onclick = () => $("sheet").close();
$("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) $("sheet").close(); });
const tbl = (rows) => `<table>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>`;
const tile = (title, html, cls = "") => `<section class="tile ${cls}"><h3>${esc(title)}</h3>${html}</section>`;
async function openSheet(panel) {
  $("sheet-title").textContent = SHEETS[panel] || "Details";
  const body = $("sheet-body");
  body.innerHTML = '<p class="empty">Loading…</p>';
  if (!$("sheet").open) $("sheet").showModal();
  try { body.innerHTML = await sheetHtml(panel); if (panel === "modes") bindModes(body); }
  catch (e) { body.innerHTML = `<p class="empty">Couldn't load this right now (${esc(e.message || "error")}).</p>`; }
}
async function kuramaResources() { // System sheet: what each part of KURAMA uses right now
  let r;
  try { r = await api.resources(); } catch { return '<p class="empty">Couldn\'t read it right now.</p>'; }
  const max = Math.max(1, ...r.parts.map((p) => p.mb));
  const rows = r.parts.map((p) => [`${esc(p.name)}<small>${p.procs} process${p.procs > 1 ? "es" : ""}</small>`,
    `<span class="bar"><span class="fill" style="width:${Math.max(3, Math.round(100 * p.mb / max))}%"></span></span>`, `${p.mb} MB`, `${p.cpu}% CPU`]);
  const sem = r.semantic;
  const modes = { always: "always ready", auto: "loads when needed", off: "off" };
  return tbl(rows) + `<p class="tiny">Total: <b>${r.total_mb} MB</b> (${r.ram_share}% of this laptop's RAM) · ${r.total_cpu}% of the laptop's CPU (all cores).
    Memory counts shared libraries once. Opening this sheet makes the screen work for a moment, so the screen's CPU here is higher than usual.
    Understanding model: ${modes[sem.mode] || sem.mode}, ${sem.loaded ? `loaded (${sem.mb} MB)` : "not loaded"}.</p>
    <div class="btns">${sem.loaded ? '<button type="button" class="act ghost" id="res-free">Free the model now</button>' : ""}
    <button type="button" class="act ghost" id="res-settings">Memory settings</button></div>`;
}
document.addEventListener("click", async (e) => {
  if (e.target.id === "res-free") { try { await api.freeModel(); toast("Model memory freed."); } catch { /* ignore */ } openSheet("system"); }
  if (e.target.id === "res-settings") { $("sheet").close(); openSettings(); }
});
function codingHtml(d) {
    if (!d.project) return '<p class="empty">No project yet. Say “protect my project”.</p>';
    const files = d.files.length ? tbl(d.files.slice(0, 14).map((f) => [`<button type="button" class="link" data-act="open_vscode" data-path="${esc(d.path + "/" + f.file)}">${esc(f.file)}</button>`,
      f.ins === "new" ? '<span class="ok">new</span>' : `<span class="ok">+${esc(f.ins)}</span> <span class="bad">−${esc(f.dels)}</span>`])) : '<p class="empty">No uncommitted changes.</p>';
    const errs = d.errors.length ? tbl(d.errors.map((e) => [`<code>${esc(e.error)}</code><small>${esc(e.where || "")} · ${esc(e.ago)} ago</small>`, e.fix ? `fixed: ${esc(e.fix)}` : `${e.count}×`])) : '<p class="empty">No recent errors.</p>';
    return `<div class="sgrid">${tile(`Changes · ${d.project}${d.branch ? " (" + d.branch + ")" : ""}`, files + `<div class="btns"><button type="button" class="act" data-act="open_vscode" data-path="${esc(d.path)}">Open in VS Code</button><button type="button" class="act ghost" data-act="show_folder" data-path="${esc(d.path)}">Folder</button><button type="button" class="act ghost" data-ask="what did I change in the last hour">What changed</button><button type="button" class="act ghost" data-ask="commit my changes">Commit…</button></div>`, "span2")}
      ${tile("Where you left off", '<p>Ask me and I\'ll sum it up from git, your errors and your snapshots.</p><div class="btns"><button type="button" class="act" data-ask="where was I">Where was I?</button></div>')}
      ${tile("Snapshots", d.snapshots.length ? `<pre class="plain">${esc(d.snapshots.join("\n"))}</pre>` : '<p class="empty">None yet.</p>')}
      ${tile("Recent errors", errs, "span2")}
      ${tile("Projects", tbl(d.projects.slice(0, 10).map((x) => [esc(x.name), `<button type="button" class="act ghost" data-act="open_vscode" data-path="${esc(x.path)}">VS Code</button>`])), "span3")}</div>`;
  }
function workHtml(d) {
  const ask = (q, label, cls = "ghost") => `<button type="button" class="act ${cls}" data-ask="${esc(q)}">${esc(label)}</button>`;
  const goals = (d.goals || []).map((g) => goalHtml(g, true).replace(/<\/div>$/, `<div class="btns">${ask(`what did we do today in ${g.name}`, "Today", "")}
    ${ask(`what did we do this week on ${g.name}`, "This week")}${ask(`how is ${g.name} going`, "Progress")}
    ${g.kind === "project" ? ask(`make the ${g.name} report`, "Report") : ""}
    ${g.folder ? `<button type="button" class="act ghost" data-act="show_folder" data-path="${esc(g.folder)}">Folder</button>` : ""}
    ${ask(`${g.status === "paused" ? "resume" : "pause"} the ${g.name} long task`, g.status === "paused" ? "Resume" : "Pause")}</div></div>`)).join("");
  const help = '<p class="tiny">Say: “my exam is in 30 days, remind me 3 times a day” · “I started a project that ends in 6 months, ask me every day” · “Thesis update: wrote chapter 2” · “move my exam to December 2” · “the exam is over”. Stored in ~/Documents/KURAMA/goals.xlsx.</p>';
  const todo = (d.items || []).length ? `<ul class="tlist big">${d.items.map((r) => todoLi(r)).join("")}</ul>`
    : '<p class="empty">No to-dos. Say “add finish the report to my to-do, due Friday, high priority”.</p>';
  const rem = (d.reminders || []).length ? tbl(d.reminders.map((r) => [`${r.kind === "alarm" ? "⏰" : "🔔"} ${esc(r.text)}`,
    `${esc(r.when)} <button type="button" class="tb" data-todo="remove" data-type="reminder" data-id="${r.id}" title="Cancel" aria-label="Cancel">✕</button>`]))
    : '<p class="empty">No reminders. Say “remind me to call mom at 5 pm”.</p>';
  const reads = (d.reads || []).length ? tbl(d.reads.map((r, i) => [`${i + 1}. 📖 <a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a>${r.tag ? ` <small>#${esc(r.tag)}</small>` : ""}`,
    `${esc(fmtDue(r.due))} <button type="button" class="tb ok" data-todo="done" data-type="read" data-title="${esc(r.title)}" title="Read" aria-label="Mark read">✓</button>`]))
    : '<p class="empty">Nothing to read later.</p>';
  const c = d.coding || {};
  const code = c.project ? codingHtml(c).replace(/^<div class="sgrid">|<\/div>$/g, "") : tile("Coding", '<p class="empty">No project yet. Say “protect my project”.</p>', "span3");
  return `<div class="sgrid">${tile("Long tasks", (goals || '<p class="empty">No long tasks yet.</p>') + help, "span3 gtile")}
    ${tile("✅ To-do · tasks to do", todo + `<div class="btns">${ask("show my to-do list", "Show in chat")}</div>`, "span3")}
    ${tile("🔔 Reminders · alerts at a time", rem, "span2")}
    ${tile("📖 Read later", reads, "")}
    ${code}</div>`;
}
async function sheetHtml(panel) {
  if (panel === "modes") return modesHtml();
  if (panel === "weather") {
    const f = wxFull || await api.weatherFull();
    if (!f || f.error) return '<p class="empty">The forecast isn\'t available right now.</p>';
    const hs = f.hours.slice(0, 24), lo = Math.min(...hs.map((h) => h.temp)), hi = Math.max(...hs.map((h) => h.temp));
    const pts = hs.map((h, i) => `${(i / (hs.length - 1) * 600).toFixed(0)},${(100 - (h.temp - lo) / Math.max(1, hi - lo) * 80).toFixed(0)}`).join(" ");
    const chart = `<svg class="chart" viewBox="0 0 600 110" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2"/></svg>
      <div class="axis">${hs.filter((_, i) => i % 4 === 0).map((h) => `<span>${h.t} · ${Math.round(h.temp)}°${h.rain >= 30 ? ` ☂${h.rain}%` : ""}</span>`).join("")}</div>`;
    return `<div class="sgrid">${tile("Next 24 hours", chart, "span2")}${tile("Sun", tbl([["Sunrise", f.sun.rise], ["Sunset", f.sun.set]]))}
      ${tile("Next days", tbl(f.days.map((d) => [new Date(d.day).toLocaleDateString([], { weekday: "long" }), `${Math.round(d.min)}° – ${Math.round(d.max)}° · ${esc(d.desc)}${d.rain ? ` · rain ${d.rain}%` : ""}`])), "span3")}</div>`;
  }
  if (panel === "now") {
    const d = await api.detail("now");
    const run = d.now.length ? tbl(d.now.map((x) => [`${NOW_IC[x.kind] || "•"} ${esc(x.title)}<small>${esc(x.sub || "")}</small>`,
      `${esc(x.right || "")} ${x.kind === "train" ? '<button type="button" class="act ghost" data-ask="stop training">Stop</button>' : ""}`])) : '<p class="empty">Nothing running.</p>';
    return `<div class="sgrid">${tile("Running", run, "span2")}
      ${tile("Today", `<pre class="plain">${esc(d.text)}</pre>`)}
      ${tile("Reminders, alarms, timers & stopwatch", '<button type="button" class="act" id="open-sched">Open the schedule</button>', "span3")}</div>`;
  }
  const d = await api.detail(panel === "system" ? "system" : panel);
  if (panel === "apps") {
    return `<div class="sgrid">${tile("By app", tbl(d.apps.map((a) => [`${esc(a.name)}<small>${a.procs} process${a.procs > 1 ? "es" : ""}</small>`, gbOf(a.bytes)])), "span2")}
      ${tile("Doctor says", `<p>${d.findings.map(esc).join("<br>")}</p><div class="btns"><button type="button" class="act" data-ask="why is my laptop slow">Full check</button>${d.kernels.length ? '<button type="button" class="act ghost" data-ask="free some RAM">Free idle kernels</button>' : ""}</div>`)}
      ${tile("Ports in use", d.ports.length ? tbl(d.ports.map((x) => [`:${x.port}`, `${esc(x.name)} ${x.pid ? `<button type="button" class="act ghost" data-ask="stop what is on port ${x.port}">Stop</button>` : ""}`])) : '<p class="empty">No open ports.</p>', "span3")}</div>`;
  }
  if (panel === "coding") return codingHtml(d);
  if (panel === "work") return workHtml(d);
  if (panel === "laptop") {
    const w = d.wifi, v = d.volume, b = d.battery, sw = d.switches || {};
    const sws = Object.entries({ wifi: "Wi-Fi", bluetooth: "Bluetooth", dnd: "Do not disturb", night: "Night light", saver: "Battery saver", guard: "Laptop guard" })
      .map(([k, n]) => `<button type="button" class="tg${k === "guard" ? " cool" : ""}${sw[k] ? " on" : ""}" data-switch="${k}">${n}</button>`).join("");
    return `<div class="sgrid">${tile("Battery", tbl([["Health", b ? `${b.health}%${b.cycles ? ` · ${b.cycles} cycles` : ""}` : "–"], ["Power mode", esc(sw.power_mode || "–")]]))}
      ${tile("Network", tbl([["Wi-Fi", w ? `${esc(w.ssid)} · ${w.signal}%` : "off"], ["IP", esc(d.ip || "offline")]]) + '<div class="btns"><button type="button" class="act ghost" data-ask="check my internet">Check internet</button><button type="button" class="act ghost" data-ask="internet speed test">Speed test</button></div>')}
      ${tile("Sound & screen", tbl([["Volume", v ? `${v.percent}%${v.muted ? " (muted)" : ""}` : "–"], ["Brightness", d.brightness != null ? `${d.brightness}%` : "–"]]))}
      ${tile("Switches", `<div class="toggles">${sws}</div><p class="tiny">Click a switch to turn it on or off.</p>`, "span2")}
      ${tile("Device", tbl([["Model", esc(d.model || "–")], ["System", esc(d.os || "–")], ["Up", fmtDur(d.uptime_s)]]))}</div>`;
  }
  if (panel === "system") {
    const k = d.kurama || {};
    const disks = tbl(d.disks.map((x) => [esc(x.mount), `${Math.round(x.used / 1e9)} / ${Math.round(x.total / 1e9)} GB`]));
    const s0 = lastStatus || {};
    return `<div class="sgrid">${tile("Now", tbl([["CPU", `${Math.round(s0.cpu?.percent ?? 0)}% · ${s0.cpu?.freq_ghz?.toFixed(2) ?? "–"} GHz · load ${s0.cpu?.load?.[0]?.toFixed(2) ?? "–"}`],
        ["Memory", `${fmtGb(s0.ram?.used_gb)} / ${fmtGb(s0.ram?.total_gb)} GB · swap ${s0.swap?.percent ?? 0}%`], ["Temperature", s0.cpu?.temp_c != null ? `${Math.round(s0.cpu.temp_c)} °C` : "–"]]), "span2")}
      ${tile("KURAMA", tbl([["Memory", `${Math.round(s0.jarvis?.rss_mb ?? 0)} MB`], ["Workers", `${k.workers?.[0] ?? 0} / ${k.workers?.[1] ?? 0} running`],
        ["Tokens today", `${fmtK(k.tokens_today)} · ${k.calls_today ?? 0} calls`], ["Free answers", k.free_pct == null ? "–" : `${k.free_pct}% (0 tokens)`]]))}
      ${tile("Disks", disks + `<div class="btns"><button type="button" class="act" data-ask="what is using my disk space">What can I free?</button></div>`, "span2")}
      ${tile("Trash", `<p>${esc(d.trash)}</p><div class="btns"><button type="button" class="act ghost" data-ask="empty the trash">Empty trash…</button></div>`)}
      ${tile("KURAMA resources", await kuramaResources(), "span3")}</div>`;
  }
  return '<p class="empty">Nothing more to show.</p>';
}
document.addEventListener("click", (e) => { if (e.target.id === "open-sched") { $("sheet").close(); openSched(); } });

// suggestions above the box: what fits right now (0 tokens to pick)
// suggestions under the chat box: a few urgent ones first, then random picks from a pool of ~300 (server side,
// weighted: more coding ones while VS Code is in front, the day in the morning, money/habits in the evening).
// They change every 3 minutes and after each answer, never every 10 s dashboard refresh.
let sugg = [], suggAt = 0;
async function loadSuggest(force = false) {
  if (MINI || (!force && Date.now() - suggAt < 180000)) return; // the mini panel shows no suggestions (owner)
  suggAt = Date.now();
  try { sugg = (await api.suggest(4)).items || []; } catch { /* keep the old ones */ }
  renderSuggest();
}
function renderSuggest() {
  const s = [];
  if (dash?.now?.some((x) => x.kind === "train")) s.push("How's training?");
  if ((lastStatus?.ram?.percent || 0) >= 85) s.push("Why is my laptop slow?");
  for (const x of (sugg.length ? sugg : ["What's on today?", "Status"])) if (!s.includes(x)) s.push(x);
  $("suggest").innerHTML = s.slice(0, 3).map((t) => `<button type="button" data-ask="${esc(t)}">${esc(t)}</button>`).join("");
  loadSuggest();
}
setInterval(() => loadSuggest(), 60000);

// ---------- a wallpaper KURAMA made is drawn behind the dashboard (this window covers the real desktop) ----------
let wallMtime = -1;
async function loadWall() {
  if (MINI || minimized || paused) return;
  try {
    const w = await api.wallpaperInfo();
    const m = w.kurama ? w.mtime : 0;
    if (m === wallMtime) return;
    wallMtime = m;
    const box = $("wall");
    if (!m) { box.style.backgroundImage = `url("${api.url("/api/v1/wallpaper/real", true)}")`; box.classList.add("on"); return; } // your own picture
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
  remember: "remember ", add_reminder: "remind me to  at ", calculate: "what is ",
  focus_mode: "start a 25 minute focus session", 
  gesture_control: "enable hand gesture control", daily_digest: "summarize today", write_document: "write an essay about ",
  set_wallpaper: "change my wallpaper", screenshot: "take a screenshot", audio: "set volume to 50", find_files: "find file ",
  training: "how is my training going", run_training: "start training with python train.py and watch it",
  command_alerts: "turn on command alerts", fix_error: "what does this error mean", python_env: "install ",
  check_dataset: "check my dataset ", time_machine: "what did I change in the last 2 hours", where_was_i: "where was I",
  laptop_doctor: "why is my laptop slow", internet_doctor: "why is my internet slow", disk_cleaner: "what is using my disk space",
  download_file: "download  tonight", tidy_downloads: "sort my downloads", backup: "back up my projects",
  laptop_guard: "guard my laptop", web_watch: "watch  for ", study_notes: "note for : ", lecture: "record the lecture",
  timetable: "what do I have tomorrow", quiz: "quiz me",
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
  if (S.mute) { player.stop(); spoken.cut = true; } // voice off = nothing more is spoken, and the mic is free at once
  renderMute();
  updateState();
  maybeResume();
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
  $("tb-time").textContent = `${hh}:${mm ?? ""}${parts[1] ? " " + parts[1] : ""}`;
  $("tb-date").textContent = now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  renderTodayLive();
  clockTimer = setTimeout(tick, 1000 - (Date.now() % 1000) + 5);
}
function stopClock() { clearTimeout(clockTimer); clockTimer = 0; }

// ---------- pause / visibility (wallpaper covered, tab hidden) ----------
function applyActivity() {
  const idle = paused || document.hidden;
  // minimized = mini KURAMA is the UI: the dashboard behind it freezes completely (orb stops, no CSS animation,
  // no polling) so it costs ~0 CPU while you work; restore brings it all back
  document.body.classList.toggle("paused", idle || minimized);
  orb.pause(paused || MINI || minimized);
  if (idle || minimized) { stopStatus(); stopClock(); clearTimeout(devTimer); devTimer = 0; clearTimeout(schedTimer); schedTimer = 0; clearTimeout(dashTimer); dashTimer = 0; }
  else { if (!clockTimer) tick(); if (!es && !pollTimer) startStatus(); if (!devTimer) loadDevice(); if (!schedTimer) loadToday(); if (!dashTimer) loadDash(); }
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
let shrinkTimer = 0;
function shrinkPage() { // covered for a while: drop what isn't on screen so WebKit can give the memory back
  while (log.children.length > 20) log.firstElementChild.remove();
  if (!$("sheet").open) $("sheet-body").innerHTML = "";
  if (!$("ws-big").open) $("ws-big-view").innerHTML = "";
  for (const it of ws.items) if (it !== ws.items[ws.cur]) it.text = null; // re-read from disk when shown again
}
window.kuramaPause = (on) => {
  paused = !!on;
  clearTimeout(shrinkTimer);
  shrinkTimer = paused ? setTimeout(shrinkPage, 60000) : 0;
  applyActivity();
  return paused;
};
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
  $("orb").title = minimized ? "Click to restore KURAMA" : "Click: status · double-click: talk to me";
  if (minimized && !asleep) setMode("text"); // one mic user at a time; the wake word (asleep) keeps listening
  applyActivity();
};
// ---------- mini KURAMA's workspace: a sheet over the chat, hidden until a job has something to show ----------
const mws = { items: [], cur: 0 };
async function mwsOpen(show = true) {
  if (!MINI) return;
  try { mws.items = ((await api.outputs(15)).items || []).filter((x) => !(String(x.name).startsWith("results/") && x.size < 4000)); }
  catch { return; }
  if (!mws.items.length) return;
  $("m-ws").hidden = false;
  mws.cur = 0; // newest first
  if (show) { $("mws").hidden = false; $("m-ws").querySelector(".dot").hidden = true; mwsShow(); }
  else $("m-ws").querySelector(".dot").hidden = false;
}
async function mwsShow() {
  const x = mws.items[mws.cur];
  if (!x) return;
  $("mws-title").textContent = `${wsTitle(x.name)}  (${mws.cur + 1}/${mws.items.length})`;
  const body = $("mws-body");
  body.textContent = "";
  if (x.kind === "audio" || x.kind === "video") {
    const m = document.createElement(x.kind);
    m.controls = true; m.src = api.outputUrl(x.name);
    m.style.width = "100%";
    body.append(m);
    return;
  }
  if (x.kind === "image" || /\.(png|jpe?g|webp|gif)$/i.test(x.name)) {
    const img = document.createElement("img");
    img.src = api.outputUrl(x.name);
    img.alt = x.name;
    body.append(img);
    return;
  }
  let txt = "";
  try { txt = await (await fetch(api.outputUrl(x.name))).text(); } catch { txt = "(couldn't load it)"; }
  for (const block of txt.slice(0, 40000).split(/\n(?=## )/)) { // "## Folder (n)" headings of a plan
    const m = block.match(/^## (.*)\n?([\s\S]*)$/);
    if (m) { const h = document.createElement("h4"); h.textContent = m[1]; body.append(h); }
    const pre = document.createElement("pre");
    pre.textContent = (m ? m[2] : block).replace(/^# .*\n+/, "");
    body.append(pre);
  }
}
// mini KURAMA: the workspace is its own small window (host "ws"); in a plain browser it's a sheet over the chat
function openWorkspace(focus = true) {
  if (hostSay(focus ? "ws:open" : "ws:quiet")) return;
  mwsOpen(true);
}
$("m-ws").onclick = () => { if (host) openWorkspace(true); else if ($("mws").hidden) mwsOpen(true); else $("mws").hidden = true; };
if (MINI && !WSONLY) $("m-ws").hidden = false; // always reachable from the panel header
window.kuramaWsRefresh = () => { if (WSONLY) mwsOpen(true); };
// the workspace window refreshes itself while it's visible: a new picture/plan/document shows up on its own
let mwsNewest = 0;
async function mwsWatch() {
  if (WSONLY && !document.hidden) {
    try {
      const top = ((await api.outputs(1)).items || [])[0];
      const m = top ? top.mtime : 0;
      if (m !== mwsNewest) { mwsNewest = m; mwsOpen(true); }
    } catch { /* API restarting */ }
  }
  setTimeout(mwsWatch, document.hidden ? 15000 : 4000);
}
if (WSONLY) { document.title = "KURAMA · Workspace"; mwsWatch(); }
async function cleanWorkspace() {
  if (!confirm("Clean the workspace? Everything in it goes to the trash (you can restore it from there).")) return;
  try {
    const r = await api.clearOutputs();
    toast(`Workspace cleaned (${r.moved} item${r.moved === 1 ? "" : "s"} moved to the trash).`);
  } catch (e) { toast("Couldn't clean the workspace: " + e.message); return; }
  mws.items = []; mws.cur = 0; mwsNewest = 0;
  $("mws-body").textContent = "Empty. New pictures, plans and documents will appear here.";
  $("mws-title").textContent = "Workspace";
  if (!MINI) wsClearAll();
}
$("mws-clear").onclick = cleanWorkspace;
$("mws-del").onclick = async () => { // mini: remove the item being shown
  const x = mws.items[mws.cur];
  if (!x || !confirm(`Delete "${wsTitle(x.name)}"? It goes to the trash.`)) return;
  try { await api.deleteOutput(x.name); } catch (e) { toast("Couldn't delete it: " + e.message); return; }
  mws.items.splice(mws.cur, 1);
  mws.cur = Math.min(mws.cur, Math.max(0, mws.items.length - 1));
  if (mws.items.length) mwsShow();
  else { $("mws-body").textContent = "Empty. New pictures, plans and documents will appear here."; $("mws-title").textContent = "Workspace"; }
};
$("ws-clear").onclick = cleanWorkspace;
$("mws-close").onclick = () => { $("mws").hidden = true; };
$("mws-prev").onclick = () => { if (mws.cur < mws.items.length - 1) { mws.cur++; mwsShow(); } };
$("mws-next").onclick = () => { if (mws.cur > 0) { mws.cur--; mwsShow(); } };

window.kuramaMiniWake = (rest = "") => { // minimized: the host heard "KURAMA / wake up" -> talk in this panel
  if (!MINI) return;
  wakeUp(rest || "");
};
window.kuramaMiniShown = (on, keepTalking = false) => { // mini panel opened / hidden
  miniGhost = !on && keepTalking; // talk mode, or a reply still on its way (any mode), goes on with the panel closed
  document.body.classList.toggle("paused", !on); // freeze CSS animations while hidden
  if (on) {
    const c = document.querySelector(".chat"); // a short rise-in as the window fades in
    c.classList.remove("enter"); void c.offsetWidth; c.classList.add("enter");
    input.focus(); return;
  }
  if (miniGhost) { saveMiniLog(); return; }
  if (recording) cancelRecording();
  if (conv.on) setMode("text"); // never keep listening while the panel is hidden
  saveMiniLog();
};
// Talk mode with the panel closed: the host (kurama_wallpaper.py) colours the button's ring by voice state and
// shows what was said + the reply in a caption beside it. Messages only; nothing is sent while the panel is open.
let miniTalk = null, miniSt = null, capTimer = 0;
function miniReport(st) {
  const h = window.webkit?.messageHandlers?.kurama; // (updateState runs before `host` is defined)
  if (!h) return;
  const talk = mode === "conv" && conv.on;
  if (talk !== miniTalk) { miniTalk = talk; h.postMessage("talk:" + (talk ? "on" : "off")); }
  if (st !== miniSt) { miniSt = st; h.postMessage("state:" + st); }
}
function miniCaption(who, text, done = false) {
  if (!MINI || !miniGhost || !text) return;
  clearTimeout(capTimer); capTimer = 0;
  hostSay("caption:" + JSON.stringify({ who, text, done }));
}
// Hold-to-talk (global key, see jarvis/core/ptt.py): the host calls kuramaPTT(1) on key down, (0) on release
// (send what was said), (-1) to drop it (the key was part of a shortcut). Works with the panel open or closed.
let pttOn = false;
window.kuramaPTT = async (v) => {
  if (v === 1) {
    if (recording) return;
    audioCtx();
    try { await mic.start(); } catch (e) { miniCaption("bot", micError(e), true); return; }
    player.stop();
    recorder.start(); recording = pttOn = true; recSecs = 0;
    updateState();
    miniCaption("you", "Listening…");
    return;
  }
  if (!pttOn) return;
  pttOn = false; recording = false;
  if (v === -1) { recorder.cancel(); mic.stop(); updateState(); miniCaption("you", " ", true); return; }
  sttBusy = true; updateState(); // the host keeps the hidden panel alive while this says "thinking"
  const blob = await recorder.stop();
  mic.stop();
  let r = null;
  if (blob && blob.size >= 1200) { try { r = await api.stt(blob, S.lang); } catch { /* offline */ } }
  sttBusy = false;
  const text = (r?.text || "").trim();
  if (!text) { updateState(); miniCaption("bot", "Didn't catch that.", true); return; }
  if (S.mute === undefined || !S.mute) audioCtx();
  sendChat(text, { voice: true, speak: !S.mute, lang: r.lang || S.lang });
};
function miniCaptionSoon(get) { // streamed reply: at most ~4 updates a second
  if (!capTimer) capTimer = setTimeout(() => { capTimer = 0; miniCaption("bot", get()); }, 250);
}
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
  const own = ok && String(r.progress || "").startsWith("» ") ? r.progress.slice(2) : ""; // the job wrote its own reply
  const msg = own || (ok ? `Done: ${title}.${r.output_path ? " It's in your workspace." : ""}`
    : `Sorry, ${title} failed${r.error ? `: ${r.error.slice(0, 120)}` : "."}`);
  if (ok && r.output_path && MINI) openWorkspace(false); // mini: the result opens in the workspace window
  const b = new BotBubble();
  b.append(msg);
  b.finish();
  scrollDown(true);
  if (!S.mute) { audioCtx(); player.enqueue(msg, S.lang === "auto" ? null : S.lang); }
  if (ok) loadOutputs();
}

// ---------- wake word + sleep: talk mode is on by default and asleep; "wake up KURAMA" wakes it,
// "sleep now" (or 2 quiet minutes) puts it back to sleep. Asleep, only short phrases are transcribed.
const SLEEP_RE = /^(?:ok(?:ay)?[,\s]+)?(?:(?:kurama|jarvis)[,\s]+)?(?:(?:now\s+)?(?:you\s+)?(?:can\s+)?(?:go\s+)?(?:to\s+)?sleep(?:\s+(?:now|you|yourself|kurama|jarvis))*|(?:i'?ll|i\s+will|i'?m\s+going\s+to|i\s+am\s+going\s+to|i'?m\s+gonna|let\s+me)\s+(?:go\s+(?:to\s+)?)?sleep(?:\s+now)?|good\s*night(?:\s+(?:kurama|jarvis))?|so\s+jao|सो\s*जाओ|सुत\S*)[\s.!।]*$/i;
// "...I'm not saying sleep the laptop, I'm saying you sleep, KURAMA": the last part asks KURAMA itself to sleep
function wantsSleep(text) {
  const t = (text || "").trim();
  if (SLEEP_RE.test(t)) return true;
  // Scan each clause: "so actually I want you to sleep now", "sleep now. sleep now." etc.
  const clauses = t.split(/[,.;!?।]+/).map((s) => s.trim()).filter(Boolean);
  for (const c of clauses) {
    if (!/\bsleep\b|सो\s*जा|सुत/i.test(c)) continue;
    if (/\b(?:laptop|computer|pc|screen|system|display|monitor|mode|machine|device)\b/i.test(c)) continue; // that's suspend-the-laptop, not this
    if (/\b(?:you|yourself|kurama|jarvis)\b/i.test(c) || /\b(?:go|going|now|good\s*night)\b/i.test(c) || c.split(/\s+/).length <= 3) return true;
  }
  return false;
}
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
  wakeES.onopen = () => { if (asleep && serverWake && !conv.muted) api.wakeSleep().catch(() => {}); }; // API restarted: listen again
  wakeES.onmessage = (e) => {
    let ev = null;
    try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.type === "wake" && asleep && !conv.muted) wakeUp(ev.command && !isEcho(ev.command) ? ev.command : "");
    if (ev.type === "error" && asleep) { serverWake = false; sleepListen(); } // fall back to the page's mic
  };
}
// Remove KURAMA's own recently-spoken words from the start/end of a transcription (the mic catches the tail of
// "Yes? I'm listening." or a reply just before/after the user speaks), so only the user's real words are routed.
function stripEcho(text) {
  const said = player.said || [];
  if (!said.length || !text) return text;
  const norm = (s) => (s || "").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
  const original = norm(text);
  let words = original.slice();
  const spoken = said.map(norm).filter((w) => w.length);
  // peel KURAMA's phrases off the FRONT, repeatedly (it may have said two short lines)
  let step;
  do {
    step = 0;
    for (const sw of spoken) {
      let k = 0;
      while (k < sw.length && k < words.length && words[k] === sw[k]) k++;
      if (k >= Math.min(sw.length, 2) && k >= 2) { words = words.slice(k); step = k; break; }
    }
  } while (step && words.length);
  // and one echo off the END
  for (const sw of spoken) {
    let k = 0;
    while (k < sw.length && k < words.length && words[words.length - 1 - k] === sw[sw.length - 1 - k]) k++;
    if (k >= Math.min(sw.length, 3)) { words = words.slice(0, words.length - k); break; }
  }
  if (words.length === original.length) return text; // nothing was KURAMA's
  return words.join(" "); // the user's remaining words (lower-cased; routing is case-insensitive)
}

function isEcho(text) { // the mic heard KURAMA's own voice (anything it said in the last 90 s), not the user
  // An echo is a long stretch of KURAMA's own words in the same order; a follow-up question that only shares
  // some words ("what is using the most RAM?") is not one.
  const norm = (x) => (x || "").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
  const words = norm(text), all = norm((player.said || []).join(" "));
  if (words.length < 2 || !all.length) return false;
  let best = 0;
  for (let i = 0; i < words.length; i++) {
    for (let j = 0; j < all.length; j++) {
      let k = 0;
      while (i + k < words.length && j + k < all.length && words[i + k] === all[j + k]) k++;
      if (k > best) best = k;
    }
  }
  return best >= Math.max(3, Math.ceil(words.length * 0.7)) || (words.length === 2 && best === 2);
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
    if (conv.muted) { updateState(); return; } // muted: nobody listens, not even for the wake word
    try { await api.wakeSleep(); updateState(); return; } catch { serverWake = false; }
  }
  try { if (!conv.on) { mode = "conv"; await mic.start({ plain: true }); await conv.start(); } conv.sleep(true); setMode("conv"); }
  catch (e) { toast(micError(e)); }
}
function goSleep(quiet = false) {
  if (asleep) return;
  asleep = true;
  if (conv.on) conv.sleep(true); // from now on only the wake phrase counts, even before the API takes over
  if (openConfirm) answerConfirm(openConfirm, false, "sleep"); // "sleep" while a question waits is a real no
  abortChat(true);
  player.stop();
  if (!quiet && !S.mute) player.enqueue(`Okay, going to sleep. Say wake up ${botName} when you need me.`);
  updateState();
  sleepListen();
}
async function wakeUp(rest) {
  asleep = false;
  lastBotAt = Date.now(); // just woken: the next thing said is for KURAMA
  api.wakeAwake().catch(() => {});
  try { // talk mode with echo cancellation
    audioCtx();
    if (conv.on) { conv.sleep(false); await mic.restart({ plain: false }); }
    else { mode = "conv"; await mic.start(); await conv.start(); }
    setMode("conv");
  } catch (e) { toast(micError(e)); setMode("text"); }
  updateState();
  if (rest && rest.split(/\s+/).length >= 2) { sendChat(rest, { voice: true, speak: !S.mute }); return; }
  // just listen (silently): speaking "Yes? I'm listening." made the mic hear its own voice and corrupt the next
  // command; the orb + "Listening…" already show it's awake
  conv.listen();
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
  if (pendingConfirm && (YES.test(t) || NO.test(t))) { player.stop(); addUser(t, true); answerConfirm(pendingConfirm, !NO.test(t) && YES.test(t), "barge:" + t.slice(0, 40)); return; }
  if (openConfirm) return; // a question is waiting: anything but yes/no must not cancel it
  if (STOP_RE.test(t) && t.split(/\s+/).length <= 4) { player.stop(); if (!openConfirm) abortChat(); updateState(); maybeResume(); return; }
  const words = t.toLowerCase().match(/\p{L}+/gu) || [];
  if (words.length >= 3 && !isEcho(t)) { player.stop(); if (!openConfirm) abortChat(); sendChat(t, { voice: true, lang: r.lang, speak: !S.mute }); }
  // else: noise, KURAMA's own echo or a short aside: keep talking
}

// ---------- power modes: how much of KURAMA runs, so it fits next to big tasks (8 GB laptop) ----------
let powerMode = null;
const AI_TXT = { best: "Best AI", normal: "Normal AI", fast: "Small AI", off: "No AI" };
const SCREEN_TXT = { full: "Full dashboard", calm: "Calm dashboard", mini: "Small button" };
const segBtns = (key, opts, cur) => `<div class="mseg" data-key="${key}">${Object.entries(opts).map(([v, t]) =>
  `<button type="button" data-v="${v}" aria-pressed="${String(v) === String(cur)}">${esc(t)}</button>`).join("")}</div>`;
async function modesHtml() {
  const [m, r] = await Promise.all([api.modes(), api.resources().catch(() => null)]);
  const cur = m.current;
  const now = r ? `KURAMA uses <b>${r.total_mb} MB</b> now (${r.ram_share}% of the laptop's RAM).` : "";
  const cards = m.presets.map((p) => `<button type="button" class="mcard${p.id === cur.mode ? " on" : ""}" data-mode="${p.id}">
      <span class="mc-top"><b>${esc(p.name)}</b><small>≈ ${p.est_mb} MB</small></span>
      <span class="mc-desc">${esc(p.desc)}</span>
      <span class="mc-tags"><i>${AI_TXT[p.ai]}</i><i>${p.workers.length}/${m.workers.length} helpers</i>${p.model === "off" ? "" : `<i>model ${p.model}</i>`}${p.wake ? "<i>wake word</i>" : ""}<i>${SCREEN_TXT[p.screen]}</i></span></button>`).join("");
  const helpers = m.workers.map((w) => `<label class="mhelp${w.available ? "" : " off"}"><input type="checkbox" data-worker="${w.id}" ${cur.workers.includes(w.id) ? "checked" : ""} ${w.available ? "" : "disabled"}>
      <span><b>${esc(w.name)}</b><small>${esc(w.desc)}</small></span></label>`).join("");
  return `<p class="mnow">Mode: <b>${esc(m.name)}</b> · ≈ ${cur.est_mb} MB. ${now} A lighter mode leaves more RAM for your own work; your files and memory stay the same.</p>
    <div class="mgrid">${cards}</div>
    <div class="sgrid mswitch">
      ${tile("AI answers", segBtns("ai", { best: "Best", normal: "Normal", fast: "Small", off: "Off" }, cur.ai) +
        '<small class="note">Best = the big model for everything. Small = the quick model only. Off = 0 tokens, built-in commands only. (Tokens, not RAM.)</small>')}
      ${tile("Understanding model", segBtns("model", { always: "Always", auto: "When needed", off: "Off" }, cur.model) +
        '<small class="note">Local, ~130 MB while loaded. It understands free phrasing; off = keywords + the AI decide.</small>')}
      ${tile("Screen", segBtns("screen", { full: "Full", calm: "Calm", mini: "Small" }, cur.screen) +
        '<small class="note">Small frees the big dashboard (~100 MB): only the floating button stays. Calm stops the animations (CPU).</small>')}
      ${tile("Wake word", segBtns("wake", { true: "On", false: "Off" }, cur.wake) +
        '<small class="note">Listens for "KURAMA" / "wake up": the mic stays open and each speech burst is checked online.</small>', "")}
      ${tile("Background helpers", `<div class="mhelpers">${helpers}</div><small class="note">Helpers run inside KURAMA's server (a few MB each). Grey = not set up.</small>`, "span2")}
    </div>`;
}
function bindModes(body) {
  const done = (m, msg) => { applyModeClient(m.current, true); toast(msg); openSheet("modes"); };
  const fail = (e) => toast("Couldn't change it: " + (e.message || e));
  for (const c of body.querySelectorAll("[data-mode]")) {
    c.onclick = () => api.setPowerMode(c.dataset.mode).then((m) => done(m, `${m.name} mode on.`)).catch(fail);
  }
  for (const g of body.querySelectorAll(".mseg")) {
    for (const b of g.querySelectorAll("button")) {
      b.onclick = () => {
        const v = g.dataset.key === "wake" ? b.dataset.v === "true" : b.dataset.v;
        api.setPowerSwitch(g.dataset.key, v).then((m) => done(m, `Changed. Mode: ${m.name}.`)).catch(fail);
      };
    }
  }
  for (const x of body.querySelectorAll("[data-worker]")) {
    x.onchange = () => api.setPowerSwitch("workers", { [x.dataset.worker]: x.checked })
      .then((m) => done(m, `${x.closest("label").querySelector("b").textContent} ${x.checked ? "on" : "off"}.`)).catch(fail);
  }
}
function setWake(on) { // the wake word on/off (settings checkbox or the power mode)
  const was = S.wakeListen;
  S.wakeListen = on;
  if (on && !was) setTimeout(startListening, 0);
  if (!on && was && asleep) { asleep = false; api.wakeAwake().catch(() => {}); if (conv.on) { conv.stop(); mic.stop(); setMode("text"); } updateState(); }
}
function setLowPower(on) {
  S.lowPower = on;
  dust.setLowPower(on); // (the hidden orb stays static whatever this says)
  document.body.classList.toggle("low-power", on);
}
function applyModeClient(cur, changed) { // the parts of a mode that live in this page: wake word, screen
  powerMode = cur;
  const pill = $("btn-mode");
  if (pill) { $("mode-name").textContent = cur.name || "Mode"; pill.dataset.mode = cur.mode; }
  if (!cur.wake && S.wakeListen) setWake(false);
  if (changed && cur.wake && !S.wakeListen) setWake(true);
  if (cur.screen !== "full" && !lowPowerOn()) setLowPower(true);
  if (changed && cur.screen === "full" && lowPowerOn()) setLowPower(false);
  saveSettings(S);
  if (changed && cur.screen === "mini" && !MINI) setTimeout(() => $("btn-mini").click(), 700); // free the big dashboard
}
$("btn-mode").onclick = () => openSheet("modes");
api.modes().then((m) => applyModeClient(m.current, false)).catch(() => {});

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
  $("set-hear").checked = mic.hearDevice;
  api.deviceSound().then((d) => { $("set-hear").checked = !!d.hear; $("set-hear").disabled = d.available === false; }).catch(() => {});
  $("set-lang").value = S.lang || "auto";
  $("set-msg").textContent = msg || "";
  loadMemory();
  loadVoice();
  if (!dlg.open) dlg.showModal();
}

// ---------- Settings -> Voice: live level, sensitivity, pause, noise / echo / volume, mic volume, wake word ----------
function applyVoiceSettings() {
  mic.proc = { ns: !!S.voice.ns, ec: !!S.voice.ec, agc: !!S.voice.agc };
  conv.applyVoice(S.voice);
}
applyVoiceSettings();
let vmRaf = 0, vmOwnMic = false;
function showVoice() {
  const v = S.voice;
  $("v-sens").value = v.sens; $("v-sens-v").textContent = `${v.sens}/10`;
  $("v-pause").value = v.pause; $("v-pause-v").textContent = `${Number(v.pause).toFixed(1)} s`;
  $("v-min").value = v.minMs; $("v-min-v").textContent = `${v.minMs} ms`;
  $("v-ns").checked = v.ns; $("v-ec").checked = v.ec; $("v-agc").checked = v.agc;
}
async function loadVoice() {
  showVoice();
  try {
    const r = await api.voiceSettings();
    if (r.mic.volume != null) { $("v-vol").value = r.mic.volume; $("v-vol-v").textContent = `${r.mic.volume}%`; }
    $("v-vol").disabled = r.mic.volume == null;
    $("v-wake").value = r.wake;
    $("v-tip").textContent = r.mic.echo_canceller ? "The laptop's echo canceller is on (\"Hear device sound\" is off). It can make your voice less clear: if KURAMA mishears you, turn \"Hear device sound\" on and keep \"Remove KURAMA's own voice\" on." : "";
  } catch { /* API busy */ }
  if (!vmRaf) vmRaf = requestAnimationFrame(voiceMeter);
}
function voiceMeter() {
  if (!dlg.open) { vmRaf = 0; if (vmOwnMic && !conv.on) { mic.stop?.(); } vmOwnMic = false; return; }
  if (mic.open) {
    const rms = mic.rms(), thr = conv.threshold(), scale = (x) => Math.min(100, Math.sqrt(x / 0.2) * 100);
    $("vm-lvl").style.width = `${scale(rms)}%`;
    $("vm-lvl").classList.toggle("on", rms > thr);
    $("vm-thr").style.left = `${scale(thr)}%`;
    $("vm-txt").textContent = rms > thr ? "Speech heard ✓" : `Room noise ${Math.round(scale(conv.floor))} · speech starts at ${Math.round(scale(thr))}`;
  }
  vmRaf = requestAnimationFrame(voiceMeter);
}
$("vm-test").onclick = async () => {
  if (mic.open) { toast("The mic is already on: speak and watch the bar."); return; }
  try { await mic.start(); vmOwnMic = true; toast("Speak normally: the bar should pass the line only when you talk."); }
  catch (e) { toast("Couldn't open the mic: " + e.message); }
};
function setVoice(patch, restartMic = false) {
  S.voice = { ...S.voice, ...patch };
  saveSettings(S);
  applyVoiceSettings();
  showVoice();
  if (restartMic && mic.open && !mic.plain) mic.restart({ plain: false, force: true }).catch(() => {});
}
$("v-sens").oninput = (e) => setVoice({ sens: Number(e.target.value) });
$("v-pause").oninput = (e) => setVoice({ pause: Number(e.target.value) });
$("v-min").oninput = (e) => setVoice({ minMs: Number(e.target.value) });
for (const k of ["ns", "ec", "agc"]) $("v-" + k).onchange = (e) => setVoice({ [k]: e.target.checked }, true);
let volTimer = 0;
$("v-vol").oninput = (e) => {
  $("v-vol-v").textContent = `${e.target.value}%`;
  clearTimeout(volTimer);
  volTimer = setTimeout(() => api.setVoiceSettings({ mic_volume: Number(e.target.value) }).catch(() => toast("Couldn't change the mic volume.")), 250);
};
$("v-wake").onchange = (e) => api.setVoiceSettings({ wake: e.target.value })
  .then(() => toast("Wake word sensitivity: " + e.target.selectedOptions[0].text + ".")).catch(() => toast("Couldn't change it."));
$("v-reset").onclick = () => {
  setVoice({ ...VOICE_DEFAULTS }, true);
  api.setVoiceSettings({ wake: "normal" }).then(() => { $("v-wake").value = "normal"; }).catch(() => {});
  toast("Voice settings are back to the defaults.");
};
async function loadMemory() { // Settings -> Memory: what each part uses, and the model's mode
  try {
    const r = await api.resources();
    $("set-sem").value = r.semantic.mode;
    const parts = r.parts.map((p) => `${p.name} ${p.mb} MB`).join(" · ");
    $("set-mem").textContent = `KURAMA now: ${r.total_mb} MB (${parts}). Model: ${r.semantic.loaded ? `loaded, ${r.semantic.mb} MB` : "not loaded"}.`;
  } catch { $("set-mem").textContent = "Couldn't read memory use."; }
}
$("set-sem").onchange = async (e) => {
  try { const m = await api.setPowerSwitch("model", e.target.value); applyModeClient(m.current, false); toast("Understanding model: " + e.target.selectedOptions[0].text + "."); }
  catch (err) { toast("Couldn't change it: " + err.message); }
  loadMemory();
};
$("set-free").onclick = async () => {
  try { await api.freeModel(); toast("Model memory freed; it loads again when needed."); } catch (err) { toast("Couldn't free it: " + err.message); }
  setTimeout(loadMemory, 500);
};
$("btn-settings").onclick = () => openSettings();
for (const b of document.querySelectorAll("[data-reset]")) {
  b.onclick = async () => {
    const level = b.dataset.reset;
    if (level === "all" && !confirm("Reset KURAMA to brand new?\n\nEvery chat, fact, reminder, to-do, alert, result and personal sheet is wiped (a backup copy is kept). Your password and settings stay.")) return;
    b.disabled = true;
    try {
      const r = await api.reset(level);
      log.innerHTML = ""; // clear the on-screen conversation
      player.stop(); if (busy) abortChat(true);
      toast(r.message || "Done.");
      $("settings").close();
      if (level !== "chat") setTimeout(() => location.reload(), 1500); // every card shows the empty state
    } catch { toast("Couldn't do that right now."); }
    finally { b.disabled = false; }
  };
}
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
  setWake($("set-wake").checked);
  if ($("set-wake").checked && powerMode && !powerMode.wake) api.setPowerSwitch("wake", true).then((m) => applyModeClient(m.current, false)).catch(() => {});
  setLowPower($("set-low").checked);
  const hear = $("set-hear").checked;
  if (hear !== mic.hearDevice) {
    mic.hearDevice = hear;
    if (mic.open && !mic.plain) mic.restart({ plain: false, force: true }).catch(() => {});
    api.setDeviceSound(hear).then((d) => toast(d.error ? `Couldn't change the mic: ${d.error}`
      : hear ? "I'll hear the laptop's sound too." : "I'll hear only you: the laptop's own sound is removed from the mic."))
      .catch(() => toast("Couldn't reach KURAMA to change the mic."));
  }
  S.lang = $("set-lang").value;
  saveSettings(S);
  const nm = $("set-name").value.trim();
  if (nm && nm !== botName) api.setName(nm).then((r) => { setBotName(r.name); toast(`My name is ${r.name} now.`); })
    .catch(() => toast("That name didn't work: use 2-24 letters."));
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
// a short note under the control that was clicked (mode / agent switches), gone after ~2.5 s
let tipTimer = 0;
function tip(el, msg) {
  let t = $("tip");
  if (!t) { t = el.ownerDocument.createElement("div"); t.id = "tip"; t.className = "tip"; document.body.append(t); }
  t.textContent = msg;
  const r = el.getBoundingClientRect();
  t.style.left = Math.max(8, Math.min(window.innerWidth - 248, r.left + r.width / 2 - 110)) + "px";
  t.style.top = Math.min(window.innerHeight - 40, r.bottom + 6) + "px";
  t.classList.add("show");
  clearTimeout(tipTimer);
  tipTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

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
conv.muted = !!S.micMuted;
checkHealth().then(() => { startStatus(); loadDevice(); loadToday(); loadDash(); syncDeviceSound(); sendLocation(); bootVoice(); });
// the browser's Geolocation API (Google-backed: real GPS/Wi-Fi, accurate, moves with the laptop) -> the backend,
// so /where and the dashboard show the true current location, not a coarse IP guess
function sendLocation() {
  if (MINI || !navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    (p) => api.sendLocation({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy || 0 }).catch(() => {}),
    () => {}, // denied or unavailable: the backend falls back to Wi-Fi/IP
    { enableHighAccuracy: true, maximumAge: 120000, timeout: 15000 });
}
setInterval(() => { if (!document.hidden && !paused && !minimized) sendLocation(); }, 10 * 60 * 1000); // refresh every 10 min while active
async function syncDeviceSound() { // the server owns this setting (it changes the system's echo canceller)
  try { const d = await api.deviceSound(); mic.hearDevice = !!d.hear; } catch { /* old API: keep the default */ }
}
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

// ---------- minimal layout: the slim bar (default) or the full dashboard (⊞), remembered per browser ----------
const LAYOUT_KEY = "kurama.layout";
function setLayout(full) {
  document.body.classList.toggle("minimal", !full && !MINI);
  $("tb-full").setAttribute("aria-pressed", String(!!full));
  try { localStorage.setItem(LAYOUT_KEY, full ? "full" : "minimal"); } catch { /* private mode */ }
}
function wsPanel(open) { // the workspace slides in/out (minimal layout only)
  if (!document.body.classList.contains("minimal")) return;
  document.body.classList.toggle("ws-open", open);
  $("tb-ws").setAttribute("aria-pressed", String(open));
  $("tb-ws").querySelector(".dot").hidden = true;
}
let savedLayout = "minimal";
try { savedLayout = localStorage.getItem(LAYOUT_KEY) || "minimal"; } catch { /* private mode */ }
setLayout(savedLayout === "full");
$("tb-full").onclick = () => setLayout(document.body.classList.contains("minimal"));
$("btn-minimal").onclick = () => setLayout(false);
$("tb-ws").onclick = () => wsPanel(!document.body.classList.contains("ws-open"));
for (const b of document.querySelectorAll(".tb-chip[data-sheet]")) b.onclick = () => openSheet(b.dataset.sheet);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("ws-open") && !document.querySelector("dialog[open]")) wsPanel(false); });

// ---------- downloads: one live bar per download, inside the workspace (main UI and mini's workspace window) ----------
// The mini chat itself shows no bars: a new download opens mini's workspace window instead.
let dlTimer = 0, dlKey = "", dlSeen = null, dlTab = "run", dlLib = [], dlRun = [];
const DL_HERE = !MINI || WSONLY;
const dlPref = (k, v) => { try { if (v === undefined) return localStorage.getItem("kurama.dl." + k); localStorage.setItem("kurama.dl." + k, v); } catch { /* private window */ } return null; };
async function loadDownloads() {
  clearTimeout(dlTimer); dlTimer = 0;
  let items = null;
  try { items = (await api.downloads()).items || []; } catch { /* offline: keep the last bars */ }
  if (items) {
    const live = items.filter((d) => d.status === "active").map((d) => d.id);
    if (dlSeen && live.some((id) => !dlSeen.has(id))) { // a new download started: show the workspace with its bar
      if (MINI && !WSONLY) hostSay("ws:quiet"); else if (!MINI && document.body.classList.contains("minimal")) wsPanel(true);
    }
    if (DL_HERE && dlSeen && [...dlSeen].some((id) => !live.includes(id))) loadVideos(); // one finished: the library grew
    dlSeen = new Set(live);
    if (DL_HERE) renderDownloads(items);
  }
  if (document.hidden) return; // visibilitychange starts it again
  dlTimer = setTimeout(loadDownloads, items?.some((d) => d.status === "active") ? 2000 : 20000);
}
function renderDownloads(items) {
  const key = JSON.stringify(items);
  if (key === dlKey) return;
  dlKey = key;
  dlRun = items;
  const tray = $("dl-tray");
  tray.hidden = !items.length && !dlLib.length;
  const live = items.filter((d) => d.status === "active");
  const pct = (d) => (d.frac != null ? Math.round(d.frac * 100) + "%" : "");
  $("dl-sum").textContent = live.length ? `Downloads · ${live.length} running${live.length === 1 && live[0].frac != null ? " · " + pct(live[0]) : ""}` : "Downloads";
  if (!items.length) $("dl-list").innerHTML = '<li class="s">Nothing downloading. Say "download this video".</li>';
  if (!items.length) return;
  $("dl-list").innerHTML = items.map((d) => `<li class="dl-${esc(d.status)}"><div class="dl-row"><span class="ell" title="${esc(d.title)}">${esc(d.title)}</span><b>${d.status === "active" ? pct(d) : ""}</b>${d.kind === "ytdl" ? `<span class="dl-btns">${d.status === "active" ? `<button type="button" class="dl-btn" data-dl="pause" data-id="${d.id}">Pause</button>` : ["paused", "failed", "stopped"].includes(d.status) ? `<button type="button" class="dl-btn" data-dl="resume" data-id="${d.id}">Resume</button>` : ""}<button type="button" class="dl-btn bad" data-dl="delete" data-id="${d.id}" title="${d.status === "done" ? "Remove from the list (the video stays)" : "Stop and delete the partial file"}">${d.status === "done" ? "Remove" : "Delete"}</button></span>` : ""}</div>
    <div class="gbar"><i style="width:${d.status === "done" ? 100 : Math.max(2, Math.round((d.frac || 0) * 100))}%"></i></div>
    <div class="s" title="${esc(d.sub)}">${esc(d.sub)}</div></li>`).join("");
}
if (WSONLY) $("mws-body").before($("dl-tray")); // its place: the top of the workspace
else if (!MINI) $("ws")?.querySelector(".card-title")?.after($("dl-tray"));
$("dl-list").onclick = async (e) => {
  const b = e.target.closest("[data-dl]");
  if (!b) return;
  b.disabled = true;
  try { await api.downloadControl(b.dataset.id, b.dataset.dl); } catch (err) { toast?.(err.message || "Couldn't do that"); }
  dlKey = ""; loadDownloads();
};
// the library: every downloaded video, by day; remove one, a day's, or all (to the Trash)
const fmtVid = (b) => (b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.round(b / 1e6) + " MB");
async function loadVideos() {
  try { const r = await api.videos(); dlLib = r.items || []; } catch { return; }
  renderVideos();
  $("dl-tray").hidden = !dlRun.length && !dlLib.length;
}
function renderVideos() {
  const total = dlLib.reduce((a, v) => a + v.size, 0);
  $("dl-libsum").textContent = dlLib.length ? `${dlLib.length} file${dlLib.length > 1 ? "s" : ""} · ${fmtVid(total)}` : "No downloaded videos.";
  $("dl-clear").hidden = !dlLib.length;
  const days = [...new Set(dlLib.map((v) => v.day))];
  $("dl-libl").innerHTML = days.map((day) => {
    const vs = dlLib.filter((v) => v.day === day);
    return `<div class="dl-day"><span>${esc(day)} · ${fmtVid(vs.reduce((a, v) => a + v.size, 0))}</span><button type="button" class="dl-btn bad" data-vday="${esc(day)}" title="Take these off the list (the files stay)">Clear ${esc(day.toLowerCase() === "today" ? "today" : "day")}</button></div>
      <ul class="dl-list">${vs.map((v) => `<li><div class="dl-row"><span class="ell" title="${esc(v.name)}">${esc(v.name.replace(/\.[^.]+$/, ""))}</span><span class="s">${fmtVid(v.size)}</span>
        <span class="dl-btns"><button type="button" class="dl-btn" data-vopen="${esc(v.name)}">Play</button><button type="button" class="dl-btn bad" data-vrm="${esc(v.name)}" title="Take it off this list (the video file stays)">Remove</button></span></div></li>`).join("")}</ul>`;
  }).join("");
}
async function removeVideos(body, ask) {
  if (ask && !confirm(ask)) return;
  try { const r = await api.videosRemove(body); toast(r.text); } catch (err) { toast(err.message || "Couldn't remove it"); }
  loadVideos();
}
$("dl-libl").onclick = (e) => {
  const b = e.target.closest("[data-vrm],[data-vday],[data-vopen]");
  if (!b) return;
  if (b.dataset.vopen) return api.videosOpen({ name: b.dataset.vopen }).catch((err) => toast(err.message || "Couldn't open it"));
  if (b.dataset.vrm) return removeVideos({ names: [b.dataset.vrm] });
  const names = dlLib.filter((v) => v.day === b.dataset.vday).map((v) => v.name);
  removeVideos({ names });
};
$("dl-clear").onclick = () => removeVideos({ all: true }, `Clear the list? (${dlLib.length} videos — the files stay in the folder)`);
$("dl-folder").onclick = () => api.videosOpen({ folder: true }).catch((err) => toast(err.message || "Couldn't open the folder"));
for (const b of document.querySelectorAll("[data-dlt]")) b.onclick = () => {
  dlTab = b.dataset.dlt;
  for (const x of document.querySelectorAll("[data-dlt]")) x.classList.toggle("on", x === b);
  $("dl-list").hidden = dlTab !== "run";
  $("dl-lib").hidden = dlTab !== "lib";
  $("dl-tray").classList.remove("min");
  if (dlTab === "lib") loadVideos();
};
if (DL_HERE) loadVideos();
$("dl-min").onclick = () => { const m = !$("dl-tray").classList.contains("min"); $("dl-tray").classList.toggle("min", m); dlPref("min", m ? "1" : "0"); };
$("dl-tray").classList.toggle("min", dlPref("min") === "1");
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadDownloads(); });
loadDownloads();

// mini chat: its window has no frame, so dragging the page's edge resizes it (the host remembers the size)
if (MINI && !WSONLY) {
  const EDGE = 6, CUR = { n: "ns", s: "ns", e: "ew", w: "ew", ne: "nesw", sw: "nesw", nw: "nwse", se: "nwse" };
  const edgeAt = (e) => (e.clientY < EDGE ? "n" : e.clientY > innerHeight - EDGE ? "s" : "") + (e.clientX < EDGE ? "w" : e.clientX > innerWidth - EDGE ? "e" : "");
  let cur = "";
  document.addEventListener("mousemove", (e) => {
    const ed = edgeAt(e);
    if (ed !== cur) { cur = ed; document.documentElement.style.cursor = ed ? CUR[ed] + "-resize" : ""; }
  }, { passive: true });
  document.addEventListener("mousedown", (e) => { const ed = e.button === 0 && edgeAt(e); if (ed && hostSay("resize:" + ed)) e.preventDefault(); }, true);
}

// mini chat: a glass panel (the blur behind it is Blur my Shell's, always on), mac-style window dots,
// a language picker, background jobs as a small strip, 0-token quick asks.
if (MINI && !WSONLY) {
  const B = document.body;
  if (params.get("opaque") === "1") B.classList.add("opaque"); // no compositor: no see-through window
  $("m-close").onclick = () => $("btn-hide").click();
  $("m-min").onclick = () => { S.compact = !S.compact; saveSettings(S); B.classList.toggle("compact", !!S.compact); };
  B.classList.toggle("compact", !!S.compact);
  const logEl = $("log"), chatEl = logEl.closest(".chat");
  const atBottom = () => chatEl.classList.toggle("at-bottom", logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40);
  logEl.addEventListener("scroll", atBottom, { passive: true });
  new MutationObserver(atBottom).observe(logEl, { childList: true });
  atBottom();
  $("m-zoom").onclick = () => $("btn-full").click();
  // look: blur (Blur my Shell, system-wide for the whitelisted windows), corner radius (page + blur edge), tint (page)
  const look = Object.assign({ blur: 40, light: 90, corner: 15, tint: 58, color: "#101328", font: "inter" }, S.look || {});
  if (look.blur === 80 && !S.look?.light) look.blur = 40; // the old 0-100 scale (80 = radius 40)
  const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)).join(", ");
  const label = { blur: (v) => v + " px", light: (v) => v + "%", tint: (v) => v + "%", corner: (v) => (v ? v + " px" : "square") };
  const applyLook = () => {
    B.style.setProperty("--m-r", look.corner + "px");
    B.style.setProperty("--m-tint", (look.tint / 100).toFixed(2));
    B.style.setProperty("--m-tint-rgb", rgb(look.color));
    for (const k of Object.keys(label)) { $("lk-" + k).value = look[k]; $("lk-" + k + "-v").textContent = label[k](look[k]); }
    $("lk-color").value = look.color;
    $("lk-font").value = look.font; B.dataset.font = look.font;
    $("lk-note").textContent = look.blur > 50 && look.corner ? "Above 50 px the blur's corners turn square." : "";
  };
  let glassT = 0;
  const pushGlass = () => { clearTimeout(glassT); glassT = setTimeout(async () => {
    try { const r = await api.setGlass(look.blur, Math.round(look.corner * (window.devicePixelRatio || 1)), look.light); if (!r.ok) $("lk-note").textContent = "Blur: " + (r.error || "not available"); }
    catch { $("lk-note").textContent = "Blur: KURAMA offline"; }
  }, 400); };
  const save = () => { S.look = { ...look }; saveSettings(S); applyLook(); };
  for (const k of Object.keys(label)) $("lk-" + k).addEventListener("input", (e) => {
    look[k] = +e.target.value; save();
    if (k !== "tint") pushGlass();
  });
  $("lk-color").addEventListener("input", (e) => { look.color = e.target.value; save(); });
  $("lk-font").addEventListener("change", (e) => { look.font = e.target.value; save(); });
  $("m-look").onclick = (e) => { e.stopPropagation(); $("m-lookp").hidden = !$("m-lookp").hidden; };
  document.addEventListener("click", (e) => { if (!e.target.closest("#m-lookp, #m-look")) $("m-lookp").hidden = true; });
  applyLook();
  const lang = $("m-lang");
  lang.value = S.lang || "auto";
  lang.onchange = () => { S.lang = lang.value; saveSettings(S); if ($("set-lang")) $("set-lang").value = S.lang; };
  const box = $("m-jobs");
  let jobsKey = "", armed = 0;
  const frac = (p) => { const m = /(\d+)\s*\/\s*(\d+)/.exec(p || ""); return m && +m[2] ? Math.min(1, +m[1] / +m[2]) : null; };
  const row = (j) => {
    const f = frac(j.progress);
    const paused = j.status === "paused";
    return `<div class="mj${paused ? " paused" : ""}" data-id="${j.id}">
      <span class="mj-t" title="${esc(j.title)}">${esc(j.title)}</span>
      <span class="mj-p">${esc(paused ? (j.progress || "paused") : (j.progress || j.status))}</span>
      ${j.kind === "long" ? `<button type="button" class="mj-b" data-jact="${paused ? "resume" : "pause"}" title="${paused ? "Continue" : "Pause"}" aria-label="${paused ? "Continue" : "Pause"} job">${paused
        ? '<svg viewBox="0 0 24 24"><path d="M8 5l11 7-11 7z"/></svg>' : '<svg viewBox="0 0 24 24"><path d="M9 5v14M15 5v14"/></svg>'}</button>` : ""}
      <button type="button" class="mj-b x" data-jact="cancel" title="Cancel (click twice)" aria-label="Cancel job"><svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7L7 17"/></svg></button>
      <i class="mj-bar${f === null ? " ind" : ""}" style="--f:${f ?? 0.35}"></i></div>`;
  };
  const pollJobs = async () => {
    if (document.hidden) return;
    try {
      const items = (await api.activeJobs()).jobs || [];
      const key = JSON.stringify(items.map((j) => [j.id, j.status, j.progress]));
      if (key === jobsKey) return;
      jobsKey = key;
      box.innerHTML = items.slice(0, 3).map(row).join("");
      box.hidden = !items.length;
    } catch { /* offline: keep the last view */ }
  };
  box.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-jact]");
    if (!b) return;
    const id = +b.closest(".mj").dataset.id, act = b.dataset.jact;
    if (act === "cancel" && armed !== id) { armed = id; b.classList.add("armed"); setTimeout(() => { armed = 0; b.classList.remove("armed"); }, 3000); return; }
    armed = 0;
    try { await (act === "cancel" ? api.cancelJob(id) : act === "pause" ? api.pauseJob(id) : api.resumeJob(id)); } catch { /* the next poll shows the truth */ }
    jobsKey = ""; pollJobs();
  });
  setInterval(pollJobs, 5000); pollJobs();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollJobs(); });
}

// the laptop's echo canceller runs only while this page records (voice / talk mode), never in text mode
const MIC_ID = (MINI ? "mini-" : "main-") + Math.random().toString(36).slice(2, 8);
micHooks.before = () => Promise.race([api.micUse(true, MIC_ID), new Promise((r) => setTimeout(r, 2500))]).catch(() => {});
micHooks.after = () => { api.micUse(false, MIC_ID).catch(() => {}); };
addEventListener("pagehide", () => { try { navigator.sendBeacon?.(api.base() + "/api/v1/voice/mic", new Blob([JSON.stringify({ on: false, id: MIC_ID })], { type: "application/json" })); } catch { /* ignore */ } });
