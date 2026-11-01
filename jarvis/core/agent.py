"""LangGraph agent on LangChain messages: route -> llm (model.bind_tools with only the routed
groups' tools) -> tools (our own node: safety confirm/blocked + logging) -> llm ... -> answer.

Fast tier by default; smart tier when more than one group is routed or the router flags
reasoning. History is the last config.HISTORY_TURNS turns plus a rolling summary (fast tier).
`run()` returns the answer; `stream()` yields text deltas (for TTS) as the model writes them.

Multitasking (P3b-2): a plan node runs first. One quick task -> the path above, unchanged.
Several tasks -> LangGraph Send fan-out: each quick task runs the route->llm->tools subgraph
concurrently (own state), each long task is submitted to the JobManager and returns at once; a
join node composes ONE reply without an LLM call. History is updated once, at the end.

Memory (P7): every turn is persisted to SQLite under a session (store.sessions: start/end, turns,
rolling summary). A turn after config.SESSION_IDLE_S of silence starts a new session with fresh
context. User facts are captured by regex each turn (0 tokens); profile facts are injected into
the system prompt only on personal turns (<= ~60 tokens); end_session() runs at most one
fast-tier fact extraction per session.

Freedom (P7b): a turn the router could not place (and that is not small talk) binds only the compact
request_tools meta-tool (meta.py); calling it binds the chosen groups' tools for the next round.
A tool-less "I can't" answer is retried once with the meta-tool bound. Both log method="meta".
"""
from __future__ import annotations

import json
import logging
import operator
import re
import threading
import time
from typing import Annotated, Any, Callable, Iterator, TypedDict

from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage, SystemMessage,
                                     ToolMessage)

from jarvis.core import (config, fastpath, identity, selfknow, jobs, llm, meta, notify, planner, profile, registry, router, trace,
                         modes, safety, store, workspace)

log = logging.getLogger("jarvis.agent")

LANG_NAMES = {"en": "English", "ne": "Nepali (Devanagari script)", "hi": "Hindi (Devanagari script)"}

SYSTEM_PROMPT = (
    "You are {name}, a warm helper on the user's laptop. Talk like a kind friend, simple words, no jargon. "
    "One short sentence when enough, 2 at most unless asked. "
    "Do it the way the user asks. Answer in the user's language (English, Hindi or Nepali). Plain text, no "
    "emojis or tables. For a problem, use tools to find the cause and give the fix. "
    "Use tools only when needed; never invent results, say you did what no tool did, or answer saved lists from "
    "old replies; if it fails or you don't know, "
    "say so. Stuck or 'what can you do': find_capability or about_me. Never ask yes/no in chat before "
    "acting: call the tool (risky ones ask the user themselves)."
)
# the dashboard: a small chat + the workspace window (turns.py moves long answers there; Telegram has no workspace)
SCREEN_SUFFIX = (" Screen: a small chat and a workspace window. Anything long (lists, code, steps, essays) goes to "
                 "the workspace by itself and the chat shows only your first sentence: start with a one-line summary.")
VOICE_SUFFIX = (" Spoken reply: 1-2 short sentences by default, up to 6 if asked to explain. "
                "The user spoke {lang}; reply in {lang}.")
SUMMARY_SUFFIX = " Earlier conversation (summary): {summary}"
SUMMARY_PROMPT = (
    "Update the running summary of a chat between a user and the assistant. "
    "Keep facts, decisions and user preferences; drop small talk. Under 60 words, plain text."
)
NO_ANSWER = "Sorry, I'm not sure about that one."
TOO_MANY_ROUNDS = "Sorry, that needed more steps than I can manage. Could you try it a simpler way?"
JOB_STARTED = {
    "write": {"en": 'Writing "{title}" in the background (job #{id}).',
              "hi": 'मैं "{title}" बैकग्राउंड में लिख रहा हूँ (जॉब #{id}); पूरा होने पर बताऊँगा।',
              "ne": 'म "{title}" पृष्ठभूमिमा लेख्दैछु (काम #{id}); सकिएपछि भन्छु।'},
    "scan": {"en": 'Working on "{title}" in the background (job #{id}).',
             "hi": 'मैं "{title}" पर बैकग्राउंड में काम कर रहा हूँ (जॉब #{id}); पूरा होने पर बताऊँगा।',
             "ne": 'म "{title}" मा पृष्ठभूमिमा काम गर्दैछु (काम #{id}); सकिएपछि भन्छु।'},
}
TASK_FAILED = "Sorry, I couldn't manage this part: {text}."
PREV_RESULT = "\n(Result of the previous step, use it: {result})"
PREV_RESULT_MAX = 1500
AFTER_JOB = "I'll {text} as soon as job #{job} is finished (follow-up job #{follow})."
DUPLICATE = "(duplicate) Already done earlier in this request, not run again: "


class AgentState(TypedDict, total=False):
    user_text: str
    messages: list[BaseMessage]
    groups: list[str]
    tools: list[Any]  # LangChain tools of the routed groups
    tier: str
    rounds: int
    pending: list[dict]
    answer: str
    stream: bool
    mode: str
    lang: str | None
    tasks: list[dict]  # planner output: [{"text", "kind": quick|long}]
    task: dict  # one fanned-out task (Send payload)
    chain: list[dict]  # P7c: dependent tasks, run in order, each gets the previous result
    request: str  # P7c: the user's whole original request (sub-tasks keep it for tool context)
    idx: int
    results: Annotated[list, operator.add]  # fan-out results, merged by the join node
    retried: bool  # P7b: the refusal retry already happened this turn
    again: bool  # P7b: llm -> llm (refusal retry with request_tools bound)


def job_started_text(job_id: int, title: str, kind: str, lang: str | None) -> str:
    tpl = JOB_STARTED["scan" if kind == "scan" else "write"]
    return tpl.get(lang or "en", tpl["en"]).format(id=job_id, title=title)


class Agent:
    def __init__(self, confirm: Callable[[str], bool] | None = None, summarize_async: bool = True,
                 use_planner: bool = True, persist: bool = True, channel: str = ""):
        self.confirm = confirm  # overrides safety.get_confirm(mode) when set
        self.summarize_async = summarize_async
        self.use_planner = use_planner
        self.persist = persist  # P7: store messages/sessions, learn profile facts
        self.channel = channel
        self.session_id: int | None = None
        self._last_turn = 0.0
        self._self_talk: list[str] = []  # user statements about themselves (session-end extraction source)
        self._task_graph: Any = None
        self.history: list[BaseMessage] = []
        self.summary = ""
        self._overflow: list[BaseMessage] = []
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._graph: Any = None
        self.last: dict = {}

    def abort(self) -> None:
        """Signal the current turn to stop streaming (best-effort)."""
        try:
            self._abort.set()
        except Exception:
            pass

    def clear_conversation(self) -> None:
        """Forget the current chat (history + rolling summary + session), keep learned personal facts."""
        with self._lock:
            self.history = []
            self._overflow = []
            self.summary = ""
            self.session_id = None
            self._self_talk = []
            self.last = {}

    # --- graph ---
    def _build(self, planned: bool | None = None) -> Any:
        from langgraph.graph import END, START, StateGraph  # lazy: keeps `import jarvis` light

        planned = self.use_planner if planned is None else planned
        g = StateGraph(AgentState)
        g.add_node("route", self._route_node)
        g.add_node("llm", self._llm_node)
        g.add_node("tools", self._tools_node)
        g.add_edge("route", "llm")
        g.add_conditional_edges(
            "llm", lambda s: "tools" if s.get("pending") else ("llm" if s.get("again") else END),
            {"tools": "tools", "llm": "llm", END: END})
        g.add_conditional_edges("tools", lambda s: END if s.get("answer") else "llm", {"llm": "llm", END: END})
        if not planned:
            g.add_edge(START, "route")
            return g.compile()
        g.add_node("plan", self._plan_node)
        g.add_node("quick", self._quick_node)
        g.add_node("long", self._long_node)
        g.add_node("chain", self._chain_node)
        g.add_node("join", self._join_node)
        g.add_edge(START, "plan")
        g.add_conditional_edges("plan", self._after_plan, ["route", "quick", "long", "chain"])
        g.add_edge("quick", "join")
        g.add_edge("chain", "join")
        g.add_edge("long", "join")
        g.add_edge("join", END)
        return g.compile()

    @property
    def task_graph(self) -> Any:
        """The single-task route->llm->tools graph run by each fanned-out quick task."""
        if self._task_graph is None:
            self._task_graph = self._build(planned=False)
        return self._task_graph

    # --- planning / fan-out ---
    def _plan_node(self, state: AgentState) -> dict:
        t0 = time.monotonic()
        p = planner.plan(state["user_text"])
        self.last["plan"] = {"method": p.method, "tasks": p.tasks,
                             "ms": int((time.monotonic() - t0) * 1000)}
        return {"tasks": p.tasks}

    @staticmethod
    def _after_plan(state: AgentState) -> Any:
        from langgraph.types import Send

        tasks = state.get("tasks") or []
        if len(tasks) <= 1 and (not tasks or tasks[0]["kind"] == "quick"):
            return "route"  # normal single request: unchanged path
        base = {"mode": state.get("mode", "text"), "lang": state.get("lang"),
                "user_text": state["user_text"]}
        sends = []
        for group in planner.chains(tasks):  # independent tasks fan out; dependent ones run in order
            if len(group) == 1:
                i = group[0]
                t = tasks[i]
                sends.append(Send("long" if t["kind"] == "long" else "quick", {**base, "task": t, "idx": i}))
            else:
                sends.append(Send("chain", {**base, "chain": [{**tasks[i], "idx": i} for i in group],
                                            "idx": group[0]}))
        return sends

    def _run_task(self, text: str, mode: str, lang: str | None, prev: str = "", request: str = "") -> str:
        """One quick task through the route->llm->tools subgraph (prev: earlier step's result)."""
        if not prev:
            fast = self._fast(text, lang, mode, record=False)
            if fast is not None:  # zero-token quick task
                return fast.answer
        content = text + (PREV_RESULT.format(result=prev[:PREV_RESULT_MAX]) if prev else "")
        msgs = self._messages(text, mode, lang)
        msgs[-1] = HumanMessage(content=content)
        sub: AgentState = {"user_text": text, "messages": msgs, "stream": False, "mode": mode, "lang": lang,
                           "rounds": 0, "pending": [], "request": request or text}
        try:
            final = self.task_graph.invoke(sub, self._config())
            return final.get("answer") or NO_ANSWER
        except llm.LLMError as e:
            log.warning("quick task failed: %s", e)
            return TASK_FAILED.format(text=text)

    def _quick_node(self, state: AgentState) -> dict:
        t, mode = state["task"], state.get("mode", "text")
        answer = self._run_task(t["text"], mode, state.get("lang"), request=state.get("user_text", ""))
        return {"results": [{"idx": state.get("idx", 0), "kind": "quick", "text": t["text"],
                             "answer": answer}]}

    def _chain_node(self, state: AgentState) -> dict:
        """P7c: dependent tasks in order; each step sees the previous step's result. A step that only STARTED a
        background job (an essay, a report) has no result yet: the steps after it become a follow-up long job that
        waits for that job and runs on its real output (they used to run at once on "started job #4" and invent it)."""
        mode, prev, out = state.get("mode", "text"), "", []
        chain = state.get("chain") or []
        for k, t in enumerate(chain):
            before = set(jobs.get_manager().ids())
            answer = self._run_task(t["text"], mode, state.get("lang"), prev, request=state.get("user_text", ""))
            out.append({"idx": t.get("idx", 0), "kind": "quick", "text": t["text"], "answer": answer})
            prev = answer
            started = sorted(set(jobs.get_manager().ids()) - before)
            rest = chain[k + 1:]
            if started and rest:
                follow = start_after_job(started[-1], [r["text"] for r in rest], state.get("lang"))
                for r in rest:
                    out.append({"idx": r.get("idx", 0), "kind": "quick", "text": r["text"],
                                "answer": AFTER_JOB.format(text=r["text"], job=started[-1], follow=follow.id)})
                break
        self.last["chain"] = [r["idx"] for r in out]
        return {"results": out}

    def _long_node(self, state: AgentState) -> dict:
        t = state["task"]
        lang = state.get("lang") or planner.detect_lang(t["text"])
        try:
            job = jobs.start_task(t["text"], lang=lang)
            if t.get("telegram"):
                jobs.then_send(job.id)
        except Exception as e:
            log.exception("could not start job")
            return {"results": [{"idx": state.get("idx", 0), "kind": "quick", "text": t["text"],
                                 "answer": TASK_FAILED.format(text=t["text"]), "error": str(e)}]}
        return {"results": [{"idx": state.get("idx", 0), "kind": "long", "text": t["text"],
                             "job_id": job.id, "title": job.title, "job_kind": job.kind}]}

    def _join_node(self, state: AgentState) -> dict:
        lang = state.get("lang") or planner.detect_lang(state["user_text"])
        results = sorted(state.get("results") or [], key=lambda r: r.get("idx", 0))
        quick = fastpath.merge_opens([r["answer"].strip() for r in results if r["kind"] == "quick" and r.get("answer")])
        longs = [job_started_text(r["job_id"], r["title"], r.get("job_kind", "write"), lang)
                 for r in results if r["kind"] == "long"]
        self.last.setdefault("jobs", []).extend(r["job_id"] for r in results if r["kind"] == "long")
        return {"answer": " ".join(quick + longs).strip() or NO_ANSWER}

    def warm(self) -> None:
        """Pay import/compile/model-setup costs now (startup), not on the first turn."""
        from langgraph.config import get_stream_writer  # noqa: F401  (imported by stream turns)

        _ = self.graph
        registry.groups()
        router.rule_groups("warm up")
        llm.warm()

    @property
    def graph(self) -> Any:
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    _FOLLOWUP = re.compile(r"\b(?:it|this|that|them|those|again|too|also|instead|back|same|one more|another|"
                           r"on|off|more|less|louder|quieter|yes|do it|go ahead)\b", re.I)

    def _route_node(self, state: AgentState) -> dict:
        r = router.route(state["user_text"])
        prev, at = getattr(self, "_prev_groups", ([], 0.0))
        if (not r.groups and prev and time.time() - at < 300 and len(state["user_text"].split()) <= 8
                and self._FOLLOWUP.search(state["user_text"])):  # "then turn it off": same tools as the last turn
            r = router.Route(prev, "followup", r.reasoning, r.latency_ms)
        if r.groups:
            self._prev_groups = (list(r.groups), time.time())
        try:  # an agent is on: its tools come first, the router's choice after them (everything else still works)
            from jarvis import agents
            if self.channel != "telegram" and (ag := agents.spec()) is not None:
                agents.touch()
                r = router.Route([*ag.groups, *[g for g in r.groups if g not in ag.groups]][: config.ROUTER_MAX_GROUPS],
                                 r.method, r.reasoning, r.latency_ms)
        except Exception as e:  # noqa: BLE001
            log.warning("agent routing failed: %s", e)
        routed = list(r.groups)  # what the request itself needs (before the editor's context area)
        try:  # code open in VS Code or text highlighted anywhere: the text/code tool is always offered (the context
            from jarvis.core import context, rewrite  # line says what is open / selected)
            if self.channel != "telegram" and "clipboard" not in r.groups and (
                    context.editor_open() or (config.CONTEXT and rewrite.peek().strip())):
                r = router.Route(["clipboard", *r.groups][: config.ROUTER_MAX_GROUPS], r.method, r.reasoning, r.latency_ms)
        except Exception as e:  # noqa: BLE001
            log.warning("editor context failed: %s", e)
        tools: list[Any] = registry.schemas_for(r.groups, state["user_text"]) if r.groups else []
        # the clipboard area added above for the open editor is context, not a second task: it must not pick the big
        # model (with VS Code open all day, every request went to the smart tier)
        real = [g for g in r.groups if g != "clipboard"] if "clipboard" not in routed else r.groups
        tier = "smart" if (len(real) > 1 or r.reasoning or modes.ai_level() == "best") else "fast"
        if tier == "fast" and not tools and state.get("mode") == "voice":
            tier = "voice"  # plain spoken chat: lowest time-to-first-token model
        if not tools and self._meta_ok(state["user_text"]):
            tools = [meta.schema()]  # freedom: the model may pull any group (~150 tokens)
            self.last["meta_tokens"] = meta.estimate_tokens()
        self.last.update(route=r, tier=tier, tools_sent=[meta.tool_name(t) for t in tools])
        return {"groups": r.groups, "tools": tools, "tier": tier, "rounds": 0, "pending": [],
                "retried": False, "again": False}

    @staticmethod
    def _meta_ok(text: str) -> bool:
        return config.META_TOOLS and bool(registry.groups()) and not router.is_small_talk(text)

    def _retry_ok(self, state: AgentState) -> bool:
        """Refusal retry allowed: not done yet, no real tool used this turn, not small talk."""
        if state.get("retried") or not config.META_REFUSAL_RETRY:
            return False
        if any(isinstance(m, ToolMessage) and m.name != meta.NAME for m in state["messages"]):
            return False
        return self._meta_ok(state["user_text"])

    @staticmethod
    def _data_area(state: AgentState) -> bool:
        """The request's main area holds the user's own saved things (config.DATA_AREAS): links, to-dos, reminders,
        jobs, money. ('clipboard' only says something is highlighted.)"""
        main = [g for g in state.get("groups") or [] if g != "clipboard"][:1]
        return bool(main) and main[0] in config.DATA_AREAS and bool(state.get("tools"))

    @staticmethod
    def _unoffered_tool(error: str, tools: list | None) -> Any | None:
        """Groq 400 'attempted to call tool X which was not in request.tools': X if it is a real KURAMA tool."""
        m = re.search(r"attempted to call tool '([A-Za-z0-9_]+)'", error)
        if not m or not tools:
            return None
        t = registry.REGISTRY.tools.get(m.group(1))
        return t if t is not None and all(getattr(x, "name", None) != t.name for x in tools) else None

    def _llm_node(self, state: AgentState) -> dict:
        tools = state.get("tools") or None
        rounds = state.get("rounds", 0)
        last_round = rounds >= config.AGENT_MAX_TOOL_ROUNDS
        if last_round:
            tools = None  # final round: send NO tools so the model must answer in text. (tool_choice="none" is
            #              not obeyed by gpt-oss and makes Groq return a 400 "Tool choice is none but model called a tool".)
        kw: dict[str, Any] = {"tier": state.get("tier", "fast"), "tools": tools,
                              "purpose": f"agent_{state.get('mode', 'text')}",
                              "max_tokens": config.AGENT_MAX_TOKENS}
        if kw["tier"] != "voice":  # (the voice tier has its own, shorter timeout)
            kw["timeout"] = config.AGENT_TIMEOUT_S
        msgs = state["messages"]
        hold = self._retry_ok(state)  # stream: hold the first sentence back until it is not "I can't"
        unread = hold and self._data_area(state)  # the user's saved things: no tool yet = nothing read yet
        try:
            reply = self._chat(msgs, kw, state.get("stream", False) and not unread, hold)
        except llm.LLMError as e:
            low = str(e).lower()
            if "tool" not in low and "400" not in low:
                raise
            # a tool-call / tool_choice 400 from Groq: retry once with NO tools so it answers in text; already
            # tool-less (the final round, where gpt-oss still tries to call a tool): answer from the tool results
            extra = self._unoffered_tool(str(e), tools)
            if extra is not None:  # it called a real KURAMA tool we didn't offer ('clipboard': its old name in the
                tools = [*tools, extra]  # history): offer that one too and retry WITH tools (it answered with no
                kw = {**kw, "tools": tools}  # tool call before: "copy the path" copied nothing)
                log.warning("model called the unoffered tool %s; retrying with it", extra.name)
            elif (bad := re.search(r"attempted to call tool '([A-Za-z0-9_]+)'", str(e))) and tools:
                # it used an ACTION or an area as a tool name ('git' instead of code(action='git'), 'files'...):
                # retry WITH the tools and say which tool holds it (it fell back to no tools, then 'Tool choice is
                # none, but model called a tool' -> "something went wrong"; test round 1, 11-01)
                names = [meta.tool_name(t) for t in tools]
                msgs = msgs + [SystemMessage(content=f"There is no tool called '{bad.group(1)}'. Call one of "
                                                     f"{', '.join(names)} and put '{bad.group(1)}' in its action.")]
                extra = True
                log.warning("model called the non-tool %r; retrying with a hint", bad.group(1))
            else:
                log.warning("tool-call generation failed (%s); retrying without tools", str(e)[:120])
            notools = {k: v for k, v in kw.items() if k != "tools"}
            try:
                if not tools:
                    raise e
                reply = self._chat(msgs, kw if extra is not None else notools, state.get("stream", False), hold)
            except llm.LLMError:  # still failing: answer from whatever the tools already returned
                done = [str(m.content) for m in msgs if isinstance(m, ToolMessage) and m.name != meta.NAME
                        and not str(m.content).startswith("error")][-2:]
                reply = llm.Reply(" ".join(done)[:600] or NO_ANSWER, "", [])
        ai = reply.message or AIMessage(content=reply.text)
        calls = [] if last_round else list(ai.tool_calls)
        bad = [] if last_round else list(getattr(ai, "invalid_tool_calls", None) or [])
        if calls or bad:
            calls = [{**tc, "id": tc.get("id") or f"call_{rounds}_{i}"} for i, tc in enumerate(calls)]
            bad = [{**tc, "id": tc.get("id") or f"bad_{rounds}_{i}"} for i, tc in enumerate(bad)]
            msg = AIMessage(content=reply.text, tool_calls=calls, invalid_tool_calls=bad)
            return {"messages": msgs + [msg], "pending": calls + bad, "tools": tools or state.get("tools") or []}
        answer = reply.text.strip() or (TOO_MANY_ROUNDS if ai.tool_calls else NO_ANSWER)
        answer = honest(answer, msgs)
        if hold and not last_round and not self.last.get("denied") and (unread or meta.needs_tool(answer) and (
                meta.claims(answer) or worth_retry(state["user_text"]))):
            # (never after a "no" to a yes/no question; a refusal to small talk / an emoji isn't worth a retry)
            log.info("tool-less refusal, retrying once with %s: %r", meta.NAME, answer[:80])
            self._log_meta(state["user_text"], [])
            self.last["meta_retry"] = True
            # the tools it already had come too: it answered "All links have been cleared" with the link tool in
            # hand (trace f8ac97af102e) - a retry with only request_tools cost an extra round to get them back
            retry_tools: list[Any] = [t for t in state.get("tools") or [] if meta.tool_name(t) != meta.NAME]
            retry_tools.append(meta.schema())
            hint = meta.HINT if not state.get("tools") else meta.DO_IT_HINT + " " + meta.HINT
            if router.looks_like_command(state["user_text"]):  # a real task with no tool: offer the toolsmith
                retry_tools += [t for t in registry.schemas_for(["toolsmith"]) if t.name == "make_tool"]
                hint += " " + meta.TOOLSMITH_HINT if len(retry_tools) > 1 else ""
            return {"messages": msgs + [SystemMessage(content=hint)], "tools": retry_tools,
                    "pending": [], "retried": True, "again": True, "rounds": rounds + 1,
                    "tier": "fast" if state.get("tier") == "voice" else state.get("tier", "fast")}
        if not last_round and self._smith_ok(state, answer):  # "I can't" on a real task: offer to build a tool
            call = {"name": "make_tool", "args": {"task": state["user_text"]}, "id": f"smith_{rounds}"}
            smith = [t for t in registry.schemas_for(["toolsmith"]) if t.name == "make_tool"]
            return {"messages": msgs + [AIMessage(content="", tool_calls=[call])], "pending": [call],
                    "tools": list(tools or []) + smith}
        return {"messages": msgs + [AIMessage(content=answer)], "pending": [], "answer": answer,
                "again": False}

    @staticmethod
    def _smith_ok(state: AgentState, answer: str) -> bool:
        """The model refused a real task and no tool was built this turn: the toolsmith asks the user (always the
        same flow: 'I don't have a tool for that, should I make one?' -> build -> run -> 'save it?')."""
        text = state["user_text"]
        if not config.TOOLSMITH_OFFER or not meta.looks_like_refusal(answer) or router.is_small_talk(text):
            return False
        if not (router.looks_like_command(text) or state.get("groups")):
            return False
        if any(isinstance(m, ToolMessage) and m.name != meta.NAME for m in state["messages"]):
            return False  # a real tool (or make_tool) already ran this turn: its answer stands
        return any(t.name == "make_tool" for t in registry.schemas_for(["toolsmith"]))

    @staticmethod
    def _log_meta(text: str, groups: list[str]) -> None:
        try:
            store.log_routing(text, groups, "meta", 0)
        except Exception as e:
            log.warning("could not log meta routing: %s", e)

    def _chat(self, msgs: list[BaseMessage], kw: dict, stream: bool, hold: bool = False) -> llm.Reply:
        if not stream:
            return llm.chat(msgs, **kw)
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        abort = self._abort  # this turn's flag (a stale turn closing later must not cut a new one)
        gen = llm.chat(msgs, stream=True, **kw)
        parts: list[str] = []
        held = hold  # buffer until the first sentence shows it is not a refusal
        while True:
            if abort.is_set():  # consumer went away (barge-in): stop generating
                gen.close()
                return llm.Reply("".join(parts), "", [])
            try:
                delta = next(gen)
            except StopIteration as stop:
                text = "".join(parts)
                if held and text and not meta.needs_tool(text):
                    writer(text)
                return stop.value or llm.Reply(text, "", [])
            parts.append(delta)
            if not held:
                writer(delta)
                continue
            text = "".join(parts)
            if len(text) >= 80 or (len(text) >= 12 and re.search(r"[.!?।]\s", text)):
                if meta.needs_tool(text):
                    gen.close()  # will be retried with request_tools; never spoken
                    return llm.Reply(text, "", [])
                held = False
                writer(text)

    def _tools_node(self, state: AgentState) -> dict:
        allowed = {meta.tool_name(t) for t in state.get("tools") or []}
        confirm = self.confirm or safety.get_confirm(state.get("mode", "text"))
        out: list[BaseMessage] = []
        update: dict = {}
        for tc in state.get("pending") or []:
            name, args = tc.get("name") or "", tc.get("args")
            if name == meta.NAME and name in allowed:
                groups = meta.pick(args)
                if groups:
                    tools = registry.schemas_for(groups)
                    tier = ("smart" if len(groups) > 1 or state.get("tier") == "smart" or modes.ai_level() == "best"
                            else "fast")
                    update = {"tools": tools, "groups": groups, "tier": tier}
                    content = meta.LOADED.format(groups=", ".join(groups))
                    self._log_meta(state["user_text"], groups)
                    self.last.update(route=router.Route(groups, "meta", False, 0), tier=tier,
                                     tools_sent=[t.name for t in tools])
                else:
                    content = f"error: unknown groups; choose from {', '.join(registry.groups())}"
                self.last.setdefault("tools", []).append({"name": name, "ok": bool(groups)})
                out.append(ToolMessage(content=content, tool_call_id=tc["id"], name=name))
                continue
            denied = self.last.setdefault("denied", [])
            key = f"{name}:{json.dumps(args or {}, sort_keys=True, default=str)}"
            done = self.last.setdefault("done_calls", {})
            if key in done:  # the same call twice in one request (two identical timers): run it once
                self.last.setdefault("tools", []).append({"name": name, "ok": True})
                out.append(ToolMessage(content=DUPLICATE + done[key][:200], tool_call_id=tc["id"], name=name))
                continue
            if name in denied:  # never ask the same thing twice in one turn (no yes/no loops)
                content, ok = "The user already declined this. Don't call it again; say it wasn't done.", False
            elif name not in allowed:
                content = f"error: tool {name!r} is not available for this request"
                store.log_tool(name, args, False, 0, safety="unknown", error="not routed",
                               outcome="error", result=content)
                ok = False
            else:
                res = safety.execute(name, args, confirm=confirm,
                                     ctx={"user_text": state["user_text"], "lang": state.get("lang"),
                                          "mode": state.get("mode", "text"), "channel": self.channel,
                                          "published": self.last.setdefault("workspace", []),
                                          "full": workspace.wants_all(state["user_text"]),
                                          "jobs": self.last.setdefault("jobs", []),
                                          "request": state.get("request") or state["user_text"]})
                content, ok = res.output, res.ok
                if content.startswith("The user declined"):
                    denied.append(name)
                elif ok:
                    done[key] = content
            self.last.setdefault("tools", []).append({"name": name, "ok": ok})
            out.append(ToolMessage(content=content, tool_call_id=tc["id"], name=name))
        direct = self._direct_reply(state, out)
        if direct:
            return {"messages": state["messages"] + out, "pending": [], "answer": direct,
                    "rounds": state.get("rounds", 0) + 1, **update}
        return {"messages": state["messages"] + out, "pending": [],
                "rounds": state.get("rounds", 0) + 1, **update}

    def _direct_reply(self, state: AgentState, results: list[ToolMessage]) -> str:
        """Every call this round was a simple action that worked: word the reply from the fast path's templates
        instead of a second LLM call (about half the tokens of a "open YouTube" turn)."""
        from jarvis.tools.core._hub import underlying
        calls = {tc["id"]: tc for tc in state.get("pending") or []}
        real = {m.tool_call_id: underlying(m.name, (calls.get(m.tool_call_id) or {}).get("args") or {}) for m in results}
        if not results or any(real[m.tool_call_id][0] not in config.DIRECT_REPLY_TOOLS for m in results):
            return ""
        lang = state.get("lang") or "en"
        said = []
        for m in results:
            text = str(m.content)
            if text.startswith(DUPLICATE):
                continue  # said once already
            if text.lower().startswith(("error", "the user", "refused")):
                return ""  # something went wrong: let the model explain it
            tool_name, args = real[m.tool_call_id]  # a general tool's call is worded as the action it ran
            if str(args.get("action") or "") in config.DIRECT_REPLY_STEPS.get(tool_name, ()):
                return ""  # a step of something bigger ('switch to Brave' before 'open a new tab'): the AI goes on
            intent = config.DIRECT_REPLY_TOOLS[tool_name]
            if intent == "said":  # the tool's own sentence
                said.append(text[:1].upper() + text[1:])
                continue
            if intent == "audio":  # one tool, three kinds of reply
                intent = "mic" if args.get("target") == "mic" else (
                    "volume" if args.get("action", "get") in ("get", "set", "up", "down") else "mute")
            if intent is None:
                said.append("Done, I sent it to your Telegram.")
                continue
            label = str(args.get("target") or args.get("name") or "")
            said.append(fastpath.render(fastpath.Intent(intent, tool_name, "", args, label), True, text, lang))
        return " ".join(fastpath.merge_opens(said)).strip()

    # --- history ---
    def _messages(self, user_text: str, mode: str, lang: str | None) -> list[BaseMessage]:
        system = SYSTEM_PROMPT.replace("{name}", identity.name())
        if getattr(self, "channel", "") != "telegram":
            system += SCREEN_SUFFIX
        if mode == "voice":
            system += VOICE_SUFFIX.format(lang=LANG_NAMES.get(lang or "en", "English"))
        with self._lock:
            if self.summary:
                system += SUMMARY_SUFFIX.format(summary=self.summary)
            recent = self.history[-2 * config.HISTORY_TURNS:]
        if getattr(self, "reply_to", ""):  # Telegram reply: the user is answering one earlier message
            system += f' The user is replying to this earlier message of yours: "{self.reply_to}".'
        if self.persist:  # token-gated: nothing unless the turn is personal / refers to the past
            try:
                line = profile.context_line(user_text)
            except Exception as e:
                log.warning("profile injection failed: %s", e)
                line = ""
            if line:
                system += " " + line
                self.last["profile_tokens"] = self.last.get("profile_tokens", 0) + profile.estimate_tokens(line)
            told = notify.context_line(user_text, self.channel)  # reminders/alerts it sent on its own
            if told:
                system += " " + told
            other = self._other_channel(user_text)  # laptop <-> Telegram: one KURAMA, one conversation
            if other:
                system += " " + other
        try:  # an agent the owner turned on (coding): one line saying what to focus on
            from jarvis import agents
            if self.channel != "telegram" and (ag := agents.prompt_line()):
                system += " " + ag
        except Exception as e:  # noqa: BLE001
            log.warning("agent line failed: %s", e)
        try:
            from jarvis.core import context  # what is open: the VS Code file + its selection, or the browser tab
            if (ctx := context.line()) and self.channel != "telegram":
                system += " " + ctx
        except Exception as e:  # noqa: BLE001
            log.warning("context line failed: %s", e)
        return [SystemMessage(content=system), *recent, HumanMessage(content=user_text)]

    # --- sessions + profile (P7) ---
    _SELF_TALK = re.compile(r"\b(?:i|i'm|i am|my|mero|mera)\b|मेरो|मेरा", re.I)

    def _begin_turn(self, user_text: str) -> None:
        """New session after a long silence (fresh context); regex fact capture (0 tokens)."""
        if not self.persist:
            return
        try:  # another process (UI / Telegram) cleared the chat: drop our in-memory history too
            from jarvis.core import reset
            ep = reset.epoch()
            if ep != getattr(self, "_epoch_seen", None):
                if getattr(self, "_epoch_seen", None) is not None:
                    self.clear_conversation()
                self._epoch_seen = ep
        except Exception:
            pass
        now = time.time()
        if self.session_id is None and not self.history and self.channel:
            self._resume(now)
        if self.session_id is not None and now - self._last_turn > config.SESSION_IDLE_S:
            self.end_session(blocking=False)
            with self._lock:
                self.history, self._overflow, self.summary = [], [], ""
        try:
            facts = profile.capture_and_save(user_text)
        except Exception as e:
            log.warning("profile capture failed: %s", e)
            facts = []
        if facts:
            self.last["facts"] = facts
        elif self._SELF_TALK.search(user_text) and not user_text.rstrip().endswith("?"):
            self._self_talk = (self._self_talk + [user_text[:200]])[-6:]

    _REFERS = re.compile(r"\b(?:this|that|it|those|them|same|earlier|before|above|last|again|telegram|phone|"
                         r"laptop|computer|file|folder|send)\b", re.I)

    def _other_channel(self, user_text: str) -> str:
        """The last few messages from the other channel (dashboard vs Telegram, within CROSS_CHANNEL_S), only
        when this turn may refer to them ("send that file to Telegram", "what did I ask on my laptop")."""
        if not self._REFERS.search(user_text or ""):
            return ""
        try:
            rows = store.messages_other_channels(self.channel, time.time() - config.CROSS_CHANNEL_S, 6)
        except Exception as e:
            log.warning("cross-channel context failed: %s", e)
            return ""
        if not rows:
            return ""
        where = "the laptop dashboard" if self.channel == "telegram" else "Telegram"
        lines = " | ".join(f"{r['role']}: {' '.join((r['text'] or '').split())[:220]}" for r in rows)
        return f"Recent chat with the user on {where} (same conversation, continue it): {lines}"

    def _resume(self, now: float) -> None:
        """After a restart, carry on this channel's last chat (if it was within SESSION_IDLE_S): its recent turns
        and summary come back, so "what I asked you before" still works on Telegram."""
        try:
            sess = store.session_latest(self.channel)
            if not sess or now - (sess.get("end") or 0) > config.SESSION_IDLE_S:
                return
            rows = store.session_messages(sess["id"], limit=500)[-2 * config.HISTORY_TURNS:]
        except Exception as e:
            log.warning("could not resume the %s chat: %s", self.channel, e)
            return
        kinds = {"user": HumanMessage, "assistant": AIMessage}
        with self._lock:
            self.history = [kinds[r["role"]](content=r["text"]) for r in rows if r["role"] in kinds]
            self.summary = sess.get("summary") or ""
        self.session_id, self._last_turn = sess["id"], sess.get("end") or now

    def _persist_turn(self, user_text: str, answer: str) -> None:
        if not self.persist:
            return
        try:
            if self.session_id is None:
                self.session_id = store.session_start(self.channel)
            store.add_message("user", user_text, session=self.session_id)
            store.add_message("assistant", answer, session=self.session_id)
            store.session_touch(self.session_id)
        except Exception as e:
            log.warning("could not persist turn: %s", e)
        self._last_turn = time.time()

    def end_session(self, blocking: bool = True) -> None:
        """Close the current session: at most ONE fast-tier profile extraction (from the rolling
        summary, else the user's statements about themselves). Safe to call more than once."""
        sid, summary, talk = self.session_id, self.summary, self._self_talk
        self.session_id, self._self_talk = None, []
        if sid is None:
            return

        def work() -> None:
            try:
                src = summary or " | ".join(talk)
                sess = store.session_get(sid) or {}
                if config.PROFILE_LLM_EXTRACT and src and not sess.get("extracted"):
                    profile.extract_llm(src)
                    store.session_update(sid, extracted=True)
            except Exception as e:
                log.warning("end_session failed: %s", e)

        if blocking:
            work()
        else:
            threading.Thread(target=work, name="session-end", daemon=True).start()

    def _remember(self, user_text: str, answer: str) -> None:
        user_text = selfknow.redact(user_text)  # never keep the owner password in history
        self._persist_turn(user_text, answer)
        batch: list[BaseMessage] = []
        with self._lock:
            short = answer if len(answer) <= config.HISTORY_MSG_MAX_CHARS else \
                answer[: config.HISTORY_MSG_MAX_CHARS].rstrip() + " …(shortened)"
            # long replies (file lists, reports) are kept short in the LLM history: every later turn re-sends them
            self.history += [HumanMessage(content=user_text[: config.HISTORY_MSG_MAX_CHARS]), AIMessage(content=short)]
            while len(self.history) > 2 * config.HISTORY_TURNS:
                self._overflow += self.history[:2]
                self.history = self.history[2:]
            if len(self._overflow) >= 2 * config.AGENT_SUMMARY_BATCH_TURNS:
                batch, self._overflow = self._overflow, []
        if batch:
            if self.summarize_async:
                threading.Thread(target=self._summarize, args=(batch,), name="summary",
                                 daemon=True).start()
            else:
                self._summarize(batch)

    def _summarize(self, turns: list[BaseMessage]) -> None:
        names = {"human": "user", "ai": "assistant"}
        transcript = "\n".join(f"{names.get(m.type, m.type)}: {str(m.content)[:400]}" for m in turns)
        msgs = [SystemMessage(content=SUMMARY_PROMPT),
                HumanMessage(content=f"Current summary: {self.summary or 'none'}\n\n"
                                     f"New turns:\n{transcript}")]
        try:
            text = str(llm.chat(msgs, tier="fast", purpose="summary", max_tokens=300)).strip()
        except llm.LLMError as e:
            log.warning("summary failed: %s", e)
            return
        if text:
            with self._lock:
                self.summary = text[:600]
            if self.persist and self.session_id is not None:
                try:
                    store.session_update(self.session_id, summary=self.summary)
                except Exception as e:
                    log.warning("could not save summary: %s", e)

    # --- zero-token fast path ---
    def _fast(self, user_text: str, lang: str | None, mode: str, record: bool = True) -> Any:
        """fastpath.try_answer for a single-intent request (None -> normal LLM path)."""
        if not config.FASTPATH or (record and self.use_planner and planner.is_multi(user_text)
                                   and not planner.one_tool(user_text)):
            return None
        res = fastpath.try_answer(user_text, lang=lang, confirm=self.confirm or safety.get_confirm(mode), mode=mode,
                                  ctx={"channel": getattr(self, "channel", "") or ""})
        if res is not None:
            entry = {"name": res.intent.tool, "ok": res.ok}
            if record:
                self.last = {"tools": [entry], "fastpath": res.intent.name, "t0": time.monotonic(),
                             "route": router.Route([res.intent.group], "fastpath", False, res.latency_ms)}
            else:
                self.last.setdefault("tools", []).append(entry)
            if res.workspace:
                self.last.setdefault("workspace", []).extend(res.workspace)
            if res.jobs:
                self.last.setdefault("jobs", []).extend(res.jobs)  # the UI watches and announces them
        return res

    BARE = {"yes": "There's nothing waiting for a yes right now. What should I do?",
            "no": "Okay, nothing to cancel right now."}

    def _bare_answer(self, text: str) -> str | None:
        """A bare 'yes' / 'no' when nothing waits for it (no shortcut took it) and my last reply asked nothing: a
        0-token answer. It used to go to the AI (up to 7k tokens), which guessed and redid the last action."""
        words = re.findall(r"[^\s,.!?।]+", (text or "").lower())
        if not words or len(words) > 3 or safety.parse_yes_no(text) is None:
            return None
        if not all(w in safety.YES_WORDS or w in safety.NO_WORDS or w in ("please", "ok", "okay", "sir") for w in words):
            return None
        last = next((m for m in reversed(self.history) if isinstance(m, AIMessage)), None)
        if last is not None and "?" in str(last.content)[-200:]:
            return None  # I asked something: the AI reads the answer with the conversation
        self.last = {"tools": [], "t0": time.monotonic(), "fastpath": "bare_answer"}
        return self.BARE["yes" if safety.parse_yes_no(text) else "no"]

    # --- public API ---
    def _state(self, user_text: str, mode: str, lang: str | None, stream: bool) -> AgentState:
        self.last = {"tools": [], "t0": time.monotonic()}
        return {"user_text": user_text, "messages": self._messages(user_text, mode, lang),
                "stream": stream, "mode": mode, "lang": lang, "rounds": 0, "pending": []}

    @staticmethod
    def _config() -> dict:
        return {"recursion_limit": 2 * config.AGENT_MAX_TOOL_ROUNDS + 6}

    def run(self, user_text: str, mode: str = "text", lang: str | None = None) -> str:
        tr = trace.begin(user_text, mode, getattr(self, "channel", "") or "", enabled=self.persist)
        answer, error = "", ""
        try:
            answer = self._run(user_text, mode, lang)
            return answer
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            trace.end(tr, answer, self.last, error)

    def _run(self, user_text: str, mode: str, lang: str | None) -> str:
        self._begin_turn(user_text)
        fast = self._fast(user_text, lang, mode)
        if fast is not None:
            self._remember(user_text, fast.answer)
            return fast.answer
        if (bare := self._bare_answer(user_text)) is not None:
            return bare
        if modes.ai_level() == "off":
            return modes.NO_AI
        try:
            final = self.graph.invoke(self._state(user_text, mode, lang, False), self._config())
            answer = final.get("answer") or NO_ANSWER
        except llm.LLMError as e:
            log.warning("agent run failed: %s", e)
            self.last["error"] = str(e)[:300]
            answer = ("Sorry, my AI service is busy or rate-limited right now — please try again in a few seconds."
                      if any(w in str(e).lower() for w in ("rate", "429", "busy", "quota", "budget"))
                      else "Sorry, something went wrong on my side. Please try again.")
        self._remember(user_text, answer)
        return answer

    def stream(self, user_text: str, mode: str = "text", lang: str | None = None) -> Iterator[str]:
        """Yield answer text deltas. Tool rounds (and confirmations) happen before the first one."""
        tr = trace.begin(user_text, mode, getattr(self, "channel", "") or "", enabled=self.persist)
        parts: list[str] = []
        error = ""
        try:
            for chunk in self._stream(user_text, mode, lang):
                parts.append(chunk)
                yield chunk
                trace.resume(tr)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            trace.end(tr, "".join(parts), self.last, error or ("stopped early" if not parts else ""))

    def _stream(self, user_text: str, mode: str, lang: str | None) -> Iterator[str]:
        self._begin_turn(user_text)
        fast = self._fast(user_text, lang, mode)
        if fast is not None:
            self._remember(user_text, fast.answer)
            yield fast.answer
            return
        if (bare := self._bare_answer(user_text)) is not None:
            yield bare
            return
        if modes.ai_level() == "off":
            self.last = {"tools": [], "t0": time.monotonic()}
            yield modes.NO_AI
            return
        state = self._state(user_text, mode, lang, True)
        abort = self._abort = threading.Event()  # per turn: an old turn's late close can't stop this one
        parts: list[str] = []
        final: dict | None = None
        raw: list[str] = []  # what the model sent, before cleaning (to judge it)
        held: list[str] = []  # once the stream looks like junk, nothing more is shown until it is judged
        try:
            for kind, chunk in self.graph.stream(state, self._config(),
                                                 stream_mode=["custom", "values"]):
                if kind == "custom":
                    raw.append(chunk or "")
                    if held or _JUNK.search("".join(raw[-6:])):  # gpt-oss-120b sometimes streams "Your … … …"
                        held.append(chunk or "")  # after a tool ran (14 of 191 replies, traces 10-29..11-01)
                        continue
                    chunk = _ZW.sub("", chunk or "")
                    if not chunk or (_DOTS.fullmatch(chunk) and _DOTS.search("".join(parts[-2:]) + "$")):
                        continue  # a run of "… … …" (the model stalling): at most one
                    parts.append(chunk)
                    yield chunk
                else:
                    final = chunk
            answer = (final or {}).get("answer") or ""
            said = "".join(parts)
            if held:
                log.info("junk-looking stream held (%s): %r", "garbled" if garbled("".join(raw)) else "kept",
                         "".join(raw)[:120])
            if held and not garbled("".join(raw)):  # a false alarm: show the rest, cleaned
                rest = tidy("".join(held))
                parts.append(rest)
                yield rest
                said = "".join(parts)
            if answer and not said.strip() and not held:  # nothing streamed (template/fallback text): emit it whole
                parts.append(answer)
                yield answer
            elif (said or held) and (garbled("".join(raw)) or (answer.startswith(HONEST) and answer not in said)):
                fix = answer if answer.startswith(HONEST) else last_result((final or {}).get("messages") or [])
                if final is not None:
                    final["answer"] = fix
                fix = ("\n" if said.strip() else "") + fix
                parts.append(fix)
                yield fix
        finally:
            if final is None or not final.get("answer"):
                abort.set()  # stopped early (barge-in / error): tell the graph thread to quit
                # a cut-off reply is not kept: one-word answers in history teach the model to answer in one word
        if final and final.get("answer"):
            self._remember(user_text, final["answer"])


_default: Agent | None = None


def get_agent() -> Agent:
    global _default
    if _default is None:
        _default = Agent()
    return _default


def warm() -> None:
    get_agent().warm()


_ZW = re.compile("[\u200b-\u200d\u2060\ufeff]")
_DOTS = re.compile(r"[\s.\u2026]*(?:\.\.\.|\u2026)[\s.\u2026]*")
HONEST = ("I didn't do it", "That didn't work")


# the first signs of a junk stream (held back until judged): two invisible spaces, two ellipses in a row, or an
# ellipsis glued to a no-break space ("Folder\u00a0…\u00a0has") - normal replies have none of these
_JUNK = re.compile("[\u200b-\u200d\u2060\ufeff]{2}|(?:\\.\\.\\.|\u2026)[\\s\u00a0\u202f\u200b]*(?:\\.\\.\\.|\u2026)"
                   "|[\u00a0\u202f](?:\\.\\.\\.|\u2026)|(?:\\.\\.\\.|\u2026)[\u00a0\u202f]")


def garbled(text: str) -> bool:
    """A streamed reply broken by '… … …' / invisible-space runs: a few words lost in the junk (gpt-oss-120b after
    a tool: "Folder … has been … …It seems… … …"). Real answers never have three ellipses in a row."""
    words = len(re.findall(r"[^\W\d_]{2,}", text))
    dots = len(re.findall(r"\.\.\.|\u2026", text))
    return (dots >= 3 and words <= 2) or (dots >= 3 or len(_ZW.findall(text)) >= 3) and bool(_JUNK.search(text)) \
        and (dots * 2 >= words or words < 12 or len(_ZW.findall(text)) >= 3)


def tidy(text: str) -> str:
    """Invisible characters out, a run of ellipses down to one space."""
    text = _ZW.sub("", text).replace("\u00a0", " ").replace("\u202f", " ")
    return re.sub(r"(?:\s*(?:\.\.\.|\u2026)\s*){2,}", " ", text)


def last_result(msgs: list) -> str:
    """Instead of a garbled reply: what the last tool said (or a plain 'Done.')."""
    for m in reversed(msgs):
        if isinstance(m, ToolMessage) and m.name != meta.NAME and str(m.content).strip():
            return str(m.content).strip()[:300]
    return "Done."


def worth_retry(text: str) -> bool:
    """A refusal to an emoji, "ok", "not good" or small talk is fine as it is (a retry cost up to 4k tokens)."""
    return len(re.findall(r"[^\W\d_]{2,}", text or "")) >= 3 and not router.is_small_talk(text)


def honest(answer: str, msgs: list) -> str:
    """The AI says it did something, but every tool it ran this turn failed or was refused: say so instead."""
    results = [str(m.content) for m in msgs if isinstance(m, ToolMessage) and m.name != meta.NAME]
    if not results or not meta.claims(answer) or any(not r.startswith(("error", "The user declined", "The user already"))
                                                       for r in results):
        return answer
    why = results[-1]
    return ("I didn't do it: you said no." if why.startswith("The user") else
            f"That didn't work: {why[6:].strip()[:200]}")


def run(user_text: str, mode: str = "text", lang: str | None = None) -> str:
    return get_agent().run(user_text, mode=mode, lang=lang)


def stream(user_text: str, mode: str = "text", lang: str | None = None) -> Iterator[str]:
    return get_agent().stream(user_text, mode=mode, lang=lang)


# --- a multi-step request whose earlier step started a background job: the rest waits for it (durable) ---
def start_after_job(job_id: int, texts: list[str], lang: str | None = None):
    """A long job (survives restarts) that waits for job_id to finish, then runs `texts` in order, the first one
    seeing that job's output file. Returns the job."""
    from jarvis.core import longjobs
    title = "then: " + "; ".join(texts)[:60] + f" (after job #{job_id})"
    return longjobs.submit(title, after_job, {"wait": int(job_id), "tasks": texts, "lang": lang or ""},
                           kind="follow", max_tokens=config.AGENT_ASK_ABOVE_TOKENS, max_minutes=120)


def after_job(ctx, params: dict) -> str | None:
    from jarvis.core import safety, store, writer
    jid = int(params["wait"])
    ctx.step(f"waiting for job #{jid}")
    while True:
        row = store.job_get(jid) or {}
        if row.get("status") not in jobs.ACTIVE:
            break
        if ctx.job.cancel_event.wait(5):
            ctx.check()
        ctx.check()
    if row.get("status") != "done" or not row.get("output_path"):
        ctx.step(f"job #{jid} ended {row.get('status') or 'missing'}: nothing to do")
        return None
    path = str(row["output_path"])
    try:
        head = open(path, encoding="utf-8", errors="replace").read(PREV_RESULT_MAX)
    except OSError:
        head = ""
    prev = f"Job #{jid} finished; its result is the file {path}. It begins: {head}"
    bot = Agent(confirm=safety.deny_all, summarize_async=False, use_planner=False, persist=False)
    answers = []
    for i, text in enumerate(params.get("tasks") or []):
        if i < int(ctx.state.get("done") or 0):  # resumed after a restart: this step already ran
            continue
        ctx.check()
        ctx.step(f"step {i + 1}: {text[:60]}")
        ans = bot._run_task(text, "text", params.get("lang") or None, prev, request=text)
        answers.append(f"- {text}: {ans}")
        prev = ans if i else f"{ans}\n(The file is {path}.)"
        ctx.checkpoint(done=i + 1)
    out = writer.output_path(ctx.job.title)
    out.write_text(f"# {ctx.job.title}\n\n" + "\n".join(answers) + "\n", encoding="utf-8")
    ctx.set_output(out)
    return str(out)
