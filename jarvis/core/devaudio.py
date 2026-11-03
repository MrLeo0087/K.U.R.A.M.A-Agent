"""Device sound and the mic ("Hear device sound" in settings).

OFF (default): the laptop's own sound (videos, music, KURAMA's own voice) is removed from what KURAMA hears —
ONLY while a page records the mic (voice / talk mode: mic_use()), plus EC_LINGER_S after. The rest of the time the
canceller is unloaded: the laptop's speaker and mic are the plain ones (no quieter sound, mic not held).
PipeWire's echo canceller (module-echo-cancel, webrtc) gets a sink that every app plays through and a mic source
with that sound subtracted; both become the defaults, so it covers all apps. Measured here: the speaker's echo drops
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
import re
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


def cancelling() -> bool:
    try:
        return bool(_ours())
    except Exception:
        return False


def status() -> dict:
    return {"hear": hear(), "cancelling": cancelling(), "available": available()}


def raw_source() -> str | None:
    """The real mic while the canceller runs (the sleeping wake listener reads it: cheaper), else None.
    While KURAMA's own music plays, the cleaned mic instead: the wake word must be heard over the music."""
    try:
        from jarvis.core import music
        if music.running():
            return None
    except Exception:
        pass
    return _load_saved().get("source") if cancelling() else None


def _load(sink: str, source: str) -> None:
    _pactl("load-module", "module-echo-cancel", "aec_method=webrtc", f"source_name={EC_SOURCE}",
           f"sink_name={EC_SINK}", f"source_master={source}", f"sink_master={sink}",
           "source_properties=device.description='Microphone (KURAMA, no device sound)'",
           "sink_properties=device.description='Speakers (through KURAMA)'")


def _configured(kind: str) -> str | None:
    """The output / input the system remembers as chosen (WirePlumber's default.configured.audio.sink|source; it
    survives reboots and decides what a newly connected speaker does). None if unknown."""
    if not shutil.which("pw-metadata"):
        return None
    try:
        out = subprocess.run(["pw-metadata", "0", f"default.configured.audio.{kind}"], capture_output=True, text=True,
                             timeout=3).stdout
        m = re.search(r"value:'(\{.*?\})'", out)
        return json.loads(m.group(1)).get("name") if m else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _set_configured(kind: str, name: str) -> None:
    """Put the remembered choice back exactly (even when that speaker is off right now: when it connects again the
    system picks it, as if KURAMA had never been there)."""
    if shutil.which("pw-metadata"):
        subprocess.run(["pw-metadata", "0", f"default.configured.audio.{kind}", json.dumps({"name": name}),
                        "Spa:String:JSON"], capture_output=True, timeout=3)


def _descriptions() -> dict[str, str]:
    """sink name -> its description ('U-2500BT', '... HDMI / DisplayPort 1 Output')."""
    out, name = {}, ""
    for ln in _pactl("list", "sinks").splitlines():
        ln = ln.strip()
        if ln.startswith("Name:"):
            name = ln[5:].strip()
        elif ln.startswith("Description:") and name:
            out[name] = ln[12:].strip()
    return out


def _rank(name: str, desc: str = "") -> int:
    """Which output the owner most likely listens on: Bluetooth 3 > USB 2 > the laptop's speaker 1 > HDMI 0."""
    n, d = name.lower(), desc.lower()
    if n.startswith("bluez_"):
        return 3
    if "usb" in n or "usb" in d:
        return 2
    return 0 if "hdmi" in n or "hdmi" in d or "displayport" in d else 1


def _best(saved: dict) -> str | None:
    """The real speaker to send sound to when the system's own choice can't be read (our canceller is the default):
    the one the owner picked (saved explicit), else a connected Bluetooth / USB speaker before the laptop's own
    (11-03: the canceller sent everything to the laptop speaker while the U-2500BT Bluetooth speaker was on, so
    with KURAMA the sound was quiet and without it loud), then the one used before."""
    real = [x for x in _names("sinks") if _real(x)]
    if not real:
        return None
    if saved.get("explicit") and saved.get("sink") in real:
        return saved["sink"]
    desc = _descriptions()
    return max(real, key=lambda x: (_rank(x, desc.get(x, "")), x == saved.get("sink"), real.index(x)))


def _volume(sink: str) -> tuple[int, bool] | None:
    """(volume %, muted) of a sink, None when it isn't there."""
    try:
        v = re.search(r"(\d+)%", _pactl("get-sink-volume", sink))
        m = "yes" in _pactl("get-sink-mute", sink).lower()
        return (int(v.group(1)), m) if v else None
    except Exception:  # noqa: BLE001 - gone / no audio server
        return None


def _set_volume(sink: str, pct: int, muted: bool) -> None:
    _pactl("set-sink-volume", sink, f"{pct}%")
    _pactl("set-sink-mute", sink, "1" if muted else "0")


def _take_volume(master: str) -> None:
    """Our sink gets the speaker's volume and mute, the speaker goes to 100%: the volume keys (which now move ours)
    reach as loud as without KURAMA, and the two never multiply."""
    got = _volume(master) or (100, False)
    _set_volume(EC_SINK, *got)
    _set_volume(master, 100, False)


def _give_volume(master: str | None) -> None:
    """The speaker gets back the volume and mute the owner had on ours (their last change while KURAMA listened)."""
    if master and master in _names("sinks") and (got := _volume(EC_SINK)) is not None:
        _set_volume(master, *got)


def cancel_on(sink: str | None = None, explicit: bool = False) -> None:
    """Load (or re-aim at `sink`) the canceller and make it the default speaker + mic. explicit: the owner chose
    that speaker in Settings (it then wins over a Bluetooth one)."""
    with _lock:
        saved = _load_saved()
        cur_sink, cur_src = _pactl("get-default-sink").strip(), _pactl("get-default-source").strip()
        if not sink and _real(cur_sink):
            sink, explicit = cur_sink, True  # the system's own choice right now: respected
        sink = sink or _best(saved)
        source = cur_src if _real(cur_src) else saved.get("source")
        sinks, sources = _names("sinks"), _names("sources")
        if sink not in sinks:
            sink = next((s for s in sinks if _real(s)), None)
        if source not in sources:
            source = next((s for s in sources if _real(s)), None)
        if not sink or not source:
            raise RuntimeError("no speaker or mic found")
        first = not _ours()
        if first:  # the owner's remembered choice, before ours replaces it (put back by cancel_off)
            for kind, key in (("sink", "configured_sink"), ("source", "configured_source")):
                if (c := _configured(kind)) and not c.startswith("kurama_ec"):
                    saved[key] = c
        loaded = False
        if not first and (saved.get("sink"), saved.get("source")) == (sink, source):
            pass  # already aimed right
        else:
            if not first:  # re-aimed: the old speaker gets back the volume the owner set on ours
                _give_volume(saved.get("sink"))
            for mid in _ours():
                _pactl("unload-module", mid)
            _load(sink, source)
            loaded = True
        _save({**{k: v for k, v in saved.items() if k.startswith("configured_")},
               "sink": sink, "source": source, "explicit": bool(explicit)})
        for _ in range(20):  # the new nodes take a moment to appear
            if EC_SINK in _names("sinks") and EC_SOURCE in _names("sources"):
                break
            time.sleep(0.1)
        _pactl("set-default-sink", EC_SINK)
        _pactl("set-default-source", EC_SOURCE)
        if loaded:  # ONE volume: ours takes the speaker's, the speaker goes to 100% (they multiplied: 88% x 81% =
            _take_volume(sink)  # 71% while KURAMA listened, and the volume keys stopped at ours' 100%, 11-03)


def cancel_off() -> None:
    """Remove the canceller and give the real speaker/mic back. Nothing of ours loaded: the defaults are NOT touched
    (startup used to set the speaker saved long ago as the default, over the Bluetooth speaker in use)."""
    with _lock:
        mods = _ours()
        if not mods:
            return
        saved = _load_saved()
        _give_volume(saved.get("sink"))  # the speaker gets the volume the owner set while KURAMA listened
        for mid in mods:
            _pactl("unload-module", mid)
        sinks, sources = _names("sinks"), _names("sources")
        if saved.get("configured_sink"):  # exactly what the system remembered before KURAMA
            _set_configured("sink", saved["configured_sink"])
        elif (target := _best(saved)) in sinks:
            _pactl("set-default-sink", target)
        if saved.get("configured_source"):
            _set_configured("source", saved["configured_source"])
        elif saved.get("source") in sources:
            _pactl("set-default-source", saved["source"])
        _save({k: v for k, v in saved.items() if not k.startswith("configured_")})  # used once


_users: set[str] = set()  # pages recording the mic right now (voice / talk mode)
_release: threading.Timer | None = None


def mic_use(on: bool, who: str = "page") -> dict:
    """A page starts / stops recording: the canceller is loaded while anyone records, unloaded EC_LINGER_S after."""
    global _release
    with _lock:
        (_users.add if on else _users.discard)(who)
        if _release:
            _release.cancel()
            _release = None
        if not _users and cancelling():
            _release = threading.Timer(config.EC_LINGER_S, _idle_off)
            _release.daemon = True
            _release.start()
    if on and not hear() and available() and not cancelling():
        try:
            cancel_on()
            watch()
        except Exception as e:  # no speaker / mic: KURAMA still hears, just with the device sound
            log.warning("echo canceller not started: %s", e)
    return status()


def _idle_off() -> None:
    global _release
    with _lock:
        _release = None
        if not _users:
            cancel_off()
            log.info("device sound: nobody records the mic: canceller off, plain speaker + mic again")


def apply() -> dict:
    """Make the system match the setting (startup and after a change). Never raises."""
    if not available():
        return {**status(), "error": "pactl not found"}
    try:
        if hear() or not _users:
            cancel_off()  # startup: a canceller left from before is removed (mic free, normal volume)
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


def _follow(added: str | None = None) -> None:
    """A speaker came or went: a new Bluetooth / USB speaker gets the sound at once; the one in use gone -> the best
    one left."""
    if hear() or not cancelling():
        return
    saved, sinks = _load_saved(), _names("sinks")
    real = [x for x in sinks if _real(x)]
    if not real:
        return
    if added and added in real and _rank(added, _descriptions().get(added, "")) >= 2 and added != saved.get("sink"):
        want = added
    elif saved.get("sink") not in real or EC_SINK not in sinks:
        want = _best(saved)
    else:
        return
    log.info("device sound: speaker is now %s", want)
    cancel_on(want)


def watch() -> None:
    """One `pactl subscribe` (idle: no CPU) that re-aims the canceller when speakers change."""
    global _watcher
    if _watcher and _watcher.is_alive():
        return

    def run() -> None:
        while True:
            try:
                if not hear() and not cancelling():  # the audio server restarted: set it up again
                    cancel_on()
                p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
                for line in p.stdout:  # "Event 'new' on sink #123", "Event 'change' on server #45"
                    if "'change' on server" in line:  # the user picked another speaker in Settings
                        try:
                            cur = _pactl("get-default-sink").strip()
                            if _real(cur) and not hear() and cancelling():
                                cancel_on(cur, explicit=True)
                        except Exception as e:
                            log.warning("device sound: %s", e)
                        continue
                    if " on sink #" not in line or ("'new'" not in line and "'remove'" not in line):
                        continue
                    added = None
                    if "'new'" in line:
                        time.sleep(1.0)  # let it settle (Bluetooth profiles switch twice)
                        real = [x for x in _names("sinks") if _real(x)]
                        added = real[-1] if real else None  # pactl lists sinks in creation order
                    try:
                        _follow(added)
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
