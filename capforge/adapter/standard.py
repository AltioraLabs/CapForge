"""CapForge Standard Agent Adapter (discussion.mdx §8, §7).

Concrete reference implementation for standalone agents, Python LLM applications,
and custom multi-agent loops.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Dict, List, Optional

from capforge.adapter.base import BaseAgentAdapter
from capforge.core.models import (
    AgentEvent,
    Capability,
    EventType,
    ExecutionRequest,
    ExecutionResponse,
    ToolRequirement,
)
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.agent_adapter import CapForgeAgent

logger = logging.getLogger("capforge.adapter.standard")


class StandardAgentAdapter(BaseAgentAdapter):
    """Adapter bridging arbitrary Python agent loops to the CapForge runtime."""

    def __init__(
        self,
        agent_id: str = "default_agent",
        capforge_agent: Optional[CapForgeAgent] = None,
        registry: Optional[CapabilityRegistry] = None,
    ):
        self.agent_id = agent_id
        if capforge_agent is not None:
            self.sf = capforge_agent
        elif registry is not None:
            self.sf = CapForgeAgent(registry=registry)
        else:
            self.sf = CapForgeAgent()
        self.registry = self.sf.registry
        self._local_tools: Dict[str, Callable] = {}
        self._captured_events: List[AgentEvent] = []

    def register_local_tool(self, name: str, func: Callable, description: str = "") -> None:
        """Register a native Python tool known to the host agent."""
        self._local_tools[name] = func

    def discover_tools(self) -> List[ToolRequirement]:
        """Return all local tools known to the host agent."""
        return [
            ToolRequirement(name=name, description=getattr(func, "__doc__", "") or "")
            for name, func in self._local_tools.items()
        ]

    def capture_events(self) -> List[AgentEvent]:
        """Drain and return all locally queued events."""
        events = list(self._captured_events)
        self._captured_events.clear()
        return events

    def extract_task(self, raw_input: Any) -> str:
        """Extract a normalized string prompt from raw user/agent input."""
        if isinstance(raw_input, str):
            return raw_input
        if isinstance(raw_input, dict):
            return raw_input.get("task") or raw_input.get("prompt") or str(raw_input)
        return str(raw_input)

    def extract_tool_call(self, raw_call: Any) -> Dict[str, Any]:
        """Normalize tool call payload."""
        if isinstance(raw_call, dict):
            return {
                "name": raw_call.get("name") or raw_call.get("tool_name", "unknown"),
                "arguments": raw_call.get("arguments") or raw_call.get("args", {}),
            }
        return {"name": str(raw_call), "arguments": {}}

    def extract_failure(self, raw_error: Any) -> AgentEvent:
        """Convert an exception or failure into a normalized CapForge AgentEvent."""
        err_msg = str(raw_error)
        err_type = type(raw_error).__name__ if isinstance(raw_error, Exception) else "UnknownError"
        event = AgentEvent(
            event_type=EventType.TOOL_FAILED,
            agent_id=self.agent_id,
            error_type=err_type,
            error_message=err_msg,
            metadata={"traceback": traceback.format_exc() if isinstance(raw_error, Exception) else None},
        )
        self._captured_events.append(event)
        self.sf.event_gateway.emit(event)
        return event

    def invoke_skill(self, capability_id: str, inputs: Dict[str, Any]) -> ExecutionResponse:
        """Execute a verified CapForge capability inside the sandbox."""
        req = ExecutionRequest(
            capability_id=capability_id,
            inputs=inputs,
            agent_id=self.agent_id,
        )
        return self.sf.executor.execute(req)

    def inject_capability(self, capability: Capability) -> Callable:
        """Create a callable Python function wrapper for a verified capability."""
        def tool_fn(**kwargs):
            res = self.invoke_skill(capability.id, kwargs)
            if res.status != "SUCCESS":
                raise RuntimeError(f"Skill '{capability.id}' execution failed: {res.error}")
            return res.output

        tool_fn.__name__ = capability.id
        tool_fn.__doc__ = capability.description
        self._local_tools[capability.id] = tool_fn
        logger.info(f"Injected capability '{capability.id}' into agent '{self.agent_id}'")
        return tool_fn

    def run_task_with_evolution(
        self,
        task_intent: str,
        inputs: Dict[str, Any],
        knowledge_spec: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResponse:
        """Convenience helper: execute task, triggering autonomous acquisition if missing."""
        trace = self.sf.handle_task(
            task_intent=task_intent,
            task_inputs=inputs,
            knowledge_spec=knowledge_spec,
            agent_id=self.agent_id,
        )
        if trace.execution_result:
            return trace.execution_result
        return ExecutionResponse(
            capability_id="unknown",
            version="0.0.0",
            status="FAILED",
            error="Task could not be executed or verified.",
            execution_time_ms=0.0,
        )
