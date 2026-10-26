import shutil
import subprocess

import pytest

from jarvis.core import config, fastpath, qr

needs = pytest.mark.skipif(not shutil.which("qrencode"), reason="qrencode not installed")


def _qr(path, text):
    subprocess.run(["qrencode", "-s", "6", "-o", str(path), text], check=True)
    return path


@pytest.fixture
def copied(monkeypatch):
    got = []
    monkeypatch.setattr(qr, "_copy", got.append)
    return got


@needs
def test_link_is_shown_and_copied_not_opened(tmp_path, copied, monkeypatch):
    from jarvis.tools.general import open_url
    opened = []
    monkeypatch.setattr(open_url, "_open", opened.append)
    p = _qr(tmp_path / "q.png", "https://example.com/menu")
    out = qr.run("file", str(p))
    assert out.startswith("Link: https://example.com/menu") and copied == ["https://example.com/menu"] and not opened
    assert qr.run("file", str(p), open_link=True) == "Opened https://example.com/menu" and opened


@needs
def test_wifi_password_goes_to_clipboard_only(tmp_path, copied, monkeypatch):
    p = _qr(tmp_path / "w.png", r"WIFI:T:WPA;S:Home\;Net;P:se:cret;;")
    out = qr.run("file", str(p))
    assert "Home;Net" in out and "se:cret" not in out and copied == ["se:cret"]
    calls = []
    monkeypatch.setattr(qr.shutil, "which", lambda n: "/usr/bin/nmcli")
    monkeypatch.setattr(qr.subprocess, "run", lambda a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    assert qr.run("file", str(p), connect=True) == "Connected to the Wi-Fi 'Home;Net'."
    assert calls[0][:5] == ["nmcli", "dev", "wifi", "connect", "Home;Net"]


def test_no_code(tmp_path, copied):
    from PIL import Image
    p = tmp_path / "blank.png"
    Image.new("RGB", (200, 200), "white").save(p)
    assert "don't see a QR code" in qr.run("file", str(p))


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    a = lambda t: (fastpath.match(t).tool, fastpath.match(t).args)
    assert a("scan the qr code on my screen") == ("scan_qr", {"source": "screen"})
    assert a("scan the qr and open it")[1]["open_link"] is True
    assert a("scan the wifi qr and connect")[1]["connect"] is True
    assert a("scan the qr in this photo")[1] == {"source": "file", "path": "this"}
    assert a("share wifi")[0] == "share_wifi"
    assert (fastpath.match("make a qr code of this link") or fastpath.Intent("", "", "", {})).tool != "text_assist"
