from typing import TypedDict, List, Annotated
from query_process.query_preprocess import Task  
from pydantic import BaseModel, Field
import operator

class KuramaState(TypedDict):
    query: str 
    tasks: List[Task] # Better than just 'list'
    results: Annotated[dict, operator.ior] 
    merge_results: str
    final_response: str   

class code_generator(BaseModel):
    name: str = Field(description="Filename WITH extension e.g. 'calculator.py'")
    code: str = Field(description="Complete working code, no placeholders")