"""Prometheus-style metrics (text format 0.0.4) from the SQLite logs KURAMA already writes: LLM calls and tokens,
tool calls, routing, jobs, and this process's RAM/CPU. 0 tokens, no new storage, no background thread: each scrape
runs a few indexed queries over the last 24 hours (`GET /api/v1/metrics`, or `make metrics`).

Window values are gauges named *_24h (they can go down); process_* follow the standard Prometheus names.
"""
from __future__ import annotations

import os
import time

from jarvis.core import store

WINDOW_S = 24 * 3600


def _esc(v: object) -> str:
    return str(v if v is not None else "").replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ")


def _family(out: list[str], name: str, kind: str, help_: str, rows: list[tuple[dict, float]]) -> None:
    out += [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
    for labels, value in rows:
        lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        out.append(f"{name}{{{lab}}} {value:g}" if lab else f"{name} {value:g}")


def render(now: float | None = None) -> str:
    since = (now or time.time()) - WINDOW_S
    out: list[str] = []
    llm = store._exec("SELECT model, ok, COUNT(*) n, SUM(total_tokens) tok, SUM(prompt_tokens) p, "
                      "SUM(completion_tokens) c, AVG(latency_ms) ms FROM llm_calls WHERE ts >= ? "
                      "GROUP BY model, ok", (since,))
    _family(out, "kurama_llm_calls_24h", "gauge", "LLM calls in the last 24 h",
            [({"model": r["model"], "ok": "true" if r["ok"] else "false"}, r["n"]) for r in llm])
    tok: dict[tuple[str, str], float] = {}
    for r in llm:
        tok[(r["model"], "prompt")] = tok.get((r["model"], "prompt"), 0) + (r["p"] or 0)
        tok[(r["model"], "completion")] = tok.get((r["model"], "completion"), 0) + (r["c"] or 0)
    _family(out, "kurama_llm_tokens_24h", "gauge", "LLM tokens in the last 24 h",
            [({"model": m, "kind": k}, v) for (m, k), v in sorted(tok.items())])
    _family(out, "kurama_llm_latency_ms_avg_24h", "gauge", "Average LLM call latency (ms), last 24 h",
            [({"model": r["model"]}, round(r["ms"] or 0)) for r in llm if r["ok"]])
    tools = store._exec("SELECT tool, ok, COUNT(*) n, AVG(latency_ms) ms FROM tool_calls WHERE ts >= ? "
                        "GROUP BY tool, ok", (since,))
    _family(out, "kurama_tool_calls_24h", "gauge", "Tool calls in the last 24 h",
            [({"tool": r["tool"], "ok": "true" if r["ok"] else "false"}, r["n"]) for r in tools])
    _family(out, "kurama_tool_latency_ms_avg_24h", "gauge", "Average tool latency (ms), last 24 h",
            [({"tool": r["tool"]}, round(r["ms"] or 0)) for r in tools if r["ok"]])
    routes = store._exec("SELECT method, COUNT(*) n, AVG(latency_ms) ms FROM routing WHERE ts >= ? GROUP BY method",
                         (since,))
    _family(out, "kurama_routing_24h", "gauge", "Requests routed in the last 24 h, by method",
            [({"method": r["method"]}, r["n"]) for r in routes])
    _family(out, "kurama_routing_latency_ms_avg_24h", "gauge", "Average routing latency (ms), last 24 h",
            [({"method": r["method"]}, round(r["ms"] or 0)) for r in routes])
    jobs = store._exec("SELECT status, COUNT(*) n FROM jobs WHERE created >= ? GROUP BY status", (since,))
    _family(out, "kurama_jobs_24h", "gauge", "Background jobs started in the last 24 h, by status",
            [({"status": r["status"]}, r["n"]) for r in jobs])
    try:
        import psutil
        p = psutil.Process(os.getpid())
        mem, cpu = p.memory_info(), p.cpu_times()
        _family(out, "process_resident_memory_bytes", "gauge", "Resident memory of the KURAMA server", [({}, mem.rss)])
        _family(out, "process_cpu_seconds_total", "counter", "CPU time used by the KURAMA server",
                [({}, round(cpu.user + cpu.system, 2))])
        _family(out, "process_start_time_seconds", "gauge", "When the KURAMA server started", [({}, round(p.create_time()))])
    except Exception:  # noqa: BLE001 - psutil missing or a sandbox: the app metrics still serve
        pass
    return "\n".join(out) + "\n"
