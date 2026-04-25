import webbrowser
import urllib.parse
import re
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("WebController")

def is_valid_url(text):
    """Checks if the input is already a formatted URL."""
    pattern = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' # domain
        r'localhost|' # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(pattern, text) is not None

# --- 1. SMART OPEN (The Main Tool) ---
@mcp.tool()
def website_open(destination: str):
    """
    Intelligently opens a website. 
    - If it's a URL (https://google.com), it opens directly.
    - If it's a name (facebook), it appends .com.
    - If it's a phrase (how to bake a cake), it searches Google.
    """
    destination = destination.strip()

    # Case A: It's already a full URL
    if is_valid_url(destination):
        webbrowser.open(destination)
        return f"Opening direct URL: {destination}"

    # Case B: It's a single word (likely a website name)
    if " " not in destination and "." not in destination:
        url = f"https://www.{destination.lower()}.com"
        webbrowser.open(url)
        return f"Assuming website name. Opening {url}"

    # Case C: It has a dot but no protocol (google.com)
    if "." in destination and " " not in destination:
        webbrowser.open(f"https://{destination}")
        return f"Opening {destination}"

    # Case D: It's a phrase - Search Google
    query = urllib.parse.quote(destination)
    webbrowser.open(f"https://www.google.com/search?q={query}")
    return f"Searching Google for: '{destination}'"

# --- 2. SPECIFIC SEARCH TOOLS ---
@mcp.tool()
def search_youtube(query: str):
    """Searches YouTube for a specific video or topic."""
    safe_query = urllib.parse.quote(query)
    webbrowser.open(f"https://www.youtube.com/results?search_query={safe_query}")
    return f"YouTube search opened for '{query}'"

@mcp.tool()
def search_wikipedia(topic: str):
    """Opens the Wikipedia page for a specific topic."""
    # Wikipedia handles spaces with underscores
    formatted_topic = topic.strip().replace(" ", "_")
    webbrowser.open(f"https://en.wikipedia.org/wiki/{formatted_topic}")
    return f"Opening Wikipedia page for '{topic}'"

# --- 3. BONUS: THE "RESEARCH MODE" TOOL ---
@mcp.tool()
def research_topic(topic: str):
    """
    Opens Google, Wikipedia, and YouTube all at once for deep learning.
    Extremely useful when you want to study something new.
    """
    search_google(topic)
    search_wikipedia(topic)
    search_youtube(topic)
    return f"Research Mode Activated: Opened Google, Wiki, and YouTube for '{topic}'"

@mcp.tool()
def search_google(query: str):
    """Directly performs a Google search."""
    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
    return f"Google search results for '{query}'"

if __name__ == "__main__":
    mcp.run()