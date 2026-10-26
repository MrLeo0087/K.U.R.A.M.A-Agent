"""Device sound and the mic ("Hear device sound" in settings).

OFF (default): the laptop's own sound (videos, music, KURAMA's own voice) is removed from what KURAMA hears.
PipeWire's echo canceller (module-echo-cancel, webrtc) gets a sink that every app plays through (the default speaker)
and a mic source with that sound subtracted, which only KURAMA's page records from (picked by name; the system's
default mic stays the real one, so other apps never lose their mic when the canceller is loaded or removed). Measured here: the speaker's echo drops
by ~20 dB after 2-3 s. Cost: ~9% of a core, but only while something records that mic (KURAMA awake and listening);
playback through it costs nothing extra, and the sleeping wake listener reads the raw mic (raw_source()).
The canceller sends sound to the real speaker of the moment: headphones plugged in or Bluetooth connected -> it
follows (watch()), so routing through it never hides a new output device.
ON: the module is removed and the real speaker/mic are the defaults again (KURAMA then hears both).

`python -m jarvis.core.devaudio off` puts the system back (the power-off script calls it).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time

from jarvis.core import config

log = logging.getLogger(__name__)

EC_SINK, EC_SOURCE = "kurama_ec_sink", "kurama_ec_source"
KEY = "hear_device_sound"  # kv: "1" = hear it (no canceller)
_lock = threading.RLock()
_watcher: threading.Thread | None = None


def _state_path():
    return config.DATA_DIR / "devaudio.json"  # the real speaker/mic to give back


def _pactl(*args: str, timeout: float = 5) -> str:
    r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "pactl failed").strip()[:200])
    return r.stdout


def available() -> bool:
    return shutil.which("pactl") is not None


def _names(kind: str) -> list[str]:
    return [ln.split("\t")[1] for ln in _pactl("list", "short", kind).splitlines() if ln.count("\t") >= 1]


def _real(name: str | None) -> bool:
    return bool(name) and not name.startswith("kurama_ec") and not name.endswith(".monitor")


def _ours() -> list[str]:
    """Module ids of our echo canceller."""
    return [ln.split("\t")[0] for ln in _pactl("list", "short", "modules").splitlines()
            if "module-echo-cancel" in ln and EC_SINK in ln]


def _load_saved() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    try:
        _state_path().write_text(json.dumps(d), encoding="utf-8")
    except OSError as e:
        log.warning("could not save device audio state: %s", e)


def hear() -> bool:
    # Default ON (no echo canceller): the virtual sink made everyday speaker sound quiet/thin. Turning the
    # canceller on (hear=False) is opt-in from Settings for people who want KURAMA to not hear device sound.
    from jarvis.core import store
    return store.kv_get(KEY, "1") == "1"


def mic_off() -> bool:
    """The user muted the mic / chose text mode: the canceller must not hold the real mic (it keeps it RUNNING)."""
    from jarvis.core import store
    return store.kv_get("mic_off") == "1"


def wanted() -> bool:
    return not hear() and not mic_off()


def cancelling() -> bool:
    try:
        return bool(_ours())
    except Exception:
        return False


def status() -> dict:
    return {"hear": hear(), "cancelling": cancelling(), "available": available()}


def raw_source() -> str | None:
    """The real mic while the canceller runs (the sleeping wake listener reads it: cheaper), else None."""
    return _load_saved().get("source") if cancelling() else None


def _load(sink: str, source: str) -> None:
    _pactl("load-module", "module-echo-cancel", "aec_method=webrtc", f"source_name={EC_SOURCE}",
           f"sink_name={EC_SINK}", f"source_master={source}", f"sink_master={sink}",
           "source_properties=device.description='Microphone (KURAMA, no device sound)'",
           "sink_properties=device.description='Speakers (through KURAMA)'")


def cancel_on(sink: str | None = None) -> None:
    """Load (or re-aim at `sink`) the canceller and make it the default speaker + mic."""
    with _lock:
        saved = _load_saved()
        cur_sink, cur_src = _pactl("get-default-sink").strip(), _pactl("get-default-source").strip()
        sink = sink or (cur_sink if _real(cur_sink) else saved.get("sink"))
        source = cur_src if _real(cur_src) else saved.get("source")
        sinks, sources = _names("sinks"), _names("sources")
        if sink not in sinks:
            sink = next((s for s in sinks if _real(s)), None)
        if source not in sources:
            source = next((s for s in sources if _real(s)), None)
        if not sink or not source:
            raise RuntimeError("no speaker or mic found")
        if _ours() and (saved.get("sink"), saved.get("source")) == (sink, source):
            pass  # already aimed right
        else:
            for mid in _ours():
                _pactl("unload-module", mid)
            _load(sink, source)
        _save({"sink": sink, "source": source})
        for _ in range(20):  # the new nodes take a moment to appear
            if EC_SINK in _names("sinks") and EC_SOURCE in _names("sources"):
                break
            time.sleep(0.1)
        _pactl("set-default-sink", EC_SINK)
        # the system's default MIC stays the real one: other apps (Brave / WhatsApp / Meet) never record through our
        # virtual mic, so loading/unloading the canceller can't pull a mic away from them ('Microphone not found');
        # KURAMA's page picks the cleaned mic by its name ('KURAMA')
        if _pactl("get-default-source").strip() != source:
            _pactl("set-default-source", source)


def cancel_off() -> None:
    """Remove the canceller and give the real speaker/mic back."""
    with _lock:
        saved = _load_saved()
        for mid in _ours():
            _pactl("unload-module", mid)
        sinks, sources = _names("sinks"), _names("sources")
        if saved.get("sink") in sinks:
            _pactl("set-default-sink", saved["sink"])
        if saved.get("source") in sources:
            _pactl("set-default-source", saved["source"])


def apply() -> dict:
    """Make the system match the setting (startup and after a change). Never raises."""
    if not available():
        return {**status(), "error": "pactl not found"}
    try:
        if not wanted():  # 'hear device sound' on, or the mic is off: no canceller, real speaker + mic
            cancel_off()
        else:
            cancel_on()
            watch()
    except Exception as e:
        log.warning("device sound setting not applied: %s", e)
        return {**status(), "error": str(e)}
    return status()


def set_hear(on: bool) -> dict:
    from jarvis.core import store
    store.kv_set(KEY, "1" if on else "0")
    return apply()


def _follow() -> None:
    """A speaker came or went: aim the canceller at the newest real one (headphones, Bluetooth, HDMI)."""
    if not wanted() or not cancelling():
        return
    saved, sinks = _load_saved(), _names("sinks")
    real = [s for s in sinks if _real(s)]
    if not real:
        return
    newest = real[-1]  # pactl lists sinks in creation order: the last one is what was just plugged in
    want = newest if newest != saved.get("sink") and _new.get("sink") == newest else (
        saved.get("sink") if saved.get("sink") in real else newest)
    if want != saved.get("sink") or EC_SINK not in sinks:
        log.info("device sound: speaker is now %s", want)
        cancel_on(want)


_new: dict = {}


def watch() -> None:
    """One `pactl subscribe` (idle: no CPU) that re-aims the canceller when speakers change."""
    global _watcher
    if _watcher and _watcher.is_alive():
        return

    def run() -> None:
        while True:
            try:
                if wanted() and not cancelling():  # the audio server restarted: set it up again
                    cancel_on()
                p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
                for line in p.stdout:  # "Event 'new' on sink #123", "Event 'change' on server #45"
                    if "'change' on server" in line:  # the user picked another speaker in Settings
                        try:
                            cur = _pactl("get-default-sink").strip()
                            if _real(cur) and wanted() and cancelling():
                                cancel_on(cur)
                        except Exception as e:
                            log.warning("device sound: %s", e)
                        continue
                    if " on sink #" not in line or ("'new'" not in line and "'remove'" not in line):
                        continue
                    if "'new'" in line:
                        time.sleep(1.0)  # let it settle (Bluetooth profiles switch twice)
                        names = _names("sinks")
                        _new["sink"] = names[-1] if names else None
                    try:
                        _follow()
                    except Exception as e:
                        log.warning("device sound: could not follow the speaker: %s", e)
                p.wait()
            except Exception as e:
                log.warning("device sound watcher: %s", e)
            time.sleep(5)

    _watcher = threading.Thread(target=run, name="kurama-devaudio", daemon=True)
    _watcher.start()


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["off"]:  # power off: put the system back as it was
        try:
            cancel_off()
        except Exception as e:
            print(f"device sound: {e}")
    else:
        print(json.dumps(apply()))
