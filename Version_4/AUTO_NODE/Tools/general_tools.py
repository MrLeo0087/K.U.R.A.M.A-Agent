from langchain.tools import tool
from typing import Optional
import platform,requests,json,psutil,os
import time,socket
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

@tool
def get_current_time() -> str:
    """Return the current time and date formatted as a string"""
    return datetime.now().strftime("%A, %B,%d, %Y, %H:%M:%S")


@tool
def get_weather(city: str = "Nepalgunj")-> str:
    """
    Fetches weather for a city. Input MUST be a string (e.g., 'London').
    If no city is known, use 'Nepalgunj'.
    """
    api_key = os.getenv('WEATHER_API')
    base_url = 'http://api.openweathermap.org/data/2.5/weather'

    if not city or str(city).strip() == "":
        city = "Nepalganj"
    
    city = city.strip()
    if "nepalg" in city.lower():
        params = {
            'lat': 28.05,
            'lon': 81.62,
            'appid': api_key,
            'units': 'metric'
        }
    else:
        params = {
            'q': f"{city}",
            'appid': api_key,
            'units': 'metric'
        }

    try:
        response = requests.get(base_url, params=params)
        data = response.json()

        if data.get('cod') == '404' and "lat" not in params:
            params['q'] = f"{city},NP"
            response = requests.get(base_url, params=params)
            data = response.json()

        if data.get('cod') != 200:
            return f"Error: {data.get('message', 'City not found')}"
        
        name = data['name']
        temp = data['main']['temp']
        desc = data['weather'][0]['description']
        humidity = data['main']['humidity']

        return f"Current weather in {name}: {temp}°C with {desc}. Humidity: {humidity}%."
    
    except Exception as e:
        return f"Request failed: {str(e)}"
    
from langchain.tools import tool
import pyautogui
from typing import Optional
import screen_brightness_control as sbc

@tool
def basic_control(command: str, value: Optional[int] = 5):
    """
    Controls system hardware like volume, brightness, and screen mode.
    
    Parameters:
    - command: The action to perform ('mute', 'volumeup', 'volumedown', 'fullscreen', 'brightnessincrease', 'brightnessdecrease','play','pause')
    - value: The percentage to increase/decrease (default is 5).
    """
    
    # Clean the command to prevent matching errors
    cmd = command.lower().strip()

    # --- VOLUME CONTROLS ---
    if cmd == 'play' or cmd == 'pause':
        """Pauses or Resumes video/audio playback."""
        pyautogui.press('playpause')
        return "Play/Pause toggled."

    if cmd == 'mute':
        pyautogui.press('volumemute')
        return "System muted/unmuted successfully."

    if cmd == 'volumeup':
        # Press the volume up key 'value' times (approximate percentage)
        for _ in range(max(1, value // 2)): 
            pyautogui.press('volumeup')
        return f"Volume increased by approx {value}%."

    if cmd == 'volumedown':
        for _ in range(max(1, value // 2)):
            pyautogui.press('volumedown')
        return f"Volume decreased by approx {value}%."

    # --- DISPLAY CONTROLS ---
    if cmd == 'fullscreen':
        pyautogui.press('f11')
        return "Toggled full screen mode."

    if cmd == 'brightnessincrease':
        current = sbc.get_brightness()[0]
        new_brightness = min(100, current + value)
        sbc.set_brightness(new_brightness)
        return f"Brightness increased to {new_brightness}%."

    if cmd == 'brightnessdecrease':
        current = sbc.get_brightness()[0]
        new_brightness = max(0, current - value)
        sbc.set_brightness(new_brightness)
        return f"Brightness decreased to {new_brightness}%."

    return f"Command '{command}' not recognized."


from langchain.tools import tool
from typing import Optional
import platform

import psutil
from datetime import datetime


@tool
def get_system_info(need: Optional[str] = "all"):
    """
    Returns system information based on what you need.
    
    Parameters:
    - need: What information to return. Options: 'cpu', 'ram', 'os','disk','battery' 'all' (default: 'all')
    
    Examples:
    - "What's my RAM?" → need='ram'
    - "Check CPU usage" → need='cpu'
    - "What OS am I on?" → need='os'
    -"what is my Local Disk C condition?" → need='disk'
    -'what bettery remain?' → need='battery' 
    - "System stats" → need='all'
    """
    need = need.lower() if need else "all"

    if need == 'cpu':
        cpu = psutil.cpu_percent(interval=1)
        return f"CPU Usage: {cpu}%"
  
    elif need == 'ram':
        ram = psutil.virtual_memory().percent
        ram_used = psutil.virtual_memory().used / (1024**3)
        ram_total = psutil.virtual_memory().total / (1024**3)
        return f"RAM Usage: {ram}% ({ram_used:.2f} GB / {ram_total:.2f} GB used)"
    
    # Get OS info
    elif need == 'os':
            os_name = platform.system()
            os_version = platform.release()
            return f"Operating System: {os_name} {os_version}"
        
    elif need == 'disk':
            try:
                # Get C: drive info
                disk_c = psutil.disk_usage('C:/')
                disk_c_total = disk_c.total / (1024**3)
                disk_c_used = disk_c.used / (1024**3)
                disk_c_free = disk_c.free / (1024**3)
                disk_c_percent = disk_c.percent
                
                result = f"""Disk C: Usage
        - Used: {disk_c_used:.2f} GB
        - Free: {disk_c_free:.2f} GB
        - Total: {disk_c_total:.2f} GB
        - Usage: {disk_c_percent}%"""
                
                # Try to get D: drive (might not exist)
                try:
                    disk_d = psutil.disk_usage('D:/')
                    disk_d_total = disk_d.total / (1024**3)
                    disk_d_used = disk_d.used / (1024**3)
                    disk_d_free = disk_d.free / (1024**3)
                    disk_d_percent = disk_d.percent
                    
                    result += f"""

        Disk D: Usage
        - Used: {disk_d_used:.2f} GB
        - Free: {disk_d_free:.2f} GB
        - Total: {disk_d_total:.2f} GB
        - Usage: {disk_d_percent}%"""
                except:
                    # D: drive doesn't exist
                    pass
                
                return result
            
            except Exception as e:
                return f"Error getting disk info: {e}"
            
    elif need == 'battery':
        battery = psutil.sensors_battery()

        if battery:
            return f"Battery : {battery.percent}% \nPlugged In: {battery.power_plugged}"


    else:     
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        os_name = platform.system()
        os_version = platform.release()
        
        return f"""System Information:
- CPU Usage: {cpu}%
- RAM Usage: {ram}%
- OS: {os_name} {os_version}"""


@tool()
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
    
@tool
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
    
@tool()
def media_forward():
    """Skips to the next track or forwards (depending on the app)."""
    pyautogui.press('nexttrack')
    return "Skipped forward / Next track."

@tool()
def media_backward():
    """Skips to the previous track or goes back."""
    pyautogui.press('prevtrack')
    return "Skipped backward / Previous track."

@tool()
def get_task_manager_info():
    """Lists top 5 processes by memory usage."""
    processes = []
    for proc in sorted(psutil.process_iter(['pid', 'name', 'memory_percent']), 
                       key=lambda x: x.info['memory_percent'], reverse=True)[:5]:
        processes.append(proc.info)
    return processes

@tool()
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
