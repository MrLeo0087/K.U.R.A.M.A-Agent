from pydantic import BaseModel, Field
from typing import List, Annotated,Optional, Literal
from dotenv import load_dotenv
from langchain_groq import ChatGroq
load_dotenv()

class Decision(BaseModel):
    id: Annotated[int, Field(description='Unique number for each task.. it like 1,2,3')]
    task: Annotated[str, Field(description='Indivisual and stand alone only one task')]
    tag: Literal['need_tool','no_need_tool']
    depend_on = Annotated[Optional[List[int]], Field(description='Is this task depend on other')]


class DecisionLLM(BaseModel):
    tasks = List[Decision]

llm = ChatGroq(model=)