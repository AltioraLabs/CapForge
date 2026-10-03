"""CapForge CrewAI Multi-Agent Adapter (discussion.mdx §8, §50).

Exposes CapForge capabilities as native CrewAI tools for multi-agent role-playing crews.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from capforge.adapter.standard import StandardAgentAdapter
from capforge.core.models import Capability, ExecutionResponse

logger = logging.getLogger("capforge.adapter.crewai")


class CrewAIToolWrapper:
    """Wrapper that matches CrewAI BaseTool interface."""

    def __init__(self, capability: Capability, adapter: CrewAIAgentAdapter):
        self.capability = capability
        self.adapter = adapter
        self.name = capability.id
        self.description = capability.description

    def run(self, **kwargs) -> Any:
        res: ExecutionResponse = self.adapter.invoke_skill(self.capability.id, kwargs)
        if res.status != "SUCCESS":
            return f"Error executing {self.name}: {res.error}"
        return res.output

    def _run(self, **kwargs) -> Any:
        return self.run(**kwargs)

    def __call__(self, **kwargs) -> Any:
        return self.run(**kwargs)


class CrewAIAgentAdapter(StandardAgentAdapter):
    """Bridge for integrating CapForge capabilities into CrewAI agent crews."""

    def to_crewai_tool(self, capability: Capability) -> CrewAIToolWrapper:
        """Wrap a CapForge Capability into a CrewAI-compatible tool."""
        return CrewAIToolWrapper(capability=capability, adapter=self)

    def get_crewai_tools(self, namespace: Optional[str] = None) -> List[CrewAIToolWrapper]:
        """Return all active capabilities formatted for CrewAI agents."""
        caps = self.registry.list_capabilities(namespace=namespace)
        return [self.to_crewai_tool(c) for c in caps]
