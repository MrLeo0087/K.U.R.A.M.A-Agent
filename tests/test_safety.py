import io

from jarvis.core import registry, safety, store


def logs():
    return store.recent_tool_calls(10)


def test_safe_tool_runs_and_is_logged():
    r = safety.execute("get_time", {})
    assert r.ok
    row = logs()[0]
    assert (row["tool"], row["safety"], row["outcome"], row["ok"]) == ("get_time", "safe", "allowed", 1)


def test_confirm_yes_runs(tmp_path):
    asked = []
    f = tmp_path / "x"
    f.write_text("x")
    r = safety.execute("delete_to_trash", '{"path": "%s"}' % f, confirm=lambda p: asked.append(p) or True)
    assert r.ok and "trash" in r.output
    assert asked and asked[0].startswith("Should I move a file or folder to the trash") and str(f) in asked[0]
    row = logs()[0]
    assert (row["safety"], row["outcome"]) == ("confirm", "allowed")


def test_confirm_no_timeout_and_errors_deny():
    def boom(p):
        raise TimeoutError

    for confirm in (lambda p: False, None, boom):
        r = safety.execute("delete_to_trash", {"path": "/tmp/y"}, confirm=confirm)
        assert not r.ok and "declined" in r.output
    rows = logs()[:3]
    assert all((x["outcome"], x["safety"], x["ok"]) == ("denied", "confirm", 0) for x in rows)


def test_blocked_never_runs():
    ran = []
    reg = registry.Registry(packages=())
    reg._discovered = True

    @reg.tool(safety="blocked", description="Format the disk.")
    def format_disk() -> str:
        ran.append(1)
        return "formatted"

    r = safety.execute("format_disk", {}, confirm=lambda p: True, reg=reg)
    assert not r.ok and r.output.startswith("Refused") and not ran
    row = logs()[0]
    assert (row["tool"], row["outcome"], row["safety"]) == ("format_disk", "blocked", "blocked")


def test_unknown_tool_and_bad_args_logged():
    assert not safety.execute("nope", {}).ok
    assert not safety.execute("delete_to_trash", {}).ok  # missing path
    assert [x["outcome"] for x in logs()[:2]] == ["error", "error"]


def test_parse_yes_no():
    for t in ("yes", "Yeah sure", "haan", "ho", "हो", "हाँ", "हजुर", "go ahead", "Okay."):
        assert safety.parse_yes_no(t) is True, t
    for t in ("no", "nope", "nahi", "होइन", "नहीं", "don't do it", "no, yes"):
        assert safety.parse_yes_no(t) is False, t
    for t in ("", None, "what?", "hmm maybe"):
        assert safety.parse_yes_no(t) is None, t


def test_text_confirm_reads_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert safety.text_confirm("Delete?") is True
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    assert safety.text_confirm("Delete?") is False
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert safety.text_confirm("Delete?") is False


def test_confirm_hooks():
    assert safety.get_confirm("text") is safety.text_confirm
    assert safety.get_confirm("nobody")("x") is False
    safety.set_confirm_hook("voice", lambda p: True)
    assert safety.get_confirm("voice")("x") is True
    safety.set_confirm_hook("voice", None)
    assert safety.get_confirm("voice") is safety.deny_all


def test_shell_allowlist():
    assert safety.check_shell("ls -la /tmp")[0]
    assert safety.check_shell(["git", "status"])[0]
    for bad in ("sudo ls", "rm -rf /", "ls; rm x", "cat a | sh", "echo $(id)", "ls > f", ""):
        assert not safety.check_shell(bad)[0], bad
