"""CapForge Task Analyzer & Decomposition Engine.

Deconstructs natural language tasks into atomic capability requirements,
identifying required tool primitives, domain categories, and workflow stages.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class DecomposedTask(BaseModel):
    original_task: str
    primary_domain: str
    target_service_or_entity: str
    required_primitives: list[str] = Field(default_factory=list)
    action_verbs: list[str] = Field(default_factory=list)


class TaskAnalyzer:
    """Analyzes user intent and extracts necessary capability primitives."""

    DOMAIN_KEYWORDS = {
        "security": ["vulnerability", "audit", "cve", "auth", "token", "credential", "security", "leak"],
        "data_analysis": ["telemetry", "metrics", "analytics", "anomaly", "timeseries", "dataset", "statistics"],
        "quantitative_finance": [
            "var",
            "value_at_risk",
            "risk",
            "drawdown",
            "volatility",
            "portfolio",
            "returns",
            "expected_shortfall",
            "cvar",
            "sharpe",
            "tail",
            "shortfall",
            "monte_carlo",
        ],
        "mathematics": ["calculate", "compute", "matrix", "optimization", "regression", "simulation", "percentile"],
        "api_integration": ["api", "rest", "endpoint", "openapi", "graphql", "client", "request", "webhook"],
        "software_engineering": ["dependency", "repository", "git", "github", "build", "package", "refactor"],
    }

    PRIMITIVE_RULES = [
        (r"(bearer|api key|oauth|token|auth)", "auth_handler"),
        (r"(paginate|pagination|cursor|page)", "cursor_pagination"),
        (r"(retry|rate limit|backoff|throttle)", "rate_limit_retry"),
        (r"(parse|extract|schema|json)", "json_schema_parser"),
        (r"(anomaly|threshold|spike|outlier)", "anomaly_detector"),
        (r"(telemetry|metrics|timeseries)", "telemetry_processor"),
        (r"(vulnerability|cve|outdated|audit)", "vulnerability_auditor"),
        (r"(git|github|commit|repo)", "git_repository_inspector"),
        (r"(value_at_risk|var|cvar|expected_shortfall|tail_risk)", "calculate_value_at_risk"),
        (r"(volatility|std_dev|variance)", "calculate_volatility"),
        (r"(drawdown|max_drawdown)", "calculate_max_drawdown"),
        (r"(log_returns|returns_calculator)", "calculate_log_returns"),
        (r"(monte_carlo|stochastic_simulation)", "monte_carlo_simulator"),
    ]

    def analyze(self, task_intent: str) -> DecomposedTask:
        """Deconstruct task prompt into domain, entity, and requisite primitives."""
        text_lower = task_intent.lower()

        # 1. Determine primary domain
        scores = {}
        for domain, kw_list in self.DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in kw_list if kw in text_lower)
        primary_domain = max(scores, key=scores.get) if any(scores.values()) else "general"

        # 2. Extract action verbs
        words = re.findall(r"\b[a-z]{3,}\b", text_lower)
        action_verbs = [
            w
            for w in words
            if w in {
                "analyze",
                "fetch",
                "extract",
                "audit",
                "monitor",
                "query",
                "build",
                "parse",
                "detect",
                "validate",
                "calculate",
                "compute",
                "simulate",
                "estimate",
            }
        ]

        # 3. Detect target entity or service name (e.g., "QuantumMetrics API", "GitHub")
        service_match = re.search(
            r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\s*(?:api|service|platform|repo)", task_intent
        )
        raw_service = service_match.group(1) if service_match else "generic_service"
        # Strip leading action verbs if inadvertently captured
        tokens = [
            t
            for t in raw_service.split()
            if t.lower() not in {"query", "analyze", "fetch", "extract", "get", "audit", "run", "calculate"}
        ]
        service_name = " ".join(tokens) if tokens else "generic_service"

        # 4. Map required primitives
        primitives: list[str] = []
        for pattern, prim_name in self.PRIMITIVE_RULES:
            if re.search(pattern, text_lower):
                if prim_name not in primitives:
                    primitives.append(prim_name)

        # 5. Direct identifier detection: If intent looks like an atomic identifier (e.g. calculate_value_at_risk)
        clean_identifier = re.sub(r"[^a-z0-9_]+", "", text_lower.replace("-", "_"))
        if "_" in clean_identifier and clean_identifier not in primitives:
            primitives.append(clean_identifier)

        # Ensure general API or execution primitives exist if none matched
        if not primitives:
            if primary_domain == "api_integration":
                primitives.append("http_request_handler")
                primitives.append("response_parser")
                slug = re.sub(r"[^a-z0-9]+", "_", f"{service_name}_{primary_domain}").strip("_").lower()
                if slug not in primitives:
                    primitives.append(slug)
            else:
                slug = re.sub(r"[^a-z0-9]+", "_", task_intent).strip("_").lower()
                if slug not in primitives:
                    primitives.append(slug)

        return DecomposedTask(
            original_task=task_intent,
            primary_domain=primary_domain,
            target_service_or_entity=service_name,
            required_primitives=primitives,
            action_verbs=action_verbs,
        )
