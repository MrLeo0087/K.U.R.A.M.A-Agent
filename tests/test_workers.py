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

    def call(method, payload=None, timeout=None):
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


def test_log_watch_patterns_and_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_WATCH_ALERT_COOLDOWN_S", 0)
    log = tmp_path / "train.log"
    log.write_text("old Error before the watch\n")
    wid, msg = process_watch.register_log(str(log), label="exp1")
    assert wid and "tailing" in msg
    w = process_watch.ProcessWatcher()
    with log.open("a") as f:
        f.write("epoch 1 loss 0.9\nEpoch 2/10 completed\nTraceback (most recent call last):\n  File x\n")
    w.tick()
    alerts = store.alerts_recent()
    assert len(alerts) == 1 and alerts[0]["title"] == "Log alert: exp1 (epoch 2)"
    assert "Traceback" in alerts[0]["text"] and "Last lines" in alerts[0]["text"]
    assert "old Error" not in alerts[0]["text"]  # only lines written after the watch started
    log.rename(tmp_path / "train.log.1")  # rotation: a new file at the same path
    log.write_text("epoch 3 loss nan\nloss: nan\n")
    w.tick()
    assert store.alerts_recent()[0]["title"] == "Log alert: exp1 (epoch 3)"
    log.write_text("training finished\n")  # truncated in place
    w.tick()
    top = store.alerts_recent()[0]
    assert top["title"] == "Log finished: exp1 (epoch 3)" and top["level"] == "info"
    with log.open("a") as f:
        f.write("half a li")  # no newline yet: wait for the rest
    w.tick()
    assert len(store.alerts_recent()) == 3
    assert "epoch 3" in process_watch.describe(store.watch_get(wid))


def test_watch_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(psutil, "Process", FakeProc)
    FakeProc.alive = {77: time.time()}
    tools = {n: registry.get(n) for n in ("watch_process", "watch_log", "list_watches", "stop_watch")}
    assert all(registry.safety_of(t) == "safe" and registry.group_of(t) == "watch" for t in tools.values())
    out = registry.call("watch_process", {"target": "77", "label": "render"}).output
    assert "watch #1" in out and "workers not running" in out
    assert "no such log file" in registry.call("watch_log", {"path": str(tmp_path / "nope.log")}).output
    (tmp_path / "a.log").write_text("")
    assert "bad regex" in registry.call("watch_log", {"path": str(tmp_path / "a.log"), "patterns": "(("}).output
    assert "render" in registry.call("list_watches", {}).output
    assert registry.call("stop_watch", {"watch": "render"}).output == "stopped #1 render"
    assert "no active watch" in registry.call("stop_watch", {"watch": "all"}).output


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
    assert "ram" in alert["title"] and "chrome 2100 MB" in alert["text"]
    assert g.evaluate(snap(ram_pct=96), now=60) == []  # still high: no spam
    assert g.evaluate(snap(ram_pct=88), now=120) == []  # below 90 but within hysteresis: not recovered
    assert g.evaluate(snap(ram_pct=95), now=180) == []
    assert g.evaluate(snap(ram_pct=95), now=1800) == ["ram"]  # 30 min later: remind
    assert g.evaluate(snap(ram_pct=70), now=1900) == []  # recovered
    assert g.evaluate(snap(ram_pct=91), now=1910) == ["ram"]  # crossed again after recovery
    assert g.evaluate(snap(jarvis_core_mb=650, disk={"/": 97.0}), now=2000) == ["jarvis_core", "disk /"]
    assert g.evaluate(snap(cpu_pct=99, cpu_pct_partial=True), now=2100) == []  # 5-min window not full


def test_resource_status_tool(monkeypatch):
    monkeypatch.setattr(resource_guard, "snapshot", lambda cpu_avg=None: dict(SNAP))
    monkeypatch.setattr(resource_guard, "top_memory", lambda n=3: [("chrome", 1, 1500.0)])
    t = registry.get("resource_status")
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
                      upd(12, voice={"file_id": "v"})]]
    bot.tick()
    assert bot._agent.calls == [("what time is it?", "text")]  # chat 999 ignored silently
    assert len(tg["sent"]) == 2 and len(tg["sent"][0]) <= config.TELEGRAM_MAX_REPLY_CHARS
    assert tg["sent"][0].endswith("(truncated)") and tg["sent"][1] == telegram_bot.TEXT_ONLY
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
    assert "RAM 50%" in out and "Watches: none" in out and "essay about Nepal" in out and "workers" in out
    assert bot.answer("/help").startswith("I'm KURAMA") and bot.answer("/start@JarvisBot") == telegram_bot.HELP


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
