// Slash-command suggestions for the chat box: type "/" and pick a command (0 tokens, no routing).
// The list comes from GET /api/v1/slash (jarvis/core/slash.py), fetched once on the first "/".
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function attachSlash(input, api, form, onChange = () => {}) {
  let cmds = null, loading = false, items = [], sel = 0;
  const pop = document.createElement("div");
  pop.className = "slash-pop";
  pop.setAttribute("role", "listbox");
  pop.hidden = true;
  form.appendChild(pop);

  const close = () => { pop.hidden = true; items = []; };
  const pick = (c) => {
    input.value = "/" + c.cmd + (c.hint ? " " : "");
    close(); input.focus(); onChange();
    if (!c.hint) form.requestSubmit(); // nothing to add: run it now
  };
  const render = () => {
    pop.innerHTML = items.map((c, i) =>
      `<div class="slash-item${i === sel ? " on" : ""}" role="option" data-i="${i}"><b>/${esc(c.cmd)}</b>` +
      `${c.hint ? ` <i>${esc(c.hint)}</i>` : ""}<span>${esc(c.desc)}</span></div>`).join("");
    pop.hidden = !items.length;
  };
  const update = async () => {
    const v = input.value;
    const m = /^\/([\w-]*)$/.exec(v.trimStart());
    if (!m) return close();
    if (!cmds) {
      if (loading) return;
      loading = true;
      try { cmds = (await api.slash()).commands || []; } catch { cmds = null; loading = false; return; }
      loading = false;
    }
    const q = m[1].toLowerCase();
    const starts = cmds.filter((c) => c.cmd.startsWith(q) || (c.aliases || []).some((a) => a.startsWith(q)));
    const inDesc = q ? cmds.filter((c) => !starts.includes(c) && c.desc.toLowerCase().includes(q)) : [];
    items = [...starts, ...inDesc].slice(0, 8);
    sel = 0;
    render();
  };

  input.addEventListener("input", update);
  input.addEventListener("blur", () => setTimeout(close, 150));
  pop.addEventListener("mousedown", (e) => {
    const el = e.target.closest(".slash-item");
    if (el) { e.preventDefault(); pick(items[+el.dataset.i]); }
  });
  // capture phase on the form: runs before the box's own Enter-to-send handler
  form.addEventListener("keydown", (e) => {
    if (pop.hidden || !items.length || e.target !== input) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length; render();
    } else if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
      e.preventDefault(); e.stopPropagation(); pick(items[sel]);
    } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
  }, true);
}
