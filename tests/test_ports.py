import os
from collections import namedtuple

import psutil

from jarvis.core import fastpath, ports, registry, safety

Addr = namedtuple("Addr", "ip port")
Conn = namedtuple("Conn", "status laddr pid")


def _fake(monkeypatch, conns):
    monkeypatch.setattr(ports.psutil, "net_connections", lambda kind="tcp": conns)


def test_list_and_check(monkeypatch):
    me = os.getpid()
    _fake(monkeypatch, [Conn(psutil.CONN_LISTEN, Addr("127.0.0.1", 5173), me),
                        Conn(psutil.CONN_LISTEN, Addr("0.0.0.0", 631), None),
                        Conn(psutil.CONN_LISTEN, Addr("127.0.0.53", 53), None),  # resolver: hidden
                        Conn(psutil.CONN_ESTABLISHED, Addr("127.0.0.1", 40000), me)])
    out = ports.list_all()
    assert out.startswith("2 ports in use") and "5173:" in out and f"pid {me}" in out and "System: 631" in out
    assert "\n53:" not in out and ", 53" not in out
    c = ports.check(5173)
    assert "Port 5173 is used by" in c and "only this laptop" in c
    assert ports.check(9999) == "Port 9999 is free, nothing is using it."
    assert "a system service" in ports.check(631) and "whole network" in ports.check(631)
    assert ports.pid_on(5173) == me


def test_doctor_port_actions_and_stop_by_port(monkeypatch):
    me = os.getpid()  # the test process stands in for KURAMA here only by its cmdline check
    _fake(monkeypatch, [Conn(psutil.CONN_LISTEN, Addr("127.0.0.1", 5173), me)])
    assert "Port 5173 is used by" in registry.call("laptop_doctor", {"action": "port", "target": "5173"}).output
    assert registry.call("laptop_doctor", {"action": "port", "target": ""}).output.startswith("1 ports in use")
    assert "free, nothing to stop" in safety.execute("laptop_doctor", {"action": "stop", "target": "port 9999"},
                                                     confirm=lambda p: True).output
    from jarvis.core import doctor
    stopped = []
    monkeypatch.setattr(doctor, "stop", lambda pids: stopped.extend(pids) or [f"x (PID {p})" for p in pids])
    out = safety.execute("laptop_doctor", {"action": "stop", "target": "port 5173"}, confirm=lambda p: True).output
    assert stopped == [me] and "Stopped" in out  # a PID 5173 is never picked by mistake


def test_routes():
    assert fastpath.match("what is running on port 8000").args == {"action": "port", "target": "8000"}
    assert fastpath.match("show my open ports").args == {"action": "port", "target": ""}
    assert fastpath.match("/ports").tool == "laptop_doctor"
    k = fastpath.match("free port 3000")
    assert k.tool == "laptop_doctor" and k.args == {"action": "stop", "target": "port 3000"}
    assert fastpath.match("the ports of nepal") is None
