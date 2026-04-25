# voice.py
import speech_recognition as sr
import edge_tts
import asyncio
import sounddevice as sd
import numpy as np
from pydub import AudioSegment
import threading
import re
import io

# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

ENGLISH_VOICE   = "en-GB-RyanNeural"
RATE            = "+20%"
VOLUME          = "+0%"
PITCH           = "+0Hz"
PAUSE_THRESHOLD = 1.0


WAKE_WORDS = [
    "wake up buddy",
    "kurama",
    "hello buddy",
    "hello kurama",
    "hey kurama",
    "ok kurama",
]

SLEEP_WORDS = [
    "go sleep",
    "go to sleep",
    "goodbye",
    "good bye",
    "system down",
    "shut down",
    "bye kurama",
]

# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════════════════════════════════════════════════════

_is_speaking      = False        # True while Kurama is speaking
_interrupt_flag   = False        # Set to True when user speaks
_interrupted_text = None         # Captured user speech during interrupt
_speak_lock       = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
#  INTERRUPT LISTENER — runs in background while speaking
# ══════════════════════════════════════════════════════════════════════════════

def _interrupt_listener():
    """
    Listens on mic while Kurama is speaking.
    If user says anything — stop playback immediately.
    """
    global _interrupt_flag, _interrupted_text

    r = sr.Recognizer()
    r.pause_threshold          = 0.5   # faster detection
    r.dynamic_energy_threshold = True
    r.energy_threshold         = 300   # adjust if too sensitive

    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.3)

        while _is_speaking:
            try:
                audio = r.listen(source, timeout=0.5, phrase_time_limit=8)
                text  = r.recognize_google(audio).lower().strip()

                if text:
                    print(f"\n[INTERRUPT] User said: '{text}'")
                    _interrupted_text = text
                    _interrupt_flag   = True
                    sd.stop()          # stop audio playback immediately
                    break

            except sr.WaitTimeoutError:
                continue               # no speech yet, keep listening
            except sr.UnknownValueError:
                continue               # couldn't understand, keep listening
            except Exception:
                break


# ══════════════════════════════════════════════════════════════════════════════
#  TTS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    text = re.sub(r'\*+',  '',  text)
    text = re.sub(r'#+\s', '',  text)
    text = re.sub(r'`+',   '',  text)
    text = re.sub(r'\n+',  ' ', text)
    return text.strip()


async def fetch_audio(text: str) -> io.BytesIO:
    communicate = edge_tts.Communicate(
        text, ENGLISH_VOICE,
        rate=RATE, volume=VOLUME, pitch=PITCH
    )
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.write(chunk["data"])
    buffer.seek(0)
    return buffer


def play_buffer(buffer: io.BytesIO):
    audio   = AudioSegment.from_mp3(buffer)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
    if audio.channels == 2:
        samples = samples.reshape((-1, 2))
    sd.play(samples, samplerate=audio.frame_rate)
    sd.wait()   # blocks until done OR sd.stop() is called


async def _speak_async(text: str):
    if not text.strip():
        return
    buffer = await fetch_audio(text)
    play_buffer(buffer)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC SPEAK — with barge-in support
# ══════════════════════════════════════════════════════════════════════════════

def speak(text: str) -> str | None:
    """
    Speak text. If user talks during playback:
      - stops immediately
      - returns the user's interrupted text
    Returns None if speech completed normally.
    """
    global _is_speaking, _interrupt_flag, _interrupted_text

    if not text or not text.strip():
        return None

    text = clean_text(text)

    with _speak_lock:
        # Reset flags
        _interrupt_flag   = False
        _interrupted_text = None
        _is_speaking      = True

        # Start interrupt listener in background
        listener_thread = threading.Thread(
            target=_interrupt_listener,
            daemon=True
        )
        listener_thread.start()

        # Speak
        asyncio.run(_speak_async(text))

        # Done speaking
        _is_speaking = False
        listener_thread.join(timeout=1)

        if _interrupt_flag:
            captured = _interrupted_text
            _interrupt_flag   = False
            _interrupted_text = None
            return captured   # return what user said

        return None           # completed normally


def pre_warm_tts():
    print("[KURAMA] Pre-warming voice engine...")
    asyncio.run(_speak_async("online"))
    print("[KURAMA] Voice engine ready.")


# ══════════════════════════════════════════════════════════════════════════════
#  SPEECH TO TEXT
# ══════════════════════════════════════════════════════════════════════════════

recognizer                          = sr.Recognizer()
recognizer.pause_threshold          = PAUSE_THRESHOLD
recognizer.dynamic_energy_threshold = True
mic = sr.Microphone()


def listen_once(timeout=5, phrase_limit=10) -> str | None:
    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_limit
            )
        return recognizer.recognize_google(audio).lower().strip()
    except sr.WaitTimeoutError:
        return None
    except sr.UnknownValueError:
        return None
    except Exception as e:
        print(f"[STT ERROR] {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  WAKE WORD LISTENER
# ══════════════════════════════════════════════════════════════════════════════

class KuramaListener:
    def __init__(self, on_command=None):
        self.on_command = on_command
        self.running    = False
        self.awake      = False

    def _is_wake_word(self, text: str) -> bool:
        return any(w in text for w in WAKE_WORDS)

    def _is_sleep_word(self, text: str) -> bool:
        return any(w in text for w in SLEEP_WORDS)

    def _loop(self):
        while self.running:

            if not self.awake:
                print("[KURAMA] Sleeping... say wake word to activate.")
                text = listen_once(timeout=None, phrase_limit=5)

                if text and self._is_wake_word(text):
                    print(f"[KURAMA] Wake word: '{text}'")
                    self.awake = True
                    speak("I'm here.")

            else:
                print("[KURAMA] Listening for command...")
                text = listen_once(timeout=8, phrase_limit=15)

                if not text:
                    speak("I didn't catch that.")
                    self.awake = False
                    continue

                print(f"[USER]: {text}")

                if self._is_sleep_word(text):
                    speak("Alright, going to sleep. Say my name when you need me.")
                    self.awake = False
                    continue

                if self.on_command:
                    self.on_command(text)

                self.awake = False

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()
        print("[KURAMA] Voice system started.")

    def stop(self):
        self.running = False