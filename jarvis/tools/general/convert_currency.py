"""convert_currency: live exchange rates (open.er-api.com, free, no key; cached 6 h) (safe).

No longer a tool of its own: the merged tool calls convert_currency() (old name kept as an alias)."""
from __future__ import annotations

import time


RATES_URL = "https://open.er-api.com/v6/latest/{base}"
_cache: dict[str, tuple[float, dict]] = {}
_ALIAS = {"rupee": "NPR", "rupees": "NPR", "nepali rupees": "NPR", "nrs": "NPR", "rs": "NPR", "npr": "NPR",
          "indian rupees": "INR", "inr": "INR", "dollar": "USD", "dollars": "USD", "usd": "USD", "$": "USD",
          "euro": "EUR", "euros": "EUR", "pound": "GBP", "pounds": "GBP", "yen": "JPY", "yuan": "CNY",
          "dirham": "AED", "riyal": "SAR", "ringgit": "MYR", "won": "KRW", "aussie dollar": "AUD"}


def _code(c: str) -> str:
    c = (c or "").strip().lower()
    return _ALIAS.get(c, c.upper()[:3])


def rates(base: str) -> dict:
    """Rates for base (patched in tests: no network)."""
    hit = _cache.get(base)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    from jarvis.tools.general import _geo
    data = _geo.get_json(RATES_URL.format(base=base), {})
    if data.get("result") != "success":
        raise RuntimeError("rate service error")
    _cache[base] = (time.time(), data["rates"])
    return data["rates"]


def convert_currency(amount: float, from_currency: str, to_currency: str = "NPR") -> str:
    """Currency conversion.

    Args:
        amount: How much money.
        from_currency: Currency code or name, e.g. USD, dollars, INR.
        to_currency: Target currency (default NPR).
    """
    a, b = _code(from_currency), _code(to_currency)
    try:
        r = rates(a)
    except Exception as e:
        return f"error: couldn't get exchange rates ({type(e).__name__})"
    if b not in r:
        return f"error: unknown currency {to_currency!r}"
    return f"{float(amount):,.2f} {a} = {float(amount) * r[b]:,.2f} {b} (rate {r[b]:.4g})"
