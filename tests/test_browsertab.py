import pytest
import time

from fastapi.testclient import TestClient

from jarvis.core import browsertab, readlater


def test_extension_tab_is_the_page_for_this_link_and_this_video(monkeypatch):
    from jarvis.api.app import create_app
    from tests.test_api import BASE, settings
    c = TestClient(create_app(settings(token="secret")), base_url=BASE)  # the extension sends no token
    r = c.post("/api/v1/context/tab", json={"url": "https://www.youtube.com/watch?v=yaad", "title": "Yaad - YouTube"},
               headers={"Origin": "chrome-extension://abcdef"})
    assert r.status_code == 200
    assert browsertab.get() == ("https://www.youtube.com/watch?v=yaad", "Yaad - YouTube")
    assert readlater.current_page("anything") == ("https://www.youtube.com/watch?v=yaad", "Yaad - YouTube")
    from jarvis.tools.general import video_download
    assert video_download.this_video() == "https://www.youtube.com/watch?v=yaad"  # not an old clipboard link
    c.post("/api/v1/context/tab", json={"url": "brave://newtab", "title": ""}, headers={"Origin": "chrome-extension://abcdef"})
    assert browsertab.get() is None  # no web page open


def test_old_tab_info_expires(monkeypatch):
    browsertab.put("https://a.b/c", "C")
    real = time.time
    monkeypatch.setattr(browsertab.time, "time", lambda: real() + 7 * 3600)
    assert browsertab.get() is None


@pytest.mark.parametrize("text,q", [
    ("downlaod this movie from youtbe in 1080p with audio \n\nhttps://www.youtube.com/watch?v=RcyW7YQ_5WU", "1080p"),
    ("download this video then https://www.youtube.com/watch?v=RcyW7YQ_5WU", ""),
    ("download this youtube video in 720p https://www.youtube.com/watch?v=RcyW7YQ_5WU", "720p"),
    ("download this video now in 4k https://www.youtube.com/watch?v=RcyW7YQ_5WU&list=RDRcyW7YQ_5WU&start_radio=1", "4k"),
])
def test_words_before_a_pasted_link_never_replace_the_link(text, q):
    """trace 4ad71202be1b: 'in 1080p with audio <link>' became source '' = the browser's open tab, quality lost."""
    from jarvis.core import fastpath
    it = fastpath.video_dl_intent(fastpath.normalize(text))
    assert it.args["source"].startswith("https://www.youtube.com/watch?v=RcyW7YQ_5WU") and it.args["quality"] == q
    assert it.args["audio"] is False  # "with audio" = the video with its sound, not an MP3
