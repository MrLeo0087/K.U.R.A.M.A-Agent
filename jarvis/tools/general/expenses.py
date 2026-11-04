"""expenses: money tracker in ~/Documents/KURAMA/expenses.xlsx (add, reports, budgets, bills), 0 tokens (safe)."""
from __future__ import annotations

import re

from typing import Literal

from jarvis.core.registry import tool


@tool(group="tracker", safety="safe", description="Money tracker: add an expense/income ('spent 500 on food'), "
      "report for today/week/month/year (optionally one category), breakdown by every category, list, delete, edit the last one, set a monthly "
      "budget, add a monthly bill reminder or mark a bill paid.")
def expenses(action: Literal["add", "report", "breakdown", "list", "delete", "edit", "budget", "bill", "pay"] = "report",
             text: str = "", period: Literal["today", "yesterday", "week", "month", "last_month", "year"] = "month",
             category: str = "", amount: float = 0, day: int = 0) -> str:
    """Money tracker.

    Args:
        action: add (text = what was spent/earned), report, breakdown (every category + budgets + totals), list, delete (text = 'last' or row number), edit (text =
            the change to the last one), budget (category + amount; category 'total' = whole month), bill (text = name,
            amount, day of month), pay (text = the bill name).
        text: The user's words for add / delete / edit / bill / pay.
        period: For report and list.
        category: For report (one category) or budget.
        amount: For budget or bill.
        day: Day of the month for a bill.
    """
    from jarvis.core import expenses as ex

    if action == "add":
        return ex.add(text)
    if action == "list":
        return ex.list_text(period)
    if action == "breakdown":
        return ex.breakdown(period)
    if action == "delete":
        return ex.delete(text or "last")
    if action == "edit":
        return ex.edit_last(text)
    if action == "budget":
        if not amount:  # the model put '2000' in text or category ('set my budget to 2000' asked twice, 11-04)
            m = re.search(r"\d[\d,]*(?:\.\d+)?\s*k?\b", f"{text} {category}", re.I)
            if m:
                v = m.group(0).replace(",", "").strip().lower()
                amount = float(v[:-1]) * 1000 if v.endswith("k") else float(v)
                category = re.sub(r"\d[\d,]*(?:\.\d+)?\s*k?\b", "", category, flags=re.I).strip()
                if not category:  # 'clothes 500' in text: the words left are the category ('set the budget of
                    rest = re.sub(r"\d[\d,]*(?:\.\d+)?\s*k?\b|\b(?:rs|npr|rupees?|for|of|to|the|budget|my|this|month)\b", " ",
                                  text, flags=re.I).strip()  # clothes to 500' set the TOTAL, 11-04)
                    category = rest if rest and ex.resolve_category(rest) else ""
        return ex.set_budget(ex.resolve_category(category) or category or "total", amount) if amount else "How much should the monthly budget be?"
    if action == "bill":
        return ex.add_bill(text, amount, day) if amount and day else "Tell me the bill, amount and day, e.g. 'internet 1500 on the 5th'."
    if action == "pay":
        return ex.pay_bill(text) or f"I don't have a bill called {text!r}."
    return ex.report(period, ex.resolve_category(category))
