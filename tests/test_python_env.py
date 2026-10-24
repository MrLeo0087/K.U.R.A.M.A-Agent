"""python_env: install into the project's own venv (asks first, heavy packages warned, torch CPU wheels)."""
import subprocess
from types import SimpleNamespace

from jarvis.core import config, errmem, fastpath, llm, registry, safety
from jarvis.tools.interactive import python_env as pe


def test_pip_names_and_venv(tmp_path):
    assert pe.pip_name("ModuleNotFoundError: No module named 'cv2'") == "opencv-python"
    assert pe.pip_name("No module named 'sklearn.metrics'") == "scikit-learn"
    assert pe.pip_name("timm") == "timm" and pe.pip_name("my_pkg") == "my-pkg"
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    sub = tmp_path / "src"
    sub.mkdir()
    assert pe.project_python(sub) == (str(tmp_path / ".venv/bin/python"), f"{tmp_path.name}/.venv")


def test_install_asks_warns_and_uses_cpu_torch(tmp_path, monkeypatch):
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "python").write_text("")
    ran, asked = [], []
    monkeypatch.setattr(pe.subprocess, "run", lambda args, **k: ran.append(args) or SimpleNamespace(
        returncode=0, stdout="Successfully installed timm-1.0", stderr=""))
    no = safety.execute("python_env", {"action": "install", "package": "timm", "folder": str(tmp_path)},
                        confirm=lambda p: asked.append(p) or False)
    assert "said no" in no.output and not ran and f"{tmp_path.name}/venv" in asked[0]
    ok = safety.execute("python_env", {"action": "install", "package": "No module named 'timm'",
                                       "folder": str(tmp_path)}, confirm=lambda p: True)
    assert ok.output.startswith("Successfully installed timm") and ran[-1][0] == str(tmp_path / "venv/bin/python")
    safety.execute("python_env", {"action": "install", "package": "torch", "folder": str(tmp_path)},
                   confirm=lambda p: asked.append(p) or True)
    assert "HEAVY" in asked[-1] and "https://download.pytorch.org/whl/cpu" in ran[-1]
    assert "doesn't look like" in safety.execute("python_env", {"action": "install", "package": "x; rm -rf /",
                                                                "folder": str(tmp_path)}, confirm=lambda p: True).output


def test_install_it_after_module_error(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "timm isn't installed in this venv.")
    r = errmem.explain("ModuleNotFoundError: No module named 'timm'")
    assert "Say 'install timm'" in errmem.answer(r)
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match("install it")
    assert it.tool == "python_env" and "timm" in it.args["package"]
    assert fastpath.match("install numpy in my kurama project").args == {"action": "install", "package": "numpy",
                                                                        "folder": "kurama"}
    assert registry.resolve("env_doctor", {"path": "x"}) == ("python_env", {"folder": "x", "action": "check"})
