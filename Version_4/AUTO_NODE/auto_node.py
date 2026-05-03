import sys
import os
import asyncio
import warnings
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore")

# Adds the Version_4 directory to the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tool Imports
from AUTO_NODE.Tools.general_tools import (
    get_current_time, get_weather, basic_control, get_system_info,
    open_app, close_app, media_forward, media_backward, 
    get_task_manager_info, get_laptop_info
)
from AUTO_NODE.Tools.screen_tools import (
    take_screenshot, read_image_file_text, find_text_on_screen, get_mouse_position
)
from AUTO_NODE.Tools.website_tools import (
    website_open, search_youtube, search_wikipedia, search_google, research_topic
)

from AUTO_NODE.Tools.other_file_tools import youtube_vision_control

from NODE.state import KuramaState
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

warnings.filterwarnings("ignore")

# ── CONFIGURATION ──────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
GITHUB_USER = os.getenv("GITHUB_USERNAME", "sator")
YOUTUBE_SERVER = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\MCP_SERVER\youtube_server.py"

# Tools that stay OUTSIDE vector search (Always loaded)
HOT_CACHE_TOOL_NAMES = [
    "get_current_time", "website_open", "basic_control", 
    "take_screenshot", "search_google", "search_youtube"
]

SYSTEM_PROMPT = f"""You are Jarvis, a high-efficiency AI assistant.
[STRICT PROTOCOL]
1. SINGLE CALL LIMIT: You are FORBIDDEN from calling the same tool twice for the same task. 
2. HALT CONDITION: Once a tool returns 'Success' or a valid result, you MUST stop calling tools and summarize.
3. NO REPETITION: Do not 'fine-tune' settings (like volume or brightness) with multiple incremental calls. Make one call and exit.

[ROUTING]
- YOUTUBE: Transcripts, Channel Stats, Sub-counts.
- GENERAL: Hardware (Volume, Brightness, Apps).
- WEBSITE: Browsing, Wikipedia, Google Search.
- SCREEN: OCR, Screenshots.
- FILES: Disk operations (D:\\ or C:\\).
- GITHUB: Repository management for {GITHUB_USER}.


[ACTION VS DATA]
- If the user says 'Search for', 'Show me', or 'Open', you MUST use a tool that starts the browser (like search_youtube).
- Only use 'search_videos' or 'get_video_details' if the user asks a specific question like 'How many views' or 'What is the title'.
- Always prefer ACTION tools over DATA tools for general requests.
- use search_wikipedia tool for search on wikipedia
[OUTPUT RULES]
- Speak naturally. Max 40 words. 
- NO MARKDOWN. NO BOLD. NO LISTS.
- If a tool fails once, explain the error; do not loop."""
# ── 1. THE TOOL MANAGER (VECTOR RETRIEVAL) ───────────────────────────────────
class ToolManager:
    def __init__(self, mcp_client, local_tools):
        self.mcp_client = mcp_client
        self.local_tools = local_tools
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.hot_tools = []
        self.dynamic_map = {}
        self.vector_db = None

    async def initialize(self):
        print("\n--- Initializing K.U.R.A.M.A Tool Index ---")
        mcp_tools = await self.mcp_client.get_tools()
        all_tools = mcp_tools + self.local_tools
        
        dynamic_docs = []
        for tool in all_tools:
            if tool.name in HOT_CACHE_TOOL_NAMES:
                self.hot_tools.append(tool)
            else:
                self.dynamic_map[tool.name] = tool
                dynamic_docs.append(Document(
                    page_content=f"{tool.name}: {tool.description}",
                    metadata={"name": tool.name}
                ))

        if dynamic_docs:
            self.vector_db = FAISS.from_documents(dynamic_docs, self.embeddings)
        print(f"Index Ready. Hot Cache: {len(self.hot_tools)} | Dynamic: {len(dynamic_docs)}")

    def get_tools_for_query(self, query: str, k=3) -> list:
        if not self.vector_db: return self.hot_tools
        # Semantic lookup for top 3 tools
        related_docs = self.vector_db.similarity_search(query, k=k)
        retrieved = [self.dynamic_map[doc.metadata["name"]] for doc in related_docs]
        return self.hot_tools + retrieved

# ── 2. GLOBAL CLIENTS ────────────────────────────────────────────────────────
mcp_client = MultiServerMCPClient({
    # "youtube": {
    #     "command": "python", "args": [YOUTUBE_SERVER], "transport": "stdio",
    #     "env": {"YOUTUBE_API_KEY": YOUTUBE_API_KEY}
    # },
    "filesystem": {
        "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\", "C:\\Users\\sator\\Documents"],
        "transport": "stdio"
    },
    "github": {
        "command": "npx", 
        "args": ["-y", "@modelcontextprotocol/server-github"], 
        "transport": "stdio",
        "env": {
            "GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
        }
    }
})

llm = ChatGroq(model="openai/gpt-oss-120b", api_key=GROQ_API_KEY)
# llm = ChatGroq(
#     model="openai/gpt-oss-120b",
#     api_key=GROQ_API_KEY,
#     model_kwargs={"reasoning_format": "hidden"}  # or "parsed"
# )


# Collect all imported tools
custom_tools_list = [
    get_current_time, get_weather, basic_control, get_system_info,
    open_app, close_app, media_forward, media_backward, 
    get_task_manager_info, get_laptop_info, take_screenshot, 
    read_image_file_text, find_text_on_screen, get_mouse_position,
    website_open, search_youtube, search_wikipedia, search_google, research_topic,youtube_vision_control
]

manager = ToolManager(mcp_client, custom_tools_list)

async def init_manager():
    await manager.initialize()

# ── 3. THE SMART NODE GENERATOR ─────────────────────────────────────────────
def make_auto_node(task, manager: ToolManager):
    async def node(state: KuramaState):
        print(f"\n--- Jarvis Node Executing Task: {task.id} ---")
        
        # Filter Tools: Hot Cache + Top 3 Relevant
        active_tools = manager.get_tools_for_query(task.content)
        tool_map = {t.name: t for t in active_tools}
        llm_with_tools = llm.bind_tools(active_tools)

        # print(f"Active Tools for this task: {[t.name for t in active_tools]}")

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=task.content)
        ]

        MAX_STEPS = 5
        for _ in range(MAX_STEPS):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls: break

            for tool_call in response.tool_calls:
                name, args, call_id = tool_call["name"], tool_call["args"], tool_call["id"]
                print(f"  -> Jarvis calling: {name} -> Arg: {args}")

                try:
                    result = await tool_map[name].ainvoke(args)
                except Exception as e:
                    result = f"[ERROR] {e}"
                
                print(result)

                messages.append(ToolMessage(content=str(result)[:800], tool_call_id=call_id))

        final_answer = messages[-1].content if isinstance(messages[-1].content, str) else str(messages[-1].content)
        state['results'][task.id] = final_answer
        # print(f"--- Task Complete: {final_answer[:50]}... ---")
        
        return {"results": state['results']}

    return node



# ── 4. MAIN RUNNER ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def test_run():
        # Initialize Tool Manager once
        manager = ToolManager(mcp_client, custom_tools_list)
        await manager.initialize()

        class MockTask:
            id = "task_001"
            content = "Find if I have a file named 'main.py' in D drive and mute the laptop"
            depends_on = []

        state = {"results": {}}
        jarvis_node = make_auto_node(MockTask(), manager)
        await jarvis_node(state)
        
    asyncio.run(test_run())