from jarvis.core import fastpath, guard, phonecmds, reset, slash
from jarvis.workers import telegram_bot


def test_telegram_commands_exist_on_the_laptop():
    tg = {c for c, _ in telegram_bot.MENU} | {"video", "here", "history", "changepass", "unlock", "clear", "reset"}
    have = {n for c in slash.COMMANDS for n in (c.name, *c.aliases)}
    assert tg <= have, tg - have


def test_camera_to_workspace_and_phone_only(monkeypatch, tmp_path):
    from jarvis.core import config
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    pic = tmp_path / "g.jpg"
    pic.write_bytes(b"jpg")
    monkeypatch.setattr(guard, "photo", lambda: pic)
    assert "It's in the workspace" in phonecmds.run("camera") and list((tmp_path / "images").glob("*-camera.jpg"))
    assert "Telegram" in phonecmds.run("control") and "/lockscreen" in phonecmds.run("lock")
    monkeypatch.setattr(reset, "clear_recent", lambda agent=None: "cleared")
    assert "Send '/clear yes'" in phonecmds.run("clear") and phonecmds.run("clear", "yes") == "cleared"
    i = fastpath.match("/mute ram 20")
    assert i.tool == "_cmd" and i.args == {"cmd": "mute", "arg": "ram 20"}
