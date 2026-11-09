"""Plan 11-09 phase 3 (part 1): a full RAM / disk alert acts: the disk's safe caches are freed at once, the alert
names what it did, and carries buttons (close the biggest app, free RAM, clean ML caches, what fills the disk) that
run as commands when tapped in Telegram."""
from jarvis.core import cleanup, config, notify
from jarvis.workers import resource_guard as rg


def _snap(ram=50.0, disk=50.0):
    return {"ram_pct": ram, "swap_pct": 0, "cpu_pct": 1, "jarvis_core_mb": 100, "jarvis_total_mb": 200,
            "disk": {"/": disk}, "cpu_pct_partial": True}


def test_full_ram_offers_to_close_the_biggest_app(monkeypatch):
    got = {}
    monkeypatch.setattr(rg, "user_apps", lambda n=2: [("brave", 2900.0), ("code", 800.0)])
    monkeypatch.setattr(rg, "top_memory", lambda n=3: [])
    monkeypatch.setattr(notify, "notify", lambda title, text, **k: got.update(text=text, **k))
    rg.ResourceGuard().evaluate(_snap(ram=95))
    taps = [b["callback_data"] for row in got["markup"]["inline_keyboard"] for b in row]
    assert taps == ["/close brave", "/close code", "/freeram"] and "close brave" in got["text"]


def test_full_disk_frees_safe_caches_at_once_and_offers_the_rest(monkeypatch):
    got = {}
    monkeypatch.setattr(rg, "top_memory", lambda n=3: [])
    monkeypatch.setattr(cleanup, "auto_storage", lambda: (3e9, ["pip 2.0 GB", "Trash older than 7 days 1.0 GB"]))
    monkeypatch.setattr(notify, "notify", lambda title, text, **k: got.update(text=text, **k))
    rg.ResourceGuard().evaluate(_snap(disk=97))
    assert "I freed 3.0 GB by myself" in got["text"]
    assert [b["callback_data"] for row in got["markup"]["inline_keyboard"] for b in row] == ["/clean storage", "/disk"]


def test_auto_storage_leaves_ml_models_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "HOME", tmp_path)
    monkeypatch.setattr(cleanup, "kurama", lambda: "KURAMA is already clean")
    for rel in (".cache/pip/x", ".cache/huggingface/hub/model.bin"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"0" * 1000)
    freed, done = cleanup.auto_storage()
    assert freed >= 1000 and not (tmp_path / ".cache/pip").exists() and (tmp_path / ".cache/huggingface/hub/model.bin").exists()


def test_a_tapped_alert_button_runs_its_command(monkeypatch):
    from jarvis.workers import telegram_bot as tb
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notify, "telegram_call", lambda method, body, **k: {})
    bot = tb.TelegramBot.__new__(tb.TelegramBot)
    seen = []
    monkeypatch.setattr(bot, "_note_group", lambda u: None, raising=False)
    monkeypatch.setattr(bot, "_own_message", lambda u: seen.append(u["message"]["text"]) or None, raising=False)
    bot.handle({"callback_query": {"id": "q", "data": "/close brave", "from": {"id": 42},
                                   "message": {"chat": {"id": 42}, "message_id": 5, "text": "alert"}}})
    assert seen == ["/close brave"]
