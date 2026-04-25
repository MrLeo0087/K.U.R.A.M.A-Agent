# memory.py
import sqlite3
import json
import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

GROQ_KEY = os.getenv("GROQ_API_KEY")
DB_PATH  = r"C:\Users\sator\Documents\kurama_memory.db"

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE SETUP
# ══════════════════════════════════════════════════════════════════════════════

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS long_term (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            key     TEXT UNIQUE,
            value   TEXT,
            updated TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            query     TEXT,
            response  TEXT,
            timestamp TEXT
        )
    """)

    con.commit()
    con.close()

init_db()


# ══════════════════════════════════════════════════════════════════════════════
#  LONG TERM MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def remember(key: str, value: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO long_term (key, value, updated)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated
    """, (key.lower(), value, datetime.now().isoformat()))
    con.commit()
    con.close()


def recall_all() -> dict:
    """Load all long term facts — called every session start."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT key, value FROM long_term")
    rows = cur.fetchall()
    con.close()
    return {row[0]: row[1] for row in rows}


# ══════════════════════════════════════════════════════════════════════════════
#  AUTO REMEMBER — LLM decides what to store
# ══════════════════════════════════════════════════════════════════════════════

memory_llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_KEY)

memory_prompt = ChatPromptTemplate([
    ('system', '''You analyze conversations and extract facts worth remembering permanently.

Save ONLY if user reveals:
- Name, nickname
- City or location  
- Preferences (music, food, color, language)
- Habits or routines
- Important personal facts

Return JSON only. Empty dict if nothing to save.
Format: {{"key": "value"}}
No explanation. No markdown. JSON only.'''),
    ('human', 'User: {query}\nKURAMA: {response}')
])


def auto_remember(query: str, response: str):
    """LLM decides what to save to long term memory."""
    try:
        chain  = memory_prompt | memory_llm | StrOutputParser()
        result = chain.invoke({'query': query, 'response': response})
        result = result.strip().replace('```json', '').replace('```', '').strip()
        facts  = json.loads(result)

        for key, value in facts.items():
            if key and value:
                remember(key, value)
                print(f"[MEMORY] Saved: {key} = {value}")

    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  SHORT TERM MEMORY
# ══════════════════════════════════════════════════════════════════════════════

class ShortTermMemory:
    def __init__(self, max_turns: int = 10):
        self.history   = []
        self.max_turns = max_turns

    def add(self, query: str, response: str):
        self.history.append({"query": query, "response": response})
        if len(self.history) > self.max_turns:
            self.history.pop(0)

    def get_context(self) -> str:
        if not self.history:
            return ""
        context = "Recent conversation:\n"
        for turn in self.history:
            context += f"User: {turn['query']}\nKURAMA: {turn['response']}\n\n"
        return context

    def clear(self):
        self.history = []


# ══════════════════════════════════════════════════════════════════════════════
#  TASK HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def save_task(query: str, response: str):
    """Save only query and final response."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO task_history (query, response, timestamp)
        VALUES (?, ?, ?)
    """, (query, response, datetime.now().isoformat()))
    con.commit()
    con.close()


# ── Global instances ──────────────────────────────────────────────────────────
short_memory = ShortTermMemory(max_turns=10)