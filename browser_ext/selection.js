// KURAMA tab link: the text you highlight on a page goes to KURAMA on this laptop (via the extension's background,
// 127.0.0.1 only), so "explain this" / "translate this" / "summarize this paragraph" know it exactly.
let timer = null;
let last = "";

function selected() {
  const el = document.activeElement;
  if (el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && /^(text|search|url|email)$/i.test(el.type || "text")))) {
    try { return el.value.slice(el.selectionStart, el.selectionEnd); } catch (e) { return ""; }
  }
  return String(window.getSelection() || "");
}

function send() {
  timer = null;
  const text = selected().slice(0, 8000);
  if (text === last) return;
  last = text;
  try { chrome.runtime.sendMessage({ kind: "selection", text, url: location.href, title: document.title }); } catch (e) { /* extension reloaded */ }
}

if (!/^(127\.0\.0\.1|localhost):8000$/.test(location.host)) { // KURAMA's own page never counts
  document.addEventListener("selectionchange", () => { clearTimeout(timer); timer = setTimeout(send, 350); });
}
