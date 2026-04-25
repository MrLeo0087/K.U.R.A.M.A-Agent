# NODE/auto/node.py
import asyncio
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.WARNING)

import os
import re
import concurrent.futures
from dotenv import load_dotenv
load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from state import KuramaState

from AUTO.internet import (
    open_url, open_google_search, open_youtube_search,
    open_youtube_video, open_app, close_app,
    open_spotify_search, open_gmail
)
from AUTO.general_tools import (
    get_current_time, get_weather,
    basic_control, get_system_info
)
from AUTO.clipboard_tools import (
    get_clipboard, set_clipboard
)
from AUTO.mcp import load_mcp_tools

GEMINI_API   = os.getenv("GOOGLE_API_KEY")
GITHUB_USER  = os.getenv("GITHUB_USERNAME", "")

# ============================================================
#  PYTHON TOOLS
# ============================================================

PYTHON_TOOLS = [
    open_url, open_google_search, open_youtube_search,
    open_youtube_video, open_app, close_app,
    open_spotify_search, open_gmail,
    get_current_time, get_weather,
    basic_control, get_system_info,
    get_clipboard, set_clipboard,
]

# ============================================================
#  SYSTEM PROMPT
# ============================================================

AUTO_SYSTEM_PROMPT = f"""You are KURAMA's action executor. Your ONLY job is to call tools.

CRITICAL RULES:
- ALWAYS call a tool. NEVER answer from memory or assumptions.
- NEVER write code, explanations, or suggestions.
- NEVER say a folder is empty without calling list_directory first.
- NEVER guess results — use tools to get real data.
- If tool fails, return the error message as result.
- Fix typos silently (opne → open).
- Max 5 tool calls per task.

PATH RULES:
- Always use single backslash in paths: D:\\Learning not D:\\\\Learning
- If user says "D drive X folder" → path is D:\\X
- If user says "inside Y" → append to parent path
- Always use exact path — never guess or modify what user said

GITHUB RULES:
- Username: {GITHUB_USER}
- ALWAYS pass owner="{GITHUB_USER}" in every GitHub tool call
- ALWAYS pass username="{GITHUB_USER}" when listing user repos

TOOL REFERENCE:
- list_directory(path)          → list files in folder
- read_file(path)               → read file content  
- write_file(path, content)     → write content to file
- create_directory(path)        → create folder
- search_files(path, pattern)   → search files
- open_url(url)                 → open website
- open_app(name)                → open application
- open_google_search(query)     → search google
- open_youtube_search(query)    → search youtube
- basic_control(action)         → mute/volume/brightness
- get_system_info()             → system information
- get_current_time()            → current time
- get_weather(city)             → weather info
- get_clipboard()               → read clipboard
- set_clipboard(text)           → write clipboard
"""

# ============================================================
#  SCHEMA FIXER
# ============================================================

def fix_tool_schemas(tools: list) -> list:
    """Recursively fix None values in tool schemas."""
    def fix_none(obj):
        if isinstance(obj, dict):
            return {k: fix_none(v) if v is not None else {"type": "string"}
                    for k, v in obj.items()}
        elif isinstance(obj, list):
            return [fix_none(i) for i in obj]
        return obj

    for tool in tools:
        try:
            if hasattr(tool, 'args_schema') and tool.args_schema:
                if hasattr(tool.args_schema, 'schema'):
                    schema = tool.args_schema.schema()
                    props  = schema.get("properties", {})
                    for key, val in props.items():
                        if val is None:
                            props[key] = {"type": "string"}
        except Exception:
            pass
    return tools

# ============================================================
#  PATH CLEANER
# ============================================================

def clean_path(text: str) -> str:
    """Fix common path issues in task content."""
    # Fix double escaped backslashes
    text = text.replace('\\\\\\\\', '\\')
    text = text.replace('\\\\', '\\')
    # Fix forward slashes in Windows paths
    if re.match(r'^[A-Za-z]:', text):
        text = text.replace('/', '\\')
    return text

# ============================================================
#  ONE-TIME INITIALIZATION
# ============================================================

async def _init():
    mcp_tools = await load_mcp_tools()
    all_tools = PYTHON_TOOLS + mcp_tools
    all_tools = fix_tool_schemas(all_tools)

    # Test each tool with Gemini — skip broken ones
    test_llm  = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-lite",
        google_api_key=GEMINI_API
    )
    good_tools = []
    for tool in all_tools:
        try:
            test_llm.bind_tools([tool])
            good_tools.append(tool)
        except Exception:
            print(f"[TOOL] Skipping broken: {tool.name}")

    tool_map = {t.name: t for t in good_tools}
    print(f"[KURAMA] Ready — {len(PYTHON_TOOLS)} python tools + {len(mcp_tools)} MCP tools loaded.")
    return tool_map

_tool_map = asyncio.run(_init())

# ============================================================
#  NODE FACTORY
# ============================================================

def make_auto_node(task):
    def node(state: KuramaState):
        task_id = task.id
        try:
            # Build context from parent results
            context = ""
            if task.depends_on:
                for parent_id in task.depends_on:
                    parent_result = state['results'].get(parent_id, "")
                    context += f"Previous result: {parent_result}\n"

            # Clean path issues in task content
            task_content = clean_path(task.content)

            def run_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def run():
                    llm = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash",  # ✅ correct model
                        google_api_key=GEMINI_API
                    )
                    llm_with_tools = llm.bind_tools(
                        list(_tool_map.values())  # ✅ no tool_choice
                    )

                    messages = [
                        SystemMessage(content=AUTO_SYSTEM_PROMPT),
                        HumanMessage(content=f"Task: {task_content}\n{context}".strip())
                    ]

                    for _ in range(5):  # ✅ 5 max
                        response = await llm_with_tools.ainvoke(messages)
                        messages.append(response)

                        if not response.tool_calls:
                            break  # ✅ done naturally

                        for tool_call in response.tool_calls:
                            tool_name = tool_call['name']
                            tool_args = tool_call['args']

                            if tool_name in _tool_map:
                                try:
                                    tool_result = await _tool_map[tool_name].ainvoke(tool_args)
                                except Exception as e:
                                    tool_result = f"[TOOL ERROR] {str(e)}"
                            else:
                                tool_result = f"[ERROR] Tool '{tool_name}' not found."

                            messages.append(ToolMessage(
                                content=str(tool_result),
                                tool_call_id=tool_call['id']
                            ))

                    return messages[-1].content

                try:
                    return loop.run_until_complete(run())
                finally:
                    # ✅ Clean up pending tasks before closing loop
                    pending = asyncio.all_tasks(loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(run_in_thread).result()

        except Exception as e:
            # ✅ Always return dict — never string
            result = f"Task failed: {str(e)}"

        return {'results': {task_id: result}}

    return node