#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
  YOUTUBE MCP SERVER — Advanced Edition
  For Jarvis-like AI assistant projects
  Tools: 10 | Token-optimized | Clean output
═══════════════════════════════════════════════════════════════

SETUP:
  1. pip install mcp httpx python-dotenv youtube-transcript-api
  2. Create a .env file with:
       YOUTUBE_API_KEY=your_key_here
       DEFAULT_REGION=NP          ← change to your country code
       DEFAULT_MAX_RESULTS=5      ← default result count
  3. Run: python youtube_mcp_server.py

GET API KEY:
  → https://console.cloud.google.com
  → Enable "YouTube Data API v3"
  → Create credentials → API Key
"""

# ── IMPORTS ────────────────────────────────────────────────────────────────────

import asyncio                        # Required for async/await support
import json                           # For converting Python dicts to JSON strings
import os                             # For reading environment variables
import re                             # For cleaning text (remove HTML tags etc.)

from dotenv import load_dotenv        # Reads your .env file into os.environ
import httpx                          # Async HTTP client to call YouTube API

from mcp.server import Server         # Core MCP server class
from mcp.server.stdio import stdio_server  # stdio transport (Claude talks via stdin/stdout)
from mcp.types import Tool, TextContent    # MCP types for tool definitions and responses

from youtube_transcript_api import YouTubeTranscriptApi   # Free transcript fetcher (v1.0+)

# ── LOAD CONFIG FROM .env ──────────────────────────────────────────────────────

load_dotenv()  # Load .env file — must be called before reading os.getenv()

# ↓ Change these in your .env file, not here
API_KEY         = os.getenv("YOUTUBE_API_KEY")          # Your YouTube Data API v3 key
DEFAULT_REGION  = os.getenv("DEFAULT_REGION", "NP")     # Default country for trending
DEFAULT_MAX     = int(os.getenv("DEFAULT_MAX_RESULTS", "5"))  # Default result count

BASE_URL = "https://www.googleapis.com/youtube/v3"      # YouTube API base URL — do not change

# Crash early if API key is missing — better than a confusing error later
if not API_KEY:
    raise RuntimeError(
        "YOUTUBE_API_KEY is not set.\n"
        "Add it to your .env file: YOUTUBE_API_KEY=your_key_here"
    )


# ── HELPER FUNCTIONS ───────────────────────────────────────────────────────────

async def yt_get(endpoint: str, params: dict) -> dict:
    """
    Central HTTP function — ALL tools use this to call YouTube API.
    Automatically injects the API key into every request.

    endpoint: the API section e.g. "search", "videos", "channels"
    params:   dict of query parameters e.g. {"part": "snippet", "q": "python"}
    returns:  parsed JSON response as Python dict
    """
    params["key"] = API_KEY  # Inject API key into every request automatically
    async with httpx.AsyncClient(timeout=15.0) as client:  # 15s timeout — increase if slow internet
        resp = await client.get(f"{BASE_URL}/{endpoint}", params=params)
        resp.raise_for_status()  # Raises exception on 4xx/5xx errors (bad key, quota exceeded etc.)
        return resp.json()


def clean_text(text: str, max_len: int = 200) -> str:
    """
    Cleans and trims text for token efficiency.
    Removes HTML tags YouTube sometimes puts in descriptions/comments.

    text:    raw string from YouTube API
    max_len: maximum characters to keep — change this to allow longer text
             ↑ increase for richer descriptions, ↓ decrease to save more tokens
    """
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)   # Strip HTML tags like <b>, <a href=...>
    text = re.sub(r"\s+", " ", text)       # Collapse multiple spaces/newlines into one
    return text.strip()[:max_len]          # Trim to max_len characters


def fmt_num(n) -> str:
    """
    Formats large numbers to human-readable form for token savings.
    e.g. 1234567 → "1.23M" instead of sending the full integer.

    Change the thresholds below if you want different formatting.
    """
    if n is None:
        return "N/A"
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"   # Billions
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"       # Millions
    if n >= 1_000:
        return f"{n/1_000:.1f}K"           # Thousands
    return str(n)


def parse_duration(iso: str) -> str:
    """
    Converts YouTube's ISO 8601 duration to human-readable format.
    e.g. "PT1H23M45S" → "1h 23m 45s"

    YouTube returns durations in this weird ISO format — this makes it readable.
    """
    if not iso:
        return "N/A"
    h = re.search(r"(\d+)H", iso)   # Hours
    m = re.search(r"(\d+)M", iso)   # Minutes
    s = re.search(r"(\d+)S", iso)   # Seconds
    parts = []
    if h: parts.append(f"{h.group(1)}h")
    if m: parts.append(f"{m.group(1)}m")
    if s: parts.append(f"{s.group(1)}s")
    return " ".join(parts) if parts else "0s"


def ok(data: dict) -> list[TextContent]:
    """
    Converts a Python dict to MCP TextContent for returning results.
    All tool handlers end with: return ok({...})
    """
    return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


def err(message: str) -> list[TextContent]:
    """
    Returns a clean error message back to Claude.
    Use when something goes wrong: return err("Video not found")
    """
    return [TextContent(type="text", text=json.dumps({"error": message}))]


# ── CREATE MCP SERVER ──────────────────────────────────────────────────────────

# "youtube-mcp" is the server name Claude sees — change if you want
app = Server("youtube-mcp")


# ── TOOL DEFINITIONS ───────────────────────────────────────────────────────────
# These tell Claude what tools exist, what they do, and what arguments they take.
# Claude reads these descriptions to decide WHEN and HOW to use each tool.
# ↓ Good descriptions = Claude uses tools more accurately

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [

        # ── TOOL 1 ──────────────────────────────────────────────────────────────
        Tool(
            name="search_videos",
            # ↓ This description is what Claude reads — be clear and specific
            description="Search YouTube videos by keyword. Returns video IDs, titles, channels, and publish dates. Use this first to find videos before using other tools.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or phrase"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of results, 1-20. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    },
                    "order": {
                        "type": "string",
                        # ↓ Add or remove sort options here
                        "enum": ["relevance", "date", "viewCount", "rating"],
                        "description": "Sort order. Default: relevance",
                        "default": "relevance"
                    },
                    "language": {
                        "type": "string",
                        "description": "Filter by language code e.g. en, ne, hi. Optional."
                    }
                },
                "required": ["query"]
            }
        ),

        # ── TOOL 2 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_video_details",
            description="Get full details of a YouTube video: title, channel, views, likes, duration, tags, description. Use when you need deep info about a specific video.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube video ID (the part after ?v= in the URL)"
                    }
                },
                "required": ["video_id"]
            }
        ),

        # ── TOOL 3 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_trending",
            description="Get currently trending YouTube videos by region and category. No video ID needed. Great for discovering what's popular right now.",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_code": {
                        "type": "string",
                        # ↓ Change default here OR in your .env file via DEFAULT_REGION
                        "description": f"2-letter country code. Default: {DEFAULT_REGION}",
                        "default": DEFAULT_REGION
                    },
                    "category_id": {
                        "type": "string",
                        # ↓ Add more category IDs here if needed
                        "description": "Category: 0=All, 10=Music, 20=Gaming, 22=Blogs, 24=Entertainment, 28=Tech",
                        "default": "0"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of results. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    }
                },
                "required": []
            }
        ),

        # ── TOOL 4 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_comments",
            description="Get top comments from a YouTube video. Useful for understanding audience sentiment and reactions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube video ID"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of comments, 1-50. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    },
                    "order": {
                        "type": "string",
                        "enum": ["relevance", "time"],
                        "description": "relevance = top liked, time = newest. Default: relevance",
                        "default": "relevance"
                    }
                },
                "required": ["video_id"]
            }
        ),

        # ── TOOL 5 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_channel_info",
            description="Get stats and info about a YouTube channel: name, subscribers, total views, video count, country.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "YouTube channel ID (starts with UC...)"
                    }
                },
                "required": ["channel_id"]
            }
        ),

        # ── TOOL 6 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_video_transcript",
            description="Get the full spoken transcript/subtitles of a YouTube video as clean text. Great for summarizing, translating, or analyzing video content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube video ID"
                    },
                    "language": {
                        "type": "string",
                        # ↓ Change default transcript language here
                        "description": "Preferred language code e.g. en, ne, hi. Default: en",
                        "default": "en"
                    }
                },
                "required": ["video_id"]
            }
        ),

        # ── TOOL 7 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_playlist_videos",
            description="Get all videos from a YouTube playlist. Returns video IDs, titles, and positions. Useful for processing entire courses or series.",
            inputSchema={
                "type": "object",
                "properties": {
                    "playlist_id": {
                        "type": "string",
                        "description": "YouTube playlist ID (starts with PL...)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of videos to fetch, 1-50. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    }
                },
                "required": ["playlist_id"]
            }
        ),

        # ── TOOL 8 ──────────────────────────────────────────────────────────────
        Tool(
            name="search_channels",
            description="Search for YouTube channels by keyword. Returns channel IDs, names, subscriber counts, and descriptions. Use to find creators in a niche.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Channel search keyword"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of results. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    }
                },
                "required": ["query"]
            }
        ),

        # ── TOOL 9 ──────────────────────────────────────────────────────────────
        Tool(
            name="get_related_videos",
            description="Get videos related to a given video. Useful for finding similar content, competitor videos, or exploring a topic further.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "YouTube video ID to find related videos for"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of results. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    }
                },
                "required": ["video_id"]
            }
        ),

        # ── TOOL 10 ─────────────────────────────────────────────────────────────
        Tool(
            name="get_channel_videos",
            description="Get the latest videos uploaded by a specific channel. Returns recent uploads sorted by date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "YouTube channel ID (starts with UC...)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Number of videos to return. Default: {DEFAULT_MAX}",
                        "default": DEFAULT_MAX
                    }
                },
                "required": ["channel_id"]
            }
        ),
    ]


# ── TOOL HANDLERS ──────────────────────────────────────────────────────────────
# Each tool has a handler below that does the actual work.
# Pattern: receive args → call YouTube API → clean data → return ok({...})

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Main dispatcher — routes each tool call to the right handler block.
    'name' is the tool name Claude chose, 'arguments' is what Claude passed.
    """

    try:

        # ══════════════════════════════════════════════════════════════════════
        # TOOL 1 — search_videos
        # ══════════════════════════════════════════════════════════════════════
        if name == "search_videos":

            # Build API params — add/remove fields here to change what YouTube returns
            params = {
                "part": "snippet",                              # snippet = titles, channels, thumbnails
                "q": arguments["query"],                        # The search keyword
                "maxResults": arguments.get("max_results", DEFAULT_MAX),
                "order": arguments.get("order", "relevance"),
                "type": "video",                               # Only return videos, not playlists/channels
            }
            # Optional language filter — only added if user provided it
            if arguments.get("language"):
                params["relevanceLanguage"] = arguments["language"]

            data = await yt_get("search", params)

            # ↓ Change which fields to include/exclude here
            results = []
            for item in data.get("items", []):
                s = item["snippet"]
                results.append({
                    "video_id":   item["id"]["videoId"],
                    "title":      s["title"],
                    "channel":    s["channelTitle"],
                    "channel_id": s["channelId"],
                    "published":  s["publishedAt"][:10],        # Only date, not full timestamp
                    "description": clean_text(s.get("description", ""), 120),  # ← change 120 for longer desc
                })

            return ok({"count": len(results), "videos": results})


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 2 — get_video_details
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_video_details":

            data = await yt_get("videos", {
                # ↓ "part" controls what data YouTube sends back — each part costs API quota
                "part": "snippet,statistics,contentDetails",
                "id": arguments["video_id"],
            })

            items = data.get("items", [])
            if not items:
                return err("Video not found. Check the video_id.")

            v  = items[0]
            s  = v["snippet"]           # Basic info section
            st = v["statistics"]        # Numbers section
            cd = v["contentDetails"]    # Duration, quality section

            result = {
                "video_id":    arguments["video_id"],
                "title":       s["title"],
                "channel":     s["channelTitle"],
                "channel_id":  s["channelId"],
                "published":   s["publishedAt"][:10],           # Just the date YYYY-MM-DD
                "duration":    parse_duration(cd["duration"]),  # e.g. "12m 34s"
                "views":       fmt_num(st.get("viewCount")),    # e.g. "1.23M"
                "likes":       fmt_num(st.get("likeCount")),    # e.g. "45.6K"
                "comments":    fmt_num(st.get("commentCount")),
                # ↓ Change 300 to allow longer descriptions
                "description": clean_text(s.get("description", ""), 300),
                # ↓ Only first 10 tags to save tokens — change 10 if you want more
                "tags":        s.get("tags", [])[:10],
                "thumbnail":   s["thumbnails"].get("high", {}).get("url", ""),
            }

            return ok(result)


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 3 — get_trending
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_trending":

            data = await yt_get("videos", {
                "part": "snippet,statistics",
                "chart": "mostPopular",                         # This is what makes it "trending"
                "regionCode": arguments.get("region_code", DEFAULT_REGION),
                "videoCategoryId": arguments.get("category_id", "0"),
                "maxResults": arguments.get("max_results", DEFAULT_MAX),
            })

            results = []
            for i, v in enumerate(data.get("items", []), 1):   # i = rank position
                s  = v["snippet"]
                st = v["statistics"]
                results.append({
                    "rank":      i,                             # Trending position 1, 2, 3...
                    "video_id":  v["id"],
                    "title":     s["title"],
                    "channel":   s["channelTitle"],
                    "views":     fmt_num(st.get("viewCount")),
                    "likes":     fmt_num(st.get("likeCount")),
                    "published": s["publishedAt"][:10],
                })

            return ok({
                "region": arguments.get("region_code", DEFAULT_REGION),
                "count": len(results),
                "trending": results
            })


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 4 — get_comments
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_comments":

            data = await yt_get("commentThreads", {
                "part": "snippet",
                "videoId": arguments["video_id"],
                "maxResults": arguments.get("max_results", DEFAULT_MAX),
                "order": arguments.get("order", "relevance"),
            })

            comments = []
            for item in data.get("items", []):
                c = item["snippet"]["topLevelComment"]["snippet"]  # Deep path to comment data
                comments.append({
                    "author":   c["authorDisplayName"],
                    # ↓ Change 200 to allow longer comment text
                    "text":     clean_text(c["textDisplay"], 200),
                    "likes":    fmt_num(c["likeCount"]),
                    "replies":  item["snippet"]["totalReplyCount"],
                    "date":     c["publishedAt"][:10],
                })

            return ok({"count": len(comments), "comments": comments})


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 5 — get_channel_info
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_channel_info":

            data = await yt_get("channels", {
                "part": "snippet,statistics,brandingSettings",  # brandingSettings has keywords
                "id": arguments["channel_id"],
            })

            items = data.get("items", [])
            if not items:
                return err("Channel not found. Check the channel_id.")

            c  = items[0]
            s  = c["snippet"]
            st = c["statistics"]

            result = {
                "channel_id":  arguments["channel_id"],
                "name":        s["title"],
                "subscribers": fmt_num(st.get("subscriberCount")),
                "total_views": fmt_num(st.get("viewCount")),
                "video_count": fmt_num(st.get("videoCount")),
                "country":     s.get("country", "N/A"),
                "created":     s["publishedAt"][:10],
                # ↓ Change 200 for longer channel description
                "description": clean_text(s.get("description", ""), 200),
                "thumbnail":   s["thumbnails"].get("high", {}).get("url", ""),
            }

            return ok(result)


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 6 — get_video_transcript
        # Uses youtube-transcript-api (free, no quota cost)
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_video_transcript":

            video_id = arguments["video_id"]
            lang     = arguments.get("language", "en")  # Preferred language

            try:
                # ── youtube-transcript-api v1.0+ uses a new API ──────────────
                # Old: YouTubeTranscriptApi.list_transcripts(video_id)
                # New: YouTubeTranscriptApi().fetch() or list_transcripts()
                # We use a try/except to support BOTH old and new versions safely.

                api = YouTubeTranscriptApi()  # New v1.0+: instantiate the class first

                # Build language fallback list — preferred lang first, then common fallbacks
                # ↓ Add more fallback languages here if needed
                lang_priority = [lang, "en", "hi", "ne"]
                # Remove duplicates while preserving order
                lang_priority = list(dict.fromkeys(lang_priority))

                fetched      = None
                used_lang    = None
                is_generated = False

                # Try each language in priority order until one works
                for try_lang in lang_priority:
                    try:
                        # v1.0+ fetch() returns FetchedTranscript object (iterable of snippets)
                        fetched   = api.fetch(video_id, languages=[try_lang])
                        used_lang = try_lang
                        break
                    except Exception:
                        continue  # Try next language

                if fetched is None:
                    # Last resort: fetch without language filter (gets whatever is available)
                    try:
                        fetched   = api.fetch(video_id)
                        used_lang = "auto"
                    except Exception as e:
                        return err(f"No transcript available for this video: {str(e)}")

                # fetched is iterable — each item has .text, .start, .duration
                chunks = list(fetched)

                # Join all text chunks into one clean paragraph
                # ↓ Change " " to "\n" if you want line breaks between caption chunks
                full_text = " ".join(
                    clean_text(chunk.text if hasattr(chunk, "text") else chunk["text"], 500)
                    for chunk in chunks
                )

                return ok({
                    "video_id":  video_id,
                    "language":  used_lang,
                    "length":    f"{len(chunks)} segments",
                    # ↓ Change 3000 to allow more/less transcript text (affects tokens significantly)
                    "transcript": full_text[:3000],
                    "truncated":  len(full_text) > 3000,  # Tells Claude if text was cut off
                })

            except Exception as e:
                return err(f"Transcript error: {str(e)}")


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 7 — get_playlist_videos
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_playlist_videos":

            data = await yt_get("playlistItems", {
                "part": "snippet,contentDetails",
                "playlistId": arguments["playlist_id"],
                "maxResults": min(arguments.get("max_results", DEFAULT_MAX), 50),  # YouTube max is 50
            })

            items = data.get("items", [])
            if not items:
                return err("Playlist not found or is empty.")

            videos = []
            for item in items:
                s = item["snippet"]
                videos.append({
                    "position":   s["position"] + 1,            # 1-based position in playlist
                    "video_id":   s["resourceId"]["videoId"],
                    "title":      s["title"],
                    "channel":    s["videoOwnerChannelTitle"],
                    "published":  s["publishedAt"][:10],
                })

            return ok({
                "playlist_id": arguments["playlist_id"],
                "count": len(videos),
                # Page token for getting next page of results — pass this back to get more videos
                "next_page_token": data.get("nextPageToken"),
                "videos": videos
            })


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 8 — search_channels
        # ══════════════════════════════════════════════════════════════════════
        elif name == "search_channels":

            data = await yt_get("search", {
                "part": "snippet",
                "q": arguments["query"],
                "type": "channel",                              # Only return channels, not videos
                "maxResults": arguments.get("max_results", DEFAULT_MAX),
                "order": "relevance",
            })

            channels = []
            for item in data.get("items", []):
                s = item["snippet"]
                channels.append({
                    "channel_id":  item["id"]["channelId"],
                    "name":        s["channelTitle"],
                    # ↓ Change 150 to allow longer descriptions
                    "description": clean_text(s.get("description", ""), 150),
                    "published":   s["publishedAt"][:10],
                    # "thumbnail":   s["thumbnails"].get("default", {}).get("url", ""),
                })

            return ok({"count": len(channels), "channels": channels})


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 9 — get_related_videos
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_related_videos":

            # NOTE: YouTube removed the relatedToVideoId filter from the public API in 2023.
            # This workaround fetches the video's tags, then searches for those tags.
            # ↓ If YouTube restores relatedToVideoId, replace this block with a direct API call.

            # Step 1: Get the video's tags and title to use as search query
            detail = await yt_get("videos", {
                "part": "snippet",
                "id": arguments["video_id"],
            })
            if not detail.get("items"):
                return err("Video not found.")

            snippet = detail["items"][0]["snippet"]
            tags    = snippet.get("tags", [])[:3]               # Use first 3 tags as query
            query   = " ".join(tags) if tags else snippet["title"]  # Fallback to title if no tags

            # Step 2: Search YouTube with that query, excluding the original video
            data = await yt_get("search", {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": arguments.get("max_results", DEFAULT_MAX) + 1,  # +1 to account for self
            })

            results = []
            for item in data.get("items", []):
                vid_id = item["id"]["videoId"]
                if vid_id == arguments["video_id"]:             # Skip the original video itself
                    continue
                s = item["snippet"]
                results.append({
                    "video_id":  vid_id,
                    "title":     s["title"],
                    "channel":   s["channelTitle"],
                    "published": s["publishedAt"][:10],
                })
                if len(results) >= arguments.get("max_results", DEFAULT_MAX):
                    break                                        # Stop once we have enough

            return ok({
                "based_on_tags": tags,
                "count": len(results),
                "related": results
            })


        # ══════════════════════════════════════════════════════════════════════
        # TOOL 10 — get_channel_videos
        # ══════════════════════════════════════════════════════════════════════
        elif name == "get_channel_videos":

            # YouTube requires searching by channelId to get latest videos
            data = await yt_get("search", {
                "part": "snippet",
                "channelId": arguments["channel_id"],
                "type": "video",
                "order": "date",                                # Latest videos first
                "maxResults": arguments.get("max_results", DEFAULT_MAX),
            })

            items = data.get("items", [])
            if not items:
                return err("No videos found. Check channel_id.")

            videos = []
            for item in items:
                s = item["snippet"]
                videos.append({
                    "video_id":  item["id"]["videoId"],
                    "title":     s["title"],
                    "published": s["publishedAt"][:10],
                    # ↓ Change 100 to allow longer descriptions
                    # "description": clean_text(s.get("description", ""), 100),
                })

            return ok({
                "channel_id": arguments["channel_id"],
                "count": len(videos),
                "latest_videos": videos
            })


        # ══════════════════════════════════════════════════════════════════════
        # UNKNOWN TOOL — safety fallback
        # ══════════════════════════════════════════════════════════════════════
        else:
            return err(f"Unknown tool: '{name}'. This tool does not exist on this server.")


    # ── GLOBAL ERROR HANDLER ──────────────────────────────────────────────────
    # Catches any unexpected error from any tool and returns a clean message
    # instead of crashing the whole server.
    except httpx.HTTPStatusError as e:
        # YouTube API returned an error (bad key, quota exceeded, etc.)
        return err(f"YouTube API error {e.response.status_code}: {e.response.text[:200]}")
    except httpx.TimeoutException:
        # Request took too long — increase timeout in yt_get() if this happens often
        return err("Request timed out. YouTube API is slow. Try again.")
    except Exception as e:
        # Any other unexpected error
        return err(f"Unexpected error: {str(e)}")


# ── ENTRY POINT ────────────────────────────────────────────────────────────────

async def main():
    """
    Starts the MCP server using stdio transport.
    Claude communicates with this server via stdin/stdout pipes.
    Do not add print() statements — they will corrupt the MCP protocol.
    Use a log file if you need to debug: open("debug.log", "a").write(...)
    """
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())  # Run the async server — this line starts everything