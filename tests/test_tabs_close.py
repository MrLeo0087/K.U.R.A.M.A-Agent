"""Closing several browser tabs (11-06: 'close 1,2,3 tabs' only switched; 'close all and keep YouTube' closed Brave)."""
from __future__ import annotations

from jarvis.core import uiagent as ui

TABS = [{"i": 1, "title": "nchat", "url": "https://nchat.com"},
        {"i": 2, "title": "Tara Assistant", "url": "https://tara.app"},
        {"i": 3, "title": "(2) Beat Professional Athlete - YouTube", "url": "https://www.youtube.com/watch?v=1"},
        {"i": 4, "title": "Baththa movie - Brave Search", "url": "https://search.brave.com/x"},
        {"i": 5, "title": "Claude", "url": "https://claude.ai"},
        {"i": 6, "title": "YouTube", "url": "https://www.youtube.com/"}]


def test_which_tabs():
    assert ui.tabs_to_close("1,2,3,4,5", TABS) == [5, 4, 3, 2, 1]  # highest first: numbers never shift
    assert ui.tabs_to_close("first second third and fourth", TABS) == [4, 3, 2, 1]
    assert ui.tabs_to_close("1-3", TABS) == [3, 2, 1]
    assert ui.tabs_to_close("all except last", TABS) == [5, 4, 3, 2, 1]
    assert ui.tabs_to_close("all except 6", TABS) == [5, 4, 3, 2, 1]
    assert ui.tabs_to_close("keep youtube", TABS) == [5, 4, 2, 1]
    assert ui.tabs_to_close("all except youtube", TABS) == [5, 4, 2, 1]
    assert ui.tabs_to_close("others", TABS, current=2) == [6, 5, 4, 3, 1]
    assert ui.tabs_to_close("9", TABS).startswith("There are only 6")
    assert ui.tabs_to_close("keep facebook", TABS).startswith("No open tab matches")
    assert ui.tabs_to_close("all", TABS) == "all"


def test_close_tabs_presses_keys_and_never_closes_everything(monkeypatch):
    from jarvis.core import browsertab
    keys = []
    monkeypatch.setattr(ui, "_need", lambda: None)
    monkeypatch.setattr(ui, "family", lambda c: "browser")
    monkeypatch.setattr(ui, "active_class", lambda: "brave")
    monkeypatch.setattr(ui, "shortcut", lambda a, n=0, app="", times=1: keys.append(("tab", n)) or "Switched")
    monkeypatch.setattr(ui, "key", lambda combo, times=1: keys.append(combo))
    monkeypatch.setattr(ui.time, "sleep", lambda s: None)
    monkeypatch.setattr(browsertab, "tabs", lambda: TABS)
    out = ui.close_tabs("1,2")
    assert out.startswith("Closed 2 tabs") and keys == [("tab", 2), "ctrl+w", ("tab", 1), "ctrl+w"]
    keys.clear()
    from jarvis.core import safety
    monkeypatch.setattr(safety, "context", lambda: {"request": "close all the tabs and only keep YouTube"})
    assert "keep some tabs" in ui.close_tabs("all") and keys == []
