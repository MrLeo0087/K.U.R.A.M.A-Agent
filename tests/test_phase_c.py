"""Phase C odds and ends: spoken math is the calculator (0 tokens), a bare yes/no with nothing waiting is answered
for free, and the meaning gate always applies."""
from langchain_core.messages import AIMessage, HumanMessage

from jarvis.core import agent, config, fastpath, semantic
from jarvis.tools.general.calculate import calculate


def test_spoken_math_is_the_calculator(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    for said, expr, answer in (("calculate 32 per of 100", "32% of 100", "= 32"),
                               ("what is the 30 percent of 100", "30% of 100", "= 30"),
                               ("i mean 20 percent of 100", "20% of 100", "= 20"),
                               ("what is 15 plus 27", "15 + 27", "= 42"),
                               ("square root of 144", "sqrt(144)", "= 12")):
        it = fastpath.match(said)
        assert it.tool == "calculate" and it.args["expression"] == expr, said
        assert calculate(it.args["expression"]).endswith(answer) and calculate(said).endswith(answer)
    assert fastpath.match("i have 2 meetings at 5") is None


def test_bare_yes_no_with_nothing_waiting_costs_nothing(monkeypatch):
    a = agent.Agent()
    monkeypatch.setattr(agent.Agent, "graph", property(lambda self: (_ for _ in ()).throw(AssertionError("no AI"))),
                        raising=False)
    a.history = [HumanMessage("open youtube"), AIMessage("Opened YouTube.")]
    assert a._bare_answer("yes") == agent.Agent.BARE["yes"] and a._bare_answer("No.") == agent.Agent.BARE["no"]
    a.history.append(AIMessage("Should I also open Gmail?"))  # I asked: the AI reads the answer
    assert a._bare_answer("yes") is None
    assert a._bare_answer("yes open gmail too") is None  # more than a yes: a real request


def test_the_meaning_gate_applies_even_when_the_model_is_unsure(monkeypatch):
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "scores", lambda t: [("power", 0.81), ("study", 0.76), ("tracker", 0.60)])
    it = fastpath.Intent("habit", "habits", "tracker", {"action": "delete", "text": "laptop"})
    assert not fastpath.meaning_ok("Stop tracking laptop", it)  # was let through: top 0.81 < 0.85 'unsure'


def test_vs_code_is_an_app_name_not_a_request_for_code(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    for t in ("open this folder in vs code", "/home/leo/Downloads/test\nopen this folder in vs code",
              "search for command.md file and open it on vs code", "Make a new python.py, test.py file in this VS Code."):
        it = fastpath.to_file_intent(t)
        assert it is None, t
    assert fastpath.to_file_intent("now write this code in test.py in vs code").tool == "code_to_file"
