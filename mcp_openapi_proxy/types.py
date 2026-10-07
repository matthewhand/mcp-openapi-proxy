from pydantic import BaseModel, AnyUrl
from typing import List, Optional


class TextContent(BaseModel):
    type: str
    text: str
    uri: Optional[str] = None


# Define resource contents as a direct subtype.
# Removed 'type' field to satisfy Pylance, though ValidationError suggests it's needed.
class Resource(BaseModel):
    name: str
    uri: AnyUrl
    description: Optional[str] = None

class TextResourceContents(BaseModel):
    text: str
    uri: AnyUrl  # Expects AnyUrl, not str


class CallToolResult(BaseModel):
    content: List[TextContent]  # Expects TextContent, not TextResourceContents directly
    isError: bool = False


class ServerResult(BaseModel):
    root: CallToolResult


class Tool(BaseModel):
    name: str
    description: str
    inputSchema: dict


class Prompt(BaseModel):
    name: str
    description: str
    arguments: List = []


# PromptMessage represents one message in a prompt conversation.
class PromptMessage(BaseModel):
    role: str
    content: TextContent


class GetPromptResult(BaseModel):
    messages: List[PromptMessage]


class ListPromptsResult(BaseModel):
    prompts: List[Prompt]


class ToolsCapability(BaseModel):
    listChanged: bool


class PromptsCapability(BaseModel):
    listChanged: bool


class ResourcesCapability(BaseModel):
    listChanged: bool


class ServerCapabilities(BaseModel):
    tools: Optional[ToolsCapability] = None
    prompts: Optional[PromptsCapability] = None
    resources: Optional[ResourcesCapability] = None


class ListToolsResult(BaseModel):
    tools: List[Tool]
