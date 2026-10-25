import json
import shutil

import pytest

from jarvis.core import convert, fastpath


def test_intents():
    i = fastpath.match("convert this pdf into md file")
    assert i.tool == "convert_file" and i.args == {"path": "this", "to": "md", "src_ext": "pdf"}
    assert fastpath.match("convert all jpg in downloads to png").args == {"path": "downloads", "to": "png",
                                                                           "src_ext": "jpg"}
    assert fastpath.match("convert 5 km to miles") is None or fastpath.match("convert 5 km to miles").tool != "convert_file"


def test_images_tables_text(tmp_path):
    from PIL import Image
    Image.new("RGBA", (20, 20), (255, 0, 0, 128)).save(tmp_path / "a.png")
    assert convert.convert(tmp_path / "a.png", "jpg").endswith("a.jpg")
    (tmp_path / "c.csv").write_text("name,phone\nRam,98\n")
    convert.convert(tmp_path / "c.csv", "xlsx")
    convert.convert(tmp_path / "c.xlsx", "json")
    assert json.loads((tmp_path / "c.json").read_text()) == [{"name": "Ram", "phone": "98"}]
    assert "already" in convert.convert(tmp_path / "c.csv", "csv")
    out = tmp_path / "x"
    out.mkdir()
    for n in range(2):
        Image.new("RGB", (10, 10)).save(out / f"{n}.jpg")
    assert "2 images" in convert.convert(out, "pdf", "jpg")


@pytest.mark.skipif(not shutil.which("pdftohtml"), reason="poppler missing")
def test_md_pdf_round_trip(tmp_path):
    (tmp_path / "r.md").write_text("# Title\n\nSome **bold** text.\n\n## Part\n\n- one\n- two\n")
    assert convert.convert(tmp_path / "r.md", "pdf").endswith("r.pdf")
    convert.convert(tmp_path / "r.pdf", "md")
    md = (tmp_path / "r (1).md").read_text()
    assert "# Title" in md and "## Part" in md and "- one" in md and "**bold**" in md


def test_tool_resolves_this(monkeypatch, tmp_path):
    from jarvis.core import focus
    from jarvis.tools.general.convert_file import convert_file
    (tmp_path / "n.md").write_text("hi")
    monkeypatch.setattr(focus, "get_path", lambda *a: str(tmp_path / "n.md"))
    monkeypatch.setattr(focus, "set_path", lambda p: None)
    fn = getattr(convert_file, "func", convert_file)
    assert fn("this", "html", "md").endswith("n.html")
