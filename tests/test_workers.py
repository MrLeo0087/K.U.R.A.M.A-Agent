"""P6 background core: worker base, supervisor, notify, process/log watcher, crash watchdog, resource guard,
Telegram remote control. Everything mocked: no network, no real processes started."""
import json
import logging
import threading
import time
import urllib.request

import psutil
import pytest

from jarvis.core import config, notify, registry, safety, store
from jarvis.workers import base, crash_watchdog, process_watch, resource_guard, status, supervisor
from jarvis.workers import telegram_bot


@pytest.fixture(autouse=True)
def p6(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "WORKERS_STATUS_PATH", tmp_path / "workers.json")
    monkeypatch.setattr(config, "WATCHDOG_TARGETS_FILE", tmp_path / "watchdog_targets.json")
    monkeypatch.setattr(config, "WATCHDOG_TARGETS", [])
    monkeypatch.setattr(config, "NOTIFY_DESKTOP", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")

    def no_network(*a, **k):
        raise AssertionError("real HTTP in a test")
    monkeypatch.setattr(notify, "_http", no_network)
    notify.reset()
    yield tmp_path
    notify.reset()


@pytest.fixture
def tg(monkeypatch):
    """Configured Telegram with a fake Bot API: queue getUpdates batches, inspect sent messages."""
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    api = {"updates": [], "sent": [], "calls": []}

    def call(method, payload=None, timeout=None, **kw):
        api["calls"].append(method)
        if method == "getUpdates":
            return api["updates"].pop(0) if api["updates"] else []
        if method == "sendMessage":
            api["sent"].append(payload["text"])
            return {"message_id": len(api["sent"])}
        raise AssertionError(method)
    monkeypatch.setattr(notify, "telegram_call", call)
    return api


NOW = int(time.time()) + 60  # one fixed "now" so repeated builds of the same update compare equal


@pytest.fixture(autouse=True)
def _fresh_now():  # set per test: fixed at import, it went stale once the whole suite ran longer than the bot's max age
    global NOW
    NOW = int(time.time()) + 60


def upd(uid, text=None, chat=42, **extra):
    msg = {"chat": {"id": chat}, "date": NOW, **extra}
    if text is not None:
        msg["text"] = text
    return {"update_id": uid, "message": msg}


# --- worker base + supervisor ---
class Flaky(base.Worker):
    name = "flaky"

    def __init__(self, fails=2, **kw):
        super().__init__(**kw)
        self.fails, self.calls = fails, 0
        self.ticked = threading.Event()

    def tick(self):
        self.calls += 1
        self.ticked.set()
        if self.calls <= self.fails:
            raise RuntimeError("boom")


def test_worker_interval_clamp_and_backoff():
    w = Flaky(interval_s=1)
    assert w.interval_s == config.WORKER_MIN_INTERVAL_S == 5
    assert w.run_once() is False and w.next_delay() == 10
    assert w.run_once() is False and w.next_delay() == 20 and "boom" in w.last_error
    assert w.run_once() is True and w.errors == 0 and w.next_delay() == 5 and w.ticks == 3
    w.errors = 20
    assert w.next_delay() == config.WORKER_MAX_BACKOFF_S
    assert (config.LOG_DIR / "worker_flaky.log").exists()


def test_worker_thread_start_stop():
    w = Flaky(fails=0, interval_s=5)
    w.start()
    assert w.ticked.wait(2)
    w.stop(timeout=2)
    assert not w.alive and w.status()["ticks"] >= 1


def test_supervisor_status_file_and_skip(caplog):
    caplog.set_level(logging.INFO)
    sup = supervisor.Supervisor(["process_watch", "telegram_bot", "bogus"])
    sup.start()
    try:
        data = status.read()
        assert data and data["pid"] and data["workers"]["process_watch"]["state"] == "running"
        assert data["workers"]["telegram_bot"] == {"state": "skipped", "reason": "not configured"}
        assert data["workers"]["bogus"]["reason"] == "unknown worker"
        assert status.running("process_watch") and not status.running("telegram_bot")
        assert "process_watch" in status.summary()
    finally:
        sup.shutdown()
    assert "not configured, skipping" in caplog.text
    assert status.read() is None and not config.WORKERS_STATUS_PATH.exists()


def test_supervisor_list(capsys):
    assert supervisor.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "telegram_bot" in out and "not configured" in out and "supervisor: not running" in out


# --- notify ---
def test_notify_dedupe_store_and_spoken_alert():
    assert notify.notify("Build done", "ok", "info") == ["store"]
    assert notify.notify("Build done", "ok", "info") == []  # identical within 60 s
    assert notify.notify("Build done", "again", "warning") == ["store"]
    assert [a["text"] for a in store.alerts_recent()] == ["again", "ok"]
    assert notify.pop_spoken_alert() == "Alert: Build done. ok"
    assert notify.pop_spoken_alert() == "Alert: Build done. again"
    assert notify.pop_spoken_alert() is None


def test_notify_desktop_and_telegram_rate_limit(tg, monkeypatch):
    popen = []
    monkeypatch.setattr(config, "NOTIFY_DESKTOP", True)
    monkeypatch.setattr(notify.shutil, "which", lambda exe: "/usr/bin/notify-send")
    monkeypatch.setattr(notify.subprocess, "Popen", lambda argv, **k: popen.append(argv))
    monkeypatch.setattr(config, "NOTIFY_TELEGRAM_PER_MIN", 2)
    assert notify.notify("A", "1", "error") == ["desktop", "telegram", "store"]
    assert popen[0][:3] == ["/usr/bin/notify-send", "-u", "critical"]
    assert tg["sent"][0].startswith("🛑 A")
    notify.notify("B", "2")
    assert notify.notify("C", "3") == ["desktop", "store"]  # third Telegram message in a minute dropped


def test_notify_mute_by_kind_and_all(tg, monkeypatch):
    from jarvis.tools.general.mute_alerts import mute_alerts
    monkeypatch.setattr(config, "NOTIFY_DESKTOP", False)
    assert "no RAM / resource warnings for 20 min" in mute_alerts("on", "resource", 20)
    assert notify.notify("Resource alert: ram", "91%", "warning", source="resource_guard") == ["store"]
    assert store.alerts_recent()[0]["channels"] == "muted" and not tg["sent"]
    assert notify.notify("Backup failed", "x", "warning", source="backup") == ["telegram", "store"]  # others still come
    st = mute_alerts("status")
    assert "🔕 Paused:\n• RAM / resource warnings: 20 min left (until" in st and "✅ On: location messages" in st
    assert mute_alerts("off", "resource") == "Unmuted RAM / resource warnings."
    assert notify.notify("Resource alert: ram", "92%", "warning", source="resource_guard") == ["telegram", "store"]
    mute_alerts("on", "all", 30)  # 'all' never silences reminders or the anti-theft guard
    assert notify.notify("Reminder", "call mom", "warning", source="scheduler") == ["telegram", "store"]
    assert notify.notify("Job done", "y", "warning", source="jobs") == ["store"]
    mute_alerts("on", "last", 10)  # 'this one' = the newest alert's kind (jobs)
    assert "job-done messages" in mute_alerts("status")
    notify.unmute("all")
    assert mute_alerts("status").startswith("🔔 All notifications are ON")
    assert "for 30 min" in mute_alerts("on", "jobs")  # no time given = 30 min, never forever
    assert "for 24 h" in mute_alerts("on", "jobs", 99999)  # at most a day
    notify.unmute("all")


def test_telegram_mute_command(monkeypatch):
    bot = telegram_bot.TelegramBot()
    assert "RAM / resource warnings for 20 min" in bot.answer("/mute ram 20")
    assert "20 min left" in bot.answer("/notification-status") and "20 min left" in bot.answer("/notifications")
    assert bot.answer("/unmutu ram") == "Unmuted RAM / resource warnings."  # before the time ends
    assert bot.answer("/notifications").startswith("🔔 All notifications are ON")


def test_telegram_errors_never_leak_token(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:SECRET")

    class Boom:
        def post(self, url, **k):
            raise ConnectionError(f"cannot reach {url}")
    monkeypatch.setattr(notify, "_http", lambda: Boom())
    with pytest.raises(RuntimeError) as e:
        notify.telegram_call("getMe")
    assert "SECRET" not in str(e.value) and "<token>" in str(e.value)


# --- process / log watcher ---
class FakeProc:
    alive: dict[int, float] = {}

    def __init__(self, pid):
        if pid not in self.alive:
            raise psutil.NoSuchProcess(pid)
        self.pid = pid

    def create_time(self):
        return self.alive[self.pid]

    def status(self):
        return psutil.STATUS_SLEEPING

    def name(self):
        return "train"


def test_process_watch_exit_detection(monkeypatch):
    monkeypatch.setattr(psutil, "Process", FakeProc)
    FakeProc.alive = {4242: time.time() - 125}
    wid, msg = process_watch.register_process("4242", "training run")
    assert wid and "training run" in msg
    assert process_watch.register_process("999")[0] is None
    w = process_watch.ProcessWatcher()
    w.tick()
    assert store.watch_get(wid)["status"] == "active" and not store.alerts_recent()
    FakeProc.alive = {4242: time.time() - 5}  # same PID, different process: the original is gone
    w.tick()
    row = store.watch_get(wid)
    assert row["status"] == "done" and row["result"].startswith("exited after 2m")
    alert = store.alerts_recent()[0]
    assert alert["title"] == "Process finished: training run" and "4242" in alert["text"]


# --- crash watchdog ---
class FakePopen:
    started: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw, self.returncode = argv, kw, None
        self.pid = 1000 + len(self.started)
        FakePopen.started.append(self)

    def poll(self):
        return self.returncode


def test_watchdog_restart_backoff_and_cap(tmp_path, monkeypatch):
    FakePopen.started = []
    monkeypatch.setattr(crash_watchdog.subprocess, "Popen", FakePopen)
    clock = [1000.0]
    monkeypatch.setattr(crash_watchdog.time, "time", lambda: clock[0])
    monkeypatch.setattr(config, "WATCHDOG_TARGETS", [
        {"name": "api", "command": "uvicorn app:app --port 8001", "cwd": str(tmp_path)},
        {"name": "evil", "command": "sudo rm -rf /", "cwd": str(tmp_path)},
        {"name": "chain", "command": "uvicorn x && rm -rf ~", "cwd": str(tmp_path)}])
    w = crash_watchdog.CrashWatchdog()
    w.tick()
    assert [p.argv[0] for p in FakePopen.started] == ["uvicorn"]  # only the allowlisted target
    assert FakePopen.started[0].kw["start_new_session"] and set(w.targets) == {"api"}
    delays = []
    for _ in range(8):
        FakePopen.started[-1].returncode = 1  # crash
        w.tick()  # detects the crash, schedules a restart
        st = w.states["api"]
        delays.append(st.next_start - clock[0])
        clock[0] = st.next_start
        w.tick()  # restart (or give up)
    assert delays[:5] == [5, 10, 20, 40, 80]
    assert len(FakePopen.started) == 1 + config.WATCHDOG_MAX_RESTARTS_PER_HOUR
    titles = [a["title"] for a in store.alerts_recent(50)]
    assert titles.count("Watchdog gave up: api") == 1 and "Crashed: api" in titles and "Restarted: api" in titles
    assert w.info()["api"]["state"] == "gave up"


def test_add_watchdog_target_tool(tmp_path):
    t = registry.get("add_watchdog_target")
    assert registry.safety_of(t) == "confirm" and registry.group_of(t) == "automation"
    assert "never allowed" in crash_watchdog.add_target("x", "sudo n8n start")
    assert "not in the shell allowlist" in crash_watchdog.add_target("x", "bash -c 'rm -rf /'")
    assert "declined" in safety.execute("add_watchdog_target", {"name": "n8n", "command": "n8n start"},
                                        confirm=lambda p: False).output
    assert not config.WATCHDOG_TARGETS_FILE.exists()  # denied: nothing written
    res = safety.execute("add_watchdog_target", {"name": "n8n", "command": "n8n start", "cwd": str(tmp_path)},
                         confirm=lambda p: True)
    assert res.ok and "added watchdog target n8n" in res.output
    assert crash_watchdog.load_targets() == [{"name": "n8n", "command": "n8n start", "cwd": str(tmp_path)}]
    assert "n8n: unknown: workers not running" in registry.call("watchdog_status", {}).output


# --- resource guard ---
SNAP = {"ram_pct": 50.0, "ram_used_gb": 4.0, "ram_total_gb": 8.0, "swap_pct": 10.0, "cpu_pct": 20.0,
        "disk": {"/": 50.0}, "jarvis_core_mb": 100, "jarvis_total_mb": 150}


def test_resource_guard_hysteresis(monkeypatch):
    monkeypatch.setattr(resource_guard, "top_memory", lambda n=3: [("chrome", 1, 2100.0), ("code", 2, 900.0),
                                                                  ("python3", 3, 300.0)])
    g = resource_guard.ResourceGuard()
    snap = lambda **kw: {**SNAP, **kw}  # noqa: E731
    assert g.evaluate(snap(ram_pct=95), now=0) == ["ram"]
    alert = store.alerts_recent()[0]
    assert "RAM" in alert["title"] and "chrome 2100 MB" in alert["text"]
    assert g.evaluate(snap(ram_pct=96), now=60) == []  # still high: no spam
    assert g.evaluate(snap(ram_pct=88), now=120) == []  # below 90 but within hysteresis: not recovered
    assert g.evaluate(snap(ram_pct=95), now=180) == []
    assert g.evaluate(snap(ram_pct=95), now=1800) == []  # still within the 2 h cooldown
    assert g.evaluate(snap(ram_pct=70), now=1900) == []  # recovered
    assert g.evaluate(snap(ram_pct=91), now=1910) == []  # back up soon after: still quiet (was the 15-min spam)
    assert g.evaluate(snap(ram_pct=91), now=7300) == ["ram"]  # 2 h later: tell again
    assert g.evaluate(snap(jarvis_core_mb=650, disk={"/": 97.0}), now=7400) == ["jarvis_core", "disk /"]
    assert g.evaluate(snap(cpu_pct=99, cpu_pct_partial=True), now=7500) == []  # 5-min window not full


def test_resource_guard_trims_itself_before_alerting(monkeypatch):
    sizes = iter([560, 300])  # high -> after the clean-up
    monkeypatch.setattr(resource_guard, "snapshot", lambda cpu_avg=None: {**SNAP, "jarvis_core_mb": next(sizes)})
    trims = []
    monkeypatch.setattr(resource_guard, "trim_memory", lambda: trims.append(1))
    g = resource_guard.ResourceGuard()
    g.tick()
    assert trims == [1] and g.last["jarvis_core_mb"] == 300 and "jarvis_core" not in g.sent


def test_resource_status_tool(monkeypatch):
    monkeypatch.setattr(resource_guard, "snapshot", lambda cpu_avg=None: dict(SNAP))
    monkeypatch.setattr(resource_guard, "top_memory", lambda n=3: [("chrome", 1, 1500.0)])
    t = registry.get("laptop_doctor")  # resource_status is an alias of laptop_doctor(action=kurama) now
    assert registry.group_of(t) == "system" and registry.safety_of(t) == "safe"
    out = registry.call("resource_status", {}).output
    assert "RAM 50% (4.0/8.0 GB)" in out and "chrome 1500 MB" in out and "workers: not running" in out


# --- Telegram remote control ---
class FakeAgent:
    def __init__(self, answer="Hello from KURAMA"):
        self.answer, self.calls = answer, []

    def run(self, text, mode="text", lang=None):
        self.calls.append((text, mode))
        return self.answer


def test_telegram_skips_when_not_configured():
    assert telegram_bot.TelegramBot().available() == "not configured"


def test_telegram_ignores_other_chats_and_routes_text(tg):
    bot = telegram_bot.TelegramBot()
    assert bot.available() is None
    bot._agent = FakeAgent("x" * 5000)
    tg["updates"] = [[upd(10, "rm everything", chat=999), upd(11, "what time is it?"),
                      upd(12, sticker={"file_id": "v"})]]
    bot.tick()
    assert bot._agent.calls == [("what time is it?", "text")]  # chat 999 ignored silently
    assert len(tg["sent"]) == 3 and all(len(m) <= config.TELEGRAM_MAX_REPLY_CHARS for m in tg["sent"])
    assert "".join(tg["sent"][:2]) == "x" * 5000 and tg["sent"][2] == telegram_bot.TEXT_ONLY  # long = split, not cut
    assert bot.offset == 13 and store.kv_get("telegram_offset") == "13"


def test_telegram_confirm_yes_no_timeout_and_blocked(tg, monkeypatch, tmp_path):
    bot = telegram_bot.TelegramBot()
    (tmp_path / "x").write_text("x")
    tg["updates"] = [[upd(1, "yes", chat=7), upd(2, "yes")]]
    res = safety.execute("delete_to_trash", {"path": str(tmp_path / "x")}, confirm=bot.confirm)
    assert res.ok and "trash" in res.output and "Reply yes/no" in tg["sent"][0]
    tg["updates"] = [[upd(3, "no"), upd(4, "/jobs")]]
    res = safety.execute("delete_to_trash", {"path": str(tmp_path / "x")}, confirm=bot.confirm)
    assert not res.ok and "declined" in res.output
    assert list(bot._backlog) == [upd(4, "/jobs")]  # the message after the answer is not lost
    bot.tick()
    assert tg["sent"][-1] == "No background jobs."
    monkeypatch.setattr(config, "TELEGRAM_CONFIRM_TIMEOUT_S", 0.05)
    assert bot.confirm("Should I delete a file?") is False and tg["sent"][-1].startswith("No answer")
    n = len(tg["sent"])
    from jarvis.core import registry
    reg = registry.Registry(packages=())
    reg._discovered = True
    reg.tool(lambda: "boom", name="self_destruct", safety="blocked")
    res = safety.execute("self_destruct", {}, confirm=bot.confirm, reg=reg)
    assert "blocked" in res.output and len(tg["sent"]) == n  # blocked: never even asks


def test_telegram_agent_uses_telegram_confirm_hook(tg):
    bot = telegram_bot.TelegramBot()
    a = bot.agent()
    assert a.confirm == bot.confirm and safety.get_confirm("telegram") == bot.confirm
    safety.set_confirm_hook("telegram", None)


def test_telegram_status_and_help(tg, monkeypatch):
    monkeypatch.setattr(resource_guard, "snapshot", lambda cpu_avg=None: dict(SNAP))
    store.job_insert("essay about Nepal", "write", status="running")
    bot = telegram_bot.TelegramBot()
    out = bot.answer("/status")
    assert "Laptop: RAM" in out and "essay about Nepal" in out  # /status = the full overview now
    from jarvis.core import slash  # /list and /help: every command and every tool (11-02, the owner's ask)
    assert bot.answer("/help") == telegram_bot.HELP + "\n\n" + slash.help_text() and bot.answer("/start@JarvisBot") == telegram_bot.HELP
    assert "/camera" in telegram_bot.HELP and "/where" in telegram_bot.HELP  # the laptop-control list
    assert bot.answer("give me all laptop control commands") in (telegram_bot.HELP, telegram_bot.HELP + "\n\n" + slash.help_text())
    assert bot.answer("/list") == telegram_bot.HELP + "\n\n" + slash.help_text()  # phone commands + every command + tool
    assert "/camera" in slash.help_text() and "/where" in slash.help_text()
    for c in ("/mute", "/battery", "/ram", "/camera", "/screen", "/guard", "/track", "/clip", "/control", "/lock"):
        assert c in telegram_bot.HELP
    assert {c for c, _ in telegram_bot.MENU} >= {"list", "mute", "camera", "where", "status"}


def test_telegram_reply_to_an_alert_mutes_that_kind(tg, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_DESKTOP", False)
    notify.notify("Resource alert: ram", "ram 91% (limit 90).", "warning", source="resource_guard")
    notify.notify("Backup failed", "disk full", "warning", source="backup")  # a newer, different alert
    bot = telegram_bot.TelegramBot()
    quoted = {"text": "⚠️ Resource alert: ram\nram 91% (limit 90)."}
    assert "no RAM / resource warnings for 20 min" in bot.answer("mute 20 min", quoted)
    assert notify.muted("resource_guard") and not notify.muted("backup")
    assert "no backup messages for 30 min" in bot.answer("stop", {"text": "⚠️ Backup failed\ndisk full"})
    # a longer reply goes on normally; 'this' in it means the replied alert, and the AI sees the quote
    notify.unmute("all")
    assert "RAM / resource warnings for 30 min" in bot.answer("do not send this alert for 30 min", quoted)
    assert notify.replied_source() == ""  # cleared after the turn


def test_telegram_reply_gives_the_ai_the_quoted_message(monkeypatch):
    seen = {}

    class FakeAgent:
        reply_to = ""

        def run(self, text, mode="text"):
            seen["text"], seen["reply_to"] = text, self.reply_to
            return "ok"
    bot = telegram_bot.TelegramBot()
    bot._agent = FakeAgent()
    monkeypatch.setattr(bot, "agent", lambda: bot._agent)
    assert bot.answer("why so high?", {"text": "Your RAM was 91% at 3 PM, mostly Brave."}) == "ok"
    assert seen == {"text": "why so high?", "reply_to": "Your RAM was 91% at 3 PM, mostly Brave."}
    assert bot._agent.reply_to == ""


class Resp:
    status_code, text = 200, '{"started": true}'


def test_telegram_ignores_stale_backlog(tg):
    w = tg["worker"] if isinstance(tg, dict) and "worker" in tg else None
    from jarvis.workers.telegram_bot import TelegramBot
    bot = w or TelegramBot()
    old = upd(1, "delete everything", date=int(time.time()) - 3600)["message"]
    fresh = upd(2, "hi")["message"]
    assert bot._own_message({"message": old}) is None
    assert bot._own_message({"message": fresh}) is not None


def test_telegram_plain_words_work_like_slash_commands(tg, monkeypatch):
    n = telegram_bot.natural_command
    assert n("what is my laptop doing") == "/status" and n("how much ram is used") == "/ram"
    assert n("what jobs are running") == "/jobs" and n("what is on the laptop clipboard") == "/clip"
    assert n("turn off the guard") == "/guard off" and n("start lost mode") == "/track on"
    assert n("show all commands") == "/list" and n("stop the task") == "/stop"
    assert n("open youtube") is None and n("stop it") is None  # not commands
    from jarvis.core import fastpath, phone
    assert fastpath.match("what is my notification status").args == {"action": "status"}
    assert fastpath.match("unmute all").args == {"action": "off", "what": "all"}
    assert fastpath.match("mute ram for 20 min").args == {"action": "on", "what": "resource", "minutes": 20.0}
    assert fastpath.match("lock the laptop screen").tool == "lock_screen"
    assert phone.CAMERA.match("send me a camera photo") and phone.CAMERA.match("take a photo")
    assert phone.VIDEO.match("record a video")
    monkeypatch.setattr(resource_guard, "snapshot", lambda cpu_avg=None: dict(SNAP))
    bot = telegram_bot.TelegramBot()
    assert bot.answer("ram usage") == resource_guard.summary(dict(SNAP))  # same answer as /ram, 0 tokens
    from jarvis.core import slash
    assert bot.answer("show all commands") == telegram_bot.HELP + "\n\n" + slash.help_text()


def test_core_alert_says_kurama_and_one_model_process(monkeypatch):
    """11-01 08:10: 'Resource alert: jarvis_core 611 MB' = the server + TWO copies of the same embedding model."""
    from jarvis.core import config, memory, semantic
    sent = []
    monkeypatch.setattr(notify, "notify", lambda title, text, *a, **k: sent.append(title) or [])
    g = resource_guard.ResourceGuard()
    g.evaluate({"ram_pct": 40.0, "swap_pct": 0.0, "cpu_pct": 5.0, "disk": {"/": 50.0}, "jarvis_core_mb": 650,
                "jarvis_total_mb": 650}, now=10)
    assert sent and "KURAMA core" in sent[0] and "jarvis" not in sent[0]
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    monkeypatch.setattr(memory, "_index", None)
    try:
        assert memory.get_index().embedder is semantic.embedder()
    finally:
        memory.set_index(None)
