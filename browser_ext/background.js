// KURAMA tab link: sends the active tab's address and title to KURAMA on this laptop (127.0.0.1) and nowhere else.
const API = "http://127.0.0.1:8000/api/v1/context/tab";
let last = "";

function send(url, title) {
  const body = JSON.stringify({ url: url || "", title: title || "", browser: navigator.userAgent.includes("Brave") ? "brave" : "chromium" });
  if (body === last) return;
  last = body;
  fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body }).catch(() => { last = ""; });
}

async function report() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (tab) send(tab.url, tab.title);
}

chrome.tabs.onActivated.addListener(report);
chrome.tabs.onUpdated.addListener((_id, info, tab) => { if (tab.active && (info.url || info.title)) report(); });
chrome.windows.onFocusChanged.addListener((w) => { if (w !== chrome.windows.WINDOW_ID_NONE) report(); });
chrome.windows.onRemoved.addListener(async () => { if (!(await chrome.windows.getAll()).length) send("", ""); });
chrome.runtime.onStartup.addListener(report);
chrome.runtime.onInstalled.addListener(report);
