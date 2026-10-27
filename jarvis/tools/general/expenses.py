"""expenses: money tracker in ~/Documents/KURAMA/expenses.xlsx (add, reports, budgets, bills), 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="tracker", safety="safe", description="Money tracker: add an expense/income ('spent 500 on food'), "
      "report for today/week/month/year (optionally one category), list, delete, edit the last one, set a monthly "
      "budget, add a monthly bill reminder or mark a bill paid.")
def expenses(action: Literal["add", "report", "list", "delete", "edit", "budget", "bill", "pay"] = "report",
             text: str = "", period: Literal["today", "yesterday", "week", "month", "last_month", "year"] = "month",
             category: str = "", amount: float = 0, day: int = 0) -> str:
    """Money tracker.

    Args:
        action: add (text = what was spent/earned), report, list, delete (text = 'last' or row number), edit (text =
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
    if action == "delete":
        return ex.delete(text or "last")
    if action == "edit":
        return ex.edit_last(text)
    if action == "budget":
        return ex.set_budget(category or "total", amount) if amount else "How much should the monthly budget be?"
    if action == "bill":
        return ex.add_bill(text, amount, day) if amount and day else "Tell me the bill, amount and day, e.g. 'internet 1500 on the 5th'."
    if action == "pay":
        return ex.pay_bill(text) or f"I don't have a bill called {text!r}."
    return ex.report(period, category.lower())
