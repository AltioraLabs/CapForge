"""CapForge Adapter SDK Module (discussion.mdx §8, Interface 4)."""

from __future__ import annotations

from capforge.adapter.base import BaseAgentAdapter
from capforge.adapter.langgraph import LangGraphAdapter
from capforge.adapter.standard import StandardAgentAdapter

__all__ = [
    "BaseAgentAdapter",
    "StandardAgentAdapter",
    "LangGraphAdapter",
]
