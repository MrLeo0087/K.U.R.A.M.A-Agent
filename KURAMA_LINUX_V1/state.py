from typing import TypedDict, Optional, List, Annotated, Any
from pydantic import BaseModel
from decision import Task

def merge_dicts(a: Optional[dict] = None, b: Optional[dict] = None) -> dict:
    return (a or {}) | (b or {})

def merge_lists(a: Optional[list] = None, b: Optional[list] = None) -> list:
    return (a or []) + (b or [])

class KuramaState(TypedDict):
    query: str
    tasks: List[Task]
    results: Annotated[dict[Any, Any], merge_dicts]
    failed_tasks: Annotated[List[Any], merge_lists]
    context: str
    final_response: Optional[str]