"""Markdown made readable in Telegram (owner 11-06: "the .md file with tables is hard to read"):

  to_html(md)     Telegram's HTML: headings and **bold** in bold, `code`, links, "- " lists as "•", code blocks
                  and tables as monospace blocks with the columns lined up (a table reads like a table on a phone)
  chunks(md, n)   the text cut into pieces of at most n characters at line breaks, never inside a code block
  page(md, title) a whole, styled web page (real tables, code boxes, dark/light) for a very long answer: it opens
                  in the phone's browser, much easier than a raw .md file
"""
from __future__ import annotations

import html
import re

_FENCE = re.compile(r"^```")


def _inline(s: str) -> str:
    """One line (already escaped): links, bold, code, italic."""
    s = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", s)
    return s


def _table(rows: list[str]) -> str:
    """'| a | b |' lines -> a monospace block with the columns lined up (the --- line dropped)."""
    cells = [[c.strip().replace("`", "").replace("**", "") for c in r.strip().strip("|").split("|")] for r in rows
             if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", r)]
    if not cells:
        return ""
    n = max(len(r) for r in cells)
    cells = [r + [""] * (n - len(r)) for r in cells]
    width = [min(28, max(len(r[i]) for r in cells)) for i in range(n)]
    out = []
    for k, r in enumerate(cells):
        out.append("  ".join((c if len(c) <= width[i] else c[: width[i] - 1] + "…").ljust(width[i]) for i, c in enumerate(r)).rstrip())
        if k == 0 and len(cells) > 1:
            out.append("  ".join("─" * w for w in width))
    return "<pre>" + html.escape("\n".join(out), quote=False) + "</pre>"


def to_html(md: str) -> str:
    lines = (md or "").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _FENCE.match(ln.strip()):
            lang = ln.strip()[3:].strip().split()[0] if ln.strip()[3:].strip() else ""
            body = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence
            code = html.escape("\n".join(body), quote=False)
            out.append(f'<pre><code class="language-{html.escape(lang)}">{code}</code></pre>' if lang else f"<pre>{code}</pre>")
            continue
        if ln.lstrip().startswith("|") and ln.count("|") >= 2:
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        e = html.escape(ln, quote=False)
        if m := re.match(r"^\s{0,3}#{1,6}\s+(.*)$", e):
            out.append(f"<b>{_inline(m.group(1)).replace('<b>', '').replace('</b>', '')}</b>")
        elif m := re.match(r"^(\s*)[-*+]\s+(.*)$", e):
            out.append(f"{m.group(1)}• {_inline(m.group(2))}")
        elif re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", e):
            out.append("──────────")
        else:
            out.append(_inline(e))
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def chunks(md: str, limit: int) -> list[str]:
    """Pieces of at most `limit` characters, cut at a blank line (else a line break), never inside a code block
    (a code block bigger than the limit is cut at its lines and each piece keeps its fences)."""
    blocks: list[str] = []
    cur: list[str] = []
    in_code = False
    for ln in (md or "").split("\n"):
        cur.append(ln)
        if _FENCE.match(ln.strip()):
            in_code = not in_code
        if not in_code and not ln.strip():
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    out: list[str] = []
    buf = ""
    for b in blocks:
        while len(b) > limit:  # one huge block: by lines, fences re-opened in every piece
            fence = b.lstrip().startswith("```")
            cut = b.rfind("\n", 0, limit - 10)
            if cut > limit // 3:
                head, b = b[:cut], b[cut + 1:]  # at a line break (the break itself dropped)
            else:
                head, b = b[: limit - 10], b[limit - 10:]  # one long line: nothing may be lost
            if fence and not head.rstrip().endswith("```"):
                head += "\n```"
                b = "```\n" + b
            if buf:
                out.append(buf)
                buf = ""
            out.append(head)
        if len(buf) + len(b) + 1 > limit and buf:
            out.append(buf)
            buf = b
        else:
            buf = f"{buf}\n{b}" if buf else b
    if buf.strip():
        out.append(buf)
    return [c.strip("\n") for c in out if c.strip()]


def page(md: str, title: str = "KURAMA") -> str:
    import markdown
    body = markdown.markdown(md or "", extensions=["tables", "fenced_code", "sane_lists"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{color-scheme:light dark}}body{{font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;padding:18px;
max-width:860px;margin-inline:auto;background:#fff;color:#1d1d1f}}@media(prefers-color-scheme:dark){{body{{background:#121317;color:#e8e6e3}}
th,td{{border-color:#333!important}}pre,code{{background:#1e2026!important}}th{{background:#1b1d22!important}}}}
h1,h2,h3{{line-height:1.25}}table{{border-collapse:collapse;width:100%;display:block;overflow-x:auto;margin:12px 0}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top}}th{{background:#f4f4f6}}
pre{{background:#f5f5f7;padding:12px;border-radius:8px;overflow-x:auto}}code{{background:#f5f5f7;padding:1px 4px;border-radius:4px;
font-family:ui-monospace,Menlo,monospace;font-size:.92em}}pre code{{padding:0;background:none}}a{{color:#0a7cff}}
</style></head><body><h1 style="font-size:1.3em">{html.escape(title)}</h1>{body}</body></html>"""
