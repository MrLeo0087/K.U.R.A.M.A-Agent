"""Error memory: parse, signature, explain once (LLM) then from memory (0 tokens) with the user's fix."""
from jarvis.core import config, errmem, fastpath, llm, registry, safety, training

TB = '''Traceback (most recent call last):
  File "{f}", line 3, in <module>
    out = model(x)
  File "/usr/lib/python3/dist-packages/torch/nn/modules/module.py", line 1501, in _call_impl
    return forward_call(*args)
RuntimeError: mat1 and mat2 shapes cannot be multiplied (64x512 and 256x10)'''


def fake_llm(monkeypatch, reply="The layer expects 256 inputs but gets 512: change nn.Linear(256, 10) to 512."):
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: calls.append(msgs) or reply)
    return calls


def test_parse_and_signature(tmp_path):
    src = tmp_path / "train.py"
    src.write_text("import torch\nx = torch.randn(64, 512)\nout = model(x)\n")
    p = errmem.parse(TB.format(f=src))
    assert p["kind"] == "RuntimeError" and p["error"].startswith("RuntimeError: mat1")
    assert errmem.user_frames(p["frames"]) == [(str(src), 3, "<module>")]
    assert ">3: out = model(x)" in errmem.code_context(p["frames"])
    assert errmem.signature("RuntimeError: shapes (64x512 and 256x10)") == \
        errmem.signature("RuntimeError: shapes (32x128 and 64x2)")
    assert errmem.signature("KeyError: 'label'") == errmem.signature("KeyError: 'target'")
    assert errmem.signature("KeyError: 'x'") != errmem.signature("ValueError: 'x'")
    assert errmem.parse("bash: torchrun: command not found")["kind"] == "terminal"


def test_explain_once_then_from_memory_with_fix(tmp_path, monkeypatch):
    src = tmp_path / "train.py"
    src.write_text("import torch\nx = torch.randn(64, 512)\nout = model(x)\n")
    calls = fake_llm(monkeypatch)
    r = errmem.explain(TB.format(f=src))
    assert not r["known"] and "change nn.Linear" in r["explanation"] and len(calls) == 1
    assert "out = model(x)" in calls[0][1]["content"]  # the user's own code went in, not torch's
    assert "remind you: set in_features to 512" in errmem.remember_fix("set in_features to 512")
    other = TB.format(f=src).replace("64x512 and 256x10", "32x1024 and 128x5")
    r2 = errmem.explain(other)
    assert r2["known"] and r2["count"] == 2 and len(calls) == 1  # 0 tokens the second time
    text = errmem.answer(r2)
    assert "Last time you fixed it by: set in_features to 512" in text and "2 times" in text


def test_tool_reads_clipboard_and_training_uses_memory(monkeypatch):
    calls = fake_llm(monkeypatch, "Install it in this venv: pip install timm.")
    from jarvis.tools.general import read_clipboard as rc
    monkeypatch.setattr(rc, "read_clipboard", lambda n=0: "ModuleNotFoundError: No module named 'timm'")
    out = registry.call("fix_error", {}).output
    assert "pip install timm" in out and len(calls) == 1
    assert "Got it" in registry.call("fix_error", {"action": "fixed", "text": "pip install timm in .venv"}).output
    monkeypatch.setattr(config, "TRAINING_EXPLAIN", True)
    why = training.explain("ModuleNotFoundError: No module named 'torchvision'", ["import torchvision"])
    assert "pip install timm" in why and "You fixed it before by: pip install timm in .venv" in why
    assert len(calls) == 1
    assert "1x" in registry.call("fix_error", {"action": "list"}).output or "2x" in \
        registry.call("fix_error", {"action": "list"}).output


def test_fastpath_routes_errors(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(TB.format(f="/tmp/t.py"))
    assert it.tool == "fix_error" and it.args["action"] == "explain" and "mat1" in it.args["text"]
    assert fastpath.match("what does this error mean").args == {"action": "explain"}
    assert fastpath.match("I fixed it by lowering the batch size").args == {"action": "fixed",
                                                                            "text": "lowering the batch size"}
    assert registry.safety_of(registry.get("fix_error")) == "safe"
