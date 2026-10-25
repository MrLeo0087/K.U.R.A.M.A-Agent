from jarvis.core import fastpath, installer


def test_intents_split_apps_and_python():
    assert fastpath.match("install obs").tool == "install_app"
    assert fastpath.match("install numpy").tool == "python_env"
    assert fastpath.match("pip install flask").tool == "python_env"
    assert fastpath.match("uninstall zoom").args == {"action": "remove", "name": "zoom"}
    assert fastpath.match("update all apps").args["action"] == "update"


def test_argv_per_source():
    assert installer._argv("install", installer.Pkg("apt", "vlc"))[:2] == ["pkexec", "env"]
    assert installer._argv("install", installer.Pkg("snap", "code", True)) == ["snap", "install", "code", "--classic"]
    assert installer._argv("remove", installer.Pkg("flatpak", "org.x.App"))[:2] == ["flatpak", "uninstall"]


def test_install_runs_in_background(monkeypatch):
    ran = []
    monkeypatch.setattr(installer, "find", lambda n: [installer.Pkg("snap", "postman")])
    monkeypatch.setattr(installer, "_bg", lambda argv, title: ran.append(argv))
    assert "Installing postman from snap" in installer.install("postman")
    assert ran == [["snap", "install", "postman"]]
    monkeypatch.setattr(installer, "find", lambda n: [installer.Pkg("apt", "vlc", installed=True)])
    assert "already installed" in installer.install("vlc")


def test_tool_is_confirm_level():
    from jarvis.core.registry import REGISTRY
    REGISTRY._ensure()
    assert REGISTRY.tools["install_app"].metadata["safety"] == "confirm"
