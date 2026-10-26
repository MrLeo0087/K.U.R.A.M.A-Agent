// Thin client for the KURAMA API (/api/v1/*). Everything the UI does goes through here.

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export class Api {
  constructor(getSettings) { this.get = getSettings; }

  base() { return (this.get().apiBase || "").trim().replace(/\/+$/, ""); }
  token() { return (this.get().token || "").trim(); }

  url(path, withToken = false) {
    let u = this.base() + path;
    if (withToken && this.token()) u += (u.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(this.token());
    return u;
  }

  headers(extra = {}) {
    const h = { ...extra };
    if (this.token()) h.Authorization = "Bearer " + this.token();
    return h;
  }

  async request(path, { method = "GET", body, headers = {}, signal, raw = false } = {}) {
    const init = { method, signal, headers: this.headers(headers) };
    if (body !== undefined) {
      if (body instanceof Blob) { init.body = body; }
      else { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
    }
    const r = await fetch(this.url(path), init);
    if (!r.ok) {
      let msg = r.statusText;
      try { msg = (await r.json()).error || msg; } catch { /* not json */ }
      throw new ApiError(r.status, msg || `HTTP ${r.status}`);
    }
    return raw ? r : r.json();
  }

  health() { return this.request("/api/v1/health"); }
  status() { return this.request("/api/v1/status"); }
  confirm(id, yes) { return this.request("/api/v1/confirm", { method: "POST", body: { id, yes } }); }
  tools() { return this.request("/api/v1/tools"); }
  profile() { return this.request("/api/v1/profile"); }
  jobs() { return this.request("/api/v1/jobs?limit=20"); }
  fetchWeather() { return this.request("/api/v1/weather"); }
  device() { return this.request("/api/v1/device"); }
  greeting() { return this.request("/api/v1/greeting"); }
  schedule() { return this.request("/api/v1/schedule"); }
  cancelSchedule(id) { return this.request(`/api/v1/schedule/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  stopwatch(action) { return this.request(`/api/v1/stopwatch/${action}`, { method: "POST", body: {} }); }
  wakeSleep() { return this.request("/api/v1/wake/sleep", { method: "POST", body: {} }); }
  deviceSound() { return this.request("/api/v1/voice/device-sound"); }
  setDeviceSound(hear) { return this.request("/api/v1/voice/device-sound", { method: "POST", body: { hear } }); }
  wakeAwake() { return this.request("/api/v1/wake/awake", { method: "POST", body: {} }); }
  wakeEvents() { return new EventSource(this.url("/api/v1/wake/events", true)); }
  powerOff() { return this.request("/api/v1/power/off", { method: "POST", body: {} }); }
  identity() { return this.request("/api/v1/identity"); }
  setName(name) { return this.request("/api/v1/identity", { method: "POST", body: { name } }); }
  wallpaperInfo() { return this.request("/api/v1/wallpaper/info"); }
  wallpaperUrl(v) { return this.url(`/api/v1/wallpaper?v=${encodeURIComponent(v)}`, true); }
  outputs(limit = 12) { return this.request(`/api/v1/outputs?limit=${limit}`); }
  resources() { return this.request("/api/v1/resources"); }
  setResources(mode) { return this.request("/api/v1/resources", { method: "POST", body: { semantic_mode: mode } }); }
  freeModel() { return this.request("/api/v1/resources/free", { method: "POST", body: {} }); }
  deleteOutput(name) { return this.request("/api/v1/outputs/delete", { method: "POST", body: { name } }); }
  clearOutputs() { return this.request("/api/v1/outputs/clear", { method: "POST", body: {} }); }
  outputUrl(name) { return this.url(`/api/v1/outputs/file?name=${encodeURIComponent(name)}`, true); }
  cancelJob(id) { return this.request(`/api/v1/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: {} }); }
  alerts() { return this.request("/api/v1/alerts?limit=20"); }
  alertsRead() { return this.request("/api/v1/alerts/read", { method: "POST", body: {} }); }
  dashboard() { return this.request("/api/v1/dashboard"); }
  detail(panel) { return this.request(`/api/v1/dashboard/detail/${encodeURIComponent(panel)}`); }
  weatherFull() { return this.request("/api/v1/weather/full"); }
  action(body) { return this.request("/api/v1/action", { method: "POST", body }); }
  sendLocation(body) { return this.request("/api/v1/location", { method: "POST", body }); }
  reset(level) { return this.request("/api/v1/reset", { method: "POST", body: { level } }); }

  async stt(blob, lang) {
    const type = (blob.type || "audio/webm").split(";")[0];
    const q = lang && lang !== "auto" ? `?lang=${encodeURIComponent(lang)}` : "";
    return this.request("/api/v1/stt" + q, { method: "POST", body: new Blob([blob], { type }), headers: { "Content-Type": type } });
  }

  async tts(text, lang, signal) {
    const body = { text };
    if (lang && lang !== "auto") body.lang = lang;
    const r = await this.request("/api/v1/tts", { method: "POST", body, signal, raw: true });
    return r.arrayBuffer();
  }

  statusStream() { return new EventSource(this.url("/api/v1/status/stream", true)); }

  // POST /chat and yield the parsed SSE events.
  async *chat(text, { mode = "text", lang = null, signal, ambient = false } = {}) {
    const body = { text, mode };
    if (ambient) body.ambient = true;
    if (lang && lang !== "auto") body.lang = lang;
    const r = await this.request("/api/v1/chat", { method: "POST", body, signal, raw: true });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let m;
        while ((m = buf.match(/\r?\n\r?\n/))) {
          const block = buf.slice(0, m.index);
          buf = buf.slice(m.index + m[0].length);
          const data = block.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
          if (data) { try { yield JSON.parse(data); } catch { /* skip malformed */ } }
        }
      }
    } finally {
      try { await reader.cancel(); } catch { /* already closed */ }
    }
  }
}
