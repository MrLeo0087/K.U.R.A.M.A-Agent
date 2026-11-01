// KURAMA tab link: sends the active tab's address and title to KURAMA on this laptop (127.0.0.1) and nowhere else.
const API = "http://127.0.0.1:8000/api/v1/context/tab";
let last = "";

function send(url, title, tabs = []) {
  const body = JSON.stringify({ url: url || "", title: title || "", tabs,
                                browser: navigator.userAgent.includes("Brave") ? "brave" : "chromium" });
  if (body === last) return;
  last = body;
  fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body }).catch(() => { last = ""; });
}

async function report() {
  // the active tab + every tab of that window (position, title, site): "switch to the Facebook tab" picks by name
  const all = await chrome.tabs.query({ lastFocusedWindow: true });
  const tab = all.find((t) => t.active);
  const tabs = all.map((t) => ({ i: t.index + 1, title: (t.title || "").slice(0, 120), url: (t.url || "").slice(0, 300) }));
  if (tab) send(tab.url, tab.title, tabs);
}

chrome.tabs.onActivated.addListener(report);
chrome.tabs.onUpdated.addListener((_id, info) => { if (info.url || info.title) report(); });
chrome.tabs.onCreated.addListener(report);
chrome.tabs.onRemoved.addListener(report);
chrome.tabs.onMoved.addListener(report);
chrome.windows.onFocusChanged.addListener((w) => { if (w !== chrome.windows.WINDOW_ID_NONE) report(); });
chrome.windows.onRemoved.addListener(async () => { if (!(await chrome.windows.getAll()).length) send("", ""); });
chrome.runtime.onStartup.addListener(report);
chrome.runtime.onInstalled.addListener(report);

// the highlighted text from a page (selection.js): passed on to KURAMA as it is
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.kind !== "selection" || !sender.tab) return;
  fetch("http://127.0.0.1:8000/api/v1/context/selection", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: msg.text || "", editable: !!msg.editable, url: msg.url || "", title: msg.title || "" }),
  }).catch(() => {});
});

// the coding agent's prompt for ChatGPT / Gemini / Claude (bridge.js asks for it once)
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.kind !== "kurama_prompt") return false;
  fetch("http://127.0.0.1:8000/api/v1/coding/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: msg.id }) }).then((r) => r.json()).then((d) => reply(d.text || "")).catch(() => reply(""));
  return true; // the reply comes later
});
