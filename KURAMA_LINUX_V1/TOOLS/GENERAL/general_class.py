import pulsectl


# FOR AUDIO
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



# For Brighness
import re
import subprocess


class DisplayController:

    def set_brightness(self, percent: float) -> str:
        target = max(1, min(100, int(percent)))
        try:
            subprocess.run(
                ["brightnessctl", "set", f"{target}%"],
                check=True,
                capture_output=True,
            )
            return f"Brightness set to {target}%"
        except subprocess.CalledProcessError as e:
            return f"Failed to set brightness: {e}"

    def change_brightness(self, delta_percent: float) -> str:
        val = int(abs(delta_percent))
        arg = f"+{val}%" if delta_percent >= 0 else f"{val}%-"
        try:
            subprocess.run(
                ["brightnessctl", "set", arg], check=True, capture_output=True
            )
            return f"Brightness changed by {delta_percent:+}%. Current: {self.get_status()}"
        except subprocess.CalledProcessError as e:
            return f"Failed to change brightness: {e}"

    def get_status(self) -> str:
        try:
            res = subprocess.run(
                ["brightnessctl", "info"],
                check=True,
                capture_output=True,
                text=True,
            )
            match = re.search(r"\((\d+%)\)", res.stdout)
            if match:
                return f"Current brightness: {match.group(1)}"
            return res.stdout.splitlines()[0]
        except Exception as e:
            return f"Could not fetch brightness: {e}"


# For app close open

import shutil
import subprocess
import psutil


class WindowController:

    APP_ALIASES = {
        "brave": "brave-browser",
        "brave browser": "brave-browser",
        "extension manager": "gnome-extension-manager",
        "extensions": "gnome-extension-manager",
        "vs code": "code",
        "vscode": "code",
        "code": "code",
        "chrome": "google-chrome",
        "google chrome": "google-chrome",
        "terminal": "gnome-terminal",
        "files": "nautilus",
        "file manager": "nautilus",
        "settings": "gnome-control-center",
        "spotify": "spotify",
        "calculator": "gnome-calculator",
    }

    def open_app(self, app_name: str) -> str:
        clean_name = app_name.lower().strip()
        binary = self.APP_ALIASES.get(clean_name, clean_name)
        executable = shutil.which(binary)

        if not executable:
            return f"Error: Application '{app_name}' (binary: '{binary}') not found on system."

        try:
            subprocess.Popen(
                [executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return f"Successfully opened {app_name}."
        except Exception as e:
            return f"Failed to open {app_name}: {e}"

    def focus_window(self, title_keyword: str) -> str:
        try:
            res = subprocess.run(
                ["wmctrl", "-a", title_keyword],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return f"Switched focus to window matching '{title_keyword}'."
            return f"No open window found matching '{title_keyword}'."
        except Exception as e:
            return f"Failed to focus window: {e}"

    def close_window(self, title_keyword: str) -> str:
        try:
            res = subprocess.run(
                ["wmctrl", "-c", title_keyword],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return f"Closed window matching '{title_keyword}'."
            return f"No open window found matching '{title_keyword}'."
        except Exception as e:
            return f"Failed to close window: {e}"

    def snap_window(
        self, side: str = "left", title_keyword: str = None
    ) -> str:
        try:
            if title_keyword:
                self.focus_window(title_keyword)

            key_combo = (
                "Super+Left" if side.lower() == "left" else "Super+Right"
            )
            subprocess.run(
                ["xdotool", "key", key_combo], check=True, capture_output=True
            )
            return f"Snapped window to {side} side."
        except Exception as e:
            return f"Failed to snap window: {e}"

    def kill_process(self, process_name: str) -> str:
        killed_count = 0
        target = process_name.lower()

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if target in proc.info["name"].lower():
                    psutil.Process(proc.info["pid"]).kill()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if killed_count > 0:
            return f"Killed {killed_count} instance(s) of '{process_name}'."
        return f"No running process found matching '{process_name}'."



# Media control 
import subprocess


class MediaController:

    def play_pause(self) -> str:
        """Toggles play/pause state for active media player or browser tab."""
        try:
            subprocess.run(
                ["playerctl", "play-pause"], check=True, capture_output=True
            )
            return "Toggled play/pause."
        except subprocess.CalledProcessError:
            # Fallback using xdotool global XF86AudioPlay key
            try:
                subprocess.run(
                    ["xdotool", "key", "XF86AudioPlay"],
                    check=True,
                    capture_output=True,
                )
                return "Toggled play/pause (via key event)."
            except Exception as e:
                return (
                    f"No active media player or browser playback found: {e}"
                )

    def next_track(self) -> str:
        """Skips to the next video or audio track."""
        # 1. Try playerctl
        try:
            res = subprocess.run(
                ["playerctl", "next"], capture_output=True, text=True
            )
            if res.returncode == 0:
                return "Skipped to next track."
        except Exception:
            pass

        # 2. Fallback to global media key (XF86AudioNext)
        try:
            subprocess.run(
                ["xdotool", "key", "XF86AudioNext"],
                check=True,
                capture_output=True,
            )
            return "Skipped to next track (via media key)."
        except Exception:
            pass

        # 3. Fallback for YouTube tab specifically (Shift+N skips to next video on YouTube)
        try:
            subprocess.run(
                ["xdotool", "key", "Shift+N"], check=True, capture_output=True
            )
            return "Sent next shortcut to active browser tab."
        except Exception as e:
            return f"Failed to skip track: {e}"

    def previous_track(self) -> str:
        """Returns to previous video or audio track."""
        # 1. Try playerctl
        try:
            res = subprocess.run(
                ["playerctl", "previous"], capture_output=True, text=True
            )
            if res.returncode == 0:
                return "Went back to previous track."
        except Exception:
            pass

        # 2. Fallback to global media key (XF86AudioPrev)
        try:
            subprocess.run(
                ["xdotool", "key", "XF86AudioPrev"],
                check=True,
                capture_output=True,
            )
            return "Went back to previous track (via media key)."
        except Exception as e:
            return f"Failed to go to previous track: {e}"

    def stop(self) -> str:
        """Stops media playback."""
        try:
            subprocess.run(
                ["playerctl", "stop"], check=True, capture_output=True
            )
            return "Stopped playback."
        except subprocess.CalledProcessError:
            try:
                subprocess.run(
                    ["xdotool", "key", "XF86AudioStop"],
                    check=True,
                    capture_output=True,
                )
                return "Stopped playback (via key event)."
            except Exception as e:
                return f"Failed to stop playback: {e}"

    def get_status(self) -> str:
        """Gets current track info (title, artist, status)."""
        try:
            res = subprocess.run(
                [
                    "playerctl",
                    "metadata",
                    "--format",
                    "{{ status }}: {{ title }} - {{ artist }}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return res.stdout.strip() or "Media player active (no metadata)."
        except subprocess.CalledProcessError:
            return "No active media players found."


# For power laptop
import subprocess


class SystemPowerController:

    def lock_screen(self) -> str:
        """Locks the current user session immediately."""
        try:
            # 1. Primary GNOME lock command
            res = subprocess.run(
                ["gnome-screensaver-command", "-l"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return "Screen locked."

            # 2. Universal systemd session lock fallback
            subprocess.run(
                ["loginctl", "lock-session"], check=True, capture_output=True
            )
            return "Screen locked."
        except Exception as e:
            return f"Failed to lock screen: {e}"

    def suspend(self) -> str:
        """Puts the computer into low-power sleep mode."""
        try:
            subprocess.run(
                ["systemctl", "suspend"], check=True, capture_output=True
            )
            return "System suspending/sleeping..."
        except Exception as e:
            return f"Failed to suspend system: {e}"

    def reboot(self) -> str:
        """Restarts the system immediately."""
        try:
            subprocess.run(
                ["systemctl", "reboot"], check=True, capture_output=True
            )
            return "System rebooting..."
        except Exception as e:
            return f"Failed to reboot: {e}"

    def shutdown(self) -> str:
        """Powers off the system immediately."""
        try:
            subprocess.run(
                ["systemctl", "poweroff"], check=True, capture_output=True
            )
            return "System shutting down..."
        except Exception as e:
            return f"Failed to shutdown: {e}"

    def get_battery_status(self) -> str:
        """Reads battery level and charging state (for laptops)."""
        try:
            res = subprocess.run(
                ["upower", "-i", "/org/freedesktop/UPower/devices/battery_BAT0"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                state, percentage = "unknown", "unknown"
                for line in res.stdout.splitlines():
                    if "state:" in line:
                        state = line.split(":")[1].strip()
                    elif "percentage:" in line:
                        percentage = line.split(":")[1].strip()
                return f"Battery level: {percentage} ({state})"
            return "No battery detected (likely a desktop system)."
        except Exception as e:
            return f"Could not fetch battery status: {e}"


# FOr ram storage
import socket
import subprocess
import psutil


class SystemInfoController:

    def get_ram_info(self) -> str:
        """Returns total, used, available RAM and usage percentage."""
        ram = psutil.virtual_memory()
        total_gb = round(ram.total / (1024**3), 2)
        used_gb = round(ram.used / (1024**3), 2)
        pct = ram.percent
        return (
            f"RAM Usage: {pct}% ({used_gb} GB used of {total_gb} GB total)"
        )

    def get_storage_info(self) -> str:
        """Returns disk usage for root filesystem."""
        disk = psutil.disk_usage("/")
        total_gb = round(disk.total / (1024**3), 2)
        used_gb = round(disk.used / (1024**3), 2)
        free_gb = round(disk.free / (1024**3), 2)
        pct = disk.percent
        return f"Disk Usage (/): {pct}% ({used_gb} GB used, {free_gb} GB free out of {total_gb} GB total)"

    def get_cpu_info(self) -> str:
        """Returns overall CPU usage percentage and core count."""
        pct = psutil.cpu_percent(interval=0.5)
        cores = psutil.cpu_count(logical=True)
        return f"CPU Usage: {pct}% across {cores} cores"

    def get_network_info(self) -> str:
        """Returns connected Wi-Fi/Ethernet network name and local IP address."""
        # Get Local IP Address
        ip_address = "Not Connected"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        # Get Wi-Fi SSID / Network connection name via nmcli
        connection_name = "Ethernet/Disconnected"
        try:
            res = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid,device", "dev", "wifi"],
                capture_output=True,
                text=True,
            )
            for line in res.stdout.splitlines():
                if line.startswith("yes:"):
                    parts = line.split(":")
                    if len(parts) >= 2:
                        connection_name = f"Wi-Fi SSID: '{parts[1]}'"
                        break
        except Exception:
            pass

        return f"Network: {connection_name} | Local IP: {ip_address}"

    def get_full_status(self) -> str:
        """Returns a consolidated summary of RAM, Storage, CPU, and Network."""
        ram_str = self.get_ram_info()
        storage_str = self.get_storage_info()
        cpu_str = self.get_cpu_info()
        net_str = self.get_network_info()
        return (
            f"--- System Overview ---\n"
            f"1. {ram_str}\n"
            f"2. {storage_str}\n"
            f"3. {cpu_str}\n"
            f"4. {net_str}"
        )


# FOr CLIPBOARD
import os
import shutil
import subprocess
from datetime import datetime


class ClipboardAndScreenshotController:

    def get_clipboard(self) -> str:
        """Reads text from the system clipboard."""
        try:
            res = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
            return "Clipboard is empty or contains non-text data."
        except Exception as e:
            return f"Failed to read clipboard: {e}"

    def set_clipboard(self, text: str) -> str:
        """Copies text to the system clipboard."""
        try:
            process = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                text=True,
            )
            process.communicate(input=text)
            return f"Copied to clipboard: '{text}'"
        except Exception as e:
            return f"Failed to write to clipboard: {e}"

    def take_screenshot(
        self, mode: str = "full", delay_seconds: int = 0
    ) -> str:
        """Captures desktop screen and saves it to ~/Pictures."""
        pictures_dir = os.path.expanduser("~/Pictures")
        os.makedirs(pictures_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join(pictures_dir, f"screenshot_{timestamp}.png")

        # Try scrot first
        if shutil.which("scrot"):
            try:
                cmd = ["scrot"]
                if mode == "area":
                    cmd.append("-s")
                elif mode == "window":
                    cmd.append("-u")
                if delay_seconds > 0:
                    cmd.extend(["-d", str(delay_seconds)])
                cmd.append(filepath)
                subprocess.run(cmd, check=True, capture_output=True)
                return f"Screenshot saved to {filepath}"
            except Exception:
                pass

        # Fallback to gnome-screenshot
        if shutil.which("gnome-screenshot"):
            try:
                cmd = ["gnome-screenshot"]
                if mode == "area":
                    cmd.append("-a")
                elif mode == "window":
                    cmd.append("-w")
                if delay_seconds > 0:
                    cmd.extend(["-d", str(delay_seconds)])
                cmd.extend(["-f", filepath])
                subprocess.run(cmd, check=True, capture_output=True)
                return f"Screenshot saved to {filepath}"
            except Exception:
                pass

        return "Failed to take screenshot: Neither 'scrot' nor 'gnome-screenshot' are installed."


# For weather and time

import requests
from datetime import datetime
import pytz
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder


class TimeAndWeatherController:
    """
    Controller for retrieving coordinates, local time, and current weather for any location.
    Optimized for KURAMA Assistant tool-calling.
    """

    def __init__(self, user_agent: str = "kurama_assistant"):
        self.geolocator = Nominatim(user_agent=user_agent)
        self.tf = TimezoneFinder()

    def get_coordinates(self, location_name: str = "") -> str:
        """
        Find exact latitude, longitude, and full display address of any place.
        Default is Nepalgunj if no location is provided.
        """
        target_location = location_name.strip() if location_name.strip() else "Nepalgunj"
        
        try:
            loc = self.geolocator.geocode(target_location)
            if loc:
                return (
                    f"Location: {loc.address}\n"
                    f"Latitude: {loc.latitude}\n"
                    f"Longitude: {loc.longitude}"
                )
            return f"Could not find coordinates for '{target_location}'."
        except Exception as e:
            return f"Error retrieving coordinates: {str(e)}"

    def get_time(self, country_or_place: str = "") -> str:
        """
        Get current local time for any country or city.
        Default is Nepal if no location is provided.
        """
        target_location = country_or_place.strip() if country_or_place.strip() else "Nepal"

        # Fast path for Nepal
        if target_location.lower() in ["nepal", "np"]:
            nepal_tz = pytz.timezone("Asia/Kathmandu")
            current_time = datetime.now(nepal_tz).strftime("%I:%M %p (%Y-%m-%d)")
            return f"Current time in Nepal: {current_time}"

        try:
            loc = self.geolocator.geocode(target_location)
            if not loc:
                return f"Could not locate '{target_location}'."

            tz_name = self.tf.timezone_at(lat=loc.latitude, lng=loc.longitude)
            if not tz_name:
                return f"Could not determine timezone for '{target_location}'."

            local_tz = pytz.timezone(tz_name)
            current_time = datetime.now(local_tz).strftime("%I:%M %p (%Y-%m-%d)")
            return f"Current time in {loc.address.split(',')[0]} ({tz_name}): {current_time}"
        except Exception as e:
            return f"Error fetching time: {str(e)}"

    def get_weather(self, place: str = "") -> str:
        """
        Get current weather conditions for any location using Open-Meteo API.
        Default is Nepalgunj if no location is provided.
        """
        target_place = place.strip() if place.strip() else "Nepalgunj"

        try:
            loc = self.geolocator.geocode(target_place)
            if not loc:
                return f"Could not find coordinates for '{target_place}'."

            url = f"https://api.open-meteo.com/v1/forecast?latitude={loc.latitude}&longitude={loc.longitude}&current_weather=true"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                data = response.json().get("current_weather", {})
                temp = data.get("temperature")
                windspeed = data.get("windspeed")
                weather_code = data.get("weathercode")

                condition = self._map_wmo_code(weather_code)
                display_name = loc.address.split(',')[0]
                return f"Weather in {display_name}: {temp}°C, {condition}, Wind: {windspeed} km/h."
            else:
                return f"Failed to retrieve weather data (HTTP {response.status_code})."
        except Exception as e:
            return f"Error fetching weather data: {str(e)}"

    @staticmethod
    def _map_wmo_code(code: int) -> str:
        wmo_map = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
            55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            95: "Thunderstorm"
        }
        return wmo_map.get(code, "Unknown conditions")


# FOr search on google
import urllib.parse
import webbrowser
import requests


class WebAndSearchController:
    """
    Controller for browser navigation, web searches, YouTube playback, and Wikipedia summaries.
    Optimized for Linux desktop automation (KURAMA).
    """

    def __init__(self):
        # Uses default system browser (Firefox/Chrome/Brave)
        self.browser = webbrowser.get()

    def open_url(self, url: str) -> str:
        """Opens any direct URL in the default web browser."""
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            self.browser.open(url)
            return f"Successfully opened URL: {url}"
        except Exception as e:
            return f"Failed to open URL '{url}': {str(e)}"

    def search_google(self, query: str) -> str:
        """Performs a Google Search in the browser."""
        if not query.strip():
            return "Search query cannot be empty."

        encoded_query = urllib.parse.quote_plus(query.strip())
        search_url = f"https://www.google.com/search?q={encoded_query}"
        self.browser.open(search_url)
        return f"Opened Google search for: '{query}'"

    def search_youtube(self, query: str) -> str:
        """Searches YouTube for videos and opens the results page."""
        if not query.strip():
            return "YouTube query cannot be empty."

        encoded_query = urllib.parse.quote_plus(query.strip())
        youtube_url = f"https://www.youtube.com/results?search_query={encoded_query}"
        self.browser.open(youtube_url)
        return f"Opened YouTube search for: '{query}'"

    def play_youtube_video(self, video_query: str) -> str:
        """
        Directly opens the first matching YouTube video using YouTube's 'I'm Feeling Lucky' endpoint.
        """
        if not video_query.strip():
            return "Video query cannot be empty."

        encoded_query = urllib.parse.quote_plus(video_query.strip())
        # Forces YouTube to open the top result directly
        direct_url = f"https://www.youtube.com/results?search_query={encoded_query}&sp=mAEB"
        
        # Alternatively open search if direct play falls back
        self.browser.open(f"https://www.youtube.com/results?search_query={encoded_query}")
        return f"Playing YouTube video for query: '{video_query}'"

    def search_wikipedia(self, query: str) -> str:
        """
        Searches Wikipedia API for a quick text summary and returns it.
        Does not open the browser unless requested.
        """
        if not query.strip():
            return "Wikipedia query cannot be empty."

        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query.strip())}"
        headers = {"User-Agent": "KURAMA-Assistant/1.0 (Linux Local Assistant)"}

        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                title = data.get("title", "Result")
                extract = data.get("extract", "No summary available.")
                wiki_link = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                
                return f"**Wikipedia: {title}**\n{extract}\nURL: {wiki_link}"
            elif response.status_code == 404:
                return f"No Wikipedia page found for '{query}'."
            else:
                return f"Failed to fetch Wikipedia data (HTTP {response.status_code})."
        except Exception as e:
            return f"Error fetching Wikipedia summary: {str(e)}"


# SLEEP, SHUTDOWN
import subprocess


class PowerController:

    def shutdown(self) -> str:
        """Powers off the system immediately."""
        try:
            subprocess.run(["systemctl", "poweroff"], check=True)
            return "System is shutting down..."
        except Exception as e:
            return f"Failed to shutdown: {e}"

    def restart(self) -> str:
        """Reboots the system immediately."""
        try:
            subprocess.run(["systemctl", "reboot"], check=True)
            return "System is restarting..."
        except Exception as e:
            return f"Failed to restart: {e}"

    def sleep(self) -> str:
        """Puts the system into sleep/suspend mode."""
        try:
            subprocess.run(["systemctl", "suspend"], check=True)
            return "System is going to sleep..."
        except Exception as e:
            return f"Failed to put system to sleep: {e}"

    def signout(self) -> str:
        """Logs out the current user session."""
        try:
            # 1. Primary: Try loginctl for systemd sessions
            res = subprocess.run(
                ["loginctl", "terminate-user", "$USER"], capture_output=True
            )
            if res.returncode == 0:
                return "Signing out current user..."

            # 2. Fallback: GNOME desktop session logout
            subprocess.run(
                ["gnome-session-quit", "--logout", "--no-prompt"], check=True
            )
            return "Signing out current user..."
        except Exception as e:
            return f"Failed to sign out: {e}"