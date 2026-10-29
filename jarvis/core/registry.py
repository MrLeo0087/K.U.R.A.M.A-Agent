"""Tool registry: `@tool(group=..., safety=..., description=...)` on a plain function -> a
LangChain StructuredTool (compact JSON schema from type hints + docstring, group and safety in
.metadata). The decorated function stays a plain function; the tool is `func.tool`.

One file = one tool under jarvis/tools/{interactive,general,external}/. `discover()` imports
them all (pkgutil walk); the module-level helpers use the default registry and discover lazily.
`schemas_for(groups)` returns only the routed groups' tools, ready for `model.bind_tools`.
"""
from __future__ import annotations

import importlib
import inspect
import json
import logging
import pkgutil
import re
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Union, get_args, get_origin

from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from jarvis.core import config

log = logging.getLogger("jarvis.registry")

SAFETY_LEVELS = ("safe", "confirm", "blocked")
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


class ToolError(Exception):
    """Unknown tool or bad arguments."""


Tool = BaseTool  # registry entries are LangChain tools


def safety_of(t: BaseTool) -> str:
    return (t.metadata or {}).get("safety", "safe")


def group_of(t: BaseTool) -> str:
    return (t.metadata or {}).get("group", "general")


def parameters_of(t: BaseTool) -> dict:
    s = t.args_schema
    return s if isinstance(s, dict) else convert_to_openai_tool(t)["function"]["parameters"]


def schema_of(t: BaseTool) -> dict:
    """OpenAI/Groq function-calling schema (what bind_tools sends)."""
    return convert_to_openai_tool(t)


@dataclass
class ToolResult:
    ok: bool
    output: str
    error: str = ""


# --- schema building ---
def _parse_doc(doc: str | None) -> tuple[str, dict[str, str]]:
    """First docstring line and Google-style `Args:` descriptions."""
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()
    summary = lines[0].strip() if lines else ""
    args: dict[str, str] = {}
    in_args, current = False, None
    for line in lines[1:]:
        stripped = line.strip()
        if re.match(r"^(Args|Arguments|Parameters):\s*$", stripped):
            in_args = True
            continue
        if not in_args:
            continue
        if re.match(r"^[A-Z][A-Za-z ]*:\s*$", stripped):  # next section (Returns:, Raises:)
            break
        m = re.match(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$", stripped)
        if m and not line.startswith(" " * 8):
            current = m.group(1)
            args[current] = m.group(2).strip()
        elif current and stripped:
            args[current] = f"{args[current]} {stripped}".strip()
    return summary, args


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) < len(get_args(tp)):
            return (args[0] if len(args) == 1 else Union[tuple(args)]), True
    return tp, False


def type_schema(tp: Any) -> dict:
    """JSON schema for one annotation (str/int/float/bool/Literal/list[...]/Optional)."""
    tp, _ = _unwrap_optional(tp)
    origin = get_origin(tp)
    if tp in _JSON_TYPES:
        return {"type": _JSON_TYPES[tp]}
    if origin is Literal:
        values = list(get_args(tp))
        kinds = {_JSON_TYPES.get(type(v), "string") for v in values}
        out: dict = {"enum": values}
        if len(kinds) == 1:
            out["type"] = kinds.pop()
        return out
    if tp in (list, tuple) or origin in (list, tuple):
        args = get_args(tp)
        return {"type": "array", "items": type_schema(args[0]) if args else {"type": "string"}}
    if tp is dict or origin is dict:
        return {"type": "object"}
    return {"type": "string"}


def build_parameters(func: Callable, arg_docs: dict[str, str] | None = None) -> dict:
    sig = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}
    props: dict[str, dict] = {}
    required: list[str] = []
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) or name.startswith("_"):
            continue
        tp = hints.get(name, str if p.default is p.empty else type(p.default))
        prop = type_schema(tp)
        if arg_docs and arg_docs.get(name):
            prop["description"] = arg_docs[name]
        props[name] = prop
        if p.default is p.empty and not _unwrap_optional(tp)[1]:
            required.append(name)
    out: dict = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def _coerce(value: Any, tp: Any) -> Any:
    """Light coercion for values models send as strings ("3" -> 3, "true" -> True)."""
    tp, _ = _unwrap_optional(tp)
    if value is None:
        return None
    try:
        if tp is bool and isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        if tp in (int, float) and isinstance(value, str):
            return tp(value)
        if tp is int and isinstance(value, float) and value.is_integer():
            return int(value)
        if (tp is list or get_origin(tp) is list) and isinstance(value, str):
            return [value]
    except (TypeError, ValueError):
        pass
    return value


def truncate(text: str, limit: int | None = None) -> str:
    limit = limit or config.TOOL_OUTPUT_MAX_CHARS
    return text if len(text) <= limit else text[: limit - 15].rstrip() + " ...[truncated]"


def _to_text(result: Any) -> str:
    if result is None:
        return "done"
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


# --- registry ---
@dataclass
class Registry:
    tools: dict[str, BaseTool] = field(default_factory=dict)
    packages: tuple[str, ...] = ("jarvis.tools",)
    _discovered: bool = False
    # retired tool name -> (new tool, convert(args) -> args, fixed args). Old names keep working for the fast
    # path, the Telegram bot and saved commands; the LLM only ever sees the new, merged tools.
    legacy: dict[str, tuple[str, Callable[[dict], dict] | None, dict]] = field(default_factory=dict)

    def tool(self, _func: Callable | None = None, *, name: str | None = None,
             group: str = "general", safety: str = "safe", description: str = "",
             max_chars: int | None = None) -> Callable:
        if safety not in SAFETY_LEVELS:
            raise ValueError(f"safety must be one of {SAFETY_LEVELS}, got {safety!r}")

        def deco(func: Callable) -> Callable:
            summary, arg_docs = _parse_doc(func.__doc__)
            t = StructuredTool.from_function(
                func=func, name=name or func.__name__,
                description=(description or summary or func.__name__).strip(),
                args_schema=build_parameters(func, arg_docs),
                metadata={"group": group, "safety": safety, "module": func.__module__,
                          **({"max_chars": max_chars} if max_chars else {})})
            old = self.tools.get(t.name)
            if old and (old.metadata or {}).get("module") != func.__module__:
                log.warning("tool %s from %s replaces the one from %s", t.name, func.__module__,
                            (old.metadata or {}).get("module"))
            self.tools[t.name] = t
            func.tool = t  # type: ignore[attr-defined]
            return func

        return deco(_func) if callable(_func) else deco

    def discover(self, subpackages: tuple[str, ...] | None = None) -> list[str]:
        """Import every module under <package>.<sub> for each tool sub-package."""
        imported: list[str] = []
        for base in self.packages:
            for sub in subpackages or config.TOOL_PACKAGES:
                pkg_name = f"{base}.{sub}"
                try:
                    pkg = importlib.import_module(pkg_name)
                except ImportError as e:
                    log.warning("tool package %s not importable: %s", pkg_name, e)
                    continue
                for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg_name}."):
                    try:
                        importlib.import_module(info.name)
                        imported.append(info.name)
                    except Exception as e:  # one broken tool must not kill the others
                        log.error("failed to load tool module %s: %s", info.name, e)
        if "jarvis.tools" in self.packages:  # P7c: saved toolsmith skills (small JSON files, lazy run)
            try:
                from jarvis.core import toolsmith
                toolsmith.register_saved(self)
            except Exception as e:
                log.warning("could not load saved skills: %s", e)
        self._discovered = True
        return imported

    def _ensure(self) -> None:
        if not self._discovered:
            self.discover()

    def get(self, name: str) -> BaseTool | None:
        self._ensure()
        return self.tools.get(name)

    def alias(self, old: str, new: str, convert: Callable[[dict], dict] | None = None, **fixed: Any) -> None:
        """Keep a retired tool name working: calls to `old` run `new` with convert(args) + fixed args."""
        self.legacy[old] = (new, convert, fixed)

    def resolve(self, name: str, args: Any = None) -> tuple[str, Any]:
        """(name, args) with a retired name mapped onto the tool that replaced it."""
        self._ensure()
        hit = self.legacy.get(name)
        if hit is None or name in self.tools:
            return name, args
        new, convert, fixed = hit
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        a = dict(args or {})
        return new, {**(convert(a) if convert else a), **fixed}

    def groups(self) -> list[str]:
        """The router's groups: every specialised tool's group, plus (v2) the groups a general tool covers."""
        self._ensure()
        groups = {group_of(t) for t in self.tools.values()} - {"core"}
        if config.CORE_TOOLS:
            groups |= {g for n, cov in config.CORE_COVERS.items() if n in self.tools for g in cov}
        return sorted(groups)

    def schemas_for(self, groups: list[str] | tuple[str, ...]) -> list[BaseTool]:
        """LangChain tools of the routed groups only (for bind_tools). v2 (config.CORE_TOOLS): the general tools that
        cover those groups; a group no general tool covers keeps its old tools."""
        self._ensure()
        wanted = set(groups)
        if not config.CORE_TOOLS:
            return [t for t in self.tools.values() if group_of(t) in wanted]
        serving = {g: [n for n, cov in config.CORE_COVERS.items() if g in cov and n in self.tools] for g in groups}
        core: list[str] = []
        for g in groups:  # each group's main general tool first (in the router's order)...
            if serving[g] and serving[g][0] not in core:
                core.append(serving[g][0])
        for g in groups:  # ...then the others that also cover it, while there is room
            core += [n for n in serving[g] if n not in core]
        core = core[:config.CORE_MAX_TOOLS]
        covered = {g for g in groups if serving[g]}
        old = [t for t in self.tools.values() if group_of(t) in wanted - covered and group_of(t) != "core"]
        return [self.tools[n] for n in core] + old

    def openai_schemas_for(self, groups: list[str] | tuple[str, ...]) -> list[dict]:
        return [schema_of(t) for t in self.schemas_for(groups)]

    def parse_args(self, tool: BaseTool, args: Any) -> dict:
        if args is None or args == "":
            args = {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError as e:
                raise ToolError(f"arguments are not valid JSON: {e}") from e
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        try:
            hints = typing.get_type_hints(getattr(tool, "func", None))
        except Exception:
            hints = {}
        params = parameters_of(tool)
        props = params.get("properties", {})
        clean = {k: _coerce(v, hints.get(k, Any)) for k, v in args.items() if k in props}
        missing = [k for k in params.get("required", []) if k not in clean]
        if missing:
            raise ToolError(f"missing required argument(s): {', '.join(missing)}")
        return clean

    def call(self, name: str, args: Any = None) -> ToolResult:
        """Run a tool (no safety checks: use jarvis.core.safety.execute for that)."""
        name, args = self.resolve(name, args)
        t = self.get(name)
        if t is None:
            return ToolResult(False, f"error: unknown tool {name!r}", "unknown tool")
        try:
            out = t.invoke(self.parse_args(t, args))
        except ToolError as e:
            return ToolResult(False, f"error: {e}", str(e))
        except Exception as e:
            log.exception("tool %s failed", name)
            return ToolResult(False, truncate(f"error: {type(e).__name__}: {e}"), f"{type(e).__name__}: {e}")
        full = _to_text(out)
        note, limit = "", (t.metadata or {}).get("max_chars")
        try:  # a long result goes to the Workspace card in full; the LLM gets a truncated copy + a note
            from jarvis.core import workspace
            note = workspace.offer(name, full)
            if workspace.full_requested() or name in config.WORKSPACE_SHOW_ALL:  # "the whole list" / a pick list
                limit = max(limit or 0, config.TOOL_OUTPUT_FULL_CHARS)
        except Exception as e:
            log.warning("workspace publish failed: %s", e)
        return ToolResult(True, truncate(full, limit) + note)


REGISTRY = Registry()

tool = REGISTRY.tool
alias = REGISTRY.alias
resolve = REGISTRY.resolve
discover = REGISTRY.discover
get = REGISTRY.get
groups = REGISTRY.groups
schemas_for = REGISTRY.schemas_for
openai_schemas_for = REGISTRY.openai_schemas_for
call = REGISTRY.call
