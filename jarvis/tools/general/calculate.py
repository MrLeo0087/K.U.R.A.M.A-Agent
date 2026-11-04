"""calculate: safe math and common unit conversions, no LLM, no network (safe)."""
from __future__ import annotations

import ast
import math
import operator as op
import re

from jarvis.core.registry import alias, tool

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
_UNIT_NAMES = {  # long / plural / other spellings -> the key above ('10000 km in meter' failed, 11-04)
    "meter": "m", "meters": "m", "metre": "m", "metres": "m", "kilometer": "km", "kilometers": "km", "kilometre": "km",
    "kilometres": "km", "kms": "km", "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "millimeter": "mm",
    "millimeters": "mm", "foot": "ft", "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg", "kgs": "kg",
    "gram": "g", "grams": "g", "gm": "g", "ounce": "oz", "ounces": "oz", "liters": "l", "litres": "l",
    "milliliter": "ml", "milliliters": "ml", "gallons": "gallon", "gigabyte": "gb", "gigabytes": "gb",
    "megabyte": "mb", "megabytes": "mb", "kilobyte": "kb", "kilobytes": "kb", "terabyte": "tb", "terabytes": "tb",
    "hr": "h", "hrs": "h", "mins": "min", "minute": "min", "second": "s", "secs": "s", "week": "wk", "weeks": "wk"}
_UNITS["wk"] = ("time", 7 * 86400)


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
    t = re.sub(r"^(?:what\s+is|what'?s|how\s+(?:many|much)|convert|change|tell\s+me)\s+", "", t)
    t = re.sub(r"\b([a-z]+)\b", lambda m: _UNIT_NAMES.get(m.group(1), m.group(1)), t.replace(",", ""))
    t = re.sub(r"^(\S+\s+\S+)\s+(?:are\s+there\s+)?in\s+(?:a\s+|one\s+)?", r"\1 in ", t)
    if m := re.match(r"^(-?[\d.]+)\s*°?\s*(c|f|celsius|fahrenheit)\s+(?:to|in)\s+°?\s*(c|f|celsius|fahrenheit)$", t):
        v, a, b = float(m.group(1)), m.group(2)[0], m.group(3)[0]
        r = v * 9 / 5 + 32 if (a, b) == ("c", "f") else (v - 32) * 5 / 9 if (a, b) == ("f", "c") else v
        return f"{_fmt(v)}°{a.upper()} = {_fmt(r)}°{b.upper()}"
    if m := re.match(r"^([\d.]+)\s*([a-z]+)\s+(?:to|in|into)\s+([a-z]+)$", t):
        v, a, b = float(m.group(1)), m.group(2), m.group(3)
        if a in _UNITS and b in _UNITS and _UNITS[a][0] == _UNITS[b][0]:
            return f"{_fmt(v)} {a} = {_fmt(v * _UNITS[a][1] / _UNITS[b][1])} {b}"
    return None


_MONEY = re.compile(r"^(?:convert\s+)?(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<a>[a-z$]+(?: [a-z]+)?)\s+(?:to|in|into)\s+"
                    r"(?P<b>[a-z]+(?: [a-z]+)?)$", re.I)
_CODES = {"NPR", "INR", "USD", "EUR", "GBP", "JPY", "CNY", "AED", "SAR", "MYR", "KRW", "AUD", "CAD", "CHF", "SGD",
          "QAR", "KWD", "BDT", "PKR", "LKR", "THB", "HKD", "NZD", "SEK", "NOK", "DKK", "RUB", "BRL", "ZAR", "TRY"}


_WORDS = ((r"\bper\s*cent(?:age)?\b|\bpercent(?:age)?\b|\bpct\b|\bper(?=\s+of\b)", "%"), (r"\bplus\b|\badd(?:ed)?\s+to\b", "+"),
          (r"\bminus\b|\bless\b", "-"), (r"\btimes\b|\bmultiplied\s+by\b|(?<=\d)\s*x\s*(?=\d)", "*"),
          (r"\bdivided\s+by\b|\bover\b", "/"), (r"\bsquare\s+root\s+of\s*([\d.]+)", r"sqrt(\1)"), (r"\bto\s+the\s+power\s+of\b", "^"))


def spoken_math(text: str) -> str:
    """'30 percent of 100' / '32 per of 100' / '5 times 6' -> '30% of 100' / '32% of 100' / '5 * 6' (the words
    people say or type, as the symbols the calculator reads); lead-ins like 'what is the' / 'i mean' dropped."""
    t = " ".join((text or "").split()).strip().rstrip("?.!=")
    t = re.sub(r"^(?:(?:i\s+mean|so|ok(?:ay)?|please|hey|kurama)[\s,]+)*(?:(?:what(?:'s|\s+is)|calculate|compute|find|tell\s+me)"
               r"\s+)?(?:the\s+)?", "", t, flags=re.I)
    for pat, sym in _WORDS:
        t = re.sub(pat, sym, t, flags=re.I)
    return re.sub(r"\s*%\s*", "% ", t).replace("% of", "% of").strip()


@tool(group="daily", safety="safe",
      description="Do math (+ - * / ^ %, sqrt, percent of), convert units (km, kg, °C, GB, hours...) or money "
                  "with today's rate (100 USD to NPR).")
def calculate(expression: str) -> str:
    """Calculate or convert.

    Args:
        expression: e.g. "18% of 2500", "(45*3)+12", "sqrt(144)", "10 km to miles", "100 f to c", "50 dollars to NPR".
    """
    text = (expression or "").strip().rstrip("?=")
    if re.search(r"\d", text) and re.search(r"[a-z]", text, re.I):
        text = spoken_math(text) if not (_convert(text) or _MONEY.match(text)) else text
    if conv := _convert(text):
        return conv
    if money := _MONEY.match(text):  # "100 usd to npr", "50 dollars in rupees"
        from jarvis.tools.general.convert_currency import _ALIAS, convert_currency
        a, b = money.group("a").lower(), money.group("b").lower()
        if (a in _ALIAS or a.upper() in _CODES) and (b in _ALIAS or b.upper() in _CODES):
            return convert_currency(float(money.group("v").replace(",", "")), a, b)
    e = text.lower().replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    e = re.sub(r"([\d.]+)\s*%\s*of\s*([\d.]+)", r"(\1/100*\2)", e)
    e = re.sub(r"\b(what is|what's|calculate|compute|equals?)\b", "", e).strip()
    try:
        return f"{text} = {_fmt(_eval(ast.parse(e, mode='eval')))}"
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError) as ex:
        return f"error: can't calculate that ({ex})"


alias("convert_currency", "calculate", lambda a: {"expression": f"{a.get('amount', 1)} {a.get('from_currency', 'USD')} to {a.get('to_currency', 'NPR')}"})
