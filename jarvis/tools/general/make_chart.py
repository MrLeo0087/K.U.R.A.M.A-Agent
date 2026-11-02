"""make_chart: charts (PNG, several views) from my spending, a CSV/Excel/JSON file or a data link; background job (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="image", safety="safe", description="Draw charts (bar, line, pie; several views) from the user's "
      "spending, a CSV/Excel/JSON file or a link to data (e.g. a government data page). Shows in the workspace.")
def make_chart(source: str = "", request: str = "", kind: Literal["auto", "bar", "line", "pie", "all"] = "auto",
               period: Literal["today", "week", "month", "last_month", "year"] = "month") -> str:
    """Charts.

    Args:
        source: 'money' (my spending), a file path, or a URL; empty = money.
        request: The user's words (which columns: 'population by district').
        kind: auto (good views for the data), bar, line, pie, or all.
        period: For money charts.
    """
    from jarvis.core import charts, jobs

    src = (source or "money").strip()
    title = "chart: " + ("my spending" if src == "money" else src.rsplit("/", 1)[-1][:40])

    def job(ctx):
        ctx.progress("reading the data")
        if src == "money":
            paths, what = charts.chart_money(period, kind=kind)
        else:
            head, rows, name = charts.load(src)
            ctx.progress("drawing")
            paths, what = charts.from_table(head, rows, request or src, name, kind)
        if not paths:
            ctx.progress("» " + what)
            return None
        ctx.progress(f"» I drew {len(paths)} chart{'s' if len(paths) > 1 else ''} of {what}. They're in the workspace.")
        return str(paths[0])

    j = jobs.get_manager().submit(title, "chart", job, request or src)
    return f"Drawing the chart now (job #{j.id}). It will appear in the workspace."
