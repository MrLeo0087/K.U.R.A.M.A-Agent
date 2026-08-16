from typing import List, Optional, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field, AliasChoices
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

load_dotenv()


class Task(BaseModel):
    id: int = Field(
        ..., 
        description="Unique sequential integer ID starting at 1."
    )
    task: str = Field(
        ..., 
        validation_alias=AliasChoices("task", "text", "description"),
        description="Standalone task description."
    )
    tag: Literal["need_tool", "no_need_tool","real_time"] = Field(
        ..., 
        description="'need_tool' for actions/tools or 'no_need_tool' for text generation/chat and 'real_time' for query that required currect data or result."
    )
    depend_on: Optional[List[int]] = Field(
        default=None, 
        description="List of task IDs this task depends on, or null."
    )


class DecisionLLM(BaseModel):
    tasks: List[Task]


# Setup output parser to extract the schema definition
parser = PydanticOutputParser(pydantic_object=DecisionLLM)

SYSTEM_PROMPT = """You are KURAMA's task parser. Breakdown user input into a structured list of tasks and respond strictly in valid json format adhering strictly to the schema below.

{format_instructions}

CRITICAL JSON RULES:
1. Every item inside "tasks" MUST contain the keys: "id", "task", "tag", "depend_on".
2. Use "task" as the exact key name for the task text (DO NOT use "text" or "description").
3. Set "tag" to "need_tool" for system actions/tools, or "no_need_tool" for chat/writing tasks and 'real_time' for search on google for real time result like sport, news, price etc.
4. Set "depend_on" to a list of prerequisite task IDs [id] or null.
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{user_input}")
]).partial(format_instructions=parser.get_format_instructions())

llm = ChatGroq(model="qwen/qwen3.6-27b", temperature=0)
llm_decision = llm.with_structured_output(DecisionLLM, method="json_mode")

chain = prompt | llm_decision

if __name__ == "__main__":
    while True:
        user = input("Enter query : ").strip()
        if user.lower() in ["exit", "quit"]:
            break
        if not user:
            continue

        response = chain.invoke({"user_input": user})
        print(response.model_dump_json(indent=2))