from typing import TypedDict, Optional, List, Annotated
from pydantic import BaseModel,Field
from decision import Task

def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}

class KuramaState(TypedDict):
    query:str
    tasks:List[Task]
    results: Annotated[dict[int, str], merge_dicts]
    # merge_results: str
    final_response:Optional[str]
    context        : str



    