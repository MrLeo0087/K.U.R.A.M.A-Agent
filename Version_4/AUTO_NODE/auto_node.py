import sys
import os

# Adds the Version_4 directory to the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from NODE.state import KuramaState
import asyncio
import os
import warnings
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

warnings.filterwarnings("ignore")

# ── CONFIGURATION ──────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
GITHUB_USER  = os.getenv("GITHUB_USERNAME", "")

BASIC_CONTROL   = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\MCP_SERVER\basic_control.py"
SCREEN_OBSERVE  = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\MCP_SERVER\screen_observe.py"
YOUTUBE_SERVER  = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\MCP_SERVER\youtube_server.py"
WEBSITE_CONTROL = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\MCP_SERVER\website_control.py"


SYSTEM_PROMPT = """You are Jarvis. Execute tasks with minimal tool calls.

[ROUTING]
- YOUTUBE: Transcripts/Channel Stats/Sub-counts/Likes.
- GENERAL: Hardware (Vol/Bright/Apps).
- WEBSITE: Search/Open URLs (YouTube, Wiki, IG).
- SCREEN: OCR/Screenshots.
- FILES: Disk operations (C:/D:).
- GITHUB: Github information

[PATH RULES]
- Format: D:\\Folder\\File (Single backslash).
- Priority: Use 'search_nodes' for deep finds; 'list_directory' for browsing.
- Exactness: Use exact user casing. Call 'list_directory' if unsure of extension.

[GITHUB]
- User/Owner: {GITHUB_USER} (Always pass to GitHub tools).

[LOGIC & CLARITY]
- 'website_open': Use to open site by name.
- 'search_youtube': Use to find videos.
- 'youtube' MCP: Use for specific data (subs, counts, transcripts).
- Efficiency: Never call the same tool twice per turn. No markdown in output.

[EXAMPLES]
- "Find main.py" -> search_nodes(root="D:\\", query="main.py")
- "Search MrBeast" -> search_youtube("MrBeast")
- "Sub count of MrBeast" -> [youtube_server]
- "Open nar in personal" -> list_directory("D:\\Personal") -> open_file_externally()

[OUTPUT]
- Clean, natural speech. Max 50 words. No Markdown.
- If tool fails: Self-correct and retry once."""
MAX_RESULT_CHARS = 800 

# ── GLOBAL MCP CLIENT ──────────────────────────────────────────────────────────
# We define this outside so the servers only start ONCE.
mcp_client = MultiServerMCPClient({
    "general_server": {
        "command": "python",
        "args": [BASIC_CONTROL],
        "transport": "stdio",
    },
    "website_server": {
        "command": "python",
        "args": [WEBSITE_CONTROL],
        "transport": "stdio",
    },
    "youtube": {
        "command": "python",
        "args": [YOUTUBE_SERVER],
        "transport": "stdio",
        "env": {
            "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
        }
    },
    "screen_observe": {
        "command": "python",
        "args": [SCREEN_OBSERVE],
        "transport": "stdio",
    },
    "filesystem": {
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            r"D:\\",
            r"C:\\Users\\sator\\Documents"
        ],
        "transport": "stdio"
    },
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "transport": "stdio"
    }
    })

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.environ["GROQ_API_KEY"]
)

# ── UTILITIES ──────────────────────────────────────────────────────────────────
def trim_result(result) -> str:
    text = str(result)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"... [trimmed]"

def extract_text(content) -> str:
    if isinstance(content, list):
        return " ".join(block.get("text", "") for block in content if block.get("type") == "text")
    return str(content)

# ── THE NODE GENERATOR ─────────────────────────────────────────────────────────
def make_auto_node(task):
    async def node(state: KuramaState):
        print(f"\n--- Jarvis Node Executing Task: {task.id} ---")
        
        # 1. Get Tools from the global client
        tools = await mcp_client.get_tools()
        tool_map = {t.name: t for t in tools}
        llm_with_tools = llm.bind_tools(tools)

        # 2. Fresh history for this specific query (Token Efficiency)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=task.content)
        ]

        # 3. Tool Execution Loop
        MAX_STEPS = 5
        for step in range(MAX_STEPS):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break  # LLM has finished its reasoning

            for tool_call in response.tool_calls:
                name = tool_call["name"]
                args = tool_call["args"]
                call_id = tool_call["id"] # Essential for Groq/Langchain tracking

                print(f"  -> Jarvis calling tool: {name}")

                try:
                    result = await tool_map[name].ainvoke(args)
                except Exception as e:
                    result = f"[ERROR] {e}"

                # Append result back to conversation
                messages.append(ToolMessage(
                    content=trim_result(result),
                    tool_call_id=call_id
                ))

        # 4. Save Final Answer to State
        final_answer = extract_text(messages[-1].content)
        state['results'][task.id] = final_answer
        print(f"--- Task Complete: {final_answer}... ---")
        
        return {"results": state['results']}

    return node

# ── MAIN RUNNER ────────────────────────────────────────────────────────────────
# This is a sample of how you'd trigger the node logic
if __name__ == "__main__":
    async def test_run():
        # Fake task object for testing
        class MockTask:
            id = "task_001"
            content = "can you mute this laptop"
            depends_on = []

        state = {"results": {}}
        jarvis_node = make_auto_node(MockTask())
        await jarvis_node(state)
        
    # Run the test
    asyncio.run(test_run())