"""Unit tests for the Capability Graph and Impact Analysis."""

from capforge.core.models import Capability, CapabilityDependency
from capforge.discovery.capability_graph import CapabilityGraph


def _make_cap(cap_id: str, deps: list[str] = None) -> Capability:
    return Capability(
        id=cap_id,
        name=cap_id.replace("_", " ").title(),
        description=f"Test capability {cap_id}",
        code_body="def execute(inputs): return {}",
        dependencies=[
            CapabilityDependency(capability_id=d) for d in (deps or [])
        ],
    )


class TestCapabilityGraph:
    def test_add_and_get_dependencies(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("security_audit", deps=["repo_analysis", "vuln_scanner"]))
        graph.add_capability(_make_cap("repo_analysis"))
        graph.add_capability(_make_cap("vuln_scanner"))

        deps = graph.get_dependencies("security_audit")
        assert set(deps) == {"repo_analysis", "vuln_scanner"}

    def test_get_dependents(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("security_audit", deps=["repo_analysis"]))
        graph.add_capability(_make_cap("repo_analysis"))

        dependents = graph.get_dependents("repo_analysis")
        assert "security_audit" in dependents

    def test_transitive_dependents(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("c", deps=["b"]))
        graph.add_capability(_make_cap("b", deps=["a"]))
        graph.add_capability(_make_cap("a"))

        transitive = graph.get_transitive_dependents("a")
        assert set(transitive) == {"b", "c"}

    def test_impact_analysis(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("npm_api"))
        graph.add_capability(_make_cap("dependency_analysis", deps=["npm_api"]))
        graph.add_capability(_make_cap("security_audit", deps=["dependency_analysis"]))

        report = graph.impact_analysis("npm_api")
        assert "dependency_analysis" in report.directly_affected
        assert "security_audit" in report.transitively_affected
        assert report.total_impact_count == 2

    def test_remove_capability(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("a"))
        graph.add_capability(_make_cap("b", deps=["a"]))

        graph.remove_capability("a")
        assert graph.get_node("a") is None
        assert graph.get_dependencies("b") == []

    def test_no_cycle(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("a"))
        graph.add_capability(_make_cap("b", deps=["a"]))
        graph.add_capability(_make_cap("c", deps=["b"]))
        assert graph.has_cycle() is False

    def test_empty_graph_impact(self):
        graph = CapabilityGraph()
        report = graph.impact_analysis("nonexistent")
        assert report.total_impact_count == 0

    def test_get_all_nodes(self):
        graph = CapabilityGraph()
        graph.add_capability(_make_cap("x"))
        graph.add_capability(_make_cap("y"))
        assert len(graph.get_all_nodes()) == 2
