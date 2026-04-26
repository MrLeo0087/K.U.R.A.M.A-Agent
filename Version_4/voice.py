import edge_tts
import asyncio
import sounddevice as sd
import numpy as np
from pydub import AudioSegment
import io

class KuramaSpeaker:
    def __init__(self):
        self.english_voice = "en-GB-RyanNeural"
        self.hindi_voice   = "hi-IN-MadhurNeural"
        # self.hindi_voice   = "hi-IN-SwaraNeural"
        
        # Speed: +0% normal, +20% faster, +50% much faster
        self.rate   = "+10%"
        
        # Pitch: +0Hz normal, +10Hz higher, -10Hz deeper
        self.pitch  = "+0Hz"

        self.volume = "+40"

    def detect_language(self, text):
        for char in text:
            if '\u0900' <= char <= '\u097F':
                return "hi"
        return "en"

    async def _speak_async(self, text, voice):
        communicate = edge_tts.Communicate(text, voice, rate=self.rate, pitch=self.pitch)

        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

        buffer.seek(0)
        audio = AudioSegment.from_mp3(buffer)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0

        if audio.channels == 2:
            samples = samples.reshape((-1, 2))

        sd.play(samples, samplerate=audio.frame_rate)
        sd.wait()

    async def speak(self, text):
        lang  = self.detect_language(text)
        voice = self.hindi_voice if lang == "hi" else self.english_voice
        # print(f"[{lang.upper()}] {text}")
        # asyncio.run(self._speak_async(text, voice))
        await self._speak_async(text, voice)

kurama = KuramaSpeaker()
def sync_speak(text):
        try:
            # Check if an event loop is already running
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # If running, we schedule it as a task and don't wait (Fire and forget)
                loop.create_task(kurama.speak(text))
        except RuntimeError:
            # If no loop is running, we start a fresh one for this task
            asyncio.run(kurama.speak(text))


