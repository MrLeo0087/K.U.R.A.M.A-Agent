from typing import Literal, Optional
from dotenv import load_dotenv
import pulsectl
from langchain_core.tools import tool
from langchain_groq import ChatGroq

# 1. Load environment variables (.env file with GROQ_API_KEY)
load_dotenv()


# 2. Base Audio Controller
class AudioController:

    def __enter__(self):
        self.pulse = pulsectl.Pulse("volume-controller-script")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.pulse.close()

    def _get_default_sink(self):
        server_info = self.pulse.server_info()
        default_sink_name = server_info.default_sink_name
        for sink in self.pulse.sink_list():
            if sink.name == default_sink_name:
                return sink
        return self.pulse.sink_list()[0]

    def set_volume(self, percent: float):
        sink = self._get_default_sink()
        target_volume = max(0.0, min(1.0, percent / 100.0))
        self.pulse.volume_set_all_chans(sink, target_volume)
        return f"Volume set to {int(target_volume * 100)}%"

    def change_volume(self, delta_percent: float):
        sink = self._get_default_sink()
        self.pulse.volume_change_all_chans(sink, delta_percent / 100.0)
        sink = self._get_default_sink()
        current = int(round(sink.volume.value_flat * 100))
        return f"Volume changed by {delta_percent}%. Current level: {current}%"

    def toggle_mute(self):
        sink = self._get_default_sink()
        new_state = not bool(sink.mute)
        self.pulse.mute(sink, new_state)
        return f"Audio is now {'Muted' if new_state else 'Unmuted'}"

    def get_status(self):
        sink = self._get_default_sink()
        vol_pct = int(round(sink.volume.value_flat * 100))
        return f"Current volume: {vol_pct}%, Muted: {bool(sink.mute)}"


# 3. Single Consolidated LangChain Tool
@tool
def manage_audio(
    task: Literal["set", "change", "mute", "status"], value: Optional[float] = 0
) -> str:
    """Controls Linux system audio output.

    Args:
        task: Action type.
              - "set": Sets absolute volume percentage (e.g. 50).
              - "change": Adjusts volume relatively. Positive values turn up (e.g. 10), negative values turn down (e.g. -15).
              - "mute": Toggles mute on or off.
              - "status": Returns current volume and mute state.
        value: Number for volume percentage or change step (required for 'set' and 'change').
    """
    with AudioController() as audio:
        if task == "set":
            return audio.set_volume(value)
        elif task == "change":
            return audio.change_volume(value)
        elif task == "mute":
            return audio.toggle_mute()
        elif task == "status":
            return audio.get_status()
        return "Invalid task specified."


# 4. Agent Execution Class
class SingleToolAudioAgent:

    def __init__(self):
        # Bind the SINGLE tool to Groq LLM
        self.llm = ChatGroq(
            model="llama-3.1-8b-instant", temperature=0.0
        ).bind_tools([manage_audio])

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        response = self.llm.invoke(user_prompt)

        if response.tool_calls:
            for tool_call in response.tool_calls:
                args = tool_call["args"]
                print(f"-> Executing 'manage_audio' with arguments: {args}")

                # Call the single function directly
                result = manage_audio.invoke(args)
                print(f"-> Result: {result}")
        else:
            print(f"LLM Response: {response.content}")


# 5. Testing
if __name__ == "__main__":
    agent = SingleToolAudioAgent()

    # The LLM passes different 'task' and 'value' arguments to the SAME function
    agent.process_command("Set volume to 90 percent")
    # agent.process_command("Turn it up by 10%")
    # agent.process_command("Lower the volume by 15 percent")
    agent.process_command("Mute the sound")
    # agent.process_command("Check audio status")