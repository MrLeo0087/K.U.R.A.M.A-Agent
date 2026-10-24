// Frontend configuration. The UI only talks to the KURAMA API, so it can be served from anywhere:
//  - API_BASE "" = same origin (when the API serves this folder at /).
//  - Override per deployment by defining window.KURAMA_CONFIG = {apiBase: "https://jarvis.example:8000"}
//    in a <script> before app.js, by opening the page with ?api=<url>, or in the settings drawer.
// The optional API token is kept in localStorage (this browser only).

const KEY = "kurama.settings.v1";
const injected = (typeof window !== "undefined" && window.KURAMA_CONFIG) || {};

export const API_BASE = injected.apiBase || "";

export const DEFAULTS = Object.freeze({
  apiBase: API_BASE,
  token: "",
  voiceReplies: true, // speak replies in Mic mode (Conversation mode always speaks)
  mute: false, // the speaker button: true = KURAMA never speaks in this UI (replies stay as text)
  lowPower: null, // null = follow prefers-reduced-motion
  lang: "auto", // auto | en | ne | hi
});

export function loadSettings() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { saved = {}; }
  const s = { ...DEFAULTS, ...saved };
  try {
    const q = new URLSearchParams(location.search).get("api");
    if (q && /^https?:\/\//i.test(q)) { s.apiBase = q.replace(/\/+$/, ""); saveSettings(s); }
    const lp = new URLSearchParams(location.search).get("lowpower");  // ?lowpower=1 (wallpaper mode)
    if (lp !== null) s.lowPower = lp !== "0";
  } catch { /* ignore */ }
  return s;
}

export function saveSettings(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode: settings last for this tab */ }
}
