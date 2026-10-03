"""CapForge Capability Synthesizer.

Converts acquired API specifications, documentation schemas, or procedure traces
into a validated, executable Capability object with tests and parameter schemas.

Synthesis Backends (in priority order):
1. Gemini API (CAPFORGE_LLM_PROVIDER=gemini, GEMINI_API_KEY set) — real code generation
2. OpenAI API (CAPFORGE_LLM_PROVIDER=openai, OPENAI_API_KEY set) — real code generation
3. Template fallback — deterministic, structured boilerplate (always available)
"""

from __future__ import annotations

import ast
import logging
import re
import textwrap
from typing import Any

from capforge.core.models import (
    Capability,
    CapabilityStatus,
    ExecutionMode,
    ParameterSpec,
    TestCase,
    TestType,
    ToolRequirement,
)

logger = logging.getLogger("capforge.synthesizer")


# ---------------------------------------------------------------------------
# LLM Synthesis Prompt Template
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM_PROMPT = """\
You are CapForge's Code Synthesis Engine. Your job is to write a single Python function
that implements a requested capability for an AI agent.

RULES (strictly follow all of them):
1. Output ONLY raw Python code — no markdown fences, no explanations, no comments outside code.
2. The function MUST be named `execute` and accept a single argument `inputs: dict`.
3. The function MUST return a dict with at minimum: `{"status": "SUCCESS"|"FAILED", "result": ...}`.
4. Handle ALL exceptions internally — never let the function raise an unhandled exception.
5. If required inputs are missing, return `{"status": "FAILED", "error": "MISSING_INPUT: <param>"}`.
6. Use only Python standard library unless the task explicitly requires an external library.
7. All network calls must use `httpx` (not `requests`). Set timeout to 10 seconds.
8. The code must be self-contained — no global state, no side effects outside the function.
9. Be concise and production-quality. No placeholder logic.
"""

_SYNTHESIS_USER_PROMPT = """\
Write a Python `execute(inputs: dict) -> dict` function that implements:

TASK: {task_intent}

AVAILABLE INPUTS: {inputs_description}
EXPECTED OUTPUT FIELDS: status (str), result (any)

Output only the Python function. Start with `def execute(inputs: dict) -> dict:`.
"""

_TEST_GENERATION_PROMPT = """\
Given this Python capability function:

```python
{code_body}
```

Generate 3 pytest-style test cases as a JSON array. Each object must have:
- "id": unique snake_case string
- "name": human-readable description
- "test_type": one of "HAPPY_PATH", "EDGE_CASE", "INVARIANT"
- "inputs": dict of inputs to pass
- "assert_expression": Python expression using `output` variable that must be True
- "expected_keys": list of keys that must exist in output dict

Output only valid JSON. No markdown, no explanation.
"""


# ---------------------------------------------------------------------------
# LLM Backend Implementations
# ---------------------------------------------------------------------------


def _synthesize_with_gemini(task_intent: str, api_key: str, model: str, temperature: float) -> str | None:
    """Call Gemini API to synthesize capability code. Returns raw Python code string or None."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        client = genai.GenerativeModel(
            model_name=model,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=4096,
            ),
            system_instruction=_SYNTHESIS_SYSTEM_PROMPT,
        )
        prompt = _SYNTHESIS_USER_PROMPT.format(
            task_intent=task_intent,
            inputs_description="passed as dict, use inputs.get('key', default) for all access",
        )
        response = client.generate_content(prompt)
        raw = response.text.strip()
        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:python)?\s*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
        return raw.strip()
    except Exception as e:
        logger.warning("Gemini synthesis failed: %s", e)
        return None


def _synthesize_with_openai(task_intent: str, api_key: str, model: str, temperature: float) -> str | None:
    """Call OpenAI API to synthesize capability code. Returns raw Python code string or None."""
    try:
        import httpx

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model or "gpt-4o-mini",
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _SYNTHESIS_USER_PROMPT.format(
                        task_intent=task_intent,
                        inputs_description="passed as dict",
                    ),
                },
            ],
            "max_tokens": 4096,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(?:python)?\s*\n?", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\n?```\s*$", "", raw, flags=re.MULTILINE)
            return raw.strip()
    except Exception as e:
        logger.warning("OpenAI synthesis failed: %s", e)
        return None


def _validate_synthesized_code(code: str, expected_function: str = "execute") -> tuple[bool, str]:
    """Validate that synthesized code is syntactically valid and contains the required entrypoint."""
    if not code or not code.strip():
        return False, "Empty code body"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    found = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == expected_function
        for node in ast.walk(tree)
    )
    if not found:
        return False, f"Function '{expected_function}' not found in synthesized code"
    return True, ""


def _build_template_code(task_intent: str, capability_id: str) -> str:
    """Build a structured template capability when no LLM is available."""
    return textwrap.dedent(f'''\
        """Synthesized Capability: {capability_id.replace("_", " ").title()}

        Task: {task_intent}

        NOTE: This capability was generated using the template fallback synthesizer.
        Configure CAPFORGE_LLM_PROVIDER and the corresponding API key for real
        LLM-powered code generation that implements the actual task logic.
        """

        def execute(inputs: dict) -> dict:
            """Execute synthesized capability for: {task_intent}"""
            try:
                payload = inputs.get("payload", {{}})
                mode = inputs.get("mode", "default")
                return {{
                    "status": "SUCCESS",
                    "result": "Template execution for: {task_intent}",
                    "processed_keys": list(payload.keys()) if isinstance(payload, dict) else [],
                    "mode": mode,
                    "note": "Configure LLM provider for real implementation.",
                }}
            except Exception as e:
                return {{"status": "FAILED", "error": str(e)}}
        ''')


# ---------------------------------------------------------------------------
# Main Synthesizer Class
# ---------------------------------------------------------------------------


class CapabilitySynthesizer:
    """Synthesizes structured, testable Capability objects using LLM or template fallback."""

    def __init__(self):
        from capforge.core.config import settings

        self.settings = settings
        self._log_backend()

    def _log_backend(self) -> None:
        if self.settings.llm_configured:
            logger.info(
                "Capability synthesizer using LLM backend: provider=%s model=%s",
                self.settings.llm_provider,
                self.settings.llm_model,
            )
        else:
            logger.warning(
                "LLM not configured (CAPFORGE_LLM_PROVIDER=%s). "
                "Synthesis will use template fallback. Set GEMINI_API_KEY for real code generation.",
                self.settings.llm_provider,
            )

    def synthesize_from_intent(self, task_intent: str, target_id: str | None = None) -> Capability:
        """Synthesize a candidate capability from a natural language task intent.

        Attempts real LLM synthesis first; falls back to template on failure.
        """
        if not target_id:
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", task_intent.lower()).strip("_")
            target_id = slug[:40] if slug else "synthesized_capability"

        name = target_id.replace("_", " ").title()
        description = f"Autonomous capability forged to address: {task_intent}"

        # --- Attempt LLM synthesis ---
        code_body = None
        synthesis_method = "template"

        if self.settings.llm_configured:
            if self.settings.llm_provider == "gemini" and self.settings.gemini_api_key:
                code_body = _synthesize_with_gemini(
                    task_intent,
                    self.settings.gemini_api_key,
                    self.settings.llm_model,
                    self.settings.llm_synthesis_temperature,
                )
                if code_body:
                    valid, err = _validate_synthesized_code(code_body)
                    if not valid:
                        logger.warning("Gemini code invalid (%s), falling back to template", err)
                        code_body = None
                    else:
                        synthesis_method = "gemini"

            elif self.settings.llm_provider == "openai" and self.settings.openai_api_key:
                code_body = _synthesize_with_openai(
                    task_intent,
                    self.settings.openai_api_key,
                    self.settings.llm_model,
                    self.settings.llm_synthesis_temperature,
                )
                if code_body:
                    valid, err = _validate_synthesized_code(code_body)
                    if not valid:
                        logger.warning("OpenAI code invalid (%s), falling back to template", err)
                        code_body = None
                    else:
                        synthesis_method = "openai"

        if not code_body:
            code_body = _build_template_code(task_intent, target_id)
            synthesis_method = "template"

        logger.info("Synthesized capability '%s' via %s backend", target_id, synthesis_method)

        return Capability(
            id=target_id,
            name=name,
            version="1.0.0",
            status=CapabilityStatus.EXPERIMENTAL,
            description=description,
            domain="general",
            tags=["synthesized", "autonomous", synthesis_method],
            inputs={
                "payload": ParameterSpec(
                    name="payload",
                    type="dict",
                    description="Target input data payload",
                    required=False,
                    default={},
                ),
                "mode": ParameterSpec(
                    name="mode",
                    type="string",
                    description="Execution mode",
                    required=False,
                    default="default",
                ),
            },
            outputs={
                "status": ParameterSpec(name="status", type="string", description="Execution status"),
                "result": ParameterSpec(name="result", type="string", description="Execution output"),
            },
            execution_mode=ExecutionMode.CODE,
            code_body=code_body,
            entrypoint_function="execute",
            verification_tests=[
                TestCase(
                    id=f"test_{target_id}_smoke",
                    name="Smoke execution — must not crash",
                    test_type=TestType.SMOKE,
                    inputs={"payload": {"test_key": "val"}},
                    expected_keys=["status"],
                    assert_expression="output['status'] in ('SUCCESS', 'FAILED')",
                ),
                TestCase(
                    id=f"test_{target_id}_empty_inputs",
                    name="Empty inputs must not crash",
                    test_type=TestType.EDGE_CASE,
                    inputs={},
                    assert_expression="output is not None and 'status' in output",
                ),
            ],
            changelog=f"Synthesized from task intent via {synthesis_method}: {task_intent}",
        )

    def synthesize_api_capability(
        self,
        capability_id: str,
        name: str,
        description: str,
        domain: str,
        base_url: str,
        endpoints: list[dict[str, Any]],
        auth_type: str = "Bearer",
        tags: list[str] | None = None,
        code_override: str | None = None,
    ) -> Capability:
        """Synthesize a complete capability for interacting with an API service."""
        tags = tags or ["api", "integration", domain]
        first_path = endpoints[0]["path"] if endpoints else "/"

        inputs = {
            "api_key": ParameterSpec(
                name="api_key",
                type="string",
                description="API key or token for authentication",
                required=True,
            ),
            "endpoint_path": ParameterSpec(
                name="endpoint_path",
                type="string",
                description="Relative API endpoint",
                required=False,
                default=first_path,
            ),
            "params": ParameterSpec(
                name="params",
                type="dict",
                description="Query parameters",
                required=False,
                default={},
            ),
        }

        outputs = {
            "status": ParameterSpec(name="status", type="string", description="Execution status"),
            "records": ParameterSpec(name="records", type="list", description="Fetched records"),
            "summary": ParameterSpec(name="summary", type="dict", description="Aggregated metrics"),
        }

        if code_override:
            code_body = code_override
        else:
            code_body = textwrap.dedent(f'''\
                import httpx

                def execute(inputs: dict) -> dict:
                    api_key = inputs.get("api_key")
                    if not api_key:
                        return {{"status": "FAILED", "error": "MISSING_API_KEY", "records": [], "summary": {{}}}}

                    base_url = "{base_url}".rstrip("/")
                    endpoint = inputs.get("endpoint_path", "{first_path}").lstrip("/")
                    url = f"{{base_url}}/{{endpoint}}"
                    params = inputs.get("params", {{}})
                    headers = {{"Authorization": f"Bearer {{api_key}}", "Accept": "application/json"}}

                    try:
                        with httpx.Client(timeout=10.0) as client:
                            resp = client.get(url, params=params, headers=headers)
                            if resp.status_code == 401:
                                return {{"status": "FAILED", "error": "UNAUTHORIZED", "records": [], "summary": {{}}}}
                            if resp.status_code == 429:
                                return {{"status": "FAILED", "error": "RATE_LIMITED", "records": [], "summary": {{}}}}
                            resp.raise_for_status()
                            data = resp.json()
                            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [data])
                            return {{
                                "status": "SUCCESS",
                                "records": items,
                                "summary": {{"count": len(items), "http_status": resp.status_code}},
                            }}
                    except httpx.TimeoutException:
                        return {{"status": "FAILED", "error": "TIMEOUT", "records": [], "summary": {{}}}}
                    except Exception as e:
                        return {{"status": "FAILED", "error": str(e), "records": [], "summary": {{}}}}
                ''')

        tests = [
            TestCase(
                id=f"test_{capability_id}_missing_key",
                name="Graceful failure on missing API key",
                test_type=TestType.EDGE_CASE,
                inputs={"api_key": "", "params": {}},
                assert_expression="output['status'] == 'FAILED' and output.get('error') == 'MISSING_API_KEY'",
            ),
            TestCase(
                id=f"test_{capability_id}_output_shape",
                name="Output schema invariant",
                test_type=TestType.INVARIANT,
                inputs={"api_key": "mock_token"},
                assert_expression="isinstance(output.get('records', None), list) or output['status'] == 'FAILED'",
            ),
        ]

        return Capability(
            id=capability_id,
            name=name,
            version="1.0.0",
            status=CapabilityStatus.EXPERIMENTAL,
            description=description,
            domain=domain,
            tags=tags,
            inputs=inputs,
            outputs=outputs,
            execution_mode=ExecutionMode.CODE,
            code_body=code_body,
            entrypoint_function="execute",
            verification_tests=tests,
            tools_required=[
                ToolRequirement(
                    name="httpx_network_egress",
                    description="Network access to query target API",
                    permissions=["network"],
                )
            ],
            changelog="API capability synthesized by CapForge Acquisition Engine.",
        )
