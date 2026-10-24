"""Internet doctor: the first broken link is named with its fix (network calls faked)."""
from jarvis.core import config, fastpath, netdoctor as nd, registry, safety, store


def fake(monkeypatch, wifi=("connected", 70, "Home"), gw=4.0, net=12.0, dns=8.0, web=90.0):
    monkeypatch.setattr(nd, "wifi", lambda: wifi)
    monkeypatch.setattr(nd, "gateway", lambda: "192.168.1.1")
    monkeypatch.setattr(nd, "ping", lambda host, count=2: gw if host.startswith("192.") else net)
    monkeypatch.setattr(nd, "dns_ok", lambda host="x": dns)
    monkeypatch.setattr(nd, "https_ok", lambda: web)


def verdict(monkeypatch, **kw):
    fake(monkeypatch, **kw)
    return registry.call("internet_doctor", {}).output


def test_each_failure_point(monkeypatch):
    assert verdict(monkeypatch).startswith("The internet looks fine")
    assert verdict(monkeypatch, wifi=("disconnected", None, "")).startswith("Wi-Fi is disconnected")
    assert "can't reach the router" in verdict(monkeypatch, gw=None)
    assert "provider" in verdict(monkeypatch, net=None)
    assert "(DNS) fail" in verdict(monkeypatch, dns=None) and "'fix dns'" in verdict(monkeypatch, dns=None)
    assert "signal is weak (30%)" in verdict(monkeypatch, wifi=("connected", 30, "Home"))
    assert "slow (400 ms" in verdict(monkeypatch, net=400.0)


def test_changes_ask_and_wait_for_internet(monkeypatch):
    calls = []
    monkeypatch.setattr(nd, "reconnect", lambda: calls.append("re") or "Reconnected to Home.")
    assert "said no" in safety.execute("internet_doctor", {"action": "reconnect"}, confirm=lambda p: False).output
    assert safety.execute("internet_doctor", {"action": "reconnect"}, confirm=lambda p: True).output == "Reconnected to Home."
    assert "as soon as the internet is back" in registry.call("internet_doctor", {"action": "notify_when_back"}).output
    monkeypatch.setattr(nd, "ping", lambda host, count=2: None)
    assert nd.check_wait() is False and store.kv_get("net_wait")
    monkeypatch.setattr(nd, "ping", lambda host, count=2: 10.0)
    monkeypatch.setattr(nd, "dns_ok", lambda host="x": 5.0)
    assert nd.check_wait() is True and store.alerts_recent()[0]["title"] == "Internet is back"
    assert nd.check_wait() is False  # once


def test_phrases(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    assert fastpath.match("why is my internet so slow").args == {"action": "check"}
    assert fastpath.match("internet speed test").args == {"action": "speed"}
    assert fastpath.match("tell me when the internet is back").args == {"action": "notify_when_back"}
    assert fastpath.match("turn off wifi").tool == "laptop_toggle"
