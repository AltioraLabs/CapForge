"""Tests for CapForge Seed Subsystem & Domain Pre-warming (Priority 4)."""


from capforge import CapForgeClient
from capforge.core.models import CapabilityStatus
from capforge.registry.store import CapabilityRegistry
from capforge.seed.domains import get_available_domains, seed_domain


def test_get_available_domains():
    """Verify that expected enterprise domains are available for seeding."""
    domains = get_available_domains()
    assert "finance" in domains
    assert "devops" in domains
    assert "nlp" in domains
    assert "data" in domains


def test_seed_domain_finance():
    """Verify seeding the finance domain registers all financial capabilities."""
    registry = CapabilityRegistry()
    seeded = seed_domain("finance", registry=registry)

    assert len(seeded) >= 3
    ids = [c.id for c in seeded]
    assert "calculate_value_at_risk" in ids
    assert "calculate_volatility" in ids
    assert "calculate_max_drawdown" in ids

    for c in seeded:
        assert c.domain == "finance"
        assert c.status == CapabilityStatus.ACTIVE
        retrieved = registry.get(c.id)
        assert retrieved is not None


def test_seed_domain_all():
    """Verify seeding 'all' registers capabilities across all domains."""
    registry = CapabilityRegistry()
    seeded = seed_domain("all", registry=registry)

    domains_present = {c.domain for c in seeded}
    assert "finance" in domains_present
    assert "devops" in domains_present
    assert "nlp" in domains_present
    assert "data" in domains_present
    assert len(seeded) >= 8


def test_execute_seeded_capabilities():
    """Verify that seeded capabilities execute successfully inside the CapForge sandbox."""
    with CapForgeClient() as client:
        seed_domain("all", registry=client.registry)

        # 1. Test finance: VaR
        res_var = client.execute("calculate_value_at_risk", {"returns": [0.02, -0.05, 0.01, -0.03, 0.04]})
        assert res_var.status == "SUCCESS"
        assert res_var.output is not None
        assert "var" in res_var.output

        # 2. Test devops: conventional commits
        res_git = client.execute("git_commit_analyzer", {"message": "feat(core): add async synthesis path"})
        assert res_git.status == "SUCCESS"
        assert res_git.output["result"] is True
        assert res_git.output["type"] == "feat"

        # 3. Test nlp: token estimator
        res_tokens = client.execute("token_counter", {"text": "CapForge accelerates enterprise AI capabilities."})
        assert res_tokens.status == "SUCCESS"
        assert res_tokens.output["token_count"] > 0

        # 4. Test data: z-score outliers
        res_data = client.execute("outlier_detector_zscore", {"values": [1.0, 1.1, 1.2, 100.0, 1.0], "threshold": 1.5})
        assert res_data.status == "SUCCESS"
        assert 100.0 in res_data.output["result"]
