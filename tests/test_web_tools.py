"""Web tools (P7b), fully mocked: no network."""
import pytest

from jarvis.core import config, registry
from jarvis.tools.general import _web, read_webpage, web_search, wikipedia


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(_web, "cache", _web.TTLCache(600))
    monkeypatch.setattr(web_search, "_searx_down_until", 0.0)

    def no_net(*a, **k):
        raise AssertionError("real network in a test")
    monkeypatch.setattr(_web, "client", no_net)


ROWS = [{"title": f"Result {i}", "url": f"https://ex.com/{i}", "snippet": "line one\nline two " * 3}
        for i in range(1, 6)]


def test_registered_in_web_group():
    for name in ("web_search", "wikipedia", "read_webpage"):
        t = registry.REGISTRY.get(name)
        assert t is not None and registry.group_of(t) == "web" and registry.safety_of(t) == "safe"


def test_ddg_when_no_searxng(monkeypatch):
    monkeypatch.setattr(config, "SEARXNG_URL", "")
    seen = []
    monkeypatch.setattr(web_search, "_searx", lambda q, k: seen.append("searx") or ROWS)
    monkeypatch.setattr(web_search, "_ddg", lambda q, k: seen.append("ddg") or ROWS[:k])
    out = web_search.web_search("CarryMinati", k=3)
    assert seen == ["ddg"] and "1. Result 1 - https://ex.com/1" in out and "Result 4" not in out
    assert "\n   line one line two" in out  # snippet flattened to one line


def test_searxng_first_then_fallback(monkeypatch):
    monkeypatch.setattr(config, "SEARXNG_URL", "http://localhost:8888")
    seen = []
    monkeypatch.setattr(web_search, "_ddg", lambda q, k: seen.append("ddg") or ROWS[:k])
    monkeypatch.setattr(web_search, "_searx", lambda q, k: seen.append("searx") or ROWS[:k])
    assert web_search.search("a", 2)[0] == "searxng" and seen == ["searx"]

    def down(q, k):
        seen.append("searx-down")
        raise ConnectionError("refused")
    monkeypatch.setattr(web_search, "_searx", down)
    assert web_search.search("b", 2)[0] == "ddg"
    assert web_search.search("c", 2)[0] == "ddg"  # down: not retried for SEARX_RETRY_S
    assert seen == ["searx", "searx-down", "ddg", "ddg"]


def test_cache_and_output_cap(monkeypatch):
    monkeypatch.setattr(config, "SEARXNG_URL", "")
    calls = []
    long_rows = [{**r, "title": r["title"] * 20, "snippet": "x" * 500} for r in ROWS]
    monkeypatch.setattr(web_search, "_ddg", lambda q, k: calls.append(q) or long_rows[:k])
    a = web_search.web_search("Nepal news", k=8)
    b = web_search.web_search("  nepal   NEWS ", k=8)
    assert a == b and calls == ["Nepal news"]  # second call served from the cache
    assert len(a) <= config.WEB_SEARCH_MAX_CHARS


def test_search_errors_are_short(monkeypatch):
    monkeypatch.setattr(config, "SEARXNG_URL", "")

    def boom(q, k):
        raise TimeoutError("slow")
    monkeypatch.setattr(web_search, "_ddg", boom)
    assert web_search.web_search("x").startswith("error: web search failed")
    assert web_search.web_search("").startswith("error")


def test_wikipedia_fuzzy_fallback(monkeypatch):
    pages = {"CarryMinati": {"type": "standard", "title": "CarryMinati",
                             "extract": "Ajey Nagar, better known as CarryMinati, is an Indian YouTuber.",
                             "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/CarryMinati"}}}}
    seen = []

    def get_json(url, params=None, headers=None):
        assert "Jarvis" in headers["User-Agent"]
        seen.append(params["action"] if params else url.rsplit("/", 1)[-1])
        if "/page/summary/" in url:
            title = url.rsplit("/", 1)[-1]
            return (200, pages[title]) if title in pages else (404, {"type": "not_found"})
        if params["action"] == "opensearch":
            return 200, ["Cariminati", [], [], []]  # prefix match misses the misspelling
        return 200, {"query": {"search": [{"title": "CarryMinati"}]}}
    monkeypatch.setattr(_web, "get_json", get_json)
    out = wikipedia.wikipedia("Cariminati")
    assert out.startswith("CarryMinati: Ajey Nagar") and "wikipedia.org/wiki/CarryMinati" in out
    assert seen == ["Cariminati", "opensearch", "query", "CarryMinati"]
    assert wikipedia.wikipedia("cariminati") == out and len(seen) == 4  # cached


def test_wikipedia_nepali_and_missing(monkeypatch):
    urls = []

    def get_json(url, params=None, headers=None):
        urls.append(url)
        if "ne.wikipedia.org/api" in url:
            return 200, {"type": "standard", "title": "काठमाडौं", "extract": "काठमाडौं नेपालको राजधानी हो।"}
        if "/page/summary/" in url:
            return 404, None
        return 200, (["x", [], [], []] if params["action"] == "opensearch" else {"query": {"search": []}})
    monkeypatch.setattr(_web, "get_json", get_json)
    assert wikipedia.wikipedia("काठमाडौं", lang="ne").startswith("काठमाडौं: काठमाडौं नेपालको")
    assert urls[0].startswith("https://ne.wikipedia.org/")
    assert wikipedia.wikipedia("Zzqxv nothing").startswith("No Wikipedia article")


HTML = """<html><head><title>My Article</title><style>.x{color:red}</style></head><body>
<nav>Home | About</nav><script>var a = 1;</script><main><h1>Big news</h1><p>First   paragraph
text.</p><p>Second paragraph.</p></main><footer>(c) 2026</footer></body></html>"""


@pytest.mark.parametrize("use_lxml", [True, False])
def test_html_to_text(monkeypatch, use_lxml):
    if not use_lxml:
        import builtins
        real = builtins.__import__

        def no_lxml(name, *a, **k):
            if name.startswith("lxml"):
                raise ImportError("no lxml")
            return real(name, *a, **k)
        monkeypatch.setattr(builtins, "__import__", no_lxml)
    title, text = _web.html_to_text(HTML)
    assert title == "My Article"
    assert "Big news" in text and "First paragraph text." in text and "Second paragraph." in text
    assert "var a" not in text and "color:red" not in text and "Home | About" not in text


def test_read_webpage(monkeypatch):
    monkeypatch.setattr(read_webpage, "fetch", lambda url: ("text/html; charset=utf-8", HTML))
    out = read_webpage.read_webpage("example.com/a", max_chars=300)
    assert out.startswith("My Article\n") and "First paragraph text." in out and len(out) <= 300
    monkeypatch.setattr(read_webpage, "fetch", lambda url: ("text/html", "<p>" + "word " * 2000 + "</p>"))
    assert len(read_webpage.read_webpage("https://ex.com", max_chars=1500)) <= 1500
    assert registry.REGISTRY.call("read_webpage", {"url": "https://ex.com", "max_chars": 1500}).output.__len__() > 800
    monkeypatch.setattr(read_webpage, "fetch", lambda url: ("application/pdf", "%PDF"))
    assert read_webpage.read_webpage("https://ex.com/x.pdf").startswith("error: not a text page")
    assert read_webpage.read_webpage("http://127.0.0.1:8000/admin").startswith("error: local")
    assert read_webpage.read_webpage("ftp://ex.com").startswith("error")
