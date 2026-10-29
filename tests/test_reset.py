"""Reset KURAMA = a brand-new KURAMA: every record gone (backed up first); password, settings, Telegram position kept."""
from jarvis.core import config, reset, store, todos


def test_factory_reset_forgets_everything_but_keeps_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "MEMORY_DB_PATH", tmp_path / "memory.db")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "chat.log").write_text("old chat")
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUTPUTS_DIR / "essay.md").write_text("essay")
    store.add_message("user", "my name is Leo")
    todos.add("buy milk")
    store.schedule_add("call mom", "reminder", 9e9)
    store.kv_set("power_mode", "smart")
    store.kv_set("telegram_offset", "42")
    store.kv_set("assistant_name", "Jarvis")
    from pathlib import Path
    Path(config.EXPENSES_FILE).write_text("money")
    msg = reset.reset_all()
    assert msg.startswith("KURAMA is brand new")
    assert todos.items() == [] and store.schedules_list(enabled_only=False) == []
    assert store.kv_get("power_mode") == "smart" and store.kv_get("telegram_offset") == "42"
    assert not store.kv_get("assistant_name") and store.messages_search("Leo") == []
    store.add_message("user", "fresh start")  # the search index still works after the wipe
    assert store.messages_search("fresh")
    assert not Path(config.EXPENSES_FILE).exists() and not list(config.OUTPUTS_DIR.iterdir())
    backups = list((tmp_path / "reset-backups").iterdir())
    assert backups and (backups[0] / "outputs" / "essay.md").exists() and (backups[0] / "test.db").exists()
    assert (backups[0] / "logs" / "chat.log").exists()
    assert list(tmp_path.parent.glob("KURAMA-backup-*/expenses.xlsx"))
