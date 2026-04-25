# voice.py
import speech_recognition as sr
import edge_tts
import asyncio
import os
import pygame
import tempfile
import threading
import queue
import re
import time

# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

ENGLISH_VOICE   = "en-US-ChristopherNeural"
RATE            = "+30%"
VOLUME          = "+0%"
PITCH           = "-10Hz"
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
#  TTS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

pygame.mixer.init()
generate_queue = queue.Queue()
playback_queue = queue.Queue()


def generation_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def generate(text):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.close()
        communicate = edge_tts.Communicate(
            text, ENGLISH_VOICE,
            rate=RATE, volume=VOLUME, pitch=PITCH
        )
        await communicate.save(tmp.name)
        return tmp.name

    while True:
        text = generate_queue.get()
        if text is None:
            playback_queue.put(None)
            break
        if text.strip():
            try:
                path = loop.run_until_complete(generate(text))
                playback_queue.put(path)
            except Exception as e:
                print(f"[TTS ERROR] {e}")
        generate_queue.task_done()


def playback_worker():
    while True:
        path = playback_queue.get()
        if path is None:
            break
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(10)
            pygame.mixer.music.unload()
        finally:
            if os.path.exists(path):
                os.remove(path)
        playback_queue.task_done()


threading.Thread(target=generation_worker, daemon=True).start()
threading.Thread(target=playback_worker,   daemon=True).start()


def speak(text: str):
    """Speak full response — cleans markdown before speaking."""
    if not text or not text.strip():
        return

    # Clean markdown
    text = re.sub(r'\*+', '',   text)
    text = re.sub(r'#+\s', '',  text)
    text = re.sub(r'`+', '',    text)
    text = re.sub(r'\n+', '. ', text)
    text = text.strip()

    generate_queue.put(text)

    # Wait for playback to finish before returning
    generate_queue.join()
    playback_queue.join()


def pre_warm_tts():
    """Pre-warm edge-tts connection."""
    print("[KURAMA] Pre-warming voice engine...")
    async def _warm():
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.close()
        await edge_tts.Communicate(".", ENGLISH_VOICE).save(tmp.name)
        if os.path.exists(tmp.name):
            os.remove(tmp.name)
    asyncio.run(_warm())


# ══════════════════════════════════════════════════════════════════════════════
#  SPEECH TO TEXT
# ══════════════════════════════════════════════════════════════════════════════

recognizer              = sr.Recognizer()
recognizer.pause_threshold             = PAUSE_THRESHOLD
recognizer.dynamic_energy_threshold   = True
mic = sr.Microphone()


def listen_once(timeout=5, phrase_limit=10) -> str | None:
    """Listen for one phrase and return text."""
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
        self.awake      = False   # False = waiting for wake word

    def _is_wake_word(self, text: str) -> bool:
        return any(w in text for w in WAKE_WORDS)

    def _is_sleep_word(self, text: str) -> bool:
        return any(w in text for w in SLEEP_WORDS)

    def _loop(self):
        while self.running:

            if not self.awake:
                # ── Sleeping — wait for wake word ──────────────
                print("[KURAMA] Sleeping... say wake word to activate.")
                text = listen_once(timeout=None, phrase_limit=5)

                if text and self._is_wake_word(text):
                    print(f"[KURAMA] Wake word: '{text}'")
                    self.awake = True
                    speak("I'm here.")

            else:
                # ── Awake — listen for command ──────────────────
                print("[KURAMA] Listening for command...")
                text = listen_once(timeout=8, phrase_limit=15)

                if not text:
                    speak("I didn't catch that.")
                    self.awake = False
                    continue

                print(f"[USER]: {text}")

                # Check sleep words
                if self._is_sleep_word(text):
                    speak("Alright, going to sleep. Say my name when you need me.")
                    self.awake = False
                    continue

                # Process command
                if self.on_command:
                    self.on_command(text)

                # After command done, go back to sleep
                self.awake = False

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()
        print("[KURAMA] Voice system started.")

    def stop(self):
        self.running = False