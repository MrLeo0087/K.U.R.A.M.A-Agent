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
    # Stores outputs from all nodes by task ID or node name
    results: Annotated[dict[Any, Any], merge_dicts]
    # Tracks failed task IDs or node names
    failed_tasks: Annotated[List[Any], merge_lists]
    context: str
    # Only written ONCE at the very end of the graph
    final_response: Optional[str]