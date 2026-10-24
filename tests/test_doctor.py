"""Laptop doctor: findings from (faked) measurements, freeing idle kernels and ports only after asking."""
from types import SimpleNamespace

from jarvis.core import config, doctor, fastpath, registry, safety


def fake_machine(monkeypatch, ram=92.0, swap=60.0, temp=95.0, kernels=((111, 600.0, 90.0), (112, 400.0, 45.0)),
                 hogs=(("tracker-miner-fs-3", 85.0, 50), ("python train.py", 99.0, 51))):
    monkeypatch.setattr(doctor.psutil, "virtual_memory", lambda: SimpleNamespace(percent=ram, used=7.4e9, total=8e9))
    monkeypatch.setattr(doctor.psutil, "swap_memory", lambda: SimpleNamespace(percent=swap, total=2e9))
    monkeypatch.setattr(doctor, "memory_by_app", lambda limit=6: [("Chrome", 2.7e9, 28), ("VS Code", 1.6e9, 18)])
    monkeypatch.setattr(doctor, "cpu_hogs", lambda *a, **k: list(hogs))
    monkeypatch.setattr(doctor, "idle_kernels", lambda *a: list(kernels))
    monkeypatch.setattr(doctor, "temperature", lambda: temp)
    monkeypatch.setattr(doctor.psutil, "disk_usage", lambda m: SimpleNamespace(percent=50, free=1e11))


def test_check_finds_the_real_causes(monkeypatch):
    fake_machine(monkeypatch)
    out = registry.call("laptop_doctor", {}).output
    assert "RAM is 92% full; Chrome uses the most (2.7 GB)" in out and "each Chrome tab" in out
    assert "Swap is 60% used" in out and "2 idle Jupyter kernel(s) hold 1000 MB" in out
    assert "file indexing (tracker)" in out and "python train.py uses 99% CPU" in out and "hot (95°C)" in out


def test_healthy_machine(monkeypatch):
    fake_machine(monkeypatch, ram=50, swap=0, temp=45, kernels=(), hogs=())
    assert registry.call("laptop_doctor", {}).output.startswith("Nothing looks wrong")


def test_free_ram_and_stop_ask_first(monkeypatch):
    fake_machine(monkeypatch)
    stopped = []
    monkeypatch.setattr(doctor, "stop", lambda pids: stopped.extend(pids) or [f"Jupyter (PID {p})" for p in pids])
    no = safety.execute("laptop_doctor", {"action": "free_ram"}, confirm=lambda p: False)
    assert "said no" in no.output and not stopped
    yes = safety.execute("laptop_doctor", {"action": "free_ram"}, confirm=lambda p: True)
    assert stopped == [111, 112] and "about 1000 MB freed" in yes.output
    monkeypatch.setattr(doctor, "listeners", lambda port=None: [(8000, 4242, "python app.py")])
    assert "port 8000: python app.py (PID 4242)" in registry.call("laptop_doctor", {"action": "port",
                                                                                   "target": "8000"}).output
    monkeypatch.setattr(doctor, "find", lambda t: [])
    monkeypatch.setattr(doctor.psutil, "Process", lambda pid: SimpleNamespace(pid=pid, name=lambda: "python"))
    monkeypatch.setattr(doctor, "app_name", lambda p: "python app.py")
    out = safety.execute("laptop_doctor", {"action": "stop", "target": "8000"}, confirm=lambda p: True)
    assert "Stopped" in out.output and stopped[-1] == 4242


def test_aliases_and_fastpath(monkeypatch):
    assert registry.get("resource_status") is None and registry.resolve("resource_status", {})[0] == "laptop_doctor"
    monkeypatch.setattr(config, "FASTPATH", True)
    assert fastpath.match("why is my laptop so slow").args == {"action": "check"}
    assert fastpath.match("free up some ram").args == {"action": "free_ram"}
    assert fastpath.match("what is running on port 8000").args == {"action": "port", "target": "8000"}
