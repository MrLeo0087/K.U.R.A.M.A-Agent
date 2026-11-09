// KURAMA -> ChatGPT / Gemini / Claude ("ask Gemini why this works", the coding agent's big prompts): KURAMA opens the
// site with #kurama=<id>; this script fetches that prompt from KURAMA (127.0.0.1, through the extension's
// background), types it into the chat box and presses send. A follow-up (&same=1) is sent to the chat tab already
// open instead (background.js finds it and passes the id here).
(() => {
  const EDITORS = ["#prompt-textarea", "rich-textarea .ql-editor", ".ql-editor[contenteditable=true]",
    "div.ProseMirror[contenteditable=true]", "div[contenteditable=true][role=textbox]", "textarea"];
  const SEND = ['button[data-testid="send-button"]', "button.send-button", 'button[aria-label*="Send" i]',
    'button[aria-label*="Submit" i]'];
  const find = (list) => list.map((s) => document.querySelector(s)).find((x) => x && x.offsetParent !== null);

  function send(ed, tries) {
    const b = find(SEND);
    if (b && !b.disabled && b.getAttribute("aria-disabled") !== "true") { b.click(); return; }
    if (tries < 25) { setTimeout(() => send(ed, tries + 1), 300); return; }
    ed.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
  }

  function fill(text, tries) {
    const ed = find(EDITORS);
    if (!ed) { if (tries < 60) setTimeout(() => fill(text, tries + 1), 500); return; } // the app is still loading
    ed.focus();
    if (ed.tagName === "TEXTAREA") {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(ed, text);
      ed.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      document.execCommand("selectAll", false);
      document.execCommand("insertText", false, text);
    }
    setTimeout(() => send(ed, 0), 400);
  }

  const fetchAndFill = (id) => chrome.runtime.sendMessage({ kind: "kurama_prompt", id }, (text) => { if (text) fill(text, 0); });

  // a follow-up passed from background.js (this is the chat tab already open)
  chrome.runtime.onMessage.addListener((msg) => { if (msg && msg.kind === "kurama_fill" && msg.id) fetchAndFill(msg.id); });

  const m = location.hash.match(/kurama=([\w-]+)/);
  if (!m) return;
  const same = /[#&]same=1/.test(location.hash);
  history.replaceState(null, "", location.pathname + location.search); // the id is used once
  if (!same) fetchAndFill(m[1]); // (same=1: background.js decides which tab gets it)
})();
