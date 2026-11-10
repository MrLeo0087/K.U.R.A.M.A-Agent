import time

import httpx

from jarvis.core import fastpath, wifishare


def test_intents_separate_from_telegram():
    assert fastpath.match("send this folder to my phone over wifi").tool == "wifi_share"
    assert fastpath.match("share report.pdf via wifi").args == {"action": "share", "path": "report.pdf"}
    assert fastpath.match("stop wifi share").args["action"] == "stop"
    it = fastpath.match("send me the phone folder")  # (11-10: Telegram only when said; KDE Connect first)
    assert it.tool in ("phone_link", "send_file_telegram") and "phone" in str(it.args).lower()
    assert fastpath.match("send me the phone folder on telegram").tool == "send_file_telegram"


def test_server_token_and_traversal(tmp_path, monkeypatch):
    kv = {}
    monkeypatch.setattr(wifishare.store, "kv_get", lambda k, d=None: kv.get(k, d))
    monkeypatch.setattr(wifishare.store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(wifishare, "lan_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(wifishare, "qr_png", lambda url: None)
    (tmp_path / "a.txt").write_text("hello")
    r = wifishare.start(tmp_path, show_qr=False)
    try:
        for _ in range(30):
            try:
                if httpx.get(r["url"], timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        assert httpx.get(r["url"] + "a.txt").text == "hello"
        assert httpx.get(r["url"].rsplit("/", 2)[0] + "/nope/a.txt").status_code == 404
        assert httpx.get(r["url"] + "..%2F..%2Fetc%2Fpasswd").status_code == 404
        assert httpx.get(r["url"] + "?zip=1").content[:2] == b"PK"
    finally:
        assert "Stopped" in wifishare.stop()
