import base64
import json

from jarvis.core import config, decode, fastpath


def test_auto_detects_each_kind():
    k = lambda s: decode.convert(s)[0]
    assert k('{"a":1,"b":[1,2]}') == "JSON" and decode.convert("{'a': True}")[1] == '{\n  "a": true\n}'
    hdr = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps({"sub": "ram", "exp": 1700000000}).encode()).decode().rstrip("=")
    kind, out = decode.convert(f"{hdr}.{body}.sig")
    assert kind == "JWT" and '"sub": "ram"' in out and "EXPIRED" in out
    assert k("1761465600") == "timestamp" and "2025" in decode.convert("1761465600")[1]
    assert decode.convert("name=Ram%20Bahadur&city=Kathmandu")[1] == "name = Ram Bahadur\ncity = Kathmandu"
    assert decode.convert("hello%20world%21")[1] == "hello world!"
    assert decode.convert(base64.b64encode("नमस्ते Ram".encode()).decode())[1] == "नमस्ते Ram"
    assert decode.convert("\\u0928\\u092e\\u0938\\u094d\\u0924\\u0947")[1] == "नमस्ते"
    assert decode.convert("Tom &amp; Jerry &lt;3")[1] == "Tom & Jerry <3"
    assert decode.convert("48656c6c6f20776f726c64")[1] == "Hello world"
    assert decode.convert("<a><b>1</b></a>")[1] == "<a>\n  <b>1</b>\n</a>"
    assert decode.convert("just some words") is None


def test_encode_and_run(monkeypatch):
    from jarvis.core import rewrite
    copied = []
    monkeypatch.setattr(rewrite, "_xclip", lambda a, text=None: copied.append(text))
    assert decode.convert("hi there", "encode_base64")[1] == "aGkgdGhlcmU="
    assert decode.convert("a b&c", "encode_url")[1] == "a%20b%26c"
    out = decode.run("auto", "1761465600")
    assert out.startswith("timestamp:") and out.endswith("(Copied.)") and copied
    assert "couldn't tell" in decode.run("auto", "plain words")


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    cases = {"decode this": "auto", "decode this base64": "base64", "prettify this json": "json",
             "what time is this timestamp": "timestamp", "encode this to base64": "encode_base64",
             "url decode this": "url", "decode this jwt token": "jwt", "url encode this": "encode_url"}
    for text, mode in cases.items():
        i = fastpath.match(text)
        assert i and i.tool == "decode_text" and i.args["mode"] == mode, text
    assert fastpath.match("format this file").tool == "code_tidy"
