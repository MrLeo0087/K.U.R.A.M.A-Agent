from jarvis.api.turns import addressed
from jarvis.core import fastpath


def test_ambient_speech_gate():
    assert addressed("Kill brave") and addressed("open youtube") and addressed("KURAMA, what is love?")
    for t in ("Screen dekhi raha? Ongar dekhi raha hai.", "KIDIHANI, KIDIHANI.", "Do you love me?", "Mmh.", "Hi"):
        assert not addressed(t), t


def test_zero_token_everyday_phrases():
    want = {"Hi": "_say", "Hello, how are you? What are you doing?": "_say", "Thanks": "_say", "ok": "_say",
            "Kill brave": "kill_app", "What is top memory use process .. give me top 5": "laptop_doctor",
            "Set alram for 1:53pm": "set_alarm", "Actually my laptop is slow, can you clear the RAM of my laptop?":
                "laptop_doctor", "Tell me token chat usuage": "token_usage", "Summarise today day till now":
                "daily_digest", "Give me status of traning": "training", "What is current status": "status_now",
            "give me the exact path of that folder": "_where"}
    for t, tool in want.items():
        i = fastpath.match(t)
        assert i is not None and i.tool == tool, (t, i)
    from jarvis.core import phrases
    assert fastpath.render(fastpath.match("hi"), True, "ok", "ne") in phrases.HELLO["ne"]  # Nepali, one of the variants
