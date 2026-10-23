"""Sandbox runner for generated tools (trusted code). Started by toolsmith as

    python -I runner.py <tool.py>      (spec JSON on stdin, cwd = data/sandbox/<id>/)

It lowers its own rlimits (AS, CPU, NOFILE, FSIZE, no core dumps) before touching the generated
code, installs an audit hook that blocks process spawning, sockets, deletes and writes outside the
allowed paths (the jarvis_helpers functions open a short gate for their own work), then runs
`run(arg)` and writes one JSON line {"ok", "out"|"error"} to stdout. Prints from the tool are
captured and capped. Never imports anything from the jarvis package (no config, no secrets).
"""
import io
import json
import os
import resource
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))

_BLOCK = ("os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty", "os.kill",
          "os.killpg", "subprocess.Popen", "socket.connect", "socket.bind", "socket.getaddrinfo",
          "socket.sendto", "socket.sendmsg", "os.remove", "os.unlink", "os.rmdir", "os.rename",
          "os.replace", "shutil.rmtree", "shutil.move", "shutil.copyfile", "os.chmod", "os.chown",
          "os.symlink", "os.link", "os.truncate", "os.mkdir", "ctypes.dlopen", "ctypes.dlsym",
          "ctypes.cdata", "os.putenv", "os.unsetenv", "sys._getframe", "builtins.input", "webbrowser.open",
          "pty.spawn", "os.setuid", "os.setgid")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


class _Capped(io.TextIOBase):
    def __init__(self, limit: int):
        self.limit, self.buf = limit, []
        self.size = 0

    def write(self, s):  # keep the first `limit` chars, drop the rest
        if self.size < self.limit:
            part = s[: self.limit - self.size]
            self.buf.append(part)
            self.size += len(part)
        return len(s)

    def text(self) -> str:
        return "".join(self.buf)


def _limits(spec: dict) -> None:
    mem = int(spec.get("mem_mb", 256)) * 1024 * 1024
    cpu = int(spec.get("cpu_s", 10))
    for res, soft, hard in ((resource.RLIMIT_AS, mem, mem), (resource.RLIMIT_CPU, cpu, cpu + 1),
                            (resource.RLIMIT_NOFILE, int(spec.get("nofile", 64)), int(spec.get("nofile", 64))),
                            (resource.RLIMIT_CORE, 0, 0),
                            (resource.RLIMIT_FSIZE, int(spec.get("fsize", 2_000_000)),
                             int(spec.get("fsize", 2_000_000)))):
        resource.setrlimit(res, (soft, hard))


def main() -> int:
    spec = json.loads(sys.stdin.read() or "{}")
    real_out = sys.stdout
    limit = int(spec.get("out_max", 4096))
    with open(sys.argv[1], encoding="utf-8") as fh:
        source = fh.read()
    sys.path.insert(0, HERE)  # jarvis_helpers only (-I keeps cwd and PYTHONPATH out)
    import jarvis_helpers as H

    H.configure(spec)
    code = compile(source, "tool.py", "exec")
    _limits(spec)

    def hook(event, args):
        if H._GATE[0]:
            return
        if event in _BLOCK or event.startswith(("os.exec", "os.spawn", "os.posix_spawn")):
            raise PermissionError(f"blocked in the sandbox: {event}")
        if event == "open" and args and not isinstance(args[0], int):
            mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
            write = any(c in mode for c in "wax+") if isinstance(mode, str) else bool((flags or 0) & _WRITE_FLAGS)
            if write and not H.write_ok(args[0]):
                raise PermissionError("blocked in the sandbox: writing outside the allowed folders")

    sys.addaudithook(hook)
    captured = _Capped(limit)
    sys.stdout = captured
    try:
        ns: dict = {"__name__": "jarvis_tool"}
        exec(code, ns)
        result = ns["run"](spec.get("arg", "")) if spec.get("pass_arg", True) else ns["run"]()
        out = (captured.text() + ("" if result is None else str(result))).strip()
        real_out.write(json.dumps({"ok": True, "out": out[:limit]}))
    except BaseException as e:  # noqa: BLE001  (report everything, incl. MemoryError / SystemExit)
        tb = traceback.format_exc()[-1500:]
        real_out.write(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "trace": tb}))
    real_out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
