import shutil

import pytest

from jarvis.core import vault


@pytest.mark.skipif(not shutil.which("gpg"), reason="gpg missing")
def test_lock_unlock_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("GNUPGHOME", str(tmp_path / "gnupg"))
    (tmp_path / "gnupg").mkdir(mode=0o700)
    d = tmp_path / "exam"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "q.txt").write_text("secret answers")
    locked = vault.lock(d, "pass1234")
    assert locked.name == "exam.locked.gpg" and not d.exists()
    assert b"secret answers" not in locked.read_bytes()
    with pytest.raises(vault.VaultError, match="wrong password"):
        vault.unlock(locked, "nope")
    assert locked.exists() and not d.exists()  # a wrong password changes nothing
    out = vault.unlock(locked, "pass1234")
    assert (out / "sub" / "q.txt").read_text() == "secret answers" and not locked.exists()


def test_tool_never_takes_password_in_chat(monkeypatch, tmp_path):
    from jarvis.tools.general.folder_lock import folder_lock
    import inspect
    assert "password" not in inspect.signature(getattr(folder_lock, "func", folder_lock)).parameters
