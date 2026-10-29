"""todo: the user's to-do list (tasks they have to do), separate from reminders (alerts at a time). Safe, 0 tokens
on the fast path. A to-do never rings; 'remind' adds a linked reminder that is cancelled when the to-do is done."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="todo", safety="safe",
      description="The user's to-do list (tasks to do, with optional due date, priority, tag): add, list, today, done, "
                  "delete, edit, clear. A to-do does not ring; use 'remind' only if the user also wants an alert.")
def todo(action: Literal["add", "list", "today", "done", "delete", "edit", "clear"] = "list", task: str = "",
         item: str = "", due: str = "", tag: str = "", priority: str = "", remind: str = "") -> str:
    """Manage the to-do list.

    Args:
        action: add, list, today (today's to-dos + reminders + classes), done, delete, edit, clear.
        task: The task text (add) or its new name (edit).
        item: Which to-do: its number from the list ("2") or words from it ("report"); for clear: "done" = only finished.
        due: Optional due date/time: "tomorrow", "by Friday", "Nov 28", "Friday 5 pm"; "none" removes it (edit).
        tag: Optional tag, e.g. work, study, shopping.
        priority: high, normal or low.
        remind: Only if the user wants an alert too: when to remind ("Thursday 6 pm", "in 2 hours").
    """
    from jarvis.core import todos

    todos.ensure_migrated()
    if action == "add":
        return todos.add(task, due, tag, priority, remind)
    if action == "today":
        return todos.day()
    if action in ("done", "delete"):
        if not item.strip():
            return f"Which one? Give its number or name.\n{todos.show()}"
        return todos.done(item) if action == "done" else todos.remove(item)
    if action == "edit":
        return todos.edit(item, task, due, tag, priority, remind)
    if action == "clear":
        return todos.clear(done_only=item.strip().lower() in ("done", "finished", "completed"))
    return todos.show(tag)
