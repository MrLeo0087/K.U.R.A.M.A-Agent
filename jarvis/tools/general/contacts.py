"""contacts: a name + phone number sheet (Excel, ~/Documents/KURAMA/contacts.xlsx): add, find, list, update, delete (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="memory", safety="safe",
      description="Contacts sheet (Excel): save a person's phone number, find someone's number (fuzzy name or part of "
                  "the number), list all, change a number, or delete a contact.")
def contacts(action: Literal["add", "find", "list", "update", "delete"] = "find", name: str = "", phone: str = "",
             note: str = "") -> str:
    """Contacts.

    Args:
        action: add, find, list, update (new number), delete.
        name: The person's name (or part of a number for find).
        phone: The phone number (add/update).
        note: Optional note, e.g. 'college friend'.
    """
    from jarvis.core import contacts as c
    if action == "list":
        return c.list_all()
    if not name.strip():
        return "error: whose contact?"
    if action == "add":
        return c.add(name, phone, note)
    if action == "update":
        return c.update(name, phone)
    if action == "delete":
        return c.delete(name)
    return c.find(name)
