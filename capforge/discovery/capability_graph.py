"""CapForge Capability Graph.

In-memory dependency and impact analysis graph for capabilities
(discussion.mdx §32). Tracks tool dependencies, skill compositions,
and cross-capability relationships for impact analysis.
"""

from __future__ import annotations

from collections import defaultdict, deque

from pydantic import BaseModel, Field

from capforge.core.models import Capability
from capforge.registry.store import CapabilityRegistry


class GraphNode(BaseModel):
    """A node in the capability graph."""

    capability_id: str
    version: str
    capability_type: str
    domain: str
    dependencies: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)


class ImpactReport(BaseModel):
    """Report of which capabilities are affected by a change."""

    changed_capability_id: str
    directly_affected: list[str] = Field(default_factory=list)
    transitively_affected: list[str] = Field(default_factory=list)
    total_impact_count: int = 0


class CapabilityGraph:
    """Manages a directed acyclic graph of capability dependencies.

    Edges: capability_id → depends_on_capability_id
    Reverse edges maintained for impact analysis.
    """

    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self.registry = registry
        # Forward edges: cap_id → set of dependency cap_ids
        self._deps: dict[str, set[str]] = defaultdict(set)
        # Reverse edges: cap_id → set of dependent cap_ids
        self._rdeps: dict[str, set[str]] = defaultdict(set)
        # Node metadata
        self._nodes: dict[str, GraphNode] = {}

    def add_capability(self, capability: Capability) -> None:
        """Add a capability and its declared dependencies to the graph."""
        cap_id = capability.id
        dep_ids = [d.capability_id for d in capability.dependencies]

        self._nodes[cap_id] = GraphNode(
            capability_id=cap_id,
            version=capability.version,
            capability_type=capability.capability_type.value,
            domain=capability.domain,
            dependencies=dep_ids,
            dependents=list(self._rdeps.get(cap_id, set())),
        )

        # Update forward edges
        self._deps[cap_id] = set(dep_ids)

        # Update reverse edges
        for dep in dep_ids:
            self._rdeps[dep].add(cap_id)

    def remove_capability(self, capability_id: str) -> None:
        """Remove a capability from the graph."""
        # Remove forward edges
        for dep in self._deps.get(capability_id, set()):
            self._rdeps[dep].discard(capability_id)
        self._deps.pop(capability_id, None)

        # Remove reverse edges
        for dependent in self._rdeps.get(capability_id, set()):
            self._deps[dependent].discard(capability_id)
        self._rdeps.pop(capability_id, None)

        self._nodes.pop(capability_id, None)

    def get_dependencies(self, capability_id: str) -> list[str]:
        """Get direct dependencies of a capability."""
        return list(self._deps.get(capability_id, set()))

    def get_dependents(self, capability_id: str) -> list[str]:
        """Get capabilities that directly depend on this one."""
        return list(self._rdeps.get(capability_id, set()))

    def get_transitive_dependents(self, capability_id: str) -> list[str]:
        """Get all transitively dependent capabilities (BFS)."""
        visited: set[str] = set()
        queue: deque[str] = deque([capability_id])

        while queue:
            current = queue.popleft()
            for dependent in self._rdeps.get(current, set()):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append(dependent)

        return list(visited)

    def impact_analysis(self, capability_id: str) -> ImpactReport:
        """Compute the impact of changing a capability.

        Returns direct dependents and transitive dependents.
        """
        direct = self.get_dependents(capability_id)
        transitive = self.get_transitive_dependents(capability_id)
        # Remove direct from transitive to avoid double-counting
        transitive_only = [t for t in transitive if t not in direct]

        return ImpactReport(
            changed_capability_id=capability_id,
            directly_affected=direct,
            transitively_affected=transitive_only,
            total_impact_count=len(direct) + len(transitive_only),
        )

    def build_from_registry(self) -> int:
        """Rebuild the graph from all capabilities in the registry.

        Returns the number of capabilities indexed.
        """
        if not self.registry:
            return 0

        capabilities = self.registry.list_capabilities()
        for cap in capabilities:
            self.add_capability(cap)

        return len(capabilities)

    def get_node(self, capability_id: str) -> GraphNode | None:
        """Get the graph node for a capability."""
        return self._nodes.get(capability_id)

    def get_all_nodes(self) -> list[GraphNode]:
        """Get all nodes in the graph."""
        return list(self._nodes.values())

    def has_cycle(self) -> bool:
        """Check if the dependency graph contains a cycle."""
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def _dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for dep in self._deps.get(node, set()):
                if dep not in visited:
                    if _dfs(dep):
                        return True
                elif dep in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for node in list(self._nodes.keys()):
            if node not in visited:
                if _dfs(node):
                    return True
        return False
