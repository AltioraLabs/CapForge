"""Tests for CapForge Human Governance Review Lifecycle (v0.5.0)."""

from capforge.core.governance import RiskEngine
from capforge.core.models import Capability, RiskLevel, ToolPermissions


def test_ticket_approval_and_rejection_lifecycle():
    engine = RiskEngine()

    # Create high-risk capability that triggers review ticket
    cap = Capability(
        id="critical_db_migration",
        name="Critical DB Migration",
        description="Alters production database schemas",
        permissions=ToolPermissions(database="write", filesystem="write"),
        code_body="def execute(inputs): return {'status': 'OK'}",
    )
    assessment = engine.assess(cap)
    assert assessment.risk_level == RiskLevel.HIGH
    assert len(engine.review_tickets) == 1

    ticket = engine.review_tickets[0]
    assert ticket.status == "PENDING"
    assert ticket.reviewed_by is None

    # Approve ticket
    approved = engine.approve_ticket(
        ticket.ticket_id,
        reviewer="secops_admin",
        notes="Validated schema migration safety constraints",
    )
    assert approved.status == "APPROVED"
    assert approved.reviewed_by == "secops_admin"
    assert approved.resolved_at is not None

    # Test filtering
    assert len(engine.list_tickets(status="APPROVED")) == 1
    assert len(engine.list_tickets(status="PENDING")) == 0


def test_ticket_rejection():
    engine = RiskEngine()
    cap = Capability(
        id="unauthorized_eval_worker",
        name="Eval Worker",
        description="Calls eval on input strings",
        code_body="def execute(inputs): return eval(inputs['code'])",
    )
    engine.assess(cap)
    ticket = engine.review_tickets[0]

    rejected = engine.reject_ticket(
        ticket.ticket_id,
        reviewer="ciso",
        notes="Dynamic eval is strictly prohibited.",
    )
    assert rejected.status == "REJECTED"
    assert rejected.reviewed_by == "ciso"
    assert len(engine.list_tickets(status="REJECTED")) == 1
