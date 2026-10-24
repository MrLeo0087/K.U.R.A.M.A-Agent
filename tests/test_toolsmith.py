"""P7c toolsmith: consent first, AST allowlist, second confirm, sandbox limits, skills (all mocked, no network)."""
import os

import pytest

from jarvis.core import config, registry, safety, toolsmith
from jarvis.core.toolsmith import ToolSpec

PURE = "import datetime\ndef run(arg):\n    d = datetime.date.fromisoformat(arg)\n    return str((d - datetime.date(2026, 10, 23)).days) + ' days'\n"
WALL = ("from jarvis_helpers import run_cmd\ndef run(arg):\n"
        "    run_cmd(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri', 'file://' + arg])\n"
        "    return run_cmd(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri-dark', 'file://' + arg])\n")


def spec(code=PURE, reusable=False, needs=("none",), possible=True, name="days_until", arg="2027-01-01",
         summary="Counts the days until a date."):
    return ToolSpec(possible=possible, reason="" if possible else "it needs a paid service", reusable=reusable,
                    name=name, summary=summary, needs=list(needs), arg_hint="date as YYYY-MM-DD", arg=arg, code=code)


@pytest.fixture
def gen(monkeypatch):
    """Scripted generator: gen(spec1, spec2...) -> list of (task, feedback) calls."""
    def install(*specs):
        calls, script = [], list(specs)

        def fake(task, feedback=""):
            calls.append((task, feedback))
            return script.pop(0) if len(script) > 1 else script[0]
        monkeypatch.setattr(toolsmith, "generate", fake)
        return calls
    return install


def run_make(task, answers, user_text=None):
    """Call make_tool through the safety gate; answers: list of bools for successive questions."""
    asked, it = [], iter(answers)

    def confirm(p):
        asked.append(p)
        return next(it, False)
    res = safety.execute("make_tool", {"task": task}, confirm=confirm,
                         ctx={"user_text": user_text or task, "lang": "en", "mode": "text"})
    return res, asked


def test_consent_declined_makes_no_llm_call(monkeypatch):
    from jarvis.core import llm
    monkeypatch.setattr(llm, "structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("codegen")))
    res, asked = run_make("how many days until 1 January 2027", [False])
    assert res.ok and "said no" in res.output
    assert asked == [toolsmith.CONSENT["en"]]
    assert not list(config.SANDBOX_DIR.glob("*")) if config.SANDBOX_DIR.exists() else True


def test_consent_in_users_language(gen):
    gen(spec())
    asked = []
    safety.execute("make_tool", {"task": "x"}, confirm=lambda p: asked.append(p) or False,
                   ctx={"user_text": "नयाँ वर्ष आउन कति दिन बाँकी छ?", "lang": "ne"})
    assert asked == [toolsmith.CONSENT["ne"]]


def test_pure_tool_runs_after_one_yes_and_one_off_is_removed(gen):
    calls = gen(spec())
    res, asked = run_make("how many days until 1 January 2027", [True, False])  # yes build, no save
    assert res.ok and res.output.startswith("Result: 70 days"), res.output
    assert len(asked) == 2 and len(calls) == 1 and asked[1].endswith(toolsmith.SAVE_ASK["en"])
    assert "Used once and removed" in res.output
    assert not list(config.SKILLS_DIR.glob("*")) if config.SKILLS_DIR.exists() else True
    assert not list(config.SANDBOX_DIR.glob("*"))


def test_not_possible_is_explained(gen):
    gen(spec(possible=False))
    res, _ = run_make("book a flight", [True])
    assert "Not possible: it needs a paid service" in res.output


def test_ast_failure_regenerates_once_with_reason(gen):
    calls = gen(spec(code="import os\ndef run(arg):\n    return os.getcwd()"), spec())
    res, _ = run_make("days until 2027", [True])
    assert res.output.startswith("Result: 70 days")
    assert len(calls) == 2 and "safety check refused" in calls[1][1] and "import os" in calls[1][1]


def test_ast_failure_twice_gives_up_politely(gen):
    gen(spec(code="def run(arg):\n    return eval(arg)"))
    res, _ = run_make("calculate 2+2", [True])
    assert "couldn't make a safe tool" in res.output


def test_runtime_error_retries_once_with_traceback(gen):
    calls = gen(spec(code="def run(arg):\n    return 1/0"), spec())
    res, _ = run_make("days until 2027", [True])
    assert res.output.startswith("Result: 70 days")
    assert "ZeroDivisionError" in calls[1][1]


def test_sensitive_needs_ask_twice_and_show_commands(gen, monkeypatch):
    gen(spec(code=WALL, needs=("system",), name="wallpaper_skill", reusable=True, arg="/home/u/a.jpg",
             summary="Changes your desktop wallpaper to a picture you choose."))
    ran = []
    monkeypatch.setattr(toolsmith, "run_sandbox", lambda *a, **k: ran.append(a) or toolsmith.RunResult(True, "ok"))
    res, asked = run_make("change my wallpaper", [True, False])
    assert "said no" in res.output and not ran
    assert len(asked) == 2 and "gsettings set org.gnome.desktop.background picture-uri <value>" in asked[1]
    assert "wallpaper" in asked[1]


def test_personal_task_asks_twice_even_when_pure(gen):
    gen(spec())
    res, asked = run_make("check my password strength", [True, True, False])
    assert len(asked) == 3 and res.output.startswith("Result:")


def test_wallpaper_skill_saved_with_dry_run_commands(gen, monkeypatch):
    monkeypatch.setattr(toolsmith, "DRY_RUN_CMDS", True)
    gen(spec(code=WALL, needs=("system",), name="wallpaper_skill", reusable=True, arg="/home/u/a.jpg",
             summary="Changes your desktop wallpaper."))
    res, asked = run_make("change my wallpaper", [True, True, True])
    assert "[dry run] would run: gsettings set org.gnome.desktop.background picture-uri-dark" in res.output
    assert "Saved as tool 'wallpaper_skill'" in res.output
    meta = toolsmith.load_meta("wallpaper_skill")
    assert meta["sensitive"] and "shell" in meta["needs"] and "system" in meta["needs"]
    t = registry.get("wallpaper_skill")
    assert registry.group_of(t) == "skills" and registry.safety_of(t) == "confirm"
    toolsmith.delete("wallpaper_skill")


def test_reusable_saved_then_reused_with_zero_generation(gen, monkeypatch):
    calls = gen(spec(reusable=True))
    res, _ = run_make("how many days until 1 January 2027", [True, True])
    assert "Saved as tool 'days_until'" in res.output and len(calls) == 1
    assert (config.SKILLS_DIR / "days_until.py").exists()
    t = registry.get("days_until")
    assert registry.group_of(t) == "skills" and registry.safety_of(t) == "safe"
    from jarvis.core import llm
    monkeypatch.setattr(llm, "structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("codegen")))
    res2, asked = run_make("how many days until 25 December 2026", [True])
    assert "saved skill fits: days_until" in res2.output and asked == [] and len(calls) == 1
    out = safety.execute("use_skill", {"name": "days_until", "arg": "2026-12-25"}, confirm=lambda p: False)
    assert out.ok and out.output == "63 days"
    direct = safety.execute("days_until", {"arg": "2027-01-01"}, confirm=lambda p: False)
    assert direct.ok and direct.output == "70 days"
    assert toolsmith.load_meta("days_until")["uses"] == 3
    assert "days_until" in safety.execute("list_skills", {}).output
    assert safety.execute("delete_skill", {"name": "days_until"}, confirm=lambda p: True).ok
    assert registry.get("days_until") is None and not (config.SKILLS_DIR / "days_until.py").exists()


def test_sensitive_skill_asks_before_reuse(gen, monkeypatch):
    monkeypatch.setattr(toolsmith, "DRY_RUN_CMDS", True)
    gen(spec(code=WALL, needs=("system",), name="wallpaper_skill", reusable=True))
    run_make("change my wallpaper", [True, True, True])
    asked = []
    out = safety.execute("use_skill", {"name": "wallpaper_skill", "arg": "/x.jpg"},
                         confirm=lambda p: asked.append(p) or False)
    assert "said no" in out.output and len(asked) == 1
    toolsmith.delete("wallpaper_skill")


def test_lru_keeps_at_most_max(gen, monkeypatch):
    monkeypatch.setattr(config, "SKILLS_MAX", 2)
    for i, n in enumerate(("alpha_tool", "beta_tool", "gamma_tool")):
        gen(spec(reusable=True, name=n))
        toolsmith.save_skill(spec(reusable=True, name=n), f"task {n}", set(), toolsmith.Check(True))
    assert sorted(toolsmith.skill_names()) == ["beta_tool", "gamma_tool"]
    for n in ("beta_tool", "gamma_tool"):
        toolsmith.delete(n)


# --- static check matrix ---
@pytest.mark.parametrize("code", [
    "import math\ndef run(arg):\n    return str(math.sqrt(16))",
    "from datetime import date, timedelta\ndef run(arg):\n    return str(date.today() + timedelta(days=1))",
    "import urllib.parse\ndef run(arg):\n    return urllib.parse.quote(arg)",
    "import collections, json\ndef run(arg):\n    return json.dumps(collections.Counter(arg))",
    "from jarvis_helpers import http_get\ndef run(arg):\n    return http_get('https://example.com')[:50]",
    "from jarvis_helpers import read_text, write_text\ndef run(arg):\n    return write_text('o.txt', read_text(arg))",
    WALL,
])
def test_ast_allows(code):
    assert toolsmith.check_code(code).ok


@pytest.mark.parametrize("code", [
    "import os\ndef run(a): pass", "import sys\ndef run(a): pass", "import subprocess\ndef run(a): pass",
    "import socket\ndef run(a): pass", "import shutil\ndef run(a): pass", "import ctypes\ndef run(a): pass",
    "import importlib\ndef run(a): pass", "import pickle\ndef run(a): pass", "import marshal\ndef run(a): pass",
    "import urllib.request\ndef run(a): pass", "from . import x\ndef run(a): pass",
    "def run(a): return eval(a)", "def run(a): return exec(a)", "def run(a): return compile(a, 'x', 'exec')",
    "def run(a): return __import__('os')", "def run(a): return open('/etc/passwd').read()",
    "def run(a): return globals()", "def run(a): return locals()", "def run(a): return getattr(a, 'x')",
    "def run(a): return ().__class__.__bases__", "def run(a): return '{0.__class__}'.format(a)",
    "import calendar\ndef run(a): return calendar.sys.modules", "import random\ndef run(a): return random._os",
    "from calendar import sys\ndef run(a): pass", "import json\nj = json\ndef run(a): pass",
    "import jarvis_helpers\ndef run(a): pass", "from jarvis_helpers import _GATE\ndef run(a): pass",
    "from jarvis_helpers import run_cmd\ndef run(a): return run_cmd([a])",
    "from jarvis_helpers import run_cmd\ndef run(a): return run_cmd(['sudo', 'ls'])",
    "from jarvis_helpers import run_cmd\ndef run(a): return run_cmd(['python3', '-c', '1'])",
    "from jarvis_helpers import run_cmd\ndef run(a):\n    f = run_cmd\n    return f(['ls'])",
    "def run(a):\n    g = (x for x in [1])\n    return g.gi_frame",
    "def helper(a): return a", "def run(a) return", "import math\nasync def run(a): pass",
])
def test_ast_denies(code):
    assert not toolsmith.check_code(code).ok


# --- sandbox ---
def test_sandbox_runs_and_cleans_up():
    r = toolsmith.run_sandbox("def run(arg):\n    print('hi')\n    return arg.upper()", "x")
    assert r.ok and r.output == "hi\nX"
    assert not list(config.SANDBOX_DIR.glob("*"))


def test_sandbox_infinite_loop_is_killed_by_timeout():
    r = toolsmith.run_sandbox("def run(arg):\n    while True:\n        pass", timeout=1.5)
    assert not r.ok and "timed out" in r.error


def test_sandbox_huge_allocation_is_killed():
    r = toolsmith.run_sandbox("def run(arg):\n    x = 'a' * (2 * 10**9)\n    return 'no'")
    assert not r.ok and ("MemoryError" in r.error or "killed" in r.error)


def test_sandbox_cpu_limit():
    r = toolsmith.run_sandbox("def run(arg):\n    while True:\n        pass", timeout=10, cpu_s=1)
    assert not r.ok and "killed" in r.error


def test_sandbox_env_has_no_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("MY_SECRET", "x")
    # trusted test code (run_sandbox itself does not AST-check): read the child's whole environment
    r = toolsmith.run_sandbox("import os\ndef run(arg):\n    return repr(dict(os.environ))")
    assert r.ok and "gsk_secret" not in r.output and "123:abc" not in r.output and "MY_SECRET" not in r.output
    assert set(toolsmith._env()) <= {"PATH", "HOME", "LANG", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
                                     "DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
                                     "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY"}


def test_sandbox_audit_hook_blocks_spawn_and_outside_writes(tmp_path):
    outside = tmp_path / "evil.txt"
    r = toolsmith.run_sandbox("import os\ndef run(arg):\n    return str(os.system('true'))")
    assert not r.ok and "blocked" in r.error
    r = toolsmith.run_sandbox(f"def run(arg):\n    open({str(outside)!r}, 'w').write('x')\n    return 'x'")
    assert not r.ok and not outside.exists()
    r = toolsmith.run_sandbox(f"from jarvis_helpers import write_text\ndef run(arg):\n    return write_text({str(outside)!r}, 'x')",
                              write_paths=[str(outside)])
    assert r.ok and outside.read_text() == "x"  # a path the user named is allowed


def test_sandbox_stdout_is_capped():
    r = toolsmith.run_sandbox("def run(arg):\n    for i in range(100000):\n        print('x' * 100)\n    return ''")
    assert r.ok and len(r.output) <= config.SANDBOX_STDOUT_MAX


def test_helpers_refuse_private_hosts_and_secret_files():
    r = toolsmith.run_sandbox("from jarvis_helpers import http_get\ndef run(arg):\n    return http_get('http://127.0.0.1:1')")
    assert not r.ok and "private" in r.error
    r = toolsmith.run_sandbox("from jarvis_helpers import read_text\ndef run(arg):\n    return read_text('~/.ssh/id_rsa')")
    assert not r.ok and "PermissionError" in r.error


def test_named_paths():
    assert toolsmith.named_paths("save it to ~/notes/x.txt and /tmp/a.csv.") == [
        os.path.expanduser("~/notes/x.txt"), "/tmp/a.csv"]


def test_make_tool_runs_once_per_request(gen):
    calls = gen(spec())
    run_make("days until 2027", [True])
    res, asked = run_make("days until 2027", [True])
    assert "already ran" in res.output and asked == [] and len(calls) == 1
