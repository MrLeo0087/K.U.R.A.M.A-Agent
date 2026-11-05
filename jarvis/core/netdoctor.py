"""Internet doctor: "internet is slow / not working" -> which link is broken (Wi-Fi, router, provider, DNS), the
fix, an optional speed test, and "tell me when it's back" (0 tokens).

Checks in order: Wi-Fi connected + signal (nmcli), the router (ping the default gateway), the internet (ping 1.1.1.1
and 8.8.8.8), names (DNS lookup), and a real HTTPS request. The first failing step is the problem.
"""
from __future__ import annotations

import re
import socket
import subprocess
import time
from dataclasses import dataclass, field

from jarvis.core import config, notify, store


@dataclass
class NetReport:
    steps: list[tuple[str, bool, str]] = field(default_factory=list)  # (step, ok, detail)
    verdict: str = ""
    fix: str = ""
    connection: str = ""


def _run(args: list[str], timeout: float = 6) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def ping(host: str, count: int = 2) -> float | None:
    """Average round trip in ms, or None."""
    out = _run(["ping", "-c", str(count), "-i", "0.2", "-W", "2", "-q", host], timeout=count * 2 + 3)
    m = re.search(r"= [\d.]+/([\d.]+)/", out)
    return float(m.group(1)) if m else None


def wifi() -> tuple[str, int | None, str]:
    """(state, signal %, connection name) of the Wi-Fi."""
    dev = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"])
    state, conn = "no wifi device", ""
    for ln in dev.splitlines():
        parts = ln.split(":")
        if len(parts) >= 4 and parts[1] == "wifi":
            state, conn = parts[2], parts[3]
            break
    sig = None
    for ln in _run(["nmcli", "-t", "-f", "IN-USE,SIGNAL", "dev", "wifi", "list", "--rescan", "no"]).splitlines():
        if ln.startswith("*:"):
            sig = int(ln.split(":")[1] or 0)
    wired = any(":ethernet:connected" in ln for ln in dev.splitlines())
    return ("wired" if wired and state != "connected" else state), sig, conn


def gateway() -> str | None:
    m = re.search(r"default via (\S+)", _run(["ip", "route", "show", "default"]))
    return m.group(1) if m else None


def dns_ok(host: str = "www.google.com") -> float | None:
    t = time.monotonic()
    try:
        socket.setdefaulttimeout(4)
        socket.getaddrinfo(host, 443)
        return (time.monotonic() - t) * 1000
    except OSError:
        return None
    finally:
        socket.setdefaulttimeout(None)


def https_ok() -> float | None:
    t = time.monotonic()
    try:
        r = notify._http().get("https://www.gstatic.com/generate_204", timeout=6)
        return (time.monotonic() - t) * 1000 if r.status_code in (204, 200) else None
    except Exception:
        return None


def diagnose() -> NetReport:
    r = NetReport()
    state, sig, conn = wifi()
    r.connection = conn
    if state not in ("connected", "wired"):
        r.steps.append(("Wi-Fi", False, state))
        r.verdict, r.fix = f"Wi-Fi is {state}.", "Turn Wi-Fi on (say 'turn on wifi') or connect to a network."
        return r
    r.steps.append(("Wi-Fi", True, f"{conn}, signal {sig}%" if sig is not None else conn or state))
    gw = gateway()
    gms = ping(gw) if gw else None
    r.steps.append(("Router", gms is not None, f"{gw} {gms:.0f} ms" if gms is not None else f"{gw or 'no gateway'} not answering"))
    if gms is None:
        r.verdict = "The laptop can't reach the router."
        r.fix = "Reconnect the Wi-Fi (say 'reconnect wifi'), move closer to the router, or restart the router."
        return r
    net = ping("1.1.1.1") or ping("8.8.8.8")
    r.steps.append(("Internet", net is not None, f"{net:.0f} ms" if net is not None else "no reply from 1.1.1.1/8.8.8.8"))
    if net is None:
        r.verdict = "The router works but has no internet: the provider (ISP) line is down or the plan ran out."
        r.fix = "Restart the router; if it stays down, call your internet provider."
        return r
    dms = dns_ok()
    r.steps.append(("Names (DNS)", dms is not None, f"{dms:.0f} ms" if dms is not None else "lookups fail"))
    if dms is None:
        r.verdict = "The internet works but name lookups (DNS) fail, so websites don't open."
        r.fix = "Switch to a public DNS (say 'fix dns': 1.1.1.1 and 8.8.8.8), or restart the router."
        return r
    hms = https_ok()
    r.steps.append(("Web", hms is not None, f"{hms:.0f} ms" if hms is not None else "HTTPS requests fail"))
    slow = [s for s, ok, d in r.steps if ok and (m := re.search(r"(\d+) ms", d)) and int(m.group(1)) > 300]
    if hms is None:
        r.verdict, r.fix = "Websites don't load although the line is up.", "Check a VPN/proxy, or restart the router."
    elif sig is not None and sig < 40:
        r.verdict, r.fix = f"Everything works, but the Wi-Fi signal is weak ({sig}%).", "Move closer to the router."
    elif slow or net > 150:
        r.verdict = f"It works but is slow ({net:.0f} ms to the internet)."
        r.fix = "Others may be streaming/downloading on the same network; try again later or restart the router."
    else:
        r.verdict, r.fix = "The internet looks fine right now.", ""
    return r


def text(r: NetReport) -> str:
    steps = "\n".join(f"{'✔' if ok else '✘'} {s}: {d}" for s, ok, d in r.steps)
    return f"{r.verdict}" + (f" {r.fix}" if r.fix else "") + f"\n{steps}"


def speed(total: float | None = None) -> str:
    """A real speed test against Cloudflare's test servers (config.SPEEDTEST_SECONDS in total, 15 s by default, the
    owner can change it: "make the speed test 30 seconds"): latency (5 pings), download ~55%, upload ~40%. The old test fetched 10 MB once (0.3 s on a fast line: a number from a fraction of a second, 11-04)."""
    import httpx  # lazy
    seconds = float(total or config.SPEEDTEST_SECONDS) * 0.55  # download time; upload gets 0.75 of it
    base = "https://speed.cloudflare.com"
    with httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0)) as c:
        try:
            pings = []
            for _ in range(5):
                t = time.monotonic()
                c.get(f"{base}/__down?bytes=0")
                pings.append((time.monotonic() - t) * 1000)
            ping = sorted(pings)[len(pings) // 2]
        except Exception as e:  # noqa: BLE001
            return f"error: speed test failed, can't reach the test server ({type(e).__name__})"
        n, t0 = 0, time.monotonic()
        try:  # download: 25 MB pieces until the time is up (a slow line stops early, a fast one keeps measuring)
            while time.monotonic() - t0 < seconds:
                with c.stream("GET", f"{base}/__down?bytes=25000000") as resp:
                    for chunk in resp.iter_bytes():
                        n += len(chunk)
                        if time.monotonic() - t0 > seconds:
                            break
        except Exception:  # noqa: BLE001
            pass
        down = n * 8 / max(time.monotonic() - t0, 0.001) / 1e6
        up_n, t1, blob = 0, time.monotonic(), b"0" * 2_000_000
        try:
            while time.monotonic() - t1 < seconds * 0.75:
                c.post(f"{base}/__up", content=blob)
                up_n += len(blob)
        except Exception:  # noqa: BLE001
            pass
        up = up_n * 8 / max(time.monotonic() - t1, 0.001) / 1e6
    if not n:
        return "error: speed test failed (the download didn't start)"
    return (f"Download {down:.0f} Mbps, upload {up:.0f} Mbps, ping {ping:.0f} ms "
            f"(measured just now: {n / 1e6:.0f} MB down, {up_n / 1e6:.0f} MB up, Cloudflare's test server).")


def reconnect() -> str:
    _, _, conn = wifi()
    if not conn:
        return "error: no Wi-Fi connection to restart"
    _run(["nmcli", "con", "down", "id", conn], timeout=15)
    out = _run(["nmcli", "con", "up", "id", conn], timeout=30)
    return f"Reconnected to {conn}." if "success" in out.lower() else f"Tried to reconnect {conn}; check it in a moment."


def fix_dns() -> str:
    _, _, conn = wifi()
    if not conn:
        return "error: no active connection"
    _run(["nmcli", "con", "mod", "id", conn, "ipv4.dns", "1.1.1.1 8.8.8.8", "ipv4.ignore-auto-dns", "yes"], timeout=10)
    _run(["nmcli", "con", "up", "id", conn], timeout=30)
    return f"{conn} now uses DNS 1.1.1.1 and 8.8.8.8."


def wait_for_internet() -> str:
    store.kv_set("net_wait", str(time.time()))
    return "OK, I'll tell you as soon as the internet is back."


def check_wait() -> bool:
    """Worker tick: if the user asked to be told, announce when the internet is back."""
    since = float(store.kv_get("net_wait") or 0)
    if not since:
        return False
    if time.time() - since > 12 * 3600:
        store.kv_set("net_wait", "")
        return False
    if (ping("1.1.1.1", 1) or ping("8.8.8.8", 1)) and dns_ok():
        store.kv_set("net_wait", "")
        down = int((time.time() - since) / 60)
        notify.notify("Internet is back", f"Back after about {down} min.", level="info", source="netdoctor",
                      telegram=True)
        return True
    return False
