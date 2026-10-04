"""CapForge Domain Capability Seeds.

Pre-warms the Capability Registry with production-grade baseline capabilities
across critical enterprise domains: finance, devops, nlp, and data.
Eliminates cold-start latency for common agent workflows.
"""

from __future__ import annotations

import logging
from typing import Any

from capforge.core.models import (
    Capability,
    CapabilityStatus,
    CapabilityType,
    ParameterSpec,
    TestCase,
    TestType,
    ToolPermissions,
)
from capforge.registry.store import CapabilityRegistry

logger = logging.getLogger("capforge.seed")


# ---------------------------------------------------------------------------
# Domain Capability Catalogs
# ---------------------------------------------------------------------------

FINANCE_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "calculate_value_at_risk",
        "name": "Calculate Value-at-Risk",
        "description": "Computes historical or parametric Value-at-Risk (VaR) for a series of returns.",
        "domain": "finance",
        "code_body": (
            "def execute(returns: list = None, confidence: float = 0.95, **kw) -> dict:\n"
            "    data = returns if returns is not None else [0.01, -0.02, 0.015, -0.005, 0.03, -0.01]\n"
            "    if not data:\n"
            "        return {'var': 0.0, 'status': 'empty_data', 'result': 0.0}\n"
            "    sorted_data = sorted(float(x) for x in data)\n"
            "    idx = int((1.0 - float(confidence)) * len(sorted_data))\n"
            "    var_val = abs(sorted_data[min(idx, len(sorted_data) - 1)])\n"
            "    return {'var': round(var_val, 6), 'confidence': confidence, 'status': 'ok', 'result': round(var_val, 6)}\n"
        ),
        "inputs": {
            "returns": ParameterSpec(name="returns", type="list", description="Series of asset returns", required=False, default=[]),
            "confidence": ParameterSpec(name="confidence", type="number", description="Confidence level (e.g. 0.95, 0.99)", required=False, default=0.95),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="number", description="Calculated Value-at-Risk"),
            "var": ParameterSpec(name="var", type="number", description="Calculated Value-at-Risk"),
        },
        "tests": [
            TestCase(
                id="test_var_happy",
                name="Historical VaR standard inputs",
                test_type=TestType.HAPPY_PATH,
                inputs={"returns": [0.05, -0.02, 0.01, -0.04, 0.02], "confidence": 0.95},
                assert_expression="'result' in output and output['status'] == 'ok'",
            ),
            TestCase(
                id="test_var_boundary",
                name="Historical VaR empty returns",
                test_type=TestType.EDGE_CASE,
                inputs={"returns": []},
                assert_expression="'result' in output",
            ),
        ],
    },
    {
        "id": "calculate_volatility",
        "name": "Calculate Annualized Volatility",
        "description": "Calculates sample standard deviation of asset returns annualized by standard trading days (252).",
        "domain": "finance",
        "code_body": (
            "import math\n\n"
            "def execute(returns: list = None, trading_days: int = 252, **kw) -> dict:\n"
            "    data = returns if returns is not None else [0.01, -0.01, 0.02, -0.02, 0.015]\n"
            "    if len(data) < 2:\n"
            "        return {'volatility': 0.0, 'annualized_volatility': 0.0, 'status': 'insufficient_data', 'result': 0.0}\n"
            "    mean = sum(data) / len(data)\n"
            "    variance = sum((x - mean) ** 2 for x in data) / (len(data) - 1)\n"
            "    daily_vol = math.sqrt(variance)\n"
            "    annual_vol = daily_vol * math.sqrt(trading_days)\n"
            "    return {'volatility': round(daily_vol, 6), 'annualized_volatility': round(annual_vol, 6), 'status': 'ok', 'result': round(annual_vol, 6)}\n"
        ),
        "inputs": {
            "returns": ParameterSpec(name="returns", type="list", description="Daily return observations", required=False, default=[]),
            "trading_days": ParameterSpec(name="trading_days", type="integer", description="Annualization factor", required=False, default=252),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="number", description="Annualized volatility percentage"),
        },
        "tests": [
            TestCase(
                id="test_vol_happy",
                name="Volatility calculation happy path",
                test_type=TestType.HAPPY_PATH,
                inputs={"returns": [0.01, -0.01, 0.02, -0.02]},
                assert_expression="output['result'] > 0 and output['status'] == 'ok'",
            ),
        ],
    },
    {
        "id": "calculate_max_drawdown",
        "name": "Calculate Maximum Drawdown",
        "description": "Calculates the maximum peak-to-trough drop in a cumulative portfolio value series.",
        "domain": "finance",
        "code_body": (
            "def execute(prices: list = None, **kw) -> dict:\n"
            "    data = prices if prices is not None else [100.0, 105.0, 95.0, 110.0, 90.0, 115.0]\n"
            "    if len(data) < 2:\n"
            "        return {'max_drawdown': 0.0, 'status': 'insufficient_data', 'result': 0.0}\n"
            "    max_dd = 0.0\n"
            "    peak = data[0]\n"
            "    for p in data:\n"
            "        if p > peak:\n"
            "            peak = p\n"
            "        dd = (peak - p) / peak if peak > 0 else 0.0\n"
            "        if dd > max_dd:\n"
            "            max_dd = dd\n"
            "    return {'max_drawdown': round(max_dd, 6), 'status': 'ok', 'result': round(max_dd, 6)}\n"
        ),
        "inputs": {
            "prices": ParameterSpec(name="prices", type="list", description="Time series of asset or portfolio prices", required=False, default=[]),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="number", description="Maximum observed drawdown (0.0 to 1.0)"),
        },
        "tests": [
            TestCase(
                id="test_dd_happy",
                name="Max drawdown happy path",
                test_type=TestType.HAPPY_PATH,
                inputs={"prices": [100.0, 120.0, 90.0, 110.0]},
                assert_expression="output['result'] == 0.25",
            ),
        ],
    },
]

DEVOPS_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "git_commit_analyzer",
        "name": "Git Commit Message Analyzer",
        "description": "Validates Conventional Commit compliance (feat, fix, docs, refactor, chore) and extracts metadata.",
        "domain": "devops",
        "code_body": (
            "import re\n\n"
            "def execute(message: str = '', **kw) -> dict:\n"
            "    pattern = r'^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\\([\\w\\-]+\\))?: (.+)$'\n"
            "    match = re.match(pattern, message.strip())\n"
            "    if not match:\n"
            "        return {'valid': False, 'type': None, 'scope': None, 'description': message, 'status': 'invalid_format', 'result': False}\n"
            "    commit_type = match.group(1)\n"
            "    scope = match.group(2).strip('()') if match.group(2) else None\n"
            "    desc = match.group(3)\n"
            "    return {'valid': True, 'type': commit_type, 'scope': scope, 'description': desc, 'status': 'ok', 'result': True}\n"
        ),
        "inputs": {
            "message": ParameterSpec(name="message", type="string", description="Git commit message string", required=False, default="feat: initial commit"),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="boolean", description="Whether message conforms to Conventional Commits"),
        },
        "tests": [
            TestCase(
                id="test_commit_valid",
                name="Valid conventional commit",
                test_type=TestType.HAPPY_PATH,
                inputs={"message": "fix(core): resolve null pointer in parser"},
                assert_expression="output['result'] is True and output['type'] == 'fix'",
            ),
        ],
    },
    {
        "id": "dockerfile_linter",
        "name": "Dockerfile Security Linter",
        "description": "Inspects Dockerfile source for common anti-patterns (root execution, unpinned 'latest' tags, curl piping).",
        "domain": "devops",
        "code_body": (
            "def execute(content: str = '', **kw) -> dict:\n"
            "    issues = []\n"
            "    lines = content.splitlines()\n"
            "    has_user = any(line.strip().upper().startswith('USER ') for line in lines)\n"
            "    if not has_user:\n"
            "        issues.append('Missing non-root USER instruction')\n"
            "    for i, line in enumerate(lines, 1):\n"
            "        if line.strip().upper().startswith('FROM ') and ':latest' in line:\n"
            "            issues.append(f'Unpinned latest tag at line {i}')\n"
            "        if 'curl ' in line and '| sh' in line:\n"
            "            issues.append(f'Dangerous curl piping to shell at line {i}')\n"
            "    passed = len(issues) == 0\n"
            "    return {'passed': passed, 'issues': issues, 'issue_count': len(issues), 'status': 'ok', 'result': passed}\n"
        ),
        "inputs": {
            "content": ParameterSpec(name="content", type="string", description="Dockerfile text content", required=False, default="FROM python:3.11\nCMD ['python']"),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="boolean", description="Whether Dockerfile passed all security checks"),
        },
        "tests": [
            TestCase(
                id="test_docker_lint",
                name="Dockerfile lint test",
                test_type=TestType.HAPPY_PATH,
                inputs={"content": "FROM alpine:3.18\nUSER appuser\nCMD ['sh']"},
                assert_expression="output['result'] is True",
            ),
        ],
    },
]

NLP_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "token_counter",
        "name": "Token & Cost Estimator",
        "description": "Estimates token counts using whitespace and character heuristics and calculates inference cost.",
        "domain": "nlp",
        "code_body": (
            "def execute(text: str = '', cost_per_million: float = 0.50, **kw) -> dict:\n"
            "    words = text.split()\n"
            "    # Standard heuristic: ~1.3 tokens per word or ~4 chars per token\n"
            "    est_tokens = max(1, int(len(words) * 1.33)) if text else 0\n"
            "    cost_usd = (est_tokens / 1_000_000.0) * float(cost_per_million)\n"
            "    return {'token_count': est_tokens, 'word_count': len(words), 'estimated_cost_usd': round(cost_usd, 6), 'status': 'ok', 'result': est_tokens}\n"
        ),
        "inputs": {
            "text": ParameterSpec(name="text", type="string", description="Input text to measure", required=False, default=""),
            "cost_per_million": ParameterSpec(name="cost_per_million", type="number", description="Cost per million tokens USD", required=False, default=0.50),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="integer", description="Estimated token count"),
        },
        "tests": [
            TestCase(
                id="test_token_happy",
                name="Token estimation happy path",
                test_type=TestType.HAPPY_PATH,
                inputs={"text": "The quick brown fox jumps over the lazy dog."},
                assert_expression="output['result'] > 0 and 'estimated_cost_usd' in output",
            ),
        ],
    },
    {
        "id": "keyword_extractor",
        "name": "Keyphrase & Term Frequency Extractor",
        "description": "Extracts prominent keywords and n-gram terms filtering common English stop words.",
        "domain": "nlp",
        "code_body": (
            "def execute(text: str = '', top_k: int = 5, **kw) -> dict:\n"
            "    stopwords = {'the', 'a', 'an', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'is', 'it', 'this'}\n"
            "    words = [w.strip('.,!?;:\"\\'()[]{}').lower() for w in text.split()]\n"
            "    filtered = [w for w in words if w and w not in stopwords and len(w) > 2]\n"
            "    counts = {}\n"
            "    for w in filtered:\n"
            "        counts[w] = counts.get(w, 0) + 1\n"
            "    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_k]\n"
            "    keywords = [k for k, _ in ranked]\n"
            "    return {'keywords': keywords, 'frequencies': dict(ranked), 'status': 'ok', 'result': keywords}\n"
        ),
        "inputs": {
            "text": ParameterSpec(name="text", type="string", description="Input text document", required=False, default=""),
            "top_k": ParameterSpec(name="top_k", type="integer", description="Max keywords to return", required=False, default=5),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="array", description="List of top extracted keywords"),
        },
        "tests": [
            TestCase(
                id="test_kw_happy",
                name="Keyword extraction happy path",
                test_type=TestType.HAPPY_PATH,
                inputs={"text": "Machine learning systems and reinforcement learning algorithms.", "top_k": 3},
                assert_expression="'learning' in output['result']",
            ),
        ],
    },
]

DATA_CAPABILITIES: list[dict[str, Any]] = [
    {
        "id": "outlier_detector_zscore",
        "name": "Z-Score Anomaly Detector",
        "description": "Identifies numeric data points exceeding a standard deviation threshold (Z-Score).",
        "domain": "data",
        "code_body": (
            "import math\n\n"
            "def execute(values: list = None, threshold: float = 3.0, **kw) -> dict:\n"
            "    data = values if values is not None else [10.0, 10.5, 9.8, 10.2, 50.0, 10.1]\n"
            "    if len(data) < 3:\n"
            "        return {'outliers': [], 'outlier_count': 0, 'status': 'insufficient_data', 'result': []}\n"
            "    mean = sum(data) / len(data)\n"
            "    variance = sum((x - mean) ** 2 for x in data) / len(data)\n"
            "    std_dev = math.sqrt(variance)\n"
            "    outliers = []\n"
            "    if std_dev > 0:\n"
            "        for idx, val in enumerate(data):\n"
            "            z = abs(val - mean) / std_dev\n"
            "            if z >= threshold:\n"
            "                outliers.append({'index': idx, 'value': val, 'z_score': round(z, 2)})\n"
            "    return {'outliers': outliers, 'outlier_count': len(outliers), 'status': 'ok', 'result': [o['value'] for o in outliers]}\n"
        ),
        "inputs": {
            "values": ParameterSpec(name="values", type="list", description="Series of numeric values to inspect", required=False, default=[]),
            "threshold": ParameterSpec(name="threshold", type="number", description="Z-Score standard deviation threshold", required=False, default=3.0),
        },
        "outputs": {
            "result": ParameterSpec(name="result", type="array", description="List of outlier values"),
        },
        "tests": [
            TestCase(
                id="test_outlier_happy",
                name="Z-score outlier detection",
                test_type=TestType.HAPPY_PATH,
                inputs={"values": [1.0, 1.1, 1.2, 1.0, 100.0, 1.1], "threshold": 2.0},
                assert_expression="100.0 in output['result']",
            ),
        ],
    },
]

DOMAIN_MAP: dict[str, list[dict[str, Any]]] = {
    "finance": FINANCE_CAPABILITIES,
    "devops": DEVOPS_CAPABILITIES,
    "nlp": NLP_CAPABILITIES,
    "data": DATA_CAPABILITIES,
}


# ---------------------------------------------------------------------------
# Seeding Functions
# ---------------------------------------------------------------------------


def get_available_domains() -> list[str]:
    """Return all supported seed domain names."""
    return list(DOMAIN_MAP.keys())


def seed_domain(
    domain: str,
    registry: CapabilityRegistry | None = None,
) -> list[Capability]:
    """Seed capabilities for a specific domain or 'all' into the Capability Registry.

    Returns the list of registered Capability objects.
    """
    reg = registry or CapabilityRegistry()
    target_domains = get_available_domains() if domain.lower() in ("all", "*") else [domain.lower()]

    seeded: list[Capability] = []

    for d in target_domains:
        catalogs = DOMAIN_MAP.get(d)
        if not catalogs:
            logger.warning("No seed definitions found for domain '%s'", d)
            continue

        for item in catalogs:
            cap = Capability(
                id=item["id"],
                name=item["name"],
                description=item["description"],
                domain=item["domain"],
                code_body=item["code_body"],
                entrypoint_function="execute",
                inputs=item.get("inputs", {}),
                outputs=item.get("outputs", {}),
                verification_tests=item.get("tests", []),
                permissions=ToolPermissions(),
                status=CapabilityStatus.ACTIVE,
                capability_type=CapabilityType.TOOL,
            )
            reg.register(cap)
            seeded.append(cap)
            logger.info("Seeded capability '%s' into domain '%s'", cap.id, cap.domain)

    return seeded
