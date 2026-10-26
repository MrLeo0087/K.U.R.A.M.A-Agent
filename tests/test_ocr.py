import shutil

import pytest

from jarvis.core import config, fastpath, ocr


def _img(path, text, size=(900, 200)):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(im).text((20, 60), text, fill="black", font=font)
    im.save(path)
    return path


@pytest.fixture
def copied(monkeypatch):
    got = []
    monkeypatch.setattr(ocr, "copy", got.append)
    return got


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_tesseract_reads_printed_text_for_free(tmp_path, copied, monkeypatch):
    monkeypatch.setattr(ocr, "vision", lambda p: pytest.fail("printed text must not use the AI"))
    p = _img(tmp_path / "note.png", "Meeting at five tomorrow")
    out = ocr.run("file", str(p))
    assert "Meeting at five tomorrow" in out and copied == ["Meeting at five tomorrow"]
    assert "(Copied.)" in out


def test_poor_result_uses_vision_once(tmp_path, copied, monkeypatch):
    p = _img(tmp_path / "hand.png", "")
    monkeypatch.setattr(ocr, "tesseract", lambda p: ocr.Result("~~ ,, ..", "tesseract", 20.0))
    calls = []
    monkeypatch.setattr(ocr, "vision", lambda p: calls.append(p) or ocr.Result("Buy milk and eggs", "vision", 100.0))
    out = ocr.run("file", str(p))
    assert out.startswith("Buy milk and eggs") and "read by the AI" in out and len(calls) == 1
    monkeypatch.setattr(config, "OCR_VISION", False)  # never send pictures: Tesseract's best try
    out = ocr.run("file", str(p))
    assert "Some words may be wrong" in out or "couldn't find any text" in out


def test_vision_failure_keeps_tesseract(tmp_path, copied, monkeypatch):
    p = _img(tmp_path / "x.png", "")
    monkeypatch.setattr(ocr, "tesseract", lambda p: ocr.Result("half readable", "tesseract", 40.0))

    def boom(p):
        raise RuntimeError("AI is off")
    monkeypatch.setattr(ocr, "vision", boom)
    assert ocr.run("file", str(p)).startswith("half readable")


def test_not_a_picture(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    assert "isn't a picture" in ocr.run("file", str(f))


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    cases = {"read this area": ("area", None), "ocr this": ("area", None), "read the text on my screen": ("screen", None),
             "what does this photo say": ("file", "this"), "read the copied image": ("clipboard", None),
             "read handwriting from note.jpg": ("file", "note.jpg"), "what is written in this picture": ("file", "this")}
    for text, (src, path) in cases.items():
        i = fastpath.match(text)
        assert i.tool == "read_text" and i.args["source"] == src and i.args.get("path") == path, text
    assert fastpath.match("take a screenshot").tool == "screenshot"
    assert fastpath.match("convert this image to png").tool == "convert_file"
    assert (fastpath.match("what is this photo of") or fastpath.Intent("", "", "", {})).tool != "read_text"


def test_telegram_photo_with_read_caption(tmp_path, monkeypatch):
    from jarvis.core import phone
    monkeypatch.setattr(phone, "download", lambda fid: (b"jpg", None))
    monkeypatch.setattr(phone, "_folder", lambda c: tmp_path)
    monkeypatch.setattr(ocr, "read", lambda p: ocr.Result("Dear Ram, see you at 5.", "tesseract", 90.0))
    msg = {"photo": [{"file_id": "a"}], "caption": "read this"}
    assert phone.save_incoming(msg) == "Dear Ram, see you at 5."
    assert phone.save_incoming({"photo": [{"file_id": "b"}], "caption": ""}).startswith("Saved on your laptop")
