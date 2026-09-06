from pydantic import BaseModel
from typing import List, Optional


class TextContent(BaseModel):
    type: str
    text: str
    uri: Optional[str] = None


class TextResourceContents(BaseModel):
    text: str
    uri: str
    mime_type: Optional[str] = None


class CallToolResult(BaseModel):
    content: List[TextContent]
    is_error: bool = False


class ServerResult(BaseModel):
    root: CallToolResult


class Tool(BaseModel):
    name: str
    description: str
    input_schema: dict


class Prompt(BaseModel):
    name: str
    description: str
    arguments: List = []


class PromptMessage(BaseModel):
    role: str
    content: TextContent


class GetPromptResult(BaseModel):
    messages: List[PromptMessage]


class ListPromptsResult(BaseModel):
    prompts: List[Prompt]


class ToolsCapability(BaseModel):
    list_changed: bool


class PromptsCapability(BaseModel):
    list_changed: bool


class ResourcesCapability(BaseModel):
    list_changed: bool


class ServerCapabilities(BaseModel):
    tools: Optional[ToolsCapability] = None
    prompts: Optional[PromptsCapability] = None
    resources: Optional[ResourcesCapability] = None
