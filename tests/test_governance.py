"""Unit tests for the Risk Engine and Capability Firewall."""

from capforge.core.governance import CapabilityFirewall, RiskEngine
from capforge.core.models import (
    Capability,
    CapabilityStatus,
    ExecutionRequest,
    Provenance,
    RiskLevel,
    ToolPermissions,
    ToolRequirement,
)


def _make_capability(**overrides) -> Capability:
    defaults = dict(
        id="test_cap",
        name="Test Capability",
        description="A test capability",
        code_body="def execute(inputs): return {'status': 'OK'}",
    )
    defaults.update(overrides)
    return Capability(**defaults)


class TestRiskEngine:
    def test_low_risk_default_permissions(self):
        engine = RiskEngine()
        cap = _make_capability()
        assessment = engine.assess(cap)
        assert assessment.risk_level == RiskLevel.LOW
        assert assessment.auto_promote_allowed is True
        assert assessment.requires_human_approval is False

    def test_medium_risk_with_network(self):
        engine = RiskEngine()
        cap = _make_capability(
            permissions=ToolPermissions(network="full", filesystem="read"),
        )
        assessment = engine.assess(cap)
        assert assessment.risk_level == RiskLevel.MEDIUM
        assert assessment.auto_promote_allowed is False

    def test_high_risk_with_write_permissions(self):
        engine = RiskEngine()
        cap = _make_capability(
            permissions=ToolPermissions(
                filesystem="write",
                network="full",
                database="write",
            ),
        )
        assessment = engine.assess(cap)
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_human_approval is True

    def test_low_trust_provenance_increases_risk(self):
        engine = RiskEngine()
        cap = _make_capability(
            provenance=Provenance(trust_level=0.3, source="web"),
        )
        assessment = engine.assess(cap)
        # Low trust adds 0.15 to score
        assert assessment.risk_score >= 0.15
        assert "low_trust_provenance" in assessment.factors[0]

    def test_tool_network_permission_increases_risk(self):
        engine = RiskEngine()
        cap = _make_capability(
            tools_required=[
                ToolRequirement(name="http_tool", permissions=["network"]),
            ],
        )
        assessment = engine.assess(cap)
        assert any("network" in f for f in assessment.factors)


class TestCapabilityFirewall:
    def test_allows_active_low_risk(self):
        fw = CapabilityFirewall()
        cap = _make_capability(status=CapabilityStatus.ACTIVE)
        req = ExecutionRequest(capability_id="test_cap", inputs={})
        decision = fw.check(cap, req)
        assert decision.allowed is True

    def test_blocks_quarantined(self):
        fw = CapabilityFirewall()
        cap = _make_capability(status=CapabilityStatus.QUARANTINED)
        req = ExecutionRequest(capability_id="test_cap", inputs={})
        decision = fw.check(cap, req)
        assert decision.allowed is False
        assert "QUARANTINED" in decision.blocked_reason

    def test_blocks_deprecated(self):
        fw = CapabilityFirewall()
        cap = _make_capability(status=CapabilityStatus.DEPRECATED)
        req = ExecutionRequest(capability_id="test_cap", inputs={})
        decision = fw.check(cap, req)
        assert decision.allowed is False

    def test_blocks_explicit_blocklist(self):
        fw = CapabilityFirewall(blocked_capabilities={"dangerous_cap"})
        cap = _make_capability(id="dangerous_cap", status=CapabilityStatus.ACTIVE)
        req = ExecutionRequest(capability_id="dangerous_cap", inputs={})
        decision = fw.check(cap, req)
        assert decision.allowed is False
        assert "block list" in decision.blocked_reason

    def test_blocks_exceeding_max_risk(self):
        fw = CapabilityFirewall(max_risk_level=RiskLevel.LOW)
        cap = _make_capability(
            status=CapabilityStatus.ACTIVE,
            permissions=ToolPermissions(filesystem="write", network="full", database="write"),
        )
        req = ExecutionRequest(capability_id="test_cap", inputs={})
        decision = fw.check(cap, req)
        assert decision.allowed is False
        assert "exceeds" in decision.blocked_reason

    def test_ast_prohibited_eval_escalation(self):
        engine = RiskEngine()
        cap = _make_capability(
            code_body="def execute(inputs): return eval(inputs.get('expr', '1+1'))",
            permissions=ToolPermissions(filesystem="none", network="none"),
        )
        assessment = engine.assess(cap)
        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_human_approval is True
        assert assessment.auto_promote_allowed is False
        assert any("eval" in f for f in assessment.factors)
        assert len(engine.review_tickets) == 1
        assert engine.review_tickets[0].capability_id == cap.id

    def test_ast_undeclared_network_import(self):
        engine = RiskEngine()
        cap = _make_capability(
            code_body="def execute(inputs): import socket; return {'ip': '127.0.0.1'}",
            permissions=ToolPermissions(network="none"),
        )
        assessment = engine.assess(cap)
        assert assessment.risk_level == RiskLevel.HIGH
        assert any("unauthorized network module" in f for f in assessment.factors)

    def test_firewall_blocks_prohibited_ast_construct(self):
        fw = CapabilityFirewall()
        cap = _make_capability(
            status=CapabilityStatus.ACTIVE,
            code_body="def execute(inputs): import subprocess; subprocess.run(['ls'])",
        )
        req = ExecutionRequest(capability_id="test_cap", inputs={})
        decision = fw.check(cap, req)
        assert decision.allowed is False
        assert "AST" in decision.blocked_reason or "prohibited" in decision.blocked_reason
