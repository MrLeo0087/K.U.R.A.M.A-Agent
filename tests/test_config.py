import pathlib
import re

from jarvis.core import config


def test_models_and_voices():
    for m in (config.LLM_DEFAULT, config.LLM_FAST, config.LLM_VISION, config.STT_MODEL, config.STT_FALLBACK):
        assert isinstance(m, str) and m
    assert config.STT_MODEL == "whisper-large-v3-turbo" and config.STT_FALLBACK == "whisper-large-v3"
    assert config.VOICES == {"en": "en-GB-RyanNeural", "en_multi": "en-US-AvaMultilingualNeural",
                             "hi": "hi-IN-MadhurNeural", "ne": "ne-NP-SagarNeural"}
    assert config.TIER_CHAIN["smart"] == [config.LLM_DEFAULT, config.LLM_FAST]
    for m in config.TIERS.values():
        assert config.DAILY_TOKEN_BUDGET[m] > 0
    assert config.DB_PATH.parent == pathlib.Path(__import__("os").getenv("JARVIS_DATA_DIR", str(config.ROOT / "data")))  # (DATA_DIR is a tmp dir in tests)


def test_model_ids_only_in_config():
    pkg = pathlib.Path(config.__file__).resolve().parents[1]
    ids = [config.LLM_DEFAULT, config.LLM_FAST, config.LLM_VISION, config.STT_MODEL]
    pat = re.compile("|".join(re.escape(i) for i in ids))
    for f in pkg.rglob("*.py"):
        if f.name != "config.py":
            assert not pat.search(f.read_text()), f"model ID hardcoded in {f}"
