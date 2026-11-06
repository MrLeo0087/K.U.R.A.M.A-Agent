// KURAMA editor link: tells KURAMA (on this laptop only) which file is open in VS Code and exactly what is selected,
// and lets KURAMA put code into the editor itself (one Ctrl+Z undoes it; unsaved edits are kept).
//
// - State: one small JSON per VS Code window in ~/.local/share/kurama/vscode/<pid>.json, rewritten on every change
//   (file, selection text + lines, cursor, unsaved edits, project folder). Nothing polls; idle cost is zero.
// - Edits: a tiny HTTP server on 127.0.0.1 (random port + random token, both only in that 0600 file) that KURAMA
//   calls to read the live text or replace / insert text. Nothing ever leaves this laptop.
"use strict";
const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const crypto = require("crypto");

const DIR = path.join(os.homedir(), ".local", "share", "kurama", "vscode");
const FILE = path.join(DIR, `${process.pid}.json`);
const TOKEN = crypto.randomBytes(16).toString("hex");
const EXT_VERSION = 6; // KURAMA checks it: 3 = watches the terminal for the coding agent, 5 = claude_say, 6 = claude_new
const MAX_SEL = 20000; // characters of selected text written to the state file
const MAX_BODY = 8 * 1024 * 1024;
let port = 0;
let server = null;
let timer = null;
let focusedAt = vscode.window.state.focused ? Date.now() / 1000 : 0;
let lastDirty = null;

function fileDoc(doc) {
  return doc && (doc.uri.scheme === "file" || doc.isUntitled);
}

function snapshot() {
  const ed = vscode.window.activeTextEditor;
  const doc = ed && fileDoc(ed.document) ? ed.document : null;
  const folder = doc ? vscode.workspace.getWorkspaceFolder(doc.uri) : null;
  const root = folder || (vscode.workspace.workspaceFolders || [])[0];
  const sel = doc ? ed.selection : null;
  const text = sel && !sel.isEmpty ? doc.getText(sel) : "";
  return {
    v: 1, ext: EXT_VERSION, pid: process.pid, port, token: TOKEN, ts: Date.now() / 1000,
    focused: vscode.window.state.focused, focused_at: focusedAt,
    workspace: vscode.workspace.name || "", root: root ? root.uri.fsPath : "",
    file: doc && !doc.isUntitled ? doc.uri.fsPath : "", untitled: !!(doc && doc.isUntitled),
    language: doc ? doc.languageId : "", dirty: !!(doc && doc.isDirty), lines: doc ? doc.lineCount : 0,
    selection: text.length > MAX_SEL ? "" : text, selection_chars: text.length,
    sel: sel ? { start: [sel.start.line, sel.start.character], end: [sel.end.line, sel.end.character] } : null,
    cursor: sel ? [sel.active.line, sel.active.character] : null,
    open: vscode.window.visibleTextEditors.filter((e) => e.document.uri.scheme === "file").map((e) => e.document.uri.fsPath),
  };
}

function write() {
  timer = null;
  try {
    fs.mkdirSync(DIR, { recursive: true, mode: 0o700 });
    const tmp = `${FILE}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(snapshot()), { mode: 0o600 });
    fs.renameSync(tmp, FILE);
  } catch (e) { /* KURAMA is a bonus: never bother the user */ }
}

function soon(ms = 120) {
  if (ms === 0) { clearTimeout(timer); write(); return; }
  if (!timer) timer = setTimeout(write, ms);
}

async function docFor(file) {
  if (!file) {
    const ed = vscode.window.activeTextEditor;
    return ed ? ed.document : null;
  }
  const open = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === file);
  return open || vscode.workspace.openTextDocument(vscode.Uri.file(file));
}

function editorFor(doc) {
  return vscode.window.visibleTextEditors.find((e) => e.document === doc) || null;
}

function rangeOf(doc, r) {
  return new vscode.Range(r[0][0], r[0][1], r[1][0], r[1][1]);
}

// ---- coding agent (only while it is on: ~/.local/share/kurama/agent says "coding") ----
const AGENT = path.join(os.homedir(), ".local", "share", "kurama", "agent");
const OUT_MAX = 8000; // characters of a command's output kept (the end of it)
const runs = new Map(); // execution -> Promise<output>
let lastTerminal = null;

function codingOn() {
  try { return fs.readFileSync(AGENT, "utf8").trim() === "coding"; } catch (e) { return false; }
}

async function collect(execution) {
  let out = "";
  try {
    for await (const data of execution.read()) {
      out += data;
      if (out.length > OUT_MAX * 2) out = out.slice(-OUT_MAX);
    }
  } catch (e) { /* the terminal closed */ }
  return out.slice(-OUT_MAX);
}

function api(route, body, timeout = 5000) { // POST to KURAMA (127.0.0.1); the API token too when one is set
  return new Promise((resolve) => {
    const data = JSON.stringify(body);
    const headers = { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) };
    try { headers.Authorization = "Bearer " + fs.readFileSync(path.join(os.homedir(), ".local", "share", "kurama", "api_token"), "utf8").trim(); } catch (e) { /* no token set */ }
    const req = http.request({ host: "127.0.0.1", port: 8000, path: route, method: "POST", headers, timeout }, (res) => {
      let out = "";
      res.on("data", (c) => { out += c; });
      res.on("end", () => { try { resolve(JSON.parse(out)); } catch (e) { resolve({}); } });
    });
    req.on("error", () => resolve({}));
    req.on("timeout", () => { req.destroy(); resolve({}); });
    req.end(data);
  });
}

async function showDiff(files) { // KURAMA's proposed change, side by side with the file
  for (const f of files.slice(0, 3)) {
    const tmp = path.join(os.tmpdir(), `kurama-${Date.now()}-${path.basename(f.path)}`);
    fs.writeFileSync(tmp, f.new);
    await vscode.commands.executeCommand("vscode.diff", vscode.Uri.file(f.path), vscode.Uri.file(tmp),
      `${path.basename(f.path)} ↔ KURAMA's fix`);
  }
}

async function act(say) { // a button was pressed: KURAMA does it and answers right here
  const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "KURAMA…" },
    () => api("/api/v1/coding/action", { say }, 120000));
  if (!r.text) { vscode.window.showWarningMessage("KURAMA didn't answer (is it running?)."); return; }
  if (!r.waiting) { vscode.window.showInformationMessage("KURAMA: " + r.text); return; }
  const btns = r.files && r.files.length ? ["Apply", "Show diff", "No"] : ["Yes", "No"];
  const pick = await vscode.window.showInformationMessage("KURAMA: " + r.text, ...btns);
  if (pick === "Show diff") {
    await showDiff(r.files);
    const again = await vscode.window.showInformationMessage("Apply KURAMA's change?", "Apply", "No");
    if (again === "Apply") act("yes"); else if (again === "No") act("no");
  } else if (pick === "Apply" || pick === "Yes") act("yes");
  else if (pick === "No") act("no");
}

async function report(body) { // a failed command -> KURAMA; its offer pops up right here in VS Code
  const r = await api("/api/v1/coding/terminal", body);
  const ev = r && r.event;
  if (!ev || !ev.text) return;
  const acts = ev.actions || [];
  const pick = await vscode.window.showErrorMessage("KURAMA: " + ev.text, ...acts.map((a) => a.label));
  const a = acts.find((x) => x.label === pick);
  if (a) act(a.say);
}

function watchTerminal(context) {
  if (!vscode.window.onDidStartTerminalShellExecution) return; // needs VS Code 1.93+ with shell integration
  context.subscriptions.push(vscode.window.onDidStartTerminalShellExecution((e) => {
    if (codingOn()) runs.set(e.execution, collect(e.execution));
  }));
  context.subscriptions.push(vscode.window.onDidEndTerminalShellExecution(async (e) => {
    const pending = runs.get(e.execution);
    if (!pending) return;
    runs.delete(e.execution);
    const output = await pending;
    if (e.exitCode === undefined || e.exitCode === 0) return;
    lastTerminal = e.terminal;
    const cwd = e.execution.cwd ? e.execution.cwd.fsPath : "";
    report({ command: e.execution.commandLine ? e.execution.commandLine.value : "", cwd, exit_code: e.exitCode, output });
  }));
}

function terminalRun(req) { // run a command again (after a fix the user said yes to), in the terminal it failed in
  let term = lastTerminal && vscode.window.terminals.includes(lastTerminal) ? lastTerminal : vscode.window.activeTerminal;
  if (!term) term = vscode.window.createTerminal({ name: "KURAMA", cwd: req.cwd || undefined });
  term.show(true);
  term.sendText(req.text || "", true);
  return { ok: true };
}

// one request = one operation: text | replace_all | replace_range | replace_text | insert | terminal_run
async function claudeSay(req) { // '/claude say <text>' from the phone: into the REAL Claude Code chat of this window
  try {
    await vscode.commands.executeCommand("claude-vscode.primaryEditor.open", req.session || undefined, req.text || undefined);
    await new Promise((r) => setTimeout(r, 1200)); // the chat tab opens (or comes forward) with the text in its box
    await vscode.commands.executeCommand("claude-vscode.focus"); // the cursor in that box: KURAMA presses Enter
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

async function claudeNew() { // '/claude go': a new, empty Claude Code chat in this window, ready for '/claude say'
  try {
    await vscode.commands.executeCommand("claude-vscode.editor.open");
    await new Promise((r) => setTimeout(r, 1200));
    await vscode.commands.executeCommand("claude-vscode.focus");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
}

async function handle(req) {
  if (req.op === "terminal_run") return terminalRun(req);
  if (req.op === "claude_new") return claudeNew();
  if (req.op === "claude_say") return claudeSay(req);
  const doc = await docFor(req.file || "");
  if (!doc) return { ok: false, error: "no file is open" };
  if (req.op === "text") return { ok: true, text: doc.getText(), dirty: doc.isDirty, lines: doc.lineCount };
  const all = doc.getText();
  const ed = editorFor(doc);
  let range;
  if (req.op === "replace_all") {
    range = new vscode.Range(doc.positionAt(0), doc.positionAt(all.length));
  } else if (req.op === "replace_range") {
    range = rangeOf(doc, req.range);
  } else if (req.op === "replace_text") { // exactly one place holds `old`
    const i = all.indexOf(req.old || "");
    if (!req.old || i < 0) return { ok: false, error: "that code isn't in the file anymore" };
    if (all.indexOf(req.old, i + 1) >= 0) return { ok: false, error: "that code is in the file more than once" };
    range = new vscode.Range(doc.positionAt(i), doc.positionAt(i + req.old.length));
  } else if (req.op === "insert") { // at a [line, col], else at the cursor, else at the end
    const p = req.at ? new vscode.Position(req.at[0], req.at[1])
      : ed ? ed.selection.active : doc.positionAt(all.length);
    range = new vscode.Range(p, p);
  } else {
    return { ok: false, error: `unknown operation ${req.op}` };
  }
  if (typeof req.expect === "string" && doc.getText(range) !== req.expect) {
    return { ok: false, error: "the text there changed since it was read" };
  }
  const wasDirty = doc.isDirty;
  const edit = new vscode.WorkspaceEdit();
  edit.replace(doc.uri, range, req.text || "");
  const ok = await vscode.workspace.applyEdit(edit);
  if (ok && !doc.isUntitled && (req.save === true || (req.save !== false && !wasDirty))) await doc.save();
  if (ok && ed && req.op !== "replace_all") {
    const start = range.start;
    const end = doc.positionAt(doc.offsetAt(start) + (req.text || "").length);
    ed.revealRange(new vscode.Range(start, end), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }
  soon(0);
  return ok ? { ok: true, lines: doc.lineCount, saved: !doc.isDirty } : { ok: false, error: "VS Code refused the edit" };
}

function serve() {
  server = http.createServer((req, res) => {
    const reply = (code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };
    if (req.method !== "POST" || req.headers["x-kurama-token"] !== TOKEN) return reply(403, { ok: false, error: "forbidden" });
    let size = 0;
    const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > MAX_BODY) req.destroy(); else chunks.push(c); });
    req.on("end", async () => {
      try {
        reply(200, await handle(JSON.parse(Buffer.concat(chunks).toString("utf8"))));
      } catch (e) {
        reply(200, { ok: false, error: String((e && e.message) || e) });
      }
    });
  });
  server.listen(0, "127.0.0.1", () => { port = server.address().port; soon(0); });
}

function activate(context) {
  serve();
  watchTerminal(context);
  const sub = (d) => context.subscriptions.push(d);
  sub(vscode.window.onDidChangeActiveTextEditor(() => soon()));
  sub(vscode.window.onDidChangeTextEditorSelection(() => soon()));
  sub(vscode.window.onDidChangeVisibleTextEditors(() => soon(300)));
  sub(vscode.window.onDidChangeWindowState((s) => { if (s.focused) focusedAt = Date.now() / 1000; soon(0); }));
  sub(vscode.workspace.onDidSaveTextDocument(() => soon()));
  sub(vscode.workspace.onDidChangeTextDocument((e) => { // only when "unsaved edits" flips (not every keystroke)
    const ed = vscode.window.activeTextEditor;
    if (!ed || e.document !== ed.document || e.document.isDirty === lastDirty) return;
    lastDirty = e.document.isDirty;
    soon(300);
  }));
  soon(0);
}

function deactivate() {
  try { fs.unlinkSync(FILE); } catch (e) { /* already gone */ }
  if (server) server.close();
}

module.exports = { activate, deactivate };
