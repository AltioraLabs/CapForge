"""Comprehensive test suite for Grammar Constrained Generation and OpenTelemetry in CapForge."""
import json
import tempfile
from pathlib import Path

from capforge.acquisition.grammar import (
    GBNF_PYTHON_CAPABILITY_GRAMMAR,
    GrammarConstrainedSynthesizer,
    build_capability_json_grammar,
)
from capforge.core.models import (
    Capability,
    TestCase,
    TestType,
)
from capforge.core.schemas import CapabilitySchema, FieldSchema
from capforge.core.telemetry import (
    GenAISemanticConventions,
    instrument_capability,
    record_llm_call,
    trace_manager,
)
from capforge.registry.store import get_artifact_store, get_registry_store
from capforge.verification.evaluator import CapabilityEvaluator


class TestGrammarConstrainedGeneration:
    """Verifies Grammar-Constrained Token Generation mechanics."""

    def test_gbnf_grammar_specification_structure(self):
        """GBNF grammar definition contains standard capability execution production rules."""
        assert "root ::=" in GBNF_PYTHON_CAPABILITY_GRAMMAR
        assert "def execute(inputs: dict) -> dict:" in GBNF_PYTHON_CAPABILITY_GRAMMAR
        assert "return_stmt ::=" in GBNF_PYTHON_CAPABILITY_GRAMMAR
        assert "dict_expr ::=" in GBNF_PYTHON_CAPABILITY_GRAMMAR

    def test_json_grammar_schema_generation(self):
        """JSON Schema grammar defines formal return contract for structured output."""
        schema = CapabilitySchema(
            capability_id="risk_var",
            version="1.1.0",
            output_fields=[
                FieldSchema(name="var_95_pct", field_type="float"),
                FieldSchema(name="monte_carlo_var_pct", field_type="float"),
            ],
        )
        json_grammar = build_capability_json_grammar(schema)
        assert json_grammar["type"] == "object"
        assert "status" in json_grammar["properties"]
        assert "var_95_pct" in json_grammar["properties"]
        assert json_grammar["properties"]["var_95_pct"]["type"] == "number"

    def test_markdown_fence_cleaning(self):
        """Strips conversational preamble, explanations, and markdown fences."""
        raw_llm_output = """Here is the Python implementation for calculating Value at Risk:

```python
import math

def execute(inputs: dict) -> dict:
    val = inputs.get("x", 0)
    return {"status": "SUCCESS", "val": val * 2}
```

Hope this helps! Let me know if you need modifications.
"""
        cleaned = GrammarConstrainedSynthesizer.clean_markdown_fences(raw_llm_output)
        assert not cleaned.startswith("Here is")
        assert not cleaned.endswith("Let me know")
        assert "def execute(inputs: dict) -> dict:" in cleaned
        assert not cleaned.startswith("```")
        assert not cleaned.endswith("```")

    def test_grammar_validation_accepts_valid_signature(self):
        """Accepts code conforming to def execute(inputs: dict) -> dict: returning a dict."""
        code = """
import math

def execute(inputs: dict) -> dict:
    x = inputs.get("val", 1.0)
    return {"status": "SUCCESS", "result": math.sqrt(x)}
"""
        res = GrammarConstrainedSynthesizer.validate_grammar(code)
        assert res.valid
        assert res.entrypoint_found
        assert res.signature_valid
        assert res.returns_dict

    def test_grammar_validation_rejects_missing_entrypoint(self):
        """Rejects code lacking required entrypoint function."""
        code = """
def compute_something_else(data):
    return {"status": "SUCCESS"}
"""
        res = GrammarConstrainedSynthesizer.validate_grammar(code)
        assert not res.valid
        assert not res.entrypoint_found
        assert any("Entrypoint function 'execute' not defined" in e for e in res.errors)

    def test_grammar_validation_rejects_non_dict_return(self):
        """Rejects code returning non-dictionary scalar or list."""
        code = """
def execute(inputs: dict) -> dict:
    return [1, 2, 3]
"""
        res = GrammarConstrainedSynthesizer.validate_grammar(code)
        assert not res.valid
        assert any("must return a dictionary" in e for e in res.errors)

    def test_grammar_normalization(self):
        """Normalizes naked code into proper execute(inputs: dict) -> dict signature."""
        naked = """
x = inputs.get("n", 5)
return {"answer": x * 2}
"""
        normalized = GrammarConstrainedSynthesizer.apply_grammar_normalization(naked)
        assert "def execute(inputs: dict) -> dict:" in normalized


class TestOpenTelemetryObservability:
    """Verifies OpenTelemetry distributed tracing and GenAI semantic conventions."""

    def test_genai_semantic_conventions_attributes(self):
        """GenAI semantic convention keys conform to OpenTelemetry specifications."""
        assert GenAISemanticConventions.SYSTEM == "gen_ai.system"
        assert GenAISemanticConventions.REQUEST_MODEL == "gen_ai.request.model"
        assert GenAISemanticConventions.USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
        assert GenAISemanticConventions.CAPABILITY_ID == "capforge.capability.id"
        assert GenAISemanticConventions.SANDBOX_DRIVER == "capforge.sandbox.driver"

    def test_record_llm_call_emits_span(self):
        """record_llm_call instruments LLM completions with token and duration metadata."""
        trace_manager.clear()
        span = record_llm_call(
            model="qwen2.5:7b",
            system="ollama",
            temperature=0.1,
            input_tokens=256,
            output_tokens=128,
            duration_ms=45.2,
        )
        assert span.attributes[GenAISemanticConventions.SYSTEM] == "ollama"
        assert span.attributes[GenAISemanticConventions.REQUEST_MODEL] == "qwen2.5:7b"
        assert span.attributes[GenAISemanticConventions.USAGE_INPUT_TOKENS] == 256
        assert len(trace_manager.list_spans()) >= 1

    def test_w3c_trace_context_propagation(self):
        """Injects and extracts standard W3C traceparent headers across processes."""
        with trace_manager.start_span("parent_agent_step") as span:
            carrier = {}
            trace_manager.inject_trace_context(carrier)
            assert "traceparent" in carrier
            assert span.trace_id in carrier["traceparent"]

            trace_id, span_id = trace_manager.extract_trace_context(carrier)
            assert trace_id == span.trace_id
            assert span_id == span.span_id

    def test_otlp_span_conversion_and_export(self):
        """Converts internal spans to standard OTLP JSON representation."""
        trace_manager.clear()
        with trace_manager.start_span("test_otlp_step") as s:
            s.set_attribute("env", "production")
            s.set_attribute("batch_size", 100)

        spans = trace_manager.list_spans()
        assert len(spans) == 1
        otlp = spans[0].to_otlp_span()
        assert "traceId" in otlp
        assert "spanId" in otlp
        assert "startTimeUnixNano" in otlp
        assert "attributes" in otlp

        # Test JSON file export
        with tempfile.TemporaryDirectory() as td:
            export_path = Path(td) / "traces.json"
            trace_manager.export_spans_to_json(export_path)
            assert export_path.exists()
            loaded = json.loads(export_path.read_text(encoding="utf-8"))
            assert len(loaded) >= 1

    def test_instrument_capability_decorator(self):
        """@instrument_capability automatically creates named execution spans."""
        trace_manager.clear()

        @instrument_capability("monte_carlo_var")
        def run_calc(x):
            return x * 10

        out = run_calc(5)
        assert out == 50
        spans = trace_manager.list_spans(name="monte_carlo_var")
        assert len(spans) == 1
        assert spans[0].attributes[GenAISemanticConventions.CAPABILITY_ID] == "monte_carlo_var"

    def test_sandbox_and_evaluator_telemetry_wiring(self):
        """Evaluator and SandboxRunner automatically record telemetry spans."""
        trace_manager.clear()
        evaluator = CapabilityEvaluator()
        cap = Capability(
            id="telemetry_test_cap",
            name="Tel Cap",
            description="Testing evaluator spans",
            code_body="def execute(inputs): return {'status': 'SUCCESS'}",
            verification_tests=[
                TestCase(
                    id="t1",
                    name="Smoke",
                    test_type=TestType.SMOKE,
                    inputs={},
                    assert_expression="output.get('status') == 'SUCCESS'",
                )
            ],
        )

        res = evaluator.evaluate(cap)
        assert res.passed

        # Check that spans were recorded
        eval_spans = [
            s for s in trace_manager.list_spans(name="capforge.verification.evaluate")
            if s.attributes.get(GenAISemanticConventions.CAPABILITY_ID) == "telemetry_test_cap"
        ]
        assert len(eval_spans) >= 1
        assert eval_spans[0].attributes[GenAISemanticConventions.CAPABILITY_ID] == "telemetry_test_cap"
        assert eval_spans[0].attributes[GenAISemanticConventions.VERIFICATION_PASSED] is True

        sandbox_spans = trace_manager.list_spans(name="capforge.sandbox.execute")
        assert len(sandbox_spans) >= 1
        assert GenAISemanticConventions.SANDBOX_DRIVER in sandbox_spans[0].attributes


class TestWiringOfAllFeatures:
    """Verifies that all CapForge production features are wired and actively accessible."""

    def test_registry_and_storage_factories(self):
        """Registry and artifact store factories resolve properly according to settings."""
        reg = get_registry_store()
        assert reg is not None
        # Default storage backend is local/sqlite
        art = get_artifact_store()
        # Returns None or S3 store based on configuration
        assert art is None or hasattr(art, "upload_artifact")

    def test_sandbox_driver_wiring_in_evaluator(self):
        """CapabilityEvaluator respects configured sandbox driver."""
        evaluator = CapabilityEvaluator()
        assert hasattr(evaluator.sandbox, "driver")
        assert hasattr(evaluator.sandbox.driver, "execute_code")
