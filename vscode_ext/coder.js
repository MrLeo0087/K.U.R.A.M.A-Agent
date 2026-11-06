// KURAMA Coder: a chat panel for the coding agent inside VS Code (like Claude Code's panel), in the side bar.
// What it does:
//   - the project is THIS window's folder (pinned for the agent before every message: no confusion which project)
//   - a message goes to KURAMA with the coding agent on (KURAMA's /api/v1/chat, streamed), the reply shows here
//   - background work (a plan, a build, a change) shows as a live checklist from KURAMA's Progress (/api/v1/progress)
//   - quick buttons: Run, Look, Tests, Changes, Undo, Learn, All commands
// Everything talks to KURAMA on 127.0.0.1:8000 (the API token from ~/.local/share/kurama/api_token when one is set).
"use strict";
const vscode = require("vscode");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

function headers(extra = {}) {
  const h = { "Content-Type": "application/json", ...extra };
  try { h.Authorization = "Bearer " + fs.readFileSync(path.join(os.homedir(), ".local", "share", "kurama", "api_token"), "utf8").trim(); } catch (e) { /* no token */ }
  return h;
}

function call(method, route, body, timeout = 8000) { // a plain JSON request to KURAMA
  return new Promise((resolve) => {
    const data = body ? JSON.stringify(body) : "";
    const req = http.request({ host: "127.0.0.1", port: 8000, path: route, method, timeout,
      headers: headers(data ? { "Content-Length": Buffer.byteLength(data) } : {}) }, (res) => {
      let out = "";
      res.on("data", (c) => { out += c; });
      res.on("end", () => { try { resolve(JSON.parse(out)); } catch (e) { resolve({}); } });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
    req.end(data);
  });
}

let current = null; // the chat request in flight (Stop cuts it)
function chat(text, onDelta) { // KURAMA's chat stream (Server-Sent Events): deltas as they come, then the done event
  return new Promise((resolve) => {
    const data = JSON.stringify({ text, mode: "text", via: "vscode" }); // whole answers, edits applied in the editor
    const req = http.request({ host: "127.0.0.1", port: 8000, path: "/api/v1/chat", method: "POST", timeout: 180000,
      headers: headers({ "Content-Length": Buffer.byteLength(data), Accept: "text/event-stream" }) }, (res) => {
      let buf = "", done = null;
      res.on("data", (c) => {
        buf += c;
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const line = block.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "delta") onDelta(ev.text);
            else if (ev.type === "done") done = ev;
            else if (ev.type === "error") onDelta("\n" + ev.text);
          } catch (e) { /* a keep-alive */ }
        }
      });
      res.on("end", () => resolve(done || {}));
    });
    current = req;
    req.on("error", () => resolve(req.stopped ? { error: "Stopped." } : { error: "KURAMA isn't running (start it with Super+K)" }));
    req.on("timeout", () => { req.destroy(); resolve({ error: "No answer in 3 minutes" }); });
    req.end(data);
  });
}

class CoderView {
  constructor(context) { this.context = context; this.view = null; this.watch = new Set(); this.timer = null; this.since = 0; }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = page();
    view.webview.onDidReceiveMessage((m) => this.onMessage(m));
    this.post({ type: "project", name: this.root() ? path.basename(this.root()) : "", path: this.root() || "" });
  }

  root() { return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || ""; }

  post(msg) { this.view?.webview.postMessage(msg); }

  async onMessage(m) {
    if (m.type === "stop") return this.stop();
    if (m.type === "mic") return this.mic();
    if (m.type !== "send" || !m.text.trim()) return;
    if (/^\/(clear|forget|new)\b/i.test(m.text.trim())) m.text = "/code forget"; // a fresh start for this project
    const root = this.root();
    if (root) await call("POST", "/api/v1/coding/project", { path: root }); // this window's folder = the project
    await call("POST", "/api/v1/agent", { name: "coding" });
    this.post({ type: "start" });
    this.post({ type: "busy", on: true });
    if (!this.since) this.since = Date.now() / 1000 - 1;
    const done = await chat(m.text, (t) => this.post({ type: "delta", text: t }));
    this.post({ type: "end", text: done.text || "", error: done.error || "" });
    for (const j of done.jobs || []) this.watch.add(j);
    if (this.watch.size) this.poll(); else this.post({ type: "busy", on: false });
  }

  async stop() { // ■: cut the reply in flight and cancel every job this panel started (they stop at their next step)
    if (current) { current.stopped = true; current.destroy(); current = null; }
    for (const j of this.watch) await call("POST", `/api/v1/jobs/${j}/cancel`, {});
    this.watch.clear();
    this.post({ type: "busy", on: false });
    this.post({ type: "result", text: "Stopped.", ok: false });
  }

  async mic() { // 🎤 push-to-talk: arecord into a wav, KURAMA's speech-to-text, the words go into the box
    const { spawn } = require("child_process");
    const wav = path.join(os.tmpdir(), "kurama-coder-mic.wav");
    if (!this.rec) {
      try { fs.unlinkSync(wav); } catch (e) { /* none */ }
      this.rec = spawn("arecord", ["-q", "-f", "S16_LE", "-r", "16000", "-c", "1", wav]);
      this.rec.on("error", () => { this.rec = null; this.post({ type: "mic", on: false, error: "arecord isn't available" }); });
      this.post({ type: "mic", on: true });
      return;
    }
    const rec = this.rec; this.rec = null;
    await new Promise((r) => { rec.on("exit", r); rec.kill("SIGINT"); setTimeout(r, 1500); });
    this.post({ type: "mic", on: false, busy: true });
    let audio; try { audio = fs.readFileSync(wav); } catch (e) { return this.post({ type: "mic", on: false, error: "nothing recorded" }); }
    const text = await new Promise((resolve) => {
      const req = http.request({ host: "127.0.0.1", port: 8000, path: "/api/v1/stt", method: "POST", timeout: 60000,
        headers: headers({ "Content-Type": "audio/wav", "Content-Length": audio.length }) }, (res) => {
        let out = ""; res.on("data", (c) => { out += c; });
        res.on("end", () => { try { resolve(JSON.parse(out).text || ""); } catch (e) { resolve(""); } });
      });
      req.on("error", () => resolve("")); req.end(audio);
    });
    this.post({ type: "heard", text });
  }

  async poll() { // the jobs this panel started: every step (input + output) and their checklist, live, until they end
    clearTimeout(this.timer);
    const ev = await call("GET", `/api/v1/coding/events?path=${encodeURIComponent(this.root())}&since=${this.since}`);
    for (const e of ev?.events || []) { this.since = Math.max(this.since, e.t); this.post({ type: "event", e }); }
    const r = await call("GET", "/api/v1/progress");
    const items = (r?.items || []).filter((x) => this.watch.has(x.job));
    this.post({ type: "progress", items });
    for (const x of items) {
      if (["done", "failed", "cancelled", "stopped"].includes(x.status)) {
        this.watch.delete(x.job);
        this.post({ type: "result", text: x.detail || x.status, ok: x.status === "done" });
      }
    }
    if (this.watch.size) this.timer = setTimeout(() => this.poll(), 2000);
    else this.post({ type: "busy", on: false });
  }
}

function page() {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>
body { font-family: var(--vscode-font-family); font-size: 13px; color: var(--vscode-foreground); margin: 0; padding: 0;
  display: flex; flex-direction: column; height: 100vh; }
#proj { padding: 6px 10px; font-size: 11.5px; opacity: .8; border-bottom: 1px solid var(--vscode-panel-border); }
#log { flex: 1; overflow-y: auto; padding: 8px 10px; }
.m { margin: 8px 0; padding: 7px 9px; border-radius: 8px; white-space: pre-wrap; word-wrap: break-word; line-height: 1.45; }
.me { background: var(--vscode-input-background); margin-left: 18px; }
.bot { background: var(--vscode-editor-inactiveSelectionBackground); }
.res.ok { border-left: 3px solid var(--vscode-testing-iconPassed, #3fb950); }
.res.bad { border-left: 3px solid var(--vscode-errorForeground, #f85149); }
.steps { margin: 4px 0 8px; font-size: 12px; opacity: .9; }
.steps div::before { content: "○ "; } .steps .done::before { content: "● "; color: var(--vscode-testing-iconPassed, #3fb950); }
.steps .doing::before { content: "◌ "; color: var(--vscode-charts-yellow, #d29922); } .steps .failed::before { content: "✕ "; color: #f85149; }
#acts { display: flex; flex-wrap: wrap; gap: 4px; padding: 6px 10px 0; }
#acts button { font-size: 11px; padding: 2px 7px; border-radius: 10px; border: 1px solid var(--vscode-panel-border);
  background: transparent; color: var(--vscode-foreground); cursor: pointer; }
#acts button:hover { background: var(--vscode-toolbar-hoverBackground); }
form { display: flex; gap: 6px; padding: 8px 10px 10px; }
textarea { flex: 1; resize: none; min-height: 36px; max-height: 120px; font: inherit; padding: 6px 8px; border-radius: 6px;
  color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border, transparent); }
button.send { align-self: flex-end; width: 28px; height: 28px; padding: 0; border: 0; border-radius: 50%; display: grid;
  place-items: center; color: var(--vscode-button-foreground); background: var(--vscode-button-background); cursor: pointer; }
button.send svg { width: 14px; height: 14px; }
.step { margin: 3px 0; font-size: 12px; }
.step summary { cursor: pointer; list-style: none; opacity: .95; }
.step summary::-webkit-details-marker { display: none; }
.step .io { margin: 4px 0 6px 14px; padding: 6px 8px; border-left: 2px solid var(--vscode-panel-border); font-family: var(--vscode-editor-font-family);
  font-size: 11.5px; white-space: pre-wrap; max-height: 220px; overflow: auto; opacity: .9; }
.step .lbl { opacity: .6; font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; }
.plan { margin: 8px 0; padding: 8px 10px; border: 1px solid var(--vscode-panel-border); border-radius: 8px; white-space: pre-wrap; font-size: 12.5px; }
.why { opacity: .7; font-style: italic; }
button.mic { background: transparent; color: var(--vscode-foreground); border: 1px solid var(--vscode-panel-border); }
button.mic.on { background: #c0392b; color: #fff; border-color: #c0392b; }
#go .i-stop { display: none; } #go.busy .i-send { display: none; } #go.busy .i-stop { display: block; }
.hint { opacity: .6; font-size: 12px; padding: 4px 0; }
</style></head><body>
<div id="proj">KURAMA Coder</div>
<div id="log"><div class="hint">Tell me what to build or change in this project: "make the buttons grey", "add a login page",
"run it and tell me what it prints", "fix the crash". Plans and changes show their steps here.</div></div>
<div id="acts">
  <button data-say="Run this project and tell me what it prints">▶ Run</button>
  <button data-say="Take a screenshot of the app and tell me how it looks">📸 Look</button>
  <button data-say="Write tests for this project">✓ Tests</button>
  <button data-say="Show me what you changed">⇄ Changes</button>
  <button data-say="Undo that">↶ Undo</button>
  <button data-say="what did you do">📜 Steps</button>
  <button data-say="/code learn">🧠 Learn</button>
  <button data-say="/code">☰ All</button>
</div>
<form id="f"><textarea id="t" placeholder="Ask the coding agent… (Enter sends · /clear = fresh start)"></textarea>
<button type="button" class="send mic" id="mic" title="Speak (click, talk, click again)" aria-label="Speak"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/></svg></button>
<button class="send" id="go" title="Send" aria-label="Send"><svg class="i-send" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg><svg class="i-stop" viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/></svg></button></form>
<script>
const vs = acquireVsCodeApi(), log = document.getElementById("log"), t = document.getElementById("t");
let bot = null, steps = null;
const add = (cls, text) => { const d = document.createElement("div"); d.className = "m " + cls; d.textContent = text; log.append(d); log.scrollTop = log.scrollHeight; return d; };
const ICON = { read: "📖", grep: "🔎", find: "🔎", list: "📂", edit: "✏️", apply_edits: "✏️", write: "📝", run: "▶️",
  run_project: "▶️", screenshot: "📸", look: "👀", page_errors: "🐞", web_search: "🌐", read_webpage: "🌐" };
function step(e) { // one step of the agent, like Claude Code: what it called with what input, and what came back
  if (e.kind === "plan_ready") { const d = document.createElement("div"); d.className = "plan"; d.textContent = e.text; log.append(d); }
  else if (e.kind === "plan") { const d = document.createElement("div"); d.className = "plan"; d.textContent = "Plan:\\n" + e.plan.map((x, i) => (i + 1) + ". " + x).join("\\n"); log.append(d); }
  else if (e.kind === "tool") {
    const d = document.createElement("details"); d.className = "step";
    const target = e.args && (e.args.path || e.args.command || e.args.pattern || e.args.question || e.args.query) || "";
    const s = document.createElement("summary"); s.textContent = (ICON[e.tool] || "•") + " " + e.tool + (target ? " · " + target : ""); d.append(s);
    if (e.thought) { const w = document.createElement("div"); w.className = "io why"; w.textContent = e.thought; d.append(w); }
    const i = document.createElement("div"); i.className = "io"; i.innerHTML = '<div class="lbl">input</div>'; i.append(JSON.stringify(e.args, null, 2)); d.append(i);
    if (e.result) { const o = document.createElement("div"); o.className = "io"; o.innerHTML = '<div class="lbl">output</div>'; o.append(e.result); d.append(o); }
    log.append(d);
  } else if (e.kind === "check") {
    const d = document.createElement("div"); d.className = "step"; d.textContent = (e.ok ? "✅ checked: it works" : "🔁 check found: " + (e.problems || [""])[0].slice(0, 200)); log.append(d);
  }
  log.scrollTop = log.scrollHeight;
}
const send = (text) => {
  if (!text.trim()) return;
  if (["/clear", "/forget", "/new"].some((c) => text.trim().toLowerCase().startsWith(c))) log.innerHTML = ""; // fresh start
  add("me", text); vs.postMessage({ type: "send", text }); t.value = "";
};
const go = document.getElementById("go"), mic = document.getElementById("mic");
document.getElementById("f").onsubmit = (e) => { e.preventDefault(); if (go.classList.contains("busy")) vs.postMessage({ type: "stop" }); else send(t.value); };
mic.onclick = () => vs.postMessage({ type: "mic" });
t.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(t.value); } });
document.querySelectorAll("#acts button").forEach((b) => b.onclick = () => send(b.dataset.say));
window.addEventListener("message", ({ data: m }) => {
  if (m.type === "project") document.getElementById("proj").textContent = m.name ? "Project: " + m.name + " (" + m.path + ")" : "Open a folder to work on it";
  if (m.type === "start") { bot = add("bot", "…"); bot.textContent = ""; }
  if (m.type === "delta" && bot) { bot.textContent += m.text; log.scrollTop = log.scrollHeight; }
  if (m.type === "end" && bot) { if (!bot.textContent) bot.textContent = m.error || m.text || "(no answer)"; bot = null; }
  if (m.type === "progress") {
    if (!steps) { steps = document.createElement("div"); steps.className = "steps"; log.append(steps); }
    steps.innerHTML = "";
    for (const it of m.items) {
      const h = document.createElement("div"); h.textContent = it.title + " — " + (it.detail || it.status); steps.append(h);
      for (const s of it.steps || []) { const d = document.createElement("div"); d.className = s.state; d.textContent = s.text; steps.append(d); }
    }
    log.scrollTop = log.scrollHeight;
  }
  if (m.type === "result") { add("bot res " + (m.ok ? "ok" : "bad"), m.text); steps = null; }
  if (m.type === "event") step(m.e);
  if (m.type === "busy") go.classList.toggle("busy", m.on);
  if (m.type === "mic") { mic.classList.toggle("on", m.on); if (m.error) add("bot res bad", m.error); t.placeholder = m.on ? "Listening… click 🎤 again when done" : (m.busy ? "Writing what you said…" : "Ask the coding agent… (Enter sends · /clear = fresh start)"); }
  if (m.type === "heard") { t.placeholder = "Ask the coding agent… (Enter sends · /clear = fresh start)"; if (m.text) send(m.text); else add("bot res bad", "I didn't catch that."); }
});
</script></body></html>`;
}

function register(context) {
  const view = new CoderView(context);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider("kurama.coder", view,
    { webviewOptions: { retainContextWhenHidden: true } }));
}

module.exports = { register };
