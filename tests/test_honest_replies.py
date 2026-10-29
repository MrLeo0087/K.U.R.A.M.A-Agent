from langchain_core.messages import ToolMessage

from jarvis.core import agent, config, planner, trace


def _tm(text):
    return ToolMessage(content=text, tool_call_id="1", name="saved_links")


def test_no_claimed_action_when_every_tool_failed_or_was_refused():
    assert agent.honest("I've removed the link.", [_tm("error: no link named google drive")]).startswith("That didn't work")
    assert agent.honest("Sure, opening it now.", [_tm("The user declined: run_command was not run.")]) == \
        "I didn't do it: you said no."
    assert agent.honest("I've removed the link.", [_tm("Removed 'google drive'.")]) == "I've removed the link."
    assert agent.honest("Here is the answer.", [_tm("error: x")]) == "Here is the answer."  # no claim


def test_garbled_replies_are_replaced_by_the_tool_result():
    assert agent.garbled("It's    ...   …  …  ...…") and not agent.garbled("It is playing now... enjoy!")
    assert agent.last_result([_tm("Saved 'yaad'.")]) == "Saved 'yaad'."


def test_a_long_complaint_is_one_request_not_four_tasks():
    t = ("First of all the telegram say downloaded fail video error unable to rename file Sajan Juni Official "
         "Music and the file actually appear in the KURAMA folder but there is only music video which do not "
         "have the sound and I don't know why it happened")
    assert not planner.is_multi(t)
    assert planner.is_multi("open youtube and set a timer for 5 minutes")


def test_run_command_is_not_offered_for_system_questions():
    assert "system" not in config.CORE_COVERS["run_command"] and "files" not in config.CORE_COVERS["run_command"]


def test_passwords_never_reach_the_traces():
    assert trace.redact("unlock it .. passeord is Secret@1") == "unlock it .. passeord is [hidden]"
    assert "abc123" not in trace.redact("my password: abc123")


def test_no_retry_for_emoji_or_tiny_replies():
    assert not agent.worth_retry("😆") and not agent.worth_retry("not good")
    assert agent.worth_retry("is it late already")
