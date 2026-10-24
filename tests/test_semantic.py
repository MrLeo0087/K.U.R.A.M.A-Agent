"""Semantic router: groups by meaning with a fake embedder (no model, no network)."""
import numpy as np

from jarvis.core import config, router, semantic

VOCAB = ["slow", "laggy", "memory", "loud", "sound", "joke", "hello", "rain", "umbrella", "commit"]


class FakeEmbedder:
    loaded = True

    def embed(self, texts, query=False):
        rows = []
        for t in texts:
            v = np.array([t.lower().count(w) for w in VOCAB], dtype=np.float32) + 0.01
            rows.append(v / np.linalg.norm(v))
        return np.vstack(rows)


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(semantic, "_embedder", FakeEmbedder())
    monkeypatch.setattr(semantic, "_index", None)
    monkeypatch.setattr(semantic, "_docs", lambda: [("system", "laptop slow laggy memory"), ("audio", "sound loud"),
                                                    ("weather", "rain umbrella"), (semantic.CHAT, "hello joke")])


def test_match_by_meaning_and_chat_wins(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SEMANTIC_MIN", 0.5)
    assert semantic.match("everything is so laggy and slow") == ["system"]
    assert semantic.match("tell me a joke, hello") == []  # plain chat: no tools
    assert (tmp_path / "semantic_router.npz").exists()  # embedded once, cached


def test_router_uses_semantic_before_the_llm_classifier(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SEMANTIC_MIN", 0.5)
    monkeypatch.setattr(router, "classify", lambda *a: (_ for _ in ()).throw(AssertionError("no LLM call")))
    r = router.route("umbrella needed?", log_it=False)  # no keyword matches
    assert r.method == "semantic" and r.groups == ["weather"]


def test_extra_group_only_when_model_is_warm(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SEMANTIC_ADD_MIN", 0.5)
    assert semantic.extra("so laggy and slow", ["audio"]) == "system"
    monkeypatch.setattr(semantic, "_embedder", None)
    assert semantic.extra("so laggy and slow", ["audio"]) is None
