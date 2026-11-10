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
    body: JSON.stringify({ text: msg.text || "", editable: !!msg.editable, url: msg.url || "", title: msg.title || "",
                           paragraph: msg.paragraph || "", heading: msg.heading || "", page: msg.page || "" }),
  }).catch(() => {});
});

// the coding agent's prompt for ChatGPT / Gemini / Claude (bridge.js asks for it once)
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.kind !== "kurama_prompt") return false;
  fetch("http://127.0.0.1:8000/api/v1/coding/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: msg.id }) }).then((r) => r.json()).then((d) => reply(d.text || "")).catch(() => reply(""));
  return true; // the reply comes later
});

// "ask it simpler" (a follow-up): KURAMA opens <site>#kurama=<id>&same=1 -> the chat tab of that site already open
// gets the prompt (the conversation continues there) and the new tab closes; no open chat -> the new tab gets it.
const followed = new Set();
const waiting = {}; // tab id -> prompt id (no chat open: this new tab gets it once it has loaded)
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (waiting[tabId] && info.status === "complete") {
    chrome.tabs.sendMessage(tabId, { kind: "kurama_fill", id: waiting[tabId] });
    delete waiting[tabId];
    return;
  }
  const m = (tab.url || "").match(/#kurama=([\w-]+)&same=1/);
  if (!m || followed.has(m[1])) return;
  followed.add(m[1]);
  const origin = new URL(tab.url).origin;
  const others = (await chrome.tabs.query({})).filter((t) => t.id !== tabId && (t.url || "").startsWith(origin));
  if (!others.length) {
    if (tab.status === "complete") chrome.tabs.sendMessage(tabId, { kind: "kurama_fill", id: m[1] });
    else waiting[tabId] = m[1];
    return;
  }
  const old = others.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
  await chrome.tabs.update(old.id, { active: true });
  await chrome.windows.update(old.windowId, { focused: true });
  chrome.tabs.remove(tabId);
  chrome.tabs.sendMessage(old.id, { kind: "kurama_fill", id: m[1] });
});
