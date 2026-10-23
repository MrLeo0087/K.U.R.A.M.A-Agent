"""Jarvis HTTP API (FastAPI): the only thing the frontend talks to. See jarvis/api/app.py."""


def create_app(*args, **kwargs):  # lazy: importing jarvis.api stays free
    from jarvis.api.app import create_app as _create
    return _create(*args, **kwargs)
