"""Owner report 11-01: organize 'this' folder, BS code, random image as text, Colab/Kaggle cell by meaning."""
import pytest

from jarvis.core import fastpath, semantic
from jarvis.tools.general import write_file


@pytest.mark.parametrize("text", ["/home/leo/Documents\n\norganize this folder .. make less folder",
                                  "organize file bro . you do no organize it", "organize it"])
def test_organize_junk_names_mean_the_folder_in_use(text):
    it = fastpath.match(text)
    assert it.tool == "organize_files" and it.args["folder"] == "this"


@pytest.mark.parametrize("text", ["open this folder in BS code", "B.S. code open karo", "open kurama in bs code"])
def test_bs_code_is_vs_code(text):
    assert "VS Code" in fastpath.normalize(text) or "vs code" in fastpath.normalize(text).lower()


@pytest.mark.parametrize("path", ["/home/leo/random_image.png", "pic.JPG", "song.mp3"])
def test_no_binary_files_from_text(path):
    assert write_file.write_file(path, "iVBORw0KGgo=").startswith("error: write_file only writes text")


@pytest.mark.parametrize("text", ["Setup, Colab, Notebook,", "setup kaggle notebook for training bro",
                                  "give me code for kaggle notebook so kurama watch my training"])
def test_colab_cell_by_meaning(monkeypatch, text):
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: ("colab_setup", 0.95))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    it = fastpath.meaning_intent(text)
    assert (it.tool, it.args) == ("training", {"action": "colab"})
