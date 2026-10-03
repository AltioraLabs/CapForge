"""CapForge Adapter SDK — Abstract Base Adapter (discussion.mdx §8, Interface 4).

Defines the contract for framework-agnostic agent adapters enabling LangGraph,
CrewAI, AutoGen, OpenAI Agents, or custom agent architectures to seamlessly
plug into CapForge's capability evolution runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from capforge.core.models import (
    AgentEvent,
    Capability,
    ExecutionResponse,
    ToolRequirement,
)


class BaseAgentAdapter(ABC):
    """Abstract interface for all CapForge agent framework adapters."""

    @abstractmethod
    def discover_tools(self) -> list[ToolRequirement]:
        """Discover tools currently registered in the host agent framework."""
        ...

    @abstractmethod
    def capture_events(self) -> list[AgentEvent]:
        """Drain or capture runtime events produced by the host agent."""
        ...

    @abstractmethod
    def extract_task(self, raw_input: Any) -> str:
        """Extract a normalized task intent string from host agent input."""
        ...

    @abstractmethod
    def extract_tool_call(self, raw_call: Any) -> dict[str, Any]:
        """Extract tool call parameters from host agent tool execution format."""
        ...

    @abstractmethod
    def extract_failure(self, raw_error: Any) -> AgentEvent:
        """Translate a host agent error into a normalized CapForge AgentEvent."""
        ...

    @abstractmethod
    def invoke_skill(self, capability_id: str, inputs: dict[str, Any]) -> ExecutionResponse:
        """Invoke a CapForge capability on behalf of the host agent."""
        ...

    @abstractmethod
    def inject_capability(self, capability: Capability) -> Any:
        """Inject or register a forged CapForge capability into the host agent's toolbelt."""
        ...
