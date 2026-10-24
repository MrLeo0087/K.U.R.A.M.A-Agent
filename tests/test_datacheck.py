"""Dataset quick check on small generated tables and image folders."""
import random

from PIL import Image

from jarvis.core import config, datacheck, fastpath, registry


def test_table_problems(tmp_path):
    rows = ["id,age,city,notes,const,label_code,label"]
    rnd = random.Random(1)
    for i in range(200):
        lab = "spam" if i % 10 == 0 else "ham"
        rows.append(f"{i},{rnd.randint(18, 60)},{rnd.choice(['ktm', 'pkr'])},{'' if i % 2 else 'x'},1,"
                    f"{1 if lab == 'spam' else 0},{lab}")
    rows += [rows[5], rows[6]]  # duplicates
    f = tmp_path / "train.csv"
    f.write_text("\n".join(rows) + "\n")
    assert registry.call("check_dataset", {"path": str(f)}).output.startswith("train.csv: 202 rows")
    out = datacheck.check(str(f))  # (the tool's copy for the LLM is cut; problems come first for that reason)
    assert "202 rows x 7 columns" in out and "2 duplicate rows" in out
    assert "'id' is (almost) unique for every row" in out and "'const' has a single value" in out
    assert "'notes' is 50% empty" in out and "Label 'label': ham: 182 (90%), spam: 20 (10%)" in out
    assert "imbalanced" in out and "'label_code' predicts 'label' perfectly" in out
    assert "- age: int" in out and "range 18..60" in out


def test_jsonl_and_unsupported(tmp_path):
    f = tmp_path / "d.jsonl"
    f.write_text('{"text": "hi", "label": 1}\n{"text": "yo", "label": 0}\n{"text": "hey", "label": 1}\n')
    out = datacheck.check(str(f))
    assert "3 rows x 2 columns" in out and "Label 'label'" in out
    (tmp_path / "x.parquet").write_text("x")
    assert "needs pandas" in datacheck.check(str(tmp_path / "x.parquet"))


def test_image_folder_splits_leakage_and_broken(tmp_path):
    def img(p, size=(32, 32), mode="RGB", color=(255, 0, 0)):
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new(mode, size, color if mode == "RGB" else 128).save(p)
    for i in range(10):
        img(tmp_path / "train" / "cat" / f"c{i}.png", color=(i, 0, 0))
    img(tmp_path / "train" / "dog" / "d0.png", size=(64, 48), color=(0, 9, 9))
    img(tmp_path / "test" / "cat" / "same.png", color=(3, 0, 0))  # identical to train/cat/c3.png
    img(tmp_path / "test" / "dog" / "g.png", mode="L")
    (tmp_path / "test" / "dog" / "broken.jpg").write_bytes(b"not an image")
    out = registry.call("check_dataset", {"path": str(tmp_path)}).output
    assert "train: cat 10, dog 1" in out and "classes are imbalanced" in out
    assert "different sizes" in out and "Mixed colour modes" in out and "1 unreadable image" in out
    assert "appear in more than one split" in out


def test_phrase(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match("check my dataset data/train.csv before training")
    assert (it.tool, it.args) == ("check_dataset", {"path": "data/train.csv"})
