# 0002: LangChain tools and LangGraph for the agent

**Status:** Accepted

**Context.** The owner must be able to read and change the agent. A hand-written loop would be shorter but private to this code.

**Decision.** Tools are `langchain_core` tools registered by a decorator (`jarvis/core/registry.py`); the agent,
routing, tool loops and parallel fan-out (`Send`) are a LangGraph `StateGraph`. The raw Groq SDK is used only where
LangChain has no support (Whisper).

**Consequences.** + Standard, documented concepts that transfer to other jobs. + Streaming, tool calling and
graphs come built in. - An extra dependency layer: upgrades need the test suite to pass before they are kept.
