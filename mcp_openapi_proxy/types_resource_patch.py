from pydantic import BaseModel, AnyUrl
from typing import Optional

class Resource(BaseModel):
    name: str
    uri: AnyUrl
    description: Optional[str] = None
