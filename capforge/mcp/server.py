"""CapForge Model Context Protocol (MCP) Server.

Implements standard JSON-RPC 2.0 Model Context Protocol interface, allowing
agents (Claude Desktop, Cursor, Antigravity IDE, LangChain, etc.) to discover,
execute, synthesize, and inspect CapForge capabilities.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from capforge.core.models import CapabilityStatus, ExecutionRequest
from capforge.core.manifest import capability_to_yaml
from capforge.registry.store import CapabilityRegistry
from capforge.registry.search import CapabilityMatcher
from capforge.runtime.executor import CapabilityExecutor
from capforge.acquisition.synthesizer import CapabilitySynthesizer

logger = logging.getLogger("capforge.mcp")


class CapForgeMCPServer:
    """Model Context Protocol (MCP) Server for CapForge runtime."""

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "capforge-mcp"
    SERVER_VERSION = "0.4.0"

    def __init__(
        self,
        registry: Optional[CapabilityRegistry] = None,
        executor: Optional[CapabilityExecutor] = None,
        synthesizer: Optional[CapabilitySynthesizer] = None,
    ):
        self.registry = registry or CapabilityRegistry()
        self.executor = executor or CapabilityExecutor(registry=self.registry)
        self.synthesizer = synthesizer or CapabilitySynthesizer()
        self.matcher = CapabilityMatcher(self.registry)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return MCP standard tool declarations."""
        return [
            {
                "name": "capforge_search_capabilities",
                "description": "Search the CapForge capability registry for existing skills or tools matching a task intent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language description or keywords of required capability.",
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Minimum similarity match score (default: 0.20).",
                            "default": 0.20,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "capforge_execute_capability",
                "description": "Execute a verified capability within the isolated sandbox environment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capability_id": {
                            "type": "string",
                            "description": "Unique identifier of the capability to run.",
                        },
                        "inputs": {
                            "type": "object",
                            "description": "Dictionary of input arguments required by the capability.",
                            "default": {},
                        },
                        "version": {
                            "type": "string",
                            "description": "Optional specific version to invoke (defaults to latest active).",
                        },
                    },
                    "required": ["capability_id"],
                },
            },
            {
                "name": "capforge_synthesize_capability",
                "description": "Trigger autonomous acquisition and synthesis for a missing capability.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_intent": {
                            "type": "string",
                            "description": "Description of the goal the agent needs to achieve.",
                        },
                        "target_capability_id": {
                            "type": "string",
                            "description": "Desired identifier for the newly forged capability.",
                        },
                    },
                    "required": ["task_intent"],
                },
            },
            {
                "name": "capforge_get_manifest",
                "description": "Export the canonical YAML manifest and verification report for a capability.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capability_id": {
                            "type": "string",
                            "description": "Identifier of the capability to inspect.",
                        },
                        "version": {
                            "type": "string",
                            "description": "Optional specific version (defaults to latest).",
                        },
                    },
                    "required": ["capability_id"],
                },
            },
            {
                "name": "capforge_list_capabilities",
                "description": "List all registered capabilities in the system.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Filter by status: ACTIVE, EXPERIMENTAL, DEPRECATED, QUARANTINED.",
                        }
                    },
                },
            },
        ]

    def handle_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a single JSON-RPC 2.0 message."""
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        if not method:
            return self._error_response(msg_id, -32600, "Invalid Request: missing method")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.SERVER_NAME,
                        "version": self.SERVER_VERSION,
                    },
                },
            }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self.get_tool_definitions()},
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                call_res = self._execute_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(call_res, indent=2, default=str),
                            }
                        ]
                    },
                }
            except Exception as e:
                logger.exception("Error executing MCP tool '%s'", tool_name)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error executing tool {tool_name}: {str(e)}"}],
                        "isError": True,
                    },
                }

        else:
            return self._error_response(msg_id, -32601, f"Method not found: '{method}'")

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """Route and execute an MCP tool call."""
        if name == "capforge_search_capabilities":
            query = args.get("query", "")
            thresh = float(args.get("threshold", 0.20))
            matches = self.matcher.find_matches(query=query, threshold=thresh)
            return [
                {
                    "id": cap.id,
                    "name": cap.name,
                    "version": cap.version,
                    "status": cap.status.value,
                    "description": cap.description,
                    "score": score,
                    "tags": cap.tags,
                }
                for cap, score in matches
            ]

        elif name == "capforge_execute_capability":
            req = ExecutionRequest(
                capability_id=args["capability_id"],
                version=args.get("version"),
                inputs=args.get("inputs", {}),
            )
            res = self.executor.execute(req)
            return {
                "capability_id": res.capability_id,
                "version": res.version,
                "status": res.status,
                "output": res.output,
                "error": res.error,
                "execution_time_ms": res.execution_time_ms,
            }

        elif name == "capforge_synthesize_capability":
            task_intent = args["task_intent"]
            target_id = args.get("target_capability_id")
            cap = self.synthesizer.synthesize_from_intent(task_intent, target_id=target_id)
            return {
                "capability_id": cap.id,
                "name": cap.name,
                "version": cap.version,
                "status": cap.status.value,
                "risk_level": cap.risk_level.value,
                "description": cap.description,
            }

        elif name == "capforge_get_manifest":
            cap_id = args["capability_id"]
            ver = args.get("version")
            cap = self.registry.get(cap_id, version=ver)
            if not cap:
                raise ValueError(f"Capability '{cap_id}' (version: {ver or 'latest'}) not found")
            manifest_yaml = capability_to_yaml(cap)
            return {"capability_id": cap_id, "version": cap.version, "manifest_yaml": manifest_yaml}

        elif name == "capforge_list_capabilities":
            status_filter = None
            if "status" in args and args["status"]:
                status_filter = CapabilityStatus(args["status"].upper())
            caps = self.registry.list_capabilities(status=status_filter)
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "version": c.version,
                    "status": c.status.value,
                    "risk_level": c.risk_level.value,
                    "description": c.description,
                }
                for c in caps
            ]

        else:
            raise ValueError(f"Unknown MCP tool '{name}'")

    def _error_response(self, msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    def run_stdio(self) -> None:
        """Run standard I/O loop for MCP client communication."""
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_message(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError:
                err = self._error_response(None, -32700, "Parse error")
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = CapForgeMCPServer()
    server.run_stdio()
