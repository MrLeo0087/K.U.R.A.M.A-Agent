// The Progress section (main window card + mini window panel): everything running now, each with its own bar —
// background jobs (writing, downloads, file sends, images, scans), the coding agent's plan as a checklist, the
// music playing — and what just finished (shown for a minute). One request every 2 s while something runs, every
// 6 s when idle, none while the page is hidden. Buttons: pause / continue / cancel (cancel needs a second click);
// music: pause / continue / next / stop.

const ICON = {
  music: '<path d="M9 18V6l10-2v12"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="16" r="2"/>',
  code: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12"/>',
  coding: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  write: '<path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4"/>',
  image: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 16l5-5 4 4 3-3 4 4"/>',
  tool: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
};
const PATH = {
  pause: '<path d="M9 5v14M15 5v14"/>', play: '<path d="M8 5l11 7-11 7z"/>', next: '<path d="M6 5l9 7-9 7zM18 5v14"/>',
  prev: '<path d="M18 5l-9 7 9 7zM6 5v14"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>', x: '<path d="M7 7l10 10M17 7L7 17"/>',
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const kindIcon = (it) => ICON[it.kind] || (/image|picture/i.test(it.title) ? ICON.image : /download|video/i.test(it.title) ? ICON.download
  : /essay|write|document/i.test(it.title) ? ICON.write : ICON.tool);
const btn = (act, label, d, cls = "") => `<button type="button" class="pg-b ${cls}" data-act="${act}" title="${label}" aria-label="${label}">${svg(d)}</button>`;

function row(it) {
  const ended = ["done", "failed", "cancelled", "stopped"].includes(it.status);
  const pct = it.frac != null ? Math.round(it.frac * 100) + "%" : "";
  const state = it.status === "done" ? "Done" : it.status === "failed" ? "Failed" : it.status === "cancelled" ? "Cancelled"
    : it.status === "paused" ? "Paused" : it.status === "queued" ? "Waiting" : it.status === "playing" ? "Playing" : pct || "Working";
  let acts = "";
  if (it.kind === "music") {
    acts = (it.has_prev ? btn("m-previous", "Previous song", PATH.prev) : "")
      + (it.status === "paused" ? btn("m-resume", "Continue", PATH.play) : btn("m-pause", "Pause", PATH.pause))
      + btn("m-next", "Next song", PATH.next) + btn("m-stop", "Stop the music", PATH.stop)
      + `<input type="range" class="pg-vol" min="0" max="150" step="5" value="${+it.volume || 100}" title="Music volume ${+it.volume || 100}% (over 100 = boost)" aria-label="Music volume">`;
  } else if (!ended && it.job) {
    if (it.kind === "long") acts += it.status === "paused" ? btn("resume", "Continue", PATH.play) : btn("pause", "Pause", PATH.pause);
    acts += btn("cancel", "Cancel (click twice)", PATH.x, "x");
  } else if (ended && it.job) {
    acts += btn("remove", "Remove from the list", PATH.x, "x");
  }
  const steps = (it.steps || []).length ? `<ol class="pg-steps">${it.steps.map((s) =>
    `<li class="${esc(s.state)}">${esc(s.text)}</li>`).join("")}</ol>` : "";
  return `<div class="pg-it ${esc(it.status)}" data-id="${esc(it.id)}"${it.job ? ` data-job="${it.job}"` : ""}>
    <div class="pg-top"><span class="pg-ic">${svg(kindIcon(it))}</span>
      <b class="pg-t" title="${esc(it.title)}">${esc(it.title)}</b>
      <span class="pg-s">${esc(it.status === "running" && pct ? pct : state)}${it.when ? " · " + esc(it.when) : ""}</span>${acts}</div>
    <i class="pg-bar${it.frac == null && !ended ? " ind" : ""}${it.kind === "music" && it.dur ? " seek" : ""}"${it.kind === "music" && it.dur ? ` data-dur="${it.dur}" title="Tap to jump there"` : ""} style="--f:${ended ? 1 : it.frac ?? 0.3}"></i>
    ${it.detail ? `<div class="pg-d" title="${esc(it.detail)}">${esc(it.detail)}${it.count ? " · " + esc(it.count) : ""}</div>` : ""}
    ${steps}</div>`;
}

/** Draw and keep up to date. box: the list element; card: shown only while something runs (or null); onChange:
 *  called with the number of items (a count pill). */
export function startProgress(api, box, { card = null, max = 20, onChange = null } = {}) {
  let key = "", armed = "", timer = 0, sliding = false;
  const poll = async () => {
    clearTimeout(timer);
    let n = 0;
    if (!document.hidden) {
      try {
        const items = ((await api.progress()).items || []).slice(0, max);
        n = items.filter((x) => !["done", "failed", "cancelled", "stopped"].includes(x.status)).length;
        const k = JSON.stringify(items);
        if (k !== key && !sliding) { // (not while the volume slider is held: a redraw drops it)
          key = k;
          const live = items.filter((x) => !["done", "failed", "cancelled", "stopped"].includes(x.status));
          const past = items.filter((x) => ["done", "failed", "cancelled", "stopped"].includes(x.status));
          box.innerHTML = (live.length ? live.map(row).join("") : '<p class="pg-none">Nothing running right now.</p>')
            + (past.length ? '<div class="pg-hist">Finished<button type="button" class="pg-clear" data-act="clear-all">Clear all</button></div>' + past.map(row).join("") : "");
          if (card) card.hidden = !items.length;
          onChange?.(n, items.length);
        }
      } catch { /* offline: keep the last view */ }
    }
    timer = setTimeout(poll, n ? 2000 : 6000);
  };
  box.addEventListener("pointerdown", (e) => { if (e.target.matches(".pg-vol")) sliding = true; });
  document.addEventListener("pointerup", () => { sliding = false; });
  box.addEventListener("change", async (e) => { // the music volume slider (only on release: one request)
    if (!e.target.matches(".pg-vol")) return;
    sliding = false;
    try { await api.musicControl("volume", e.target.value); } catch { /* the next poll shows the truth */ }
    key = ""; poll();
  });
  box.addEventListener("click", async (e) => {
    const bar = e.target.closest(".pg-bar.seek"); // the music bar: jump to where you tap
    if (bar) {
      const r = bar.getBoundingClientRect(), at = Math.round(((e.clientX - r.left) / r.width) * +bar.dataset.dur);
      try { await api.musicControl("seek", String(Math.max(0, at))); } catch { /* the next poll shows the truth */ }
      key = ""; poll();
      return;
    }
    const b = e.target.closest("[data-act]");
    if (!b || e.target.matches(".pg-vol")) return;
    if (b.dataset.act === "clear-all") {
      try { await api.progressHide(); } catch { /* the next poll shows the truth */ }
      key = ""; poll();
      return;
    }
    const it = b.closest(".pg-it"), act = b.dataset.act, job = +it.dataset.job;
    if (act === "cancel" && armed !== it.dataset.id) {
      armed = it.dataset.id; b.classList.add("armed");
      setTimeout(() => { armed = ""; b.classList.remove("armed"); }, 3000);
      return;
    }
    armed = "";
    try {
      if (act === "remove") { it.remove(); await api.progressHide(job); }
      else if (act.startsWith("m-")) await api.musicControl(act.slice(2));
      else await (act === "cancel" ? api.cancelJob(job) : act === "pause" ? api.pauseJob(job) : api.resumeJob(job));
    } catch { /* the next poll shows the truth */ }
    key = ""; poll();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { key = ""; poll(); } });
  poll();
  return { refresh: () => { key = ""; poll(); } };
}
