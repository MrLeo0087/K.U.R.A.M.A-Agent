import threading
import time

from jarvis.core import config, tts


def test_splitter_streaming_cases():
    sp = tts.SentenceSplitter()
    got = []
    for d in ["Hello the", "re. How are", " you? I'm fine", "! पानी चाहिन्छ।", "नमस्ते", "\nPi is 3.14 ok"]:
        got += sp.feed(d)
    got.append(sp.flush())
    assert got == ["Hello there.", "How are you?", "I'm fine!", "पानी चाहिन्छ।", "नमस्ते",
                   "Pi is 3.14 ok"]
    assert tts.split_sentences("1. First item.\n2. Second item.") == ["1. First item.", "2. Second item."]
    assert tts.split_sentences("Run:\n```py\nx = 1\ny = 2\n```\nDone.") == \
        ["Run:", "(code omitted).", "Done."]


def test_clean_for_speech():
    s = tts.clean_for_speech("## Title\n**Bold** see [docs](https://x.y) or `ls -la` 😀 https://a.b/c")
    assert s == "Title Bold see docs or ls -la a link"
    assert tts.voice_for("ne") == config.VOICES["ne"] and tts.voice_for("xx") == config.VOICES["en_multi"]


class FakePlayer:
    def __init__(self):
        self.writes, self.stopped, self.finished = [], False, False
        self.got_first = threading.Event()

    def start(self):
        return self

    def write(self, data):
        if self.stopped:
            return False
        self.writes.append(data)
        self.got_first.set()
        return True

    def finish(self):
        self.finished = True

    def stop(self):
        self.stopped = True


async def fake_synth(text, voice):
    yield f"{voice}|".encode()
    yield text.encode()


def test_stream_order_and_first_sentence_before_llm_finishes():
    player = FakePlayer()
    sp = tts.Speaker(synth=fake_synth, player_factory=lambda: player)
    waited = {}

    def llm_deltas():
        yield "Hello **there**. "
        yield "Second"
        # the first sentence must already be playing while the LLM is still generating
        waited["first_played"] = player.got_first.wait(2)
        yield " one! Third"

    sp.speak_stream(llm_deltas(), lang="hi")
    v = config.VOICES["hi"]
    assert waited["first_played"] is True
    assert b"".join(player.writes).decode() == f"{v}|Hello there.{v}|Second one!{v}|Third"
    assert player.finished and sp.first_audio_s is not None and not sp.is_speaking


def test_stop_interrupts():
    player = FakePlayer()
    sp = tts.Speaker(synth=fake_synth, player_factory=lambda: player)
    closed = threading.Event()

    def endless():
        try:
            while True:
                yield "More words here. "
                time.sleep(0.01)
        finally:
            closed.set()

    sp.speak_stream(endless(), block=False)
    assert player.got_first.wait(2)
    sp.stop()
    assert player.stopped and not sp.is_speaking and closed.wait(2)
