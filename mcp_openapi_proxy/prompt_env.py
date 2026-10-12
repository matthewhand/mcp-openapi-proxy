"""Parse the PROMPT environment variable into one extra MCP prompt.

JSON shape::

    {
      "name": "asana_prompt",
      "description": "A test prompt for Asana",
      "messages": [
        {"user": "What is Asana?", "assistant": "Asana is a work management platform."}
      ]
    }

Invalid JSON is logged and ignored. Built-in prompt names are rejected by the
servers that register the result so a custom prompt cannot replace
``summarize_spec`` or ``whimsical_blog``.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp_openapi_proxy.logging_setup import logger

BUILTIN_PROMPT_NAMES = frozenset({"summarize_spec", "whimsical_blog"})


def parse_prompt_env(raw: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return ``{name, description, messages}`` or None when unset or invalid.

    ``messages`` is a list of ``{"role": "user"|"assistant", "text": str}``
    in the order they appeared. A pair may supply ``user``, ``assistant``, or both.
    """
    if raw is None:
        raw = os.getenv("PROMPT")
    if raw is None or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse PROMPT as JSON: {exc}")
        return None
    if not isinstance(data, dict):
        logger.error("PROMPT JSON must be an object with name, description, and messages")
        return None

    name = str(data.get("name") or "custom_prompt").strip() or "custom_prompt"
    description = str(data.get("description") or "Custom prompt from PROMPT envvar")
    messages_data = data.get("messages") or []
    if not isinstance(messages_data, list):
        logger.error("PROMPT messages must be a list")
        return None

    messages: List[Dict[str, str]] = []
    for msg in messages_data:
        if not isinstance(msg, dict):
            continue
        user_msg = msg.get("user") or ""
        assistant_msg = msg.get("assistant") or ""
        if user_msg:
            messages.append({"role": "user", "text": str(user_msg)})
        if assistant_msg:
            messages.append({"role": "assistant", "text": str(assistant_msg)})

    return {"name": name, "description": description, "messages": messages}
