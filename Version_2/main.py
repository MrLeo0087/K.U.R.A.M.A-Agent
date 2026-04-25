print("Importing Library .... ")
import sys
import asyncio
import json
from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

# --- 1. STANDARD IMPORTS ---
from promt import main_prompt
from Basic_tools.basic_tool import get_current_time, get_weather
from system_tools.basic_system_tools import get_system_info
from internet_tools.basic_internet_tools import open_browser, youtube_play, send_email
from internet_tools.messanger_auto import (
    make_facebook_list, delete_facebook_list, view_list, send_message
)
from local_computer_tools.basic_laptop_control import basic_control
from local_computer_tools.app_open import open_app

print("Model Loading ..... ")
model_name = 'qwen2.5:3b'
model = ChatOllama(model=model_name, temperature=0, num_ctx=4096)  # bumped ctx for tool results
print("Model Loaded")

# ──────────────────────────────────────────────
# UNWRAP MCP content blocks → plain string
# ──────────────────────────────────────────────
def unwrap_mcp(raw) -> str:
    """MCP tools return [{'type':'text','text':...}] — extract the text."""
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(raw)

# ──────────────────────────────────────────────
# YOUTUBE RESULT FILTERS
# ──────────────────────────────────────────────
def filter_youtube_video(v: dict) -> dict:
    snippet = v.get("snippet", {})
    stats   = v.get("statistics", {})
    details = v.get("contentDetails", {})
    vid_id  = v.get("id", {})
    return {
        "videoId":     vid_id.get("videoId", v.get("id", "")),
        "title":       snippet.get("title", ""),
        "channel":     snippet.get("channelTitle", ""),
        "published":   snippet.get("publishedAt", "")[:10],
        "duration":    details.get("duration", ""),
        "views":       stats.get("viewCount", ""),
        "likes":       stats.get("likeCount", ""),
        "comments":    stats.get("commentCount", ""),
        "description": snippet.get("description", "")[:150],
    }

def filter_youtube_result(raw_str: str) -> str:
    try:
        data = json.loads(raw_str)
        videos = list(data.values()) if isinstance(data, dict) else data
        cleaned = [filter_youtube_video(v) for v in videos if isinstance(v, dict)]
        return json.dumps(cleaned, indent=2)
    except Exception:
        return raw_str[:2000]

def filter_search_result(raw_str: str) -> str:
    """searchVideos returns a list of search results — keep minimal fields."""
    try:
        data = json.loads(raw_str)
        if not isinstance(data, list):
            data = list(data.values()) if isinstance(data, dict) else [data]
        cleaned = []
        for item in data:
            vid_id = item.get("id", {})
            snippet = item.get("snippet", {})
            cleaned.append({
                "videoId":  vid_id.get("videoId", "") if isinstance(vid_id, dict) else vid_id,
                "title":    snippet.get("title", ""),
                "channel":  snippet.get("channelTitle", ""),
                "published": snippet.get("publishedAt", "")[:10],
                "description": snippet.get("description", "")[:120],
            })
        return json.dumps(cleaned, indent=2)
    except Exception:
        return raw_str[:2000]

# ──────────────────────────────────────────────
# SMART FILTER ROUTER
# ──────────────────────────────────────────────
TOOL_FILTERS = {
    "searchvideos":             filter_search_result,
    "getvideodetails":          filter_youtube_result,
    "getrelatedvideos":         filter_search_result,
    "getchanneltopvideos":      filter_youtube_result,
    "gettrendingvideos":        filter_youtube_result,
    "comparevideos":            filter_youtube_result,
    "getvideoengagementratio":  lambda x: x[:1000],
    "getchannelstatistics":     lambda x: x[:800],
    "gettranscripts":           lambda x: x[:1500],
}

def smart_filter(tool_name: str, raw_result) -> str:
    # Step 1 — unwrap MCP content block
    text = unwrap_mcp(raw_result)

    # Step 2 — apply tool-specific filter
    key = tool_name.lower()
    if key in TOOL_FILTERS:
        text = TOOL_FILTERS[key](text)

    # Step 3 — hard cap
    if len(text) > 2500:
        text = text[:2500] + "\n...[truncated]"

    return text

# ──────────────────────────────────────────────
# WRAP MCP TOOLS so they auto-filter before
# returning to the agent
# ──────────────────────────────────────────────
from langchain_core.tools import StructuredTool
from functools import wraps

def wrap_mcp_tool(tool):
    """Wrap MCP tool output through smart_filter without monkey-patching."""
    original_func  = tool.func
    original_coroutine = tool.coroutine

    # Wrap sync func
    if original_func:
        @wraps(original_func)
        def filtered_func(*args, **kwargs):
            raw = original_func(*args, **kwargs)
            return smart_filter(tool.name, raw)
    else:
        filtered_func = None

    # Wrap async coroutine
    if original_coroutine:
        @wraps(original_coroutine)
        async def filtered_coroutine(*args, **kwargs):
            raw = await original_coroutine(*args, **kwargs)
            return smart_filter(tool.name, raw)
    else:
        filtered_coroutine = None

    # Rebuild the tool with wrapped functions
    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        func=filtered_func,
        coroutine=filtered_coroutine,
    )

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
async def chat_loop():
    # --- Load YouTube MCP tools ---
    print("Loading YouTube MCP tools...")
    mcp_client = MultiServerMCPClient({
        "youtube": {
            "command": "npx",
            "args": ["-y", "youtube-data-mcp-server"],
            "transport": "stdio",
            "env": {
                "YOUTUBE_API_KEY": "AIzaSyCVaRzEwDAD8g-AEKZmbS-xHUOBJr_Y3_o",
                "YOUTUBE_TRANSCRIPT_LANG": "en"
            }
        }
    })

    raw_yt_tools  = await mcp_client.get_tools()
    yt_tools      = [wrap_mcp_tool(t) for t in raw_yt_tools]  # ✅ auto-filter output
    print(f"YouTube tools loaded: {[t.name for t in yt_tools]}")

    # --- Combine all tools ---
    local_tools = [
        get_current_time,
        get_weather,
        get_system_info,
        open_browser,
        youtube_play,
        send_email,
        make_facebook_list,
        delete_facebook_list,
        view_list,
        send_message,
        basic_control,
        open_app,
    ]

    all_tools = local_tools + yt_tools  # ✅ merged

    # --- Build agent ---
    agent          = create_tool_calling_agent(model, all_tools, main_prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=all_tools,
        verbose=False,
        handle_parsing_errors=True,
        return_intermediate_steps=False,
        max_iterations=5
    )

    print("Warming up...")
    await agent_executor.ainvoke({"input": "hi"})
    print("Ready! ✅\n")

    while True:
        user_query = await asyncio.to_thread(input, "\n[USER]: ")

        if user_query.lower() in ['exit', 'quit', 'bye']:
            print("👋 Goodbye!")
            break

        print("KURAMA IS THINKING...")
        showing_answer = False

        async for event in agent_executor.astream_events(
            {'input': user_query},
            version="v2"
        ):
            kind = event["event"]

            if kind == "on_tool_start":
                print(f"🔧 Using: {event['name']}")
                print(f"   👉 Args: {json.dumps(event['data'].get('input'))}")

            if kind == "on_tool_end":
                output = event["data"].get("output")
                if output:
                    preview = str(output)[:200]
                    print(f"   ✓ Result preview: {preview}...")

            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    if not showing_answer:
                        print(f"\n[K.U.R.A.M.A]: ", end="")
                        showing_answer = True
                    print(content, end='', flush=True)

        print("\n" + "-"*50)


if __name__ == "__main__":
    asyncio.run(chat_loop())