from pydantic import BaseModel
from typing import List

class ListToolsResult(BaseModel):
    tools: List
