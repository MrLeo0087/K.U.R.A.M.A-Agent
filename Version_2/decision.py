from langchain_groq import ChatGroq
from pydantic import BaseModel,Field
from typing import Annotated, Literal, List, Optional
from dotenv import load_dotenv
from NODE.prompt import decision_prompt
import os
load_dotenv()

GROQ_KEY = os.getenv('GROQ_API_KEY')
class Task(BaseModel):
    id: Annotated[int, Field(description="Id of task .. it should be like 1,2,3 for each task.. increment")]
    tag: Literal['general','search','auto','create']
    content: Annotated[str, Field(description="Task that user ask for")]
    depends_on: Annotated[Optional[List[int]], Field(default=None,description="is this task depend on other")]
    confidence: Annotated[float, Field(description="Confidence score of llm between 0 and 1",ge=0.0,le=1.0)]

class DecisionLLM(BaseModel):
    tasks: List[Task]

llm = ChatGroq(model='qwen/qwen3-32b',api_key=GROQ_KEY)

decision_llm = llm.with_structured_output(DecisionLLM)

def decision_node(query:str)->list:
    chain = decision_prompt | decision_llm 
    return chain.invoke({'user_input':query}).tasks

# result = decision_node("I wanna generate image and then save it into d drive and open youtube")
# print(result)