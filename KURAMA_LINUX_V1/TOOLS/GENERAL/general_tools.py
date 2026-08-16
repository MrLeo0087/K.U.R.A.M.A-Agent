from typing import Literal, Optional, Union
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from general_class import (
    AudioController,
    ClipboardAndScreenshotController,
    DisplayController,
    FileSystemManager,
    MediaController,
    SystemInfoController,
    SystemPowerController,
    TimeAndWeatherController,
    WebAndSearchController,
    WindowController,
)

load_dotenv()


# --- SCHEMAS ---
class FileSystemActionInput(BaseModel):
    action: str = Field(
        description="Action to perform: 'search' (find files), 'create' (make file or folder), or 'remove' (delete)."
    )
    target_path: str = Field(
        default=".",
        description="Target path or folder directory. Use '~' or '/home/user/' for home directory.",
    )
    pattern: Optional[str] = Field(
        default="",
        description="Filename pattern, keyword, or extension to match when searching (e.g. '*.py', 'report').",
    )
    is_directory: Union[bool, str] = Field(
        default=False,
        description="MUST be false for files. MUST be true ONLY when creating or removing a folder/directory.",
    )
    content: Optional[str] = Field(
        default="", description="Text content to write into the file if creating a file."
    )
    recursive: Union[bool, str] = Field(
        default=False, description="Set to true to force-delete non-empty directories."
    )


class WebSearchArgs(BaseModel):
    action: str = Field(
        default="google_search",
        description="Navigation action: 'google_search', 'open_url', 'youtube_search', 'play_youtube', or 'wikipedia'.",
    )
    query: str = Field(
        default="", description="Search query, web URL link, video title, or article topic."
    )


# --- TOOLS WITH ENHANCED DEEP RAG RETRIEVAL DOCSTRINGS ---


@tool
def manage_audio(
    task: Literal["set", "change", "mute", "status"], value: Optional[float] = 0
) -> str:
    """System Audio Controller: Manage output volume, mute sound, unmute, set volume level, turn up or turn down sound.

    Common Trigger Phrases:
    - "Set volume to 50%", "Increase sound level", "Turn up volume", "Turn down volume", "Lower audio"
    - "Mute speakers", "Unmute audio", "Silence system", "Check volume status", "How loud is audio"

    Tasks:
    - 'set': Set exact volume percentage (e.g., value=50)
    - 'change': Adjust volume relative (+10 or -10)
    - 'mute': Toggle mute / unmute state
    - 'status': Get current output volume level and mute status
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


@tool
def manage_brightness(
    task: Literal["set", "change", "status"], value: Optional[float] = 0
) -> str:
    """Screen Brightness Controller: Adjust monitor display brightness, dim screen, increase display light.

    Common Trigger Phrases:
    - "Screen too bright", "Dim the monitor", "Make screen brighter", "Increase display brightness"
    - "Set brightness to 80%", "Check brightness level", "Lower monitor light"

    Tasks:
    - 'set': Set specific brightness percentage (e.g., value=70)
    - 'change': Increase or decrease current brightness (+15 or -15)
    - 'status': Check current screen brightness percentage
    """
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
    """Linux Window & Process Manager: Open apps, launch software, focus desktop window, close application, snap windows, kill process.

    Common Trigger Phrases:
    - "Open terminal", "Launch Chrome browser", "Start VS Code", "Open calculator app"
    - "Focus Firefox window", "Bring app to front", "Switch to terminal window"
    - "Close browser window", "Exit app", "Force quit unresponsive program", "Kill process"
    - "Snap window left", "Split screen right"

    Tasks:
    - 'open': Launch application or executable
    - 'focus': Switch active window focus by title keyword
    - 'close': Gracefully close active app window
    - 'snap': Tile/snap window to left or right screen edge
    - 'kill': Force terminate process by name
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
    task: Literal["play_pause", "next", "previous", "stop", "status"],
) -> str:
    """Media Playback Controller: Control playing music, YouTube audio, Spotify, video playback, pause, resume, skip track.

    Common Trigger Phrases:
    - "Pause video", "Play song", "Pause music", "Resume playback", "Toggle play pause"
    - "Next track", "Skip song", "Play next video", "Previous song", "Go back track"
    - "Stop music playback", "Check what media is currently playing"

    Tasks:
    - 'play_pause': Toggle play or pause active media
    - 'next': Skip to next track or video
    - 'previous': Go back to previous song
    - 'stop': Stop media playback
    - 'status': Show currently playing track/video info
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
    task: Literal["lock", "sleep", "reboot", "shutdown", "battery"],
) -> str:
    """System Power & Battery Manager: Lock computer screen, suspend PC, reboot Linux, shutdown system, check battery charge percentage.

    Common Trigger Phrases:
    - "Lock screen", "Lock my PC", "Sleep computer", "Suspend session"
    - "Reboot system", "Restart Linux PC", "Shut down computer", "Turn off PC"
    - "Check battery status", "How much battery left", "Is laptop charging"

    Tasks:
    - 'lock': Lock desktop screen session
    - 'sleep': Suspend computer to sleep state
    - 'reboot': Restart Linux machine
    - 'shutdown': Power off system complete
    - 'battery': Return battery percentage, state, and charge status
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
    task: Literal["ram", "storage", "cpu", "network", "overview"],
) -> str:
    """Hardware Resource & System Info Monitor: Check memory usage RAM, disk space storage, CPU load, IP address, network details.

    Common Trigger Phrases:
    - "How much RAM is free", "Check memory usage", "Check free disk space", "How full is hard drive"
    - "Show CPU usage", "Is processor hot", "What is my local IP address", "Check wifi network connection"
    - "Show full system overview", "System specs diagnostics"

    Tasks:
    - 'ram': Get RAM total, used, and available space
    - 'storage': Get disk partition storage capacity
    - 'cpu': Get CPU percentage load and usage stats
    - 'network': Get IP address, local interface, and internet status
    - 'overview': Get complete hardware usage overview
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


@tool
def manage_clipboard_and_screenshot(
    action: Literal["read_clipboard", "copy_clipboard", "take_screenshot"],
    text: str = "",
    mode: Literal["full", "area", "window"] = "full",
    delay: int = 0,
) -> str:
    """Clipboard Utility & Screen Capture Tool: Copy text to clipboard, read copied text, take desktop screenshot picture.

    Common Trigger Phrases:
    - "What is in my clipboard", "Read copied text", "Paste clipboard text"
    - "Copy this string to clipboard", "Save text to clipboard"
    - "Take a screenshot", "Capture full screen", "Snip area picture", "Screenshot window"

    Actions:
    - 'read_clipboard': Read active text stored in clipboard buffer
    - 'copy_clipboard': Write text string directly into system clipboard
    - 'take_screenshot': Capture desktop image (mode='full', 'area', or 'window')
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
def get_time_weather_and_location(
    location: str = "", mode: str = "time"
) -> str:
    """Time, Date, Clock, Weather Forecast & Location Tool: Check current local time, date, time zone, weather forecast, or GPS coordinates.

    Common Trigger Phrases:
    - "Tell me time", "What time right now", "What is current time", "What is today's date", "Check clock in London"
    - "What is the weather today", "Is it raining outside", "Check weather in Tokyo", "Forecast tomorrow"
    - "Get location coordinates", "Find GPS lat long for Paris"

    Modes:
    - 'time': Returns current time, date, and timezone for location or local clock
    - 'weather': Returns temperature, forecast, and weather conditions
    - 'location': Returns geographic coordinates (latitude and longitude)
    """
    tw_controller = TimeAndWeatherController()
    mode = mode.lower().strip()
    if mode == "weather":
        return tw_controller.get_weather(place=location)
    elif mode == "location":
        return tw_controller.get_coordinates(location_name=location)
    else:
        return tw_controller.get_time(country_or_place=location)


@tool(args_schema=WebSearchArgs)
def manage_web_and_search(action: str = "google_search", query: str = "") -> str:
    """Web Browser Navigator & Search Engine: Search Google, open websites URLs, search YouTube videos, play video on YouTube, read Wikipedia.

    Common Trigger Phrases:
    - "Search Google for python tutorials", "Google search quantum computing"
    - "Open website https://github.com", "Go to url reddit.com"
    - "Search YouTube for lo-fi music", "Find video on youtube"
    - "Play MrBeast video on youtube", "Play song on YouTube"
    - "Look up Wikipedia summary for Albert Einstein"

    Actions:
    - 'google_search': Perform web search on Google
    - 'open_url': Open URL directly in web browser
    - 'youtube_search': Search YouTube for video results
    - 'play_youtube': Open and play top matching YouTube video directly
    - 'wikipedia': Search and extract article summary from Wikipedia
    """
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


@tool(args_schema=FileSystemActionInput)
def manage_files_folder(
    action: str,
    target_path: str = ".",
    pattern: Optional[str] = "",
    is_directory: Union[bool, str] = False,
    content: Optional[str] = "",
    recursive: Union[bool, str] = False,
) -> str:
    """File System Operations Manager: Find files, search directories, create files, write text file, create folder, make environment dir, remove files or delete folders.

    Common Trigger Phrases:
    - "Search for file script.py", "Find files matching *.txt", "Locate folder"
    - "Create python file", "Make new file main.py", "Create folder projects/test", "Make environment setup here"
    - "Delete file test.txt", "Remove folder build", "Delete directory recursively"

    Actions:
    - 'search': Locate matching files or folders by search pattern
    - 'create': Create a new file with optional text content, or make a new directory
    - 'remove': Safely delete file or directory
    """
    fs = FileSystemManager(target_path)
    action_type = action.lower().strip()

    is_dir_flag = str(is_directory).lower().strip() in ("true", "1", "yes")
    recursive_flag = str(recursive).lower().strip() in ("true", "1", "yes")

    file_extensions = (
        ".py",
        ".txt",
        ".json",
        ".md",
        ".sh",
        ".html",
        ".css",
        ".js",
        ".c",
        ".cpp",
    )
    if action_type in ("create", "remove") and any(
        target_path.endswith(ext) for ext in file_extensions
    ):
        is_dir_flag = False

    if action_type == "search":
        if not pattern:
            return "Error: Must supply a 'pattern' keyword to search."
        results = fs.search_items(pattern=pattern, root_dir=target_path)
        if not results:
            return f"No items matching '{pattern}' found in '{target_path}'."
        if "error" in results[0]:
            return results[0]["error"]

        lines = [f"Found {len(results)} matching items in '{target_path}':"]
        for item in results:
            lines.append(f" - [{item['type'].upper()}] {item['path']}")
        return "\n".join(lines)

    elif action_type == "create":
        return fs.create_item(
            target_path=target_path, is_directory=is_dir_flag, content=content or ""
        )

    elif action_type == "remove":
        return fs.remove_item(target_path=target_path, recursive=recursive_flag)

    else:
        return f"Error: Unknown action '{action}'. Valid actions are 'search', 'create', 'remove'."


# --- TOOL REGISTRY ---
GENERAL_TOOLS = {
    "manage_audio": manage_audio,
    "manage_brightness": manage_brightness,
    "manage_window": manage_window,
    "manage_media": manage_media,
    "manage_power": manage_power,
    "manage_system_info": manage_system_info,
    "manage_clipboard_and_screenshot": manage_clipboard_and_screenshot,
    "get_time_weather_and_location": get_time_weather_and_location,
    "manage_web_and_search": manage_web_and_search,
    "manage_files_folder": manage_files_folder,
}

GENERAL_TOOLS_LIST = list(GENERAL_TOOLS.values())


# --- AGENT ---
class GeneralAgent:

    def __init__(self):
        self.tools_map = GENERAL_TOOLS
        self.llm = ChatGroq(model="qwen/qwen3.6-27b", temperature=0)

    def process_command(self, user_prompt: str):
        print(f"\nUser: '{user_prompt}'")
        try:
            llm_with_tools = self.llm.bind_tools(GENERAL_TOOLS.values())
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