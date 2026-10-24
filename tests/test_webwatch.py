"""Website watcher: change detection (numbers-only edits ignored), alerts, the tool and phrases (no network)."""
from jarvis.core import config, fastpath, registry, store, webwatch
from jarvis.workers import process_watch as pw

PAGE = ["Exam results 2026", "BSc 1st year: coming soon", "Visitors: 1234", "Updated 10:41"]


def test_changes_ignore_counters_unless_asked():
    new = ["Exam results 2026", "BSc 1st year: coming soon", "Visitors: 1301", "Updated 11:05",
           "BSc 2nd year results published"]
    assert webwatch.changes(PAGE, new) == ["BSc 2nd year results published"]
    assert "Visitors: 1301" in webwatch.changes(PAGE, new, numbers=True)


def test_add_check_alert_and_tool(monkeypatch):
    pages = {"now": list(PAGE)}
    monkeypatch.setattr(webwatch, "page_lines", lambda url, focus="": [ln for ln in pages["now"]
                                                                     if not focus or focus.lower() in ln.lower()])
    out = registry.call("web_watch", {"action": "add", "url": "tu.edu.np/results", "word": "bsc"}).output
    assert "Watching https://tu.edu.np/results" in out and "every 60 min" in out and "1 lines mentioning 'bsc'" in out
    w = pw.ProcessWatcher()
    pages["now"] = PAGE + ["Visitors: 99999"]
    w.tick()
    assert not store.alerts_recent()  # not due yet
    for row in store.watches_list(("active",)):
        row["state"]["checked"] = 0
        store.watch_update(row["id"], state=row["state"])
    pages["now"] = PAGE + ["BSc 2nd year results published (PDF)", "MBA notice"]
    w.tick()
    a = store.alerts_recent()[0]
    assert a["title"] == "Page changed: tu.edu.np (bsc)" and "+ BSc 2nd year results published" in a["text"]
    assert "MBA" not in a["text"] and "https://tu.edu.np/results" in a["text"]
    assert "1 change(s)" in registry.call("web_watch", {}).output
    assert "no change" in registry.call("web_watch", {"action": "check"}).output
    assert "Stopped watching" in registry.call("web_watch", {"action": "stop", "url": "tu.edu"}).output
    assert registry.call("web_watch", {}).output == "No pages are being watched."


def test_unreachable_page_is_reported_once(monkeypatch):
    monkeypatch.setattr(config, "WEBWATCH_FAIL_ALERT", 2)
    monkeypatch.setattr(webwatch, "page_lines", lambda url, focus="": ["ok"])
    webwatch.add("https://example.org")

    def boom(url, focus=""):
        raise OSError("timed out")
    monkeypatch.setattr(webwatch, "page_lines", boom)
    w = next(r for r in store.watches_list(("active",)) if r["kind"] == "web")
    for _ in range(3):
        w["state"]["checked"] = 0
        webwatch.check(w)
    assert [a["title"] for a in store.alerts_recent()] == ["Can't reach example.org"]


def test_phrases(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match("watch tu.edu.np/results for BSc 2nd year")
    assert (it.tool, it.args) == ("web_watch", {"action": "add", "url": "tu.edu.np/results", "word": "BSc 2nd year"})
    it = fastpath.match("keep an eye on https://github.com/pytorch/pytorch/releases")
    assert it.args["url"] == "https://github.com/pytorch/pytorch/releases" and it.args["word"] == ""
