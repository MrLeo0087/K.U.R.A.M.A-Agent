from pydantic import BaseModel 
from typing import Optional,Dict

class Task(BaseModel):
    id: int
    task: str

