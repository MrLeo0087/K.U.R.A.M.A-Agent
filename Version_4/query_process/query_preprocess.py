# decision.py
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from typing import Annotated, Literal, List, Optional
from dotenv import load_dotenv
import os
load_dotenv()

GROQ_KEY = os.getenv('GROQ_API_KEY')

from langchain_core.prompts import ChatPromptTemplate

# ----------- DECISION PROMPT ------------

SYSTEM_PROMPT = """You are KURAMA's task parser. Convert user input into a structured task list.
Do not give answer. just structured task
 
RULE
- do not change task meaning and goal. 
TAGS
general — LLM only, no tools needed
  • casual chat, greetings, jokes, opinions
  • Do not change general query and do not mix user ask ai or ai ask user. keep it real
  • explanations, definitions, how-to knowledge
  • "explain X" / "what is X" / "who is X" / "tell me about X"

search — needs LIVE/CURRENT data, no PC action\
  •  news, prices, scores, stock, recent events
  • "what's the weather" / "latest news" / "current price of X"
  • NOT search if user says "search X on google/youtube" → that is auto

auto — real-world ACTION on PC, browser, or external service
 - Time and weather (what time right now (auto) )
  - Condition of laptop and usage of ram cpu or disk space 
  • open/close any app or website
  • read image, take screenshot 
  • "search X on google/youtube/spotify" → auto (browser action)
  - For file/folder tasks, always use full Windows path format: D:\\Download
- Never use vague descriptions like "D drive Download folder"
  • file ops: create, delete, move, save, read, list files/folders
  • system: screenshot, volume, brightness, shutdown, lock
  • clipboard: copy, paste
  • GitHub: list repos, read file, create issue, open PR
  • Notion: create/read/update pages or databases
  • send: email, slack message, any message
  • install, download anything
  • when unsure between search/auto → pick auto

create — generate NEW content via LLM
  • code, poem, story, essay, email, letter, image, report, summary, caption, bio, script
  • content MUST start with: "generate [type], [description]"
  • "write a poem" → generate poem, ...
  • "make python code" → generate code, ...
  • "give me image of messi" → generate image, ...


CONFLICT RULES

"search X"           → website action? auto | live data? search | explain X? general
"list/show my X"     → GitHub/Notion/files? auto | pure knowledge? general
"create/make X"      → file/folder on PC? auto | written content? create
"tell me X"          → live/current data? search | otherwise general
still unsure?        → default to auto
what is the weather of kathmandu current   -> auto
can you tell me about my laptop condition currently the ram the cpu uses of my laptop  -> auto


TASK RULES
-"You MUST only use the tags: 'general', 'search', 'create', or 'auto'. Do not invent new tags."
- One action = one task. Never merge two actions into one.
  BAD : "write poem and email it" → 1 task
  GOOD: "write poem and email it" → task1: create(poem) + task2: auto(send email, depends_on:[1])

- depends_on = [task_id] if task needs result of previous task, else null
- do not mix up two independ task with eachother. keep them seprate
- content = exact user intent only. Fix typos silently. No added explanation.
- confidence: 1.0=clear | 0.5=ambiguous | 0.3=unclear
- Return ONLY the task list. Zero explanation. Zero commentary."""

decision_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{user_input}")
])

class Task(BaseModel):
    id: Annotated[int, Field(description="Id of task .. it should be like 1,2,3 for each task.. increment")]
    tag: Literal['general', 'search', 'auto', 'create']
    content: Annotated[str, Field(description="Task that user ask for")]
    depends_on: Annotated[Optional[List[int]], Field(default=None, description="is this task depend on other")]
    # Added default=1.0 here to prevent the 400 Validation Error
    confidence: Annotated[float, Field(default=1.0, description="Confidence score of llm between 0 and 1", ge=0.0, le=1.0)]
class DecisionLLM(BaseModel):
    tasks: List[Task]

llm          = ChatGroq(model='qwen/qwen3-32b', api_key=GROQ_KEY)
decision_llm = llm.with_structured_output(DecisionLLM)

def decision_node(query: str) -> list:
    try:
        chain = decision_prompt | decision_llm
        return chain.invoke({'user_input': query}).tasks
    except Exception as e:
        return f"Error: {e}"