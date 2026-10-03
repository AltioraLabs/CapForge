"""CapForge Adapter SDK Module (discussion.mdx §8, Interface 4)."""

from capforge.adapter.base import BaseAgentAdapter
from capforge.adapter.standard import StandardAgentAdapter
from capforge.adapter.langgraph import LangGraphAdapter

__all__ = [
    "BaseAgentAdapter",
    "StandardAgentAdapter",
    "LangGraphAdapter",
]
