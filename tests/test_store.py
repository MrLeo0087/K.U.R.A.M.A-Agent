import threading

from jarvis.core import store


def test_logging_and_queries():
    store.log_llm("m1", "t", 10, 5, 100, True)
    store.log_llm("m1", "t", 1, 1, 50, False, "boom")
    store.log_llm("m2", "t", 3, 0, 20, True)
    assert store.tokens_today("m1") == 17
    assert store.tokens_today() == 20
    assert store.tokens_by_model_today() == {"m1": 17, "m2": 3}
    store.log_tool("volume", {"level": 5}, True, 12)
    store.log_tool("volume", {"level": 6}, True, 9, safety="safe")
    store.log_tool("shell", {"cmd": "ls"}, False, 3, safety="confirm", error="denied")
    assert store.tool_call_counts() == {"volume": 2, "shell": 1}
    store.log_routing("turn up volume", ["general"], "keyword", 2)
    assert store._exec("SELECT groups, method FROM routing")[0][:] == ('["general"]', "keyword")
    for i in range(5):
        store.add_message("user", f"m{i}")
    assert [m["text"] for m in store.recent_messages(3)] == ["m2", "m3", "m4"]
    assert store._exec("PRAGMA journal_mode")[0][0] == "wal"


def test_thread_safe_writes():
    def work():
        for _ in range(25):
            store.log_llm("m", "thr", 1, 1, 1, True)
    ts = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert store.tokens_today("m") == 200
