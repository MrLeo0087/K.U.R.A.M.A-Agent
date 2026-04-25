import asyncio
import subprocess
import platform
import psutil
import time
import socket
import screen_brightness_control as sbc
from mcp.server.fastmcp import FastMCP
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from comtypes import CLSCTX_ALL, cast
import pyautogui

# Initialize FastMCP
mcp = FastMCP("SystemController")

# --- 1. DISPLAY & BRIGHTNESS ---
@mcp.tool()
def set_brightness(level: int):
    """Sets display brightness (0-100)."""
    sbc.set_brightness(level)
    return f"Brightness set to {level}%"

# --- 2. AUDIO CONTROL (Windows Focus) ---
@mcp.tool()
def volume_up(level: int):
    """increase laptop volume key presses (0-100)."""
    for _ in range(max(1, level // 2)): 
            pyautogui.press('volumeup')
    return f"Volume increased by approx {level}%."

@mcp.tool()
def volume_down(level: int):
    """decrease laptop volume key presses (0-100)."""
    for _ in range(max(1, level // 2)): 
            pyautogui.press('volumedown')
    return f"Volume decrease by approx {level}%."

@mcp.tool()
def set_mute(mute: bool):
    """Mute (True) or Unmute (False) audio."""
    pyautogui.press('volumemute')
    return "System muted/unmuted successfully."

# --- 3. WINDOW & APP MANAGEMENT ---
@mcp.tool()
def open_app(name: str):
    """
    This function open any app in local pc/laptop
    Args:
        name: string
        description: name of app
        Example: - open photoshop (name : photoshop)
        - can you open this pc (name : this pc)
    """
    try:
        pyautogui.press('win')
        time.sleep(0.5)
        pyautogui.write(name,interval=0.1)
        time.sleep(1)
        pyautogui.press('enter')

        return f"{name} Opened! "

    except Exception as e:
        return f"Error : {e}"
    
@mcp.tool()
@mcp.tool()
def close_app(name: str):
    """
    Closes a specific application if it is currently running.
    Example: name='notepad' or name='photoshop'
    """
    found = False
    name_lower = name.lower()
    
    # Iterate through all running processes
    for proc in psutil.process_iter(['name']):
        try:
            # Check if the app name is in the process name
            # We use 'in' so that 'photoshop' matches 'Photoshop.exe'
            if name_lower in proc.info['name'].lower():
                proc.kill()
                found = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Skip processes that closed on their own or are restricted
            continue

    if found:
        return f"Successfully closed {name}."
    else:
        return f"Could not find {name}. It is likely not open."

# @mcp.tool()
# def open_settings(page: str):
#     """Opens specific Windows settings (sound, display, battery)."""
#     settings_map = {
#         "sound": "ms-settings:apps-volume",
#         "display": "ms-settings:display",
#         "battery": "ms-settings:batterysaver"
#     }
#     path = settings_map.get(page.lower(), "ms-settings:home")
#     subprocess.run(f"start {path}", shell=True)
#     return f"Opening {page} settings"

# --- 4. SYSTEM MONITORING ---
@mcp.tool()
def get_system_usage():
    """Returns CPU, RAM, and Disk usage percentages."""
    usage = {
        "cpu": f"{psutil.cpu_percent()}%",
        "ram": f"{psutil.virtual_memory().percent}%",
        "disk": f"{psutil.disk_usage('/').percent}%"
    }
    return usage

# --- VIDEO & MUSIC CONTROLS ---

@mcp.tool()
def toggle_play_pause():
    """Pauses or Resumes video/audio playback."""
    pyautogui.press('playpause')
    return "Play/Pause toggled."

@mcp.tool()
def media_forward():
    """Skips to the next track or forwards (depending on the app)."""
    pyautogui.press('nexttrack')
    return "Skipped forward / Next track."

@mcp.tool()
def media_backward():
    """Skips to the previous track or goes back."""
    pyautogui.press('prevtrack')
    return "Skipped backward / Previous track."

@mcp.tool()
def seek_forward_seconds():
    """Simulates pressing the Right Arrow key (usually 5-10s forward in videos)."""
    pyautogui.press('right')
    return "Seeked forward."

@mcp.tool()
def seek_backward_seconds():
    """Simulates pressing the Left Arrow key (usually 5-10s backward in videos)."""
    pyautogui.press('left')
    return "Seeked backward."

@mcp.tool()
def get_task_manager_info():
    """Lists top 5 processes by memory usage."""
    processes = []
    for proc in sorted(psutil.process_iter(['pid', 'name', 'memory_percent']), 
                       key=lambda x: x.info['memory_percent'], reverse=True)[:5]:
        processes.append(proc.info)
    return processes

@mcp.tool()
def get_laptop_info():
    """Returns detailed hardware and OS information."""
    # Calculate Total RAM in GB
    total_ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    
    return {
        "device_name": socket.gethostname(),          # The name you see in 'About your PC'
        "os_platform": platform.system(),             # e.g., Windows
        "window_version": platform.release(),         # e.g., 10 or 11
        "version_build": platform.version(),          # Internal build number
        "total_ram": f"{total_ram_gb} GB",            # Total installed RAM
        "processor": platform.processor(),
        "architecture": platform.machine()
    }

if __name__ == "__main__":
    mcp.run()