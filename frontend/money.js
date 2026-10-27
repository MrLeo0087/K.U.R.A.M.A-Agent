// The Money window (click the Money & habits card): pick a date or a range (and a category), see every expense
// in it, totals by category against the budget, and delete a wrong row. Data: GET /api/v1/money/range.
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function openMoney(api, { esc, toast, onChange = () => {} }) {
  let dlg = document.getElementById("money-dlg");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "money-dlg";
    dlg.className = "modal mdlg";
    dlg.innerHTML = `<div class="mdlg-head"><h2>Money</h2><button type="button" class="icon-btn" data-x aria-label="Close">&#215;</button></div>
      <div class="mdlg-filters">
        <label>From <input type="date" id="md-from"></label>
        <label>To <input type="date" id="md-to" title="Leave empty for one day"></label>
        <label>Category <select id="md-cat"><option value="">All</option></select></label>
      </div>
      <div class="mdlg-quick">
        <button type="button" class="chip" data-q="today">Today</button><button type="button" class="chip" data-q="yesterday">Yesterday</button>
        <button type="button" class="chip" data-q="week">This week</button><button type="button" class="chip" data-q="month">This month</button>
        <button type="button" class="chip" data-q="last30">Last 30 days</button><button type="button" class="chip" data-q="year">This year</button>
      </div>
      <div id="md-sum" class="mdlg-sum"></div>
      <div id="md-by" class="mdlg-by"></div>
      <ul id="md-rows" class="mdlg-rows"></ul>`;
    document.body.append(dlg);
    dlg.querySelector("[data-x]").onclick = () => dlg.close();
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
    for (const id of ["md-from", "md-to", "md-cat"]) dlg.querySelector("#" + id).addEventListener("change", () => load());
    dlg.querySelector(".mdlg-quick").addEventListener("click", (e) => {
      const q = e.target.closest("[data-q]")?.dataset.q;
      if (!q) return;
      const t = new Date(), a = new Date(t);
      if (q === "yesterday") { a.setDate(t.getDate() - 1); set(a, a); return load(); }
      if (q === "week") a.setDate(t.getDate() - ((t.getDay() + 6) % 7));
      if (q === "month") a.setDate(1);
      if (q === "last30") a.setDate(t.getDate() - 29);
      if (q === "year") { a.setMonth(0); a.setDate(1); }
      set(a, q === "today" ? null : t);
      load();
    });
    dlg.querySelector("#md-rows").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-del]");
      if (!b || !confirm("Delete this expense?")) return;
      b.disabled = true;
      try { toast((await api.tracker("expense_delete", b.dataset.del)).text); } catch { toast("Couldn't delete it right now."); }
      load(); onChange();
    });
  }
  const $ = (id) => dlg.querySelector("#" + id);
  function set(a, z) { $("md-from").value = iso(a); $("md-to").value = z ? iso(z) : ""; }
  async function load() {
    if (!$("md-from").value) return;
    let d;
    try { d = await api.moneyRange($("md-from").value, $("md-to").value, $("md-cat").value); } catch { $("md-sum").textContent = "Couldn't load the money data."; return; }
    if (d.error) { $("md-sum").textContent = d.error; return; }
    const cur = d.currency || "Rs", amt = (v) => `${cur} ${Math.round(v || 0).toLocaleString("en-IN")}`;
    const sel = $("md-cat");
    if (sel.options.length === 1) for (const c of d.categories || []) sel.append(new Option(c, c));
    $("md-sum").innerHTML = `<b>${amt(d.total)}</b> spent ${esc(d.words)}${d.category ? ` on ${esc(d.category)}` : ""}`
      + (d.income ? ` · income ${amt(d.income)}` : "") + ` · ${d.rows.length} entr${d.rows.length === 1 ? "y" : "ies"}`;
    const top = Math.max(1, ...d.by.map((x) => x.amount));
    $("md-by").innerHTML = d.by.map((x) => `<div class="mby"><span>${esc(x.cat)}</span><i><b style="width:${Math.round(x.amount / top * 100)}%"></b></i>
      <em>${amt(x.amount)}${x.budget ? ` <small>/ ${amt(x.budget)}</small>` : ""}</em></div>`).join("");
    $("md-rows").innerHTML = d.rows.length ? d.rows.map((r) => `<li class="${r.type}"><span class="md-d">${esc(r.date.slice(5))}</span>
      <span class="ell">${esc(r.note || r.category)} <small>${esc(r.category)}</small></span><b>${r.type === "income" ? "+" : ""}${amt(r.amount)}</b>
      <button type="button" class="tb" data-del="${r.row}" title="Delete" aria-label="Delete">✕</button></li>`).join("")
      : `<li class="empty">Nothing recorded ${esc(d.words)}.</li>`;
  }
  if (!$("md-from").value) { const t = new Date(), a = new Date(t); a.setDate(1); set(a, t); }
  if (!dlg.open) dlg.showModal();
  load();
}
