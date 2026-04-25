# mcp.py
import asyncio
import logging
from langchain_mcp_adapters.client import MultiServerMCPClient
import os
from dotenv import load_dotenv
load_dotenv()  # ← needed because mcp.py loads before node.py

logger = logging.getLogger(__name__)

MCP_CONFIG = {
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
    "gdrive": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "transport": "stdio"
    },
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "transport": "stdio"
    },
    # "notion": {
    #     "command": "npx",
    #     "args": ["-y", "@notionhq/notion-mcp-server"],
    #     "transport": "stdio",
    #     "env": {
    #         "OPENAPI_MCP_HEADERS": f'{{"Authorization": "Bearer {os.getenv("NOTION_API_KEY", "")}", "Notion-Version": "2022-06-28"}}'
    #     }
    # },
    "brave-search": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "transport": "stdio"
    },
    "puppeteer": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "transport": "stdio"
    },
    "memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "transport": "stdio"
    },
    "sqlite": {
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-sqlite",
            "--db-path",
            r"C:\\Users\\sator\\Documents\\kurama.db"
        ],
        "transport": "stdio"
    },
    "slack": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "transport": "stdio"
    },
}

ENABLED_SERVERS = [
    "filesystem",
    # "gdrive",
    "github",
    # "notion",
    # "brave-search",
    # "puppeteer",
    # "memory",
    # "sqlite",
    # "slack",
]


async def load_mcp_tools() -> list:
    """Load each MCP server separately — skip any that fail."""
    all_tools = []

    for server_name in ENABLED_SERVERS:
        if server_name not in MCP_CONFIG:
            print(f"[MCP] '{server_name}' not found in MCP_CONFIG, skipping.")
            continue

        config = {server_name: MCP_CONFIG[server_name]}

        try:
            client = MultiServerMCPClient(config)
            tools  = await client.get_tools()
            all_tools.extend(tools)
            print(f"[MCP] ✓ {server_name} — {len(tools)} tools loaded")
        except Exception as e:
            print(f"[MCP] ✗ {server_name} failed — {e}")
            continue  # skip broken server, keep going

    return all_tools