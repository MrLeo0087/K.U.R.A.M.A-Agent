# NODE/auto/tools/browser_tools.py
import webbrowser
import subprocess
import sys
from langchain_core.tools import tool

@tool
def open_url(url: str) -> str:
    """Open any website URL in the default browser.
    
    Use this when user gives a direct URL or website address.
    Automatically adds https:// if missing.
    
    Examples:
        - "open google.com"         → open_url("google.com")
        - "open https://github.com" → open_url("https://github.com")
        - "go to reddit"            → open_url("reddit.com")
    """
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    webbrowser.open(url)
    return f"Opened {url} in browser."


@tool
def open_google_search(query: str) -> str:
    """Search any topic on Google and open results in browser.
    
    Use when user wants to search something on Google specifically,
    or says 'look up X', 'search X online', 'google X'.
    
    Examples:
        - "search python tutorials on google" → open_google_search("python tutorials")
        - "look up elon musk online"          → open_google_search("elon musk")
        - "google best laptops 2025"          → open_google_search("best laptops 2025")
    """
    query_encoded = query.strip().replace(' ', '+')
    url = f"https://www.google.com/search?q={query_encoded}"
    webbrowser.open(url)
    return f"Searched Google for: '{query}'"


@tool
def open_youtube_search(query: str) -> str:
    """Search any topic on YouTube and open results in browser.
    
    Use when user wants to search or watch something on YouTube.
    Covers music, tutorials, videos, channels.
    
    Examples:
        - "search nepali songs on youtube"    → open_youtube_search("nepali songs")
        - "open youtube and play lofi music"  → open_youtube_search("lofi music")
        - "find python tutorial on youtube"   → open_youtube_search("python tutorial")
    """
    query_encoded = query.strip().replace(' ', '+')
    url = f"https://www.youtube.com/search?q={query_encoded}"
    webbrowser.open(url)
    return f"Searched YouTube for: '{query}'"


@tool
def open_youtube_video(url: str) -> str:
    """Open a specific YouTube video directly by its URL.
    
    Use when user provides an exact YouTube video link.
    Different from search — this opens ONE specific video.
    
    Examples:
        - "open this video: youtube.com/watch?v=abc123" → open_youtube_video("youtube.com/watch?v=abc123")
        - "play https://youtu.be/xyz789"                → open_youtube_video("https://youtu.be/xyz789")
    """
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    webbrowser.open(url)
    return f"Opened YouTube video: {url}"


@tool
def open_app(app_name: str) -> str:
    """Open any desktop application installed on the computer.
    
    Works on Windows, Mac, and Linux.
    Use for apps like notepad, vlc, spotify, calculator, settings, etc.
    
    Examples:
        - "open notepad"      → open_app("notepad")
        - "launch spotify"    → open_app("spotify")
        - "open calculator"   → open_app("calc")
        - "start file explorer" → open_app("explorer")
        - "open settings"     → open_app("ms-settings:")
    """
    try:
        if sys.platform == 'win32':
            subprocess.Popen(['start', app_name], shell=True)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-a', app_name])
        else:
            subprocess.Popen([app_name])
        return f"Opened '{app_name}' successfully."
    except Exception as e:
        return f"Failed to open '{app_name}': {str(e)}"


@tool
def close_app(app_name: str) -> str:
    """Close / kill a running desktop application by its process name.
    
    Use when user wants to close, quit, or kill an app.
    On Windows, automatically appends .exe if needed.
    
    Examples:
        - "close notepad"   → close_app("notepad")
        - "kill spotify"    → close_app("spotify")
        - "quit chrome"     → close_app("chrome")
        - "close vlc"       → close_app("vlc")
    """
    try:
        if sys.platform == 'win32':
            exe = app_name if app_name.endswith('.exe') else f"{app_name}.exe"
            subprocess.run(['taskkill', '/f', '/im', exe], capture_output=True)
        else:
            subprocess.run(['pkill', '-f', app_name], capture_output=True)
        return f"Closed '{app_name}' successfully."
    except Exception as e:
        return f"Failed to close '{app_name}': {str(e)}"


@tool
def open_spotify_search(query: str) -> str:
    """Search and play music on Spotify directly via Spotify URI.
    
    Opens Spotify app with the search query — no browser needed.
    Use when user wants to play music, artist, playlist, podcast on Spotify.
    
    Examples:
        - "play weeknd on spotify"         → open_spotify_search("weeknd")
        - "search lofi playlist spotify"   → open_spotify_search("lofi playlist")
        - "open spotify and play rap"      → open_spotify_search("rap")
    """
    query_encoded = query.strip().replace(' ', '%20')
    uri = f"spotify:search:{query_encoded}"
    webbrowser.open(uri)
    return f"Opened Spotify search for: '{query}'"


@tool  
def open_gmail(action: str = "inbox") -> str:
    """Open Gmail in browser — inbox, compose, or search.
    
    Use when user wants to open email, check inbox, or write a new email in browser.
    For actually SENDING emails, use the Gmail MCP tool instead.
    
    Examples:
        - "open gmail"          → open_gmail("inbox")
        - "open my email"       → open_gmail("inbox")
        - "compose new email"   → open_gmail("compose")
    """
    urls = {
        "inbox":   "https://mail.google.com/mail/u/0/#inbox",
        "compose": "https://mail.google.com/mail/u/0/#compose",
    }
    url = urls.get(action.lower(), urls["inbox"])
    webbrowser.open(url)
    return f"Opened Gmail ({action}) in browser."