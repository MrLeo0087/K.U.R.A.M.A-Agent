// KURAMA tab link: the text you highlight on a page goes to KURAMA on this laptop (via the extension's background,
// 127.0.0.1 only), so "explain this" / "translate this" / "summarize this paragraph" know it exactly.
let timer = null;
let last = "";

function editable() { // can the page take a replacement here (a text box / an editable area)?
  const el = document.activeElement;
  return !!el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || el.isContentEditable);
}

function selected() {
  const el = document.activeElement;
  if (el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && /^(text|search|url|email)$/i.test(el.type || "text")))) {
    try { return el.value.slice(el.selectionStart, el.selectionEnd); } catch (e) { return ""; }
  }
  return String(window.getSelection() || "");
}

// Study mode context (0 tokens): the paragraph the highlight sits in, the heading above it, and once per page its
// main text (KURAMA summarizes a page once and caches it), so "explain this" answers in the page's own context.
const BLOCK = "p,li,td,th,pre,blockquote,dd,dt,figcaption,h1,h2,h3,h4,h5,h6,section,article,div";
let pageSent = "";

function around() {
  const s = window.getSelection();
  if (!s || !s.rangeCount) return { paragraph: "", heading: "" };
  let n = s.getRangeAt(0).commonAncestorContainer;
  if (n.nodeType !== 1) n = n.parentElement;
  const block = n && n.closest ? n.closest(BLOCK) : null;
  const paragraph = block ? (block.innerText || "").trim().slice(0, 1500) : "";
  let heading = "";
  if (block) { // the nearest heading before the block, in page order
    const all = Array.from(document.querySelectorAll("h1,h2,h3,h4"));
    for (const h of all) {
      if (h.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING || h.contains(block)) heading = (h.innerText || "").trim();
      else break;
    }
  }
  return { paragraph, heading: heading.slice(0, 200) };
}

function pageText() {
  const main = document.querySelector("main, article, [role=main]") || document.body;
  return (main ? main.innerText || "" : "").replace(/\n{3,}/g, "\n\n").slice(0, 15000);
}

function send() {
  timer = null;
  const text = selected().slice(0, 8000);
  if (text === last) return;
  last = text;
  const msg = { kind: "selection", text, editable: editable(), url: location.href, title: document.title };
  if (text.trim()) {
    Object.assign(msg, around());
    if (pageSent !== location.href) { msg.page = pageText(); pageSent = location.href; }
  }
  try { chrome.runtime.sendMessage(msg); } catch (e) { /* extension reloaded */ }
}

if (!/^(127\.0\.0\.1|localhost):8000$/.test(location.host)) { // KURAMA's own page never counts
  document.addEventListener("selectionchange", () => { clearTimeout(timer); timer = setTimeout(send, 350); });
}
