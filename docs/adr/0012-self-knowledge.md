# 0012: KURAMA explains and adjusts itself from facts, through a safe settings list

**Status:** Accepted

**Context.** The owner gets lost among ~150 tools and wants to ask "how did you do that?", "can I use this with VS
Code?", and to change behaviour ("make the speed test 30 seconds") without editing code. A hand-written self
description goes stale; letting the AI edit config or code could break KURAMA.

**Decision.**
- `core/selfindex.py` builds a card per tool from its own code (description, file docstring, `config.KEY`s it reads
  that are settings, example phrases). A contract test requires every tool to have them.
- `explain_self` answers from FACTS only: the last request's trace (tools, args, results), the relevant cards, and
  the start of a file it made. One smart-model call (low reasoning), ~800-1,500 tokens, only when asked.
- `core/usersettings.py`: a fixed list of 20 settings (name, config key, range, unit). Set / undo / reset by voice at
  0 tokens; saved in `data/user_settings.json`; `config.py` applies them at start. Nothing else is changeable.
- `help_me` and `find_capability` find tools by meaning (local model, 0 tokens).

**Consequences.** + Explanations change when the code changes. + "Change yourself" can't break anything. - A
behaviour not in the settings list needs a code change (KURAMA says so). - Explanations cost a little each time.
