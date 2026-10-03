"""CapForge OpenAI Agents SDK Adapter (discussion.mdx §8, §50).

Provides seamless bi-directional integration with OpenAI Agents function calling,
tool definitions, and response message formats.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from capforge.adapter.standard import StandardAgentAdapter
from capforge.core.models import Capability, ExecutionResponse

logger = logging.getLogger("capforge.adapter.openai")


class OpenAIAgentAdapter(StandardAgentAdapter):
    """Bridge for integrating CapForge capabilities into OpenAI Agents tool calling."""

    def to_openai_tool(self, capability: Capability) -> Dict[str, Any]:
        """Convert a CapForge Capability into an OpenAI function tool definition."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for p_name, p_spec in capability.inputs.items():
            raw_type = getattr(p_spec, "type", "string") or "string"
            raw_lower = raw_type.lower()
            if raw_lower in ("string", "number", "integer", "boolean", "object", "array"):
                json_type = raw_lower
            elif raw_lower in ("int",):
                json_type = "integer"
            elif raw_lower in ("float",):
                json_type = "number"
            elif raw_lower in ("bool",):
                json_type = "boolean"
            elif raw_lower in ("dict", "map"):
                json_type = "object"
            elif raw_lower in ("list", "set", "tuple"):
                json_type = "array"
            else:
                json_type = "string"

            properties[p_name] = {
                "type": json_type,
                "description": p_spec.description or f"Input parameter {p_name}",
            }
            if p_spec.required:
                required.append(p_name)

        return {
            "type": "function",
            "function": {
                "name": capability.id,
                "description": capability.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def get_openai_tools(self, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all active capabilities formatted as OpenAI tools."""
        caps = self.registry.list_capabilities(namespace=namespace)
        return [self.to_openai_tool(c) for c in caps]

    def handle_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an OpenAI tool call dictionary and format response message."""
        call_id = tool_call.get("id", "call_unknown")
        func_info = tool_call.get("function", {})
        func_name = func_info.get("name", "")
        raw_args = func_info.get("arguments", "{}")

        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
        else:
            args = raw_args or {}

        # Invoke capability through CapForge runtime
        res: ExecutionResponse = self.invoke_skill(func_name, args)

        output_payload = {
            "status": res.status,
            "output": res.output,
            "error": res.error,
            "execution_time_ms": res.execution_time_ms,
        }

        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(output_payload, default=str),
        }
