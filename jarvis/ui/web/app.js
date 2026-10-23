// Jarvis test UI: vanilla JS, no build step. Model text is never put into innerHTML.
"use strict";

const $ = (id) => document.getElementById(id);
const log = $("log"), input = $("input"), form = $("form"), sendBtn = $("send");
const micBtn = $("mic"), speakBox = $("speak"), langSel = $("lang"), dot = $("dot");
let busy = false;
let statusTimer = null;

// ---- small helpers ----
function store(key, val) {
  try { if (val === undefined) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (e) { return null; }
  return null;
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function scrollDown() { log.scrollTop = log.scrollHeight; }
function hideEmpty() { const e = $("empty"); if (e) e.remove(); }

// ---- safe minimal markdown: ```code```, `inline`, **bold**, line breaks ----
function renderInline(parent, text) {
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
    const tok = m[0];
    if (tok.startsWith("**")) parent.appendChild(el("strong", "", tok.slice(2, -2)));
    else parent.appendChild(el("code", "", tok.slice(1, -1)));
    last = m.index + tok.length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}
function renderText(parent, text) {
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    renderInline(parent, line);
    if (i < lines.length - 1) parent.appendChild(document.createElement("br"));
  });
}
function renderMarkdown(target, src) {
  target.replaceChildren();
  const parts = src.split("```");
  parts.forEach((part, i) => {
    if (i % 2 === 1) {  // inside a fence (may be unterminated while streaming)
      const nl = part.indexOf("\n");
      const body = nl >= 0 && /^[\w+#.-]*$/.test(part.slice(0, nl).trim()) ? part.slice(nl + 1) : part;
      const pre = el("pre"), code = el("code", "", body.replace(/\n$/, ""));
      pre.appendChild(code);
      target.appendChild(pre);
    } else if (part) {
      const span = el("span");
      renderText(span, part.replace(/^\n+/, i ? "" : "$&").replace(/\n+$/, i < parts.length - 1 ? "" : "$&"));
      target.appendChild(span);
    }
  });
}

// ---- chat bubbles ----
function addUser(text) {
  hideEmpty();
  const m = el("div", "msg user"), b = el("div", "bubble");
  renderText(b, text);
  m.appendChild(b);
  log.appendChild(m);
  scrollDown();
}
function addBot() {
  hideEmpty();
  const m = el("div", "msg bot"), b = el("div", "bubble pending"), chips = el("div", "chips");
  m.append(b, chips);
  log.appendChild(m);
  scrollDown();
  let text = "", queued = false;
  return {
    msg: m, bubble: b, chips,
    get text() { return text; },
    append(delta) {
      text += delta;
      if (!queued) {
        queued = true;
        requestAnimationFrame(() => { queued = false; renderMarkdown(b, text); scrollDown(); });
      }
    },
    set(full) { text = full; renderMarkdown(b, text); },
  };
}
function chip(parent, label, cls) { parent.appendChild(el("span", "chip " + (cls || ""), label)); }

function routeLabel(route) {
  if (!route) return "";
  if (typeof route === "string") return route;
  const groups = (route.groups || []).join("+");
  return (route.method || "") + (groups ? ":" + groups : "");
}

function confirmCard(bot, ev) {
  const card = $("confirmTpl").content.firstElementChild.cloneNode(true);
  card.dataset.id = ev.id;
  card.querySelector(".confirm-q").textContent = ev.prompt || "Should I go ahead?";
  const answer = async (yes) => {
    card.classList.add("done");
    card.appendChild(el("div", "answer", yes ? "You said yes." : "You said no."));
    try {
      await fetch("/api/confirm", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: ev.id, yes }) });
    } catch (e) { /* the server denies on timeout anyway */ }
  };
  card.querySelector(".yes").addEventListener("click", () => answer(true));
  card.querySelector(".no").addEventListener("click", () => answer(false));
  bot.msg.insertBefore(card, bot.chips);
  scrollDown();
  card.querySelector(".yes").focus();
}

// ---- SSE over fetch (POST) ----
async function* sse(resp) {
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
      if (data) { try { yield JSON.parse(data); } catch (e) { /* skip bad frame */ } }
    }
  }
}

function setBusy(b) {
  busy = b;
  sendBtn.disabled = b;
  dot.className = "dot " + (b ? "busy" : "ok");
}

async function send(text, mode, lang) {
  text = (text || "").trim();
  if (!text || busy) return;
  addUser(text);
  setBusy(true);
  const bot = addBot();
  let finalText = "";
  try {
    const resp = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, mode: mode || "text", lang: lang || langSel.value || null }),
    });
    if (!resp.ok || !resp.body) throw new Error("server said " + resp.status);
    for await (const ev of sse(resp)) {
      if (ev.type === "delta") bot.append(ev.text || "");
      else if (ev.type === "tool") chip(bot.chips, "⚙ " + ev.name + (ev.ok ? "" : " ✗") + (ev.ms != null ? " " + ev.ms + "ms" : ""), "tool" + (ev.ok ? "" : " fail"));
      else if (ev.type === "confirm") confirmCard(bot, ev);
      else if (ev.type === "confirm_timeout") {
        const c = bot.msg.querySelector('.confirm[data-id="' + ev.id + '"]');
        if (c && !c.classList.contains("done")) { c.classList.add("done"); c.appendChild(el("div", "answer", "No answer in time, so I didn't do it.")); }
      } else if (ev.type === "error") { bot.bubble.classList.add("error"); bot.set(ev.text || "Something went wrong."); }
      else if (ev.type === "done") {
        finalText = ev.text || bot.text;
        if (!bot.bubble.classList.contains("error")) bot.set(finalText || "(no reply)");
        const r = routeLabel(ev.route);
        if (r) chip(bot.chips, r);
        if (ev.tier) chip(bot.chips, ev.tier);
        chip(bot.chips, (ev.tokens || 0) + " tok");
        chip(bot.chips, (ev.ms || 0) + " ms");
      }
    }
  } catch (e) {
    bot.bubble.classList.add("error");
    bot.set("I couldn't reach the server (" + e.message + "). Is `python -m jarvis.server` running?");
    dot.className = "dot bad";
  } finally {
    bot.bubble.classList.remove("pending");
    bot.msg.querySelectorAll(".confirm:not(.done)").forEach((c) => c.classList.add("done"));
    setBusy(false);
    scrollDown();
  }
  if (finalText && speakBox.checked) {
    fetch("/api/speak", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: finalText, lang: lang || langSel.value || null }) }).catch(() => {});
  }
}

// ---- composer ----
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
});
form.addEventListener("submit", (e) => {
  e.preventDefault();
  if (busy) return;
  const t = input.value;
  input.value = "";
  autosize();
  send(t, "text");
});

$("clear").addEventListener("click", () => {
  log.replaceChildren(el("div", "empty", "Chat cleared. (Jarvis still remembers the conversation context.)"));
  log.firstChild.id = "empty";
});

speakBox.checked = store("jarvis.speak") === "1";
speakBox.addEventListener("change", () => {
  store("jarvis.speak", speakBox.checked ? "1" : "0");
  if (!speakBox.checked) fetch("/api/speak/stop", { method: "POST" }).catch(() => {});
});
langSel.value = store("jarvis.lang") || "";
langSel.addEventListener("change", () => store("jarvis.lang", langSel.value));

// ---- mic: MediaRecorder -> /api/stt -> send ----
let rec = null, recTimer = null;
async function startRec() {
  if (!navigator.mediaDevices || !window.MediaRecorder) { alert("This browser can't record audio."); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); }
  catch (e) { alert("Microphone permission denied."); return; }
  const types = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", ""];
  const mimeType = types.find((t) => !t || MediaRecorder.isTypeSupported(t));
  const chunks = [];
  rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    clearTimeout(recTimer);
    micBtn.classList.remove("rec");
    const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
    rec = null;
    if (blob.size < 800) return;  // a click, not speech
    micBtn.classList.add("busy");
    try {
      const q = langSel.value ? "?lang=" + encodeURIComponent(langSel.value) : "";
      const resp = await fetch("/api/stt" + q, { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || resp.status);
      if (data.text && data.text.trim()) send(data.text, "voice", data.lang);
      else { input.value = ""; input.placeholder = "Didn't catch that. Try again?"; }
    } catch (e) {
      input.value = "";
      input.placeholder = "Speech-to-text failed: " + e.message;
    } finally { micBtn.classList.remove("busy"); }
  };
  rec.start();
  micBtn.classList.add("rec");
  recTimer = setTimeout(() => rec && rec.state === "recording" && rec.stop(), 30000);
}
micBtn.addEventListener("click", () => {
  if (busy) return;
  if (rec && rec.state === "recording") rec.stop(); else startRec();
});

// ---- status panel ----
function fill(listEl, items, render) {
  listEl.replaceChildren();
  if (!items || !items.length) { listEl.appendChild(el("li", "muted", "none")); return; }
  items.forEach((it) => listEl.appendChild(render(it)));
}
function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return Math.round(s) + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}
async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    $("sRam").textContent = s.rss_mb + " MB";
    const t = s.tokens || {};
    $("sTok").textContent = (t.today || 0).toLocaleString();
    $("sFast").textContent = t.fastpath_hits != null ? t.fastpath_hits : "–";
    $("sFacts").textContent = s.profile_facts;
    $("sAgent").textContent = s.busy ? "busy" : s.agent_ready ? "ready" : s.agent_loaded ? "loading" : "idle";
    const w = (s.workers && s.workers.workers) || null;
    if (w) {
      const names = Object.keys(w), running = names.filter((n) => w[n].state === "running").length;
      $("sWorkers").textContent = running + "/" + names.length;
    } else $("sWorkers").textContent = "off";
    fill($("jobs"), s.jobs, (j) => {
      const li = el("li", "", "#" + j.id + " " + (j.title || j.kind));
      li.appendChild(el("span", "meta", (j.status || "") + (j.progress ? " · " + j.progress : "")));
      return li;
    });
    fill($("alerts"), s.alerts, (a) => {
      const li = el("li", a.level || "", a.title || "");
      li.appendChild(el("span", "meta", (a.text || "").slice(0, 160)));
      li.appendChild(el("span", "meta", (a.source ? a.source + " · " : "") + ago(a.ts)));
      return li;
    });
    $("updated").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (!busy) dot.className = "dot ok";
    if (s.refresh_s && statusTimer && s.refresh_s * 1000 !== statusTimer.ms) startStatus(s.refresh_s * 1000);
  } catch (e) {
    if (!busy) dot.className = "dot bad";
  }
}
function startStatus(ms) {
  if (statusTimer) clearInterval(statusTimer.id);
  statusTimer = { id: setInterval(() => { if (!document.hidden) refreshStatus(); }, ms), ms };
}
$("panelBtn").addEventListener("click", () => $("panel").classList.toggle("open"));
startStatus(10000);
refreshStatus();
input.focus();
