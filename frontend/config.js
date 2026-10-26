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
  mute: true, // the speaker button: true = KURAMA never speaks in this UI (replies stay as text)
  textOnly: false, // the user chose text mode: KURAMA holds no mic at all (no wake word) until talk/mic is chosen
  micMuted: false, // talk mode: the user muted the mic (kept until unmuted)
  wakeListen: true, // talk mode on at start, asleep until "wake up KURAMA"; "sleep now" puts it back to sleep
  lowPower: true, // lean screen (owner: speed first): no animations / blur / shadows, static orb, 5 s status
  lang: "auto", // auto | en | ne | hi
  // Settings -> Voice (the best general values; the user tunes them for their mic/room)
  voice: { sens: 5, pause: 1.0, minMs: 300, ns: true, ec: true, agc: true },
});
export const VOICE_DEFAULTS = DEFAULTS.voice;

export function loadSettings() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { saved = {}; }
  const s = { ...DEFAULTS, ...saved, voice: { ...DEFAULTS.voice, ...(saved.voice || {}) } };
  try {
    const q = new URLSearchParams(location.search).get("api");
    if (q && /^https?:\/\//i.test(q)) { s.apiBase = q.replace(/\/+$/, ""); saveSettings(s); }
    const lp = new URLSearchParams(location.search).get("lowpower");  // ?lowpower=1 (wallpaper mode)
    if (lp !== null && saved.lowPower == null) s.lowPower = lp !== "0"; // only a default: the user's choice wins
    if (!saved.leanV1) { s.lowPower = true; s.leanV1 = true; saveSettings(s); } // once: everyone starts lean
  } catch { /* ignore */ }
  return s;
}

export function saveSettings(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode: settings last for this tab */ }
}
