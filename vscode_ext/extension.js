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
    v: 1, pid: process.pid, port, token: TOKEN, ts: Date.now() / 1000,
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

// one request = one operation: text | replace_all | replace_range | replace_text | insert
async function handle(req) {
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
