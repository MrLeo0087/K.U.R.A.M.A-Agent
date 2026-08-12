from typing import Literal, Optional
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_groq import ChatGroq

from general_class import AudioController, DisplayController, WindowController, MediaController, SystemPowerController, SystemInfoController, ClipboardAndScreenshotController, TimeAndWeatherController, WebAndSearchController
load_dotenv()


# --- TOOLS ---
@tool
def manage_audio(
    task: Literal["set", "change", "mute", "status"], value: Optional[float] = 0
) -> str:
    """Controls Linux system audio output."""
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


@tool
def manage_brightness(
    task: Literal["set", "change", "status"], value: Optional[float] = 0
) -> str:
    """Controls Linux system screen brightness level."""
    display = DisplayController()
    if task == "set":
        return display.set_brightness(value)
    elif task == "change":
        return display.change_brightness(value)
    elif task == "status":
        return display.get_status()
    return "Invalid task specified."


@tool
def manage_window(
    task: Literal["open", "focus", "close", "snap", "kill"],
    target: str,
    side: Optional[Literal["left", "right"]] = "left",
) -> str:
    """Controls Linux applications, window focus, positioning, and process termination.

    Args:
        task: Action type.
              - "open": Launches an app (e.g., target="code", target="google-chrome", target="gnome-extension-manager").
              - "focus": Brings an open window matching keyword to foreground (e.g., target="Code" or target="Chrome").
              - "close": Gently requests an open window matching keyword to close.
              - "snap": Snaps active window to half-screen (e.g., target="Code", side="left").
              - "kill": Forcefully terminates process by name (e.g., target="chrome").
        target: Name of application or window title keyword.
        side: Direction for snapping ('left' or 'right').
    """
    controller = WindowController()
    if task == "open":
        return controller.open_app(target)
    elif task == "focus":
        return controller.focus_window(target)
    elif task == "close":
        return controller.close_window(target)
    elif task == "snap":
        return controller.snap_window(side=side, title_keyword=target)
    elif task == "kill":
        return controller.kill_process(target)
    return "Invalid task specified."


@tool
def manage_media(
    task: Literal["play_pause", "next", "previous", "stop", "status"]
) -> str:
    """Controls media playback for YouTube (browsers like Brave/Chrome/Firefox) and media apps (Spotify/VLC).

    Args:
        task: Action type.
              - "play_pause": Toggles play/pause on YouTube or active media app.
              - "next": Skips to next track/video.
              - "previous": Goes back to previous track/video.
              - "stop": Stops media playback.
              - "status": Returns current playing track title and artist.
    """
    controller = MediaController()

    if task == "play_pause":
        return controller.play_pause()
    elif task == "next":
        return controller.next_track()
    elif task == "previous":
        return controller.previous_track()
    elif task == "stop":
        return controller.stop()
    elif task == "status":
        return controller.get_status()
    return "Invalid media task specified."

@tool
def manage_power(
    task: Literal["lock", "sleep", "reboot", "shutdown", "battery"]
) -> str:
    """Controls Ubuntu power states, screen lock, and battery information.

    Args:
        task: Action type.
              - "lock": Locks screen/session immediately.
              - "sleep": Suspends system to low-power state.
              - "reboot": Restarts computer.
              - "shutdown": Powers off system completely.
              - "battery": Checks laptop battery percentage and charging state.
    """
    controller = SystemPowerController()

    if task == "lock":
        return controller.lock_screen()
    elif task == "sleep":
        return controller.suspend()
    elif task == "reboot":
        return controller.reboot()
    elif task == "shutdown":
        return controller.shutdown()
    elif task == "battery":
        return controller.get_battery_status()
    return "Invalid power management task specified."

@tool
def manage_system_info(
    task: Literal["ram", "storage", "cpu", "network", "overview"]
) -> str:
    """Monitors system resources (RAM, Disk Storage, CPU) and Network connection details.

    Args:
        task: Action type.
              - "ram": Returns RAM consumption and available memory.
              - "storage": Returns disk usage and free space on system drive.
              - "cpu": Returns current CPU load and core count.
              - "network": Returns current Wi-Fi SSID connection and local IP address.
              - "overview": Returns a combined summary of RAM, Storage, CPU, and Network.
    """
    controller = SystemInfoController()

    if task == "ram":
        return controller.get_ram_info()
    elif task == "storage":
        return controller.get_storage_info()
    elif task == "cpu":
        return controller.get_cpu_info()
    elif task == "network":
        return controller.get_network_info()
    elif task == "overview":
        return controller.get_full_status()
    return "Invalid system info task specified."


def manage_clipboard_and_screenshot(
    action: Literal["read_clipboard", "copy_clipboard", "take_screenshot"],
    text: str = "",
    mode: Literal["full", "area", "window"] = "full",
    delay: int = 0,
) -> str:
    """Reads or copies system clipboard text, or takes desktop screenshots.

    Args:
        action: 'read_clipboard' to read clipboard, 'copy_clipboard' to copy
          text, or 'take_screenshot' to capture screen.
        text: Text to copy (when action='copy_clipboard').
        mode: Screenshot mode ('full', 'area', or 'window').
        delay: Delay in seconds before taking screenshot.
    """
    controller = ClipboardAndScreenshotController()

    if action == "read_clipboard":
        return controller.get_clipboard()

    elif action == "copy_clipboard":
        if not text:
            return "Error: Provide text to copy."
        return controller.set_clipboard(text)

    elif action == "take_screenshot":
        return controller.take_screenshot(mode=mode, delay_seconds=delay)

    return "Invalid action specified."


@tool
def get_time_weather_and_location(location: str = "", mode: str = "time") -> str:
    """
    Get the time weather and coordinates for a target location.
    - mode: 'time' or 'weather' or 'location'
    - location: Target city/country. Defaults: Nepal for time , Nepalgunj for weather and location.
    """
    tw_controller = TimeAndWeatherController()
    mode = mode.lower().strip()
    if mode == "weather":
        return tw_controller.get_weather(place=location)

    elif mode == 'location':
        return tw_controller.get_coordinates(location_name=location)
    else:
        return tw_controller.get_time(country_or_place=location)

from pydantic import BaseModel, Field

class WebSearchArgs(BaseModel):
    action: str = Field(
        default="google_search",
        description="Action type: 'open_url', 'google_search', 'youtube_search', 'play_youtube', or 'wikipedia'"
    )
    query: str = Field(
        default="",
        description="The search string, URL, or video name"
    )

@tool(args_schema=WebSearchArgs)
def manage_web_and_search(action: str = "google_search", query: str = "") -> str:
    """
    Unified web navigator tool. Performs web searches, opens websites, searches YouTube, plays videos, or fetches Wikipedia summaries.
    """
    web_controller = WebAndSearchController()
    action = action.lower().strip() if action else "google_search"
    query = query.strip() if query else ""

    if not query:
        return "Error: Query or URL cannot be empty."

    # Intercept potential pronoun confusion (e.g. "my beast" -> "mrbeast")
    if "beast" in query.lower() and "mr" not in query.lower():
        query = query.replace("my beast", "MrBeast").replace("your beast", "MrBeast")

    if action in ["open_url", "url", "website"]:
        return web_controller.open_url(query)
    elif action in ["youtube_search", "yt_search", "youtube"]:
        return web_controller.search_youtube(query)
    elif action in ["play_youtube", "play_video"]:
        return web_controller.play_youtube_video(query)
    elif action in ["wikipedia", "wiki"]:
        return web_controller.search_wikipedia(query)
    else:
        return web_controller.search_google(query)
# --- AGENT ---
class JarvisAgent:

    def __init__(self):
        self.tools_map = {
    "manage_audio": manage_audio,
    "manage_brightness": manage_brightness,
    "manage_window": manage_window,
    "manage_media": manage_media,
    "manage_power": manage_power,
    "manage_system_info": manage_system_info,
    "manage_clipboard_and_screenshot": manage_clipboard_and_screenshot,
    'get_time_weather_and_location':get_time_weather_and_location,
    'manage_web_and_search' : manage_web_and_search,
}

        self.llm = ChatGroq(
            model="qwen/qwen3.6-27b", temperature=0.0
        ).bind_tools(list(self.tools_map.values()))

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        try:
            response = self.llm.invoke(user_prompt)

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    args = tool_call["args"]

                    print(f"-> Executing [{tool_name}] with args: {args}")

                    if tool_name in self.tools_map:
                        result = self.tools_map[tool_name].invoke(args)
                        print(f"-> Result: {result}")
                        return result
                    else:
                        print(f"-> Error: Tool '{tool_name}' not registered.")
            else:
                print(f"LLM Response: {response.content}")
                return response.content
        except Exception as e:
            print(f"-> Tool execution failed: {e}")


from voice_control import VoiceController
# from jarvis_agent import JarvisAgent  # Import your existing agent

if __name__ == "__main__":
    agent = JarvisAgent()
    voice = VoiceController()

    print("==================================================")
    print("      KURAMA / JARVIS VOICE ASSISTANT ONLINE      ")
    print("==================================================")
    print("Modes: Type 'v' for voice input, or type command directly.")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            mode = input("Enter command (or press Enter for Voice Mode) : ").strip()

            if mode.lower() in ["exit", "quit"]:
                voice.speak("Shutting down system. Goodbye!")
                break

            # If user presses Enter or types 'v', trigger Microphone input
            if mode == "" or mode.lower() == "v":
                user_input = voice.listen()
                if not user_input:
                    print("-" * 50)
                    continue
            else:
                user_input = mode

            # Process command with LangChain / Groq Agent
            response = agent.process_command(user_input)
            print(response)

            # Speak out the response if available
            if response:
                voice.speak(str(response))

            print("-" * 50)

        except KeyboardInterrupt:
            print("\nExiting Jarvis...")
            break   