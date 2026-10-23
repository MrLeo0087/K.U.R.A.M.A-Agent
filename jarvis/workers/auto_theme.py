"""Auto theme worker (P9a): every 60 s, when auto theme is on (kv 'auto_theme', default
config.AUTO_THEME), switch light/dark at sunrise/sunset (or config.AUTO_THEME_TIMES). Acts only on
transitions, so a manual change holds until the next one. Logic: tools/general/_autotheme.py."""
from __future__ import annotations

from jarvis.core import config
from jarvis.tools.general import _autotheme
from jarvis.workers.base import Worker


class AutoTheme(Worker):
    name = "auto_theme"
    interval_s = config.AUTO_THEME_INTERVAL_S

    def tick(self) -> None:
        if out := _autotheme.check():
            self.log.info("auto theme: %s", out)

    def info(self) -> dict:
        from jarvis.core import store
        return {"enabled": _autotheme.enabled(), "last": store.kv_get(_autotheme.KV_LAST) or ""}
