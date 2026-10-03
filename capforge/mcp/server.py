"""CapForge Model Context Protocol (MCP) Server.

Implements standard JSON-RPC 2.0 Model Context Protocol interface, allowing
agents (Claude Desktop, Cursor, Antigravity IDE, LangChain, CrewAI, AutoGen, etc.)
to discover, execute, synthesize, and inspect CapForge capabilities over STDIO and SSE.

Every registered capability in CapForge is dynamically exposed as a native MCP Tool
with its formal JSON Schema input contract.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from capforge.acquisition.synthesizer import CapabilitySynthesizer
from capforge.core.manifest import capability_to_yaml
from capforge.core.models import CapabilityStatus, ExecutionRequest
from capforge.registry.search import CapabilityMatcher
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.executor import CapabilityExecutor

logger = logging.getLogger("capforge.mcp.server")


class CapForgeMCPServer:
    """Model Context Protocol (MCP) Server for CapForge runtime."""

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "capforge-mcp"
    SERVER_VERSION = "1.1.0"

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        executor: CapabilityExecutor | None = None,
        synthesizer: CapabilitySynthesizer | None = None,
    ):
        self.registry = registry or CapabilityRegistry()
        self.executor = executor or CapabilityExecutor(registry=self.registry)
        self.synthesizer = synthesizer or CapabilitySynthesizer()
        self.matcher = CapabilityMatcher(self.registry)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return MCP standard tool declarations, including dynamic registered capabilities."""
        tools: list[dict[str, Any]] = [
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
                        "task_description": {
                            "type": "string",
                            "description": "Detailed prompt describing the capability logic and objectives.",
                        },
                        "domain": {
                            "type": "string",
                            "description": "Functional domain (e.g. data_analysis, risk, math, devops).",
                            "default": "general",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Metadata tags categorizing the capability.",
                            "default": [],
                        },
                    },
                    "required": ["task_description"],
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
            {
                # Backward-compatibility alias: older clients/tests address the
                # manifest export as a first-class tool. New clients may use
                # the per-capability dynamic tools below.
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
        ]

        # Dynamically expose every registered capability as an MCP Tool
        try:
            active_caps = self.registry.list_capabilities()
            for cap in active_caps:
                tool_name = f"capforge_{cap.id}" if not cap.id.startswith("capforge_") else cap.id

                props: dict[str, Any] = {}
                reqs: list[str] = []

                for param_name, spec in cap.inputs.items():
                    t_str = (spec.type or "string").lower()
                    if "int" in t_str:
                        js_type = "integer"
                    elif "float" in t_str or "number" in t_str:
                        js_type = "number"
                    elif "bool" in t_str:
                        js_type = "boolean"
                    elif "list" in t_str or "array" in t_str:
                        js_type = "array"
                    elif "dict" in t_str or "object" in t_str:
                        js_type = "object"
                    else:
                        js_type = "string"

                    prop: dict[str, Any] = {
                        "type": js_type,
                        "description": spec.description or f"Input parameter {param_name}",
                    }
                    if spec.default is not None:
                        prop["default"] = spec.default
                    props[param_name] = prop

                    if spec.required and spec.default is None:
                        reqs.append(param_name)

                tools.append(
                    {
                        "name": tool_name,
                        "description": f"[CapForge Capability v{cap.version}] {cap.description}",
                        "inputSchema": {
                            "type": "object",
                            "properties": props,
                            "required": reqs,
                        },
                    }
                )
        except Exception as e:
            logger.warning("Error fetching dynamic capabilities for MCP: %s", e)

        return tools

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
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

    def _execute_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Route and execute an MCP tool call."""
        if name == "capforge_search_capabilities":
            query = args.get("query", "")
            thresh = float(args.get("threshold", 0.20))
            matches = self.matcher.find_matches(query=query, threshold=thresh)
            # find_matches returns (capability, score) tuples; unwrap defensively
            # since older callers expect plain capability objects.
            caps = [m[0] if isinstance(m, tuple) else m for m in matches]
            return [
                {
                    "id": cap.id,
                    "name": cap.name,
                    "version": cap.version,
                    "status": cap.status.value,
                    "description": cap.description,
                    "domain": cap.domain,
                    "tags": cap.tags,
                }
                for cap in caps
            ]

        elif name == "capforge_execute_capability":
            cap_id = args["capability_id"]
            inputs = args.get("inputs", {})
            version = args.get("version")
            req = ExecutionRequest(capability_id=cap_id, version=version, inputs=inputs)
            resp = self.executor.execute(req)
            return {
                "capability_id": resp.capability_id,
                "version": resp.version,
                "status": resp.status,
                "output": resp.output,
                "error": resp.error,
                "execution_time_ms": resp.execution_time_ms,
            }

        elif name == "capforge_synthesize_capability":
            desc = args["task_description"]
            domain = args.get("domain", "general")
            tags = args.get("tags", [])
            cap = self.synthesizer.synthesize(task_description=desc, domain=domain, tags=tags)
            self.registry.register(cap)
            return {
                "capability_id": cap.id,
                "version": cap.version,
                "status": cap.status.value,
                "entrypoint": cap.entrypoint_function,
                "verification_tests_count": len(cap.verification_tests),
                "manifest_yaml": capability_to_yaml(cap),
            }

        elif name == "capforge_list_capabilities":
            status_filter = args.get("status")
            if status_filter:
                try:
                    c_status = CapabilityStatus(status_filter.upper())
                    caps = self.registry.list_capabilities(status=c_status)
                except ValueError:
                    caps = []
            else:
                caps = self.registry.list_capabilities()

            return [
                {
                    "id": c.id,
                    "version": c.version,
                    "name": c.name,
                    "status": c.status.value,
                    "description": c.description,
                    "domain": c.domain,
                    "tags": c.tags,
                }
                for c in caps
            ]

        elif name == "capforge_get_manifest":
            cap_id = args["capability_id"]
            ver = args.get("version")
            cap = self.registry.get(cap_id, version=ver)
            if not cap:
                raise ValueError(f"Capability '{cap_id}' (version: {ver or 'latest'}) not found")
            manifest_yaml = capability_to_yaml(cap)
            return {"capability_id": cap_id, "version": cap.version, "manifest_yaml": manifest_yaml}

        # Dynamic Capability Execution
        cap_id = name.removeprefix("capforge_") if name.startswith("capforge_") else name
        cap = self.registry.get(cap_id)
        if cap:
            req = ExecutionRequest(capability_id=cap.id, inputs=args)
            resp = self.executor.execute(req)
            return {
                "capability_id": resp.capability_id,
                "version": resp.version,
                "status": resp.status,
                "output": resp.output,
                "error": resp.error,
                "execution_time_ms": resp.execution_time_ms,
            }

        raise ValueError(f"Unknown MCP tool: '{name}'")

    def _error_response(self, msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    def run_stdio(self) -> None:
        """Run the MCP server in standard input/output (STDIO) transport loop."""
        logger.info("CapForge MCP Server listening on STDIO")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                resp = self.handle_message(msg)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = self._error_response(None, -32700, f"Parse error: {e}")
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
