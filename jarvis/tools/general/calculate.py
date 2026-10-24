"""calculate: safe math and common unit conversions, no LLM, no network (safe)."""
from __future__ import annotations

import ast
import math
import operator as op
import re

from jarvis.core.registry import tool

_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow,
        ast.Mod: op.mod, ast.FloorDiv: op.floordiv, ast.USub: op.neg, ast.UAdd: op.pos}
_FUNCS = {n: getattr(math, n) for n in ("sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil")}
_FUNCS.update(abs=abs, round=round)
_CONST = {"pi": math.pi, "e": math.e}
# unit -> (dimension, factor to the base unit)
_UNITS = {"km": ("len", 1000), "m": ("len", 1), "cm": ("len", 0.01), "mm": ("len", 0.001), "mi": ("len", 1609.344),
          "mile": ("len", 1609.344), "miles": ("len", 1609.344), "ft": ("len", 0.3048), "feet": ("len", 0.3048),
          "in": ("len", 0.0254), "inch": ("len", 0.0254), "inches": ("len", 0.0254),
          "kg": ("mass", 1), "g": ("mass", 0.001), "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237),
          "pound": ("mass", 0.45359237), "pounds": ("mass", 0.45359237), "oz": ("mass", 0.0283495),
          "l": ("vol", 1), "liter": ("vol", 1), "litre": ("vol", 1), "ml": ("vol", 0.001), "gallon": ("vol", 3.78541),
          "gb": ("data", 1024 ** 3), "mb": ("data", 1024 ** 2), "kb": ("data", 1024), "tb": ("data", 1024 ** 4),
          "h": ("time", 3600), "hour": ("time", 3600), "hours": ("time", 3600), "min": ("time", 60),
          "minutes": ("time", 60), "s": ("time", 1), "sec": ("time", 1), "seconds": ("time", 1),
          "day": ("time", 86400), "days": ("time", 86400)}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONST:
        return _CONST[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and len(node.args) <= 2:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("unsupported expression")


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() and abs(x) < 1e15 else f"{x:,.4g}" if abs(x) >= 1e6 else f"{x:,.4f}".rstrip("0").rstrip(".")


def _convert(text: str) -> str | None:
    t = text.lower().strip()
    if m := re.match(r"^(-?[\d.]+)\s*°?\s*(c|f|celsius|fahrenheit)\s+(?:to|in)\s+°?\s*(c|f|celsius|fahrenheit)$", t):
        v, a, b = float(m.group(1)), m.group(2)[0], m.group(3)[0]
        r = v * 9 / 5 + 32 if (a, b) == ("c", "f") else (v - 32) * 5 / 9 if (a, b) == ("f", "c") else v
        return f"{_fmt(v)}°{a.upper()} = {_fmt(r)}°{b.upper()}"
    if m := re.match(r"^([\d.]+)\s*([a-z]+)\s+(?:to|in|into)\s+([a-z]+)$", t):
        v, a, b = float(m.group(1)), m.group(2), m.group(3)
        if a in _UNITS and b in _UNITS and _UNITS[a][0] == _UNITS[b][0]:
            return f"{_fmt(v)} {a} = {_fmt(v * _UNITS[a][1] / _UNITS[b][1])} {b}"
    return None


@tool(group="daily", safety="safe", description="Do math (+ - * / ^ %, sqrt, percent of) or convert units (km, kg, °C, GB, hours...).")
def calculate(expression: str) -> str:
    """Calculate or convert.

    Args:
        expression: e.g. "18% of 2500", "(45*3)+12", "sqrt(144)", "10 km to miles", "100 f to c".
    """
    text = (expression or "").strip().rstrip("?=")
    if conv := _convert(text):
        return conv
    e = text.lower().replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    e = re.sub(r"([\d.]+)\s*%\s*of\s*([\d.]+)", r"(\1/100*\2)", e)
    e = re.sub(r"\b(what is|what's|calculate|compute|equals?)\b", "", e).strip()
    try:
        return f"{text} = {_fmt(_eval(ast.parse(e, mode='eval')))}"
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError) as ex:
        return f"error: can't calculate that ({ex})"
