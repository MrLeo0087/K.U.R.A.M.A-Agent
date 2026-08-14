from typing import Literal, Optional
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from general_class import (
    AudioController,
    ClipboardAndScreenshotController,
    DisplayController,
    MediaController,
    SystemInfoController,
    SystemPowerController,
    TimeAndWeatherController,
    WebAndSearchController,
    WindowController,
    PowerController,
)

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
    """Controls Linux applications, window focus, positioning, and process termination."""
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
    task: Literal["play_pause", "next", "previous", "stop", "status"],
) -> str:
    """Controls media playback for YouTube and local media players."""
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
    task: Literal["lock", "sleep", "reboot", "shutdown", "battery"],
) -> str:
    """Controls power states, screen lock, and battery information."""
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
    task: Literal["ram", "storage", "cpu", "network", "overview"],
) -> str:
    """Monitors system resources (RAM, Disk, CPU) and Network connection details."""
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


@tool  # FIXED: Added missing @tool decorator
def manage_clipboard_and_screenshot(
    action: Literal["read_clipboard", "copy_clipboard", "take_screenshot"],
    text: str = "",
    mode: Literal["full", "area", "window"] = "full",
    delay: int = 0,
) -> str:
    """Reads or copies system clipboard text, or takes desktop screenshots."""
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
def get_time_weather_and_location(
    location: str = "", mode: str = "time"
) -> str:
    """Get time, weather, and coordinates for a location."""
    tw_controller = TimeAndWeatherController()
    mode = mode.lower().strip()
    if mode == "weather":
        return tw_controller.get_weather(place=location)
    elif mode == "location":
        return tw_controller.get_coordinates(location_name=location)
    else:
        return tw_controller.get_time(country_or_place=location)


class WebSearchArgs(BaseModel):
    action: str = Field(
        default="google_search",
        description=(
            "Action type: 'open_url', 'google_search', 'youtube_search',"
            " 'play_youtube', or 'wikipedia'"
        ),
    )
    query: str = Field(
        default="", description="The search string, URL, or video name"
    )


@tool(args_schema=WebSearchArgs)
def manage_web_and_search(
    action: str = "google_search", query: str = ""
) -> str:
    """Unified web navigator tool."""
    web_controller = WebAndSearchController()
    action = action.lower().strip() if action else "google_search"
    query = query.strip() if query else ""

    if not query:
        return "Error: Query or URL cannot be empty."

    if "beast" in query.lower() and "mr" not in query.lower():
        query = query.replace("my beast", "MrBeast").replace(
            "your beast", "MrBeast"
        )

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

@tool
def manage_power(
    action: Literal["shutdown", "restart", "sleep", "signout"],
) -> str:
    """Controls system power actions like shutdown, restart, sleep/suspend, or signout/logout.

    Args:
        action: 'shutdown' to turn off system, 'restart' to reboot, 'sleep' to suspend, or 'signout' to log out user session.
    """
    controller = PowerController()

    if action == "shutdown":
        return controller.shutdown()
    elif action == "restart":
        return controller.restart()
    elif action == "sleep":
        return controller.sleep()
    elif action == "signout":
        return controller.signout()

    return "Invalid action specified."

# --- TOOL REGISTRY & CHROMADB VECTORSTORE ---
ALL_TOOLS = {
    "manage_audio": manage_audio,
    "manage_brightness": manage_brightness,
    "manage_window": manage_window,
    "manage_media": manage_media,
    "manage_power": manage_power,
    "manage_system_info": manage_system_info,
    "manage_clipboard_and_screenshot": manage_clipboard_and_screenshot,
    "get_time_weather_and_location": get_time_weather_and_location,
    "manage_web_and_search": manage_web_and_search,
    "manage_power": manage_power,
}

# --- AGENT ---
class GeneralAgent:

    def __init__(self):
        self.tools_map = ALL_TOOLS  # FIXED: Explicitly set tools map
        self.llm = ChatGroq(model="qwen/qwen3.6-27b", temperature=0)

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        try:

            llm_with_tools = self.llm.bind_tools(ALL_TOOLS.values())
            response = llm_with_tools.invoke(user_prompt)

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
            print(f"-> Execution failed: {e}")


# if __name__ == "__main__":
    