import asyncio
import contextlib
import os
import sys
import tempfile
import edge_tts
import speech_recognition as sr


@contextlib.contextmanager
def suppress_alsa_errors():
    """Suppresses low-level ALSA/PortAudio stderr log spam."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    sys.stderr.flush()
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)


class VoiceController:
    """Handles speech-to-text (Google STT) and text-to-speech using edge-tts + mpv."""

    def __init__(self, mic_index: int = None, offline_tts: bool = False):
        self.offline_tts = offline_tts
        self.recognizer = sr.Recognizer()

        # Voice Settings (Matching your working config)
        self.voice = "en-US-ChristopherNeural"
        self.rate = "+25%"
        self.pitch = "-5Hz"
        self.volume = "+0%"

        with suppress_alsa_errors():
            mics = sr.Microphone.list_microphone_names()

        print("\n--- Detected Audio Input Devices ---")
        for idx, name in enumerate(mics):
            if "default" in name.lower() or "pulse" in name.lower():
                print(f" -> [{idx}] {name} (Recommended)")
            else:
                print(f"    [{idx}] {name}")
        print("------------------------------------\n")

        with suppress_alsa_errors():
            self.microphone = sr.Microphone(device_index=mic_index)

    def listen(self) -> str:
        """Captures voice from microphone and converts to text."""
        with suppress_alsa_errors():
            with self.microphone as source:
                print("\n🎙️ Listening... Speak now!")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                self.recognizer.dynamic_energy_threshold = False
                self.recognizer.energy_threshold = 300

                try:
                    audio = self.recognizer.listen(
                        source, timeout=6, phrase_time_limit=8
                    )
                    print("⚡ Processing speech...")
                    text = self.recognizer.recognize_google(audio)
                    print(f" You said: '{text}'")
                    return text
                except sr.WaitTimeoutError:
                    print("⏳ Listening timed out (no speech detected).")
                    return ""
                except sr.UnknownValueError:
                    print(" Could not understand audio.")
                    return ""
                except sr.RequestError as e:
                    print(f" Speech service error: {e}")
                    return ""

    async def _speak_async(self, text: str):
        """Generates audio with edge_tts and plays it via mpv."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fp:
            temp_file = fp.name

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch,
                volume=self.volume,
            )
            await communicate.save(temp_file)

            # Play using the exact system call that works on your system
            os.system(f"mpv --really-quiet '{temp_file}'")
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def speak(self, text: str):
        """Synchronous speech call for your main loop."""
        if not text.strip():
            return

        # Strip markdown symbols so TTS reads clean words
        clean_text = (
            text.replace("*", "").replace("#", "").replace("`", "").strip()
        )
        print(f"🔊 Assistant: {clean_text}")

        # Run the async speak generator safely
        try:
            asyncio.run(self._speak_async(clean_text))
        except Exception as e:
            print(f"[Speech Error]: {e}")

# tet = VoiceController()
# tet.speak('Hello')