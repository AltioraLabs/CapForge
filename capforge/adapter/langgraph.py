"""CapForge LangGraph Adapter Bridge (discussion.mdx §8, §7).

Provides pre-built node handlers and tool wrappers for LangGraph workflows.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from capforge.adapter.standard import StandardAgentAdapter
from capforge.core.models import Capability, ExecutionResponse

logger = logging.getLogger("capforge.adapter.langgraph")


class LangGraphAdapter(StandardAgentAdapter):
    """Bridge for integrating CapForge into LangGraph state graph nodes."""

    def create_langgraph_node(self, capability_id: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Create a state graph node function that executes the given capability."""
        def node_fn(state: Dict[str, Any]) -> Dict[str, Any]:
            inputs = state.get("inputs", state)
            res = self.invoke_skill(capability_id, inputs)
            new_state = dict(state)
            new_state[f"{capability_id}_output"] = res.output
            new_state[f"{capability_id}_status"] = res.status
            return new_state

        node_fn.__name__ = f"node_{capability_id}"
        return node_fn

    def create_evolution_node(self) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """A LangGraph node that detects gaps, acquires missing skills, and executes them."""
        def evolution_node(state: Dict[str, Any]) -> Dict[str, Any]:
            task = state.get("task") or state.get("current_task") or str(state)
            inputs = state.get("inputs", {})
            knowledge = state.get("knowledge_spec")
            res = self.run_task_with_evolution(task, inputs, knowledge)
            new_state = dict(state)
            new_state["capforge_result"] = res.model_dump()
            return new_state

        evolution_node.__name__ = "capforge_evolution_node"
        return evolution_node
