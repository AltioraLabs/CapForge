"""Comprehensive test suite for CapForge Production Upgrade."""

import pytest

import capforge
from capforge.core.models import (
    Capability,
    TestCase,
    TestType,
)
from capforge.core.schemas import (
    CapabilitySchema,
    FieldSchema,
    coerce_output,
    create_input_validator,
)
from capforge.core.telemetry import GenAISemanticConventions, record_llm_call
from capforge.registry.store_postgres import PostgresCapabilityRegistry
from capforge.registry.store_s3 import S3ArtifactStore, S3Config
from capforge.security.trust_chain import TamperDetectedError, TrustChain
from capforge.verification.repair import AutoRepairEngine, RepairReport
from capforge.verification.sandbox import (
    InProcessSandboxDriver,
    ProcessSandboxDriver,
    get_sandbox_driver,
)
from capforge.verification.sandbox_wasm import WasmSandboxRunner


class TestPhase1ContractsAndDiscovery:
    """Phase 1: Pydantic I/O Schemas & Dynamic Feature Discovery."""

    def test_schema_definition_and_json_schema(self):
        schema = CapabilitySchema(
            capability_id="portfolio_risk_var",
            version="1.0.0",
            input_fields=[
                FieldSchema(name="returns", field_type="list", description="Asset return series"),
                FieldSchema(name="confidence", field_type="float", default=0.95),
            ],
            output_fields=[
                FieldSchema(name="status", field_type="string"),
                FieldSchema(name="var_value", field_type="float", aliases=["var", "value_at_risk"]),
            ],
        )

        json_schema = schema.to_json_schema()
        assert json_schema["title"] == "portfolio_risk_var_v1.0.0_contract"
        assert "properties" in json_schema
        assert "returns" in json_schema["properties"]["input"]["properties"]

    def test_input_validator_and_coercion(self):
        schema = CapabilitySchema(
            capability_id="test_calc",
            version="1.0.0",
            input_fields=[
                FieldSchema(name="x", field_type="float"),
                FieldSchema(name="multiplier", field_type="int", default=2),
            ],
            output_fields=[
                FieldSchema(name="result", field_type="float", aliases=["res", "val"]),
            ],
        )

        validator = create_input_validator(schema)
        validated = validator({"x": 10.5})
        assert validated["x"] == 10.5
        assert validated["multiplier"] == 2

        raw_output = {"res": 21.0, "status": "SUCCESS"}
        coerced = coerce_output(raw_output, schema)
        assert coerced["result"] == 21.0

    def test_capability_feature_discovery(self):
        cap = Capability(
            id="market_calc",
            name="Market Calc",
            description="Testing features",
            code_body="def execute(inputs): return {'status': 'SUCCESS'}",
            features=["caching", "cross_asset_correlation", "portfolio_var"],
        )
        assert cap.has_feature("caching")
        assert cap.has_feature("CROSS_ASSET_CORRELATION")
        assert not cap.has_feature("monte_carlo")
        assert cap.has_features(["caching", "portfolio_var"])
        assert not cap.has_features(["caching", "quantum_pricing"])


class TestPhase2SelfRepair:
    """Phase 2: 3-Pass Self-Repair Engine."""

    def test_pass1_ast_structural_repair(self):
        engine = AutoRepairEngine(enable_llm_pass=False)
        cap = Capability(
            id="repairable_cap",
            name="Repairable",
            description="Tests auto repair",
            code_body="def execute(inputs):\n    # Missing import math and direct dict index\n    val = inputs['x']\n    return {'result': math.sqrt(val)}",
            verification_tests=[
                TestCase(
                    id="t1",
                    name="Smoke test",
                    test_type=TestType.SMOKE,
                    inputs={"x": 16.0},
                    assert_expression="output.get('result') == 4.0",
                ),
            ],
        )

        repaired, result, iterations = engine.repair_until_pass(cap)
        assert result.passed
        assert "import math" in repaired.code_body
        assert "inputs.get(" in repaired.code_body or "inputs.get('x')" in repaired.code_body

    def test_repair_report_audit_trail(self):
        engine = AutoRepairEngine(enable_llm_pass=False)
        # Initially failing code: missing import statistics
        cap = Capability(
            id="audit_cap",
            name="Audit Cap",
            description="Tests repair report",
            code_body="def execute(inputs):\n    nums = inputs['nums']\n    return {'mean': statistics.mean(nums)}",
            verification_tests=[
                TestCase(
                    id="t1",
                    name="Test mean",
                    test_type=TestType.SMOKE,
                    inputs={"nums": [10, 20, 30]},
                    assert_expression="output.get('mean') == 20",
                )
            ],
        )

        repaired, result, report = engine.repair_with_report(cap)
        assert isinstance(report, RepairReport)
        assert report.final_passed
        assert len(report.steps) >= 1
        assert report.steps[0].strategy == "AST_STRUCTURAL"


class TestPhase3SandboxDrivers:
    """Phase 3: Pluggable Sandbox Drivers."""

    def test_sandbox_driver_factory(self):
        p_driver = get_sandbox_driver("subprocess")
        assert isinstance(p_driver, ProcessSandboxDriver)

        in_driver = get_sandbox_driver("in_process")
        assert isinstance(in_driver, InProcessSandboxDriver)

    def test_in_process_execution(self):
        driver = InProcessSandboxDriver()
        code = "def execute(inputs):\n    return {'sum': inputs['a'] + inputs['b']}"
        res = driver.execute_code(code, "execute", {"a": 10, "b": 20})
        assert res["success"]
        assert res["output"]["sum"] == 30

    def test_subprocess_execution(self):
        driver = ProcessSandboxDriver()
        code = "def execute(inputs):\n    return {'product': inputs['x'] * inputs['y']}"
        res = driver.execute_code(code, "execute", {"x": 6, "y": 7})
        assert res["success"]
        assert res["output"]["product"] == 42

    def test_wasm_sandbox_runner(self):
        wasm = WasmSandboxRunner(memory_limit_mb=128)
        code = "def execute(inputs):\n    return {'status': 'OK', 'echo': inputs.get('msg')}"
        res = wasm.execute_code(code, "execute", {"msg": "hello wasm"})
        assert res["success"]
        assert res["output"]["echo"] == "hello wasm"
        assert res["driver"] in ("wasm_pyodide", "hardened_subprocess")


class TestPhase4DistributedRegistry:
    """Phase 4: PostgreSQL & S3 Storage."""

    def test_s3_artifact_store_key_generation(self):
        store = S3ArtifactStore(S3Config(bucket_name="my-test-bucket", prefix="custom/"))
        key = store._object_key("portfolio_var", "1.2.0", "abcdef123456")
        assert key == "custom/portfolio_var/1.2.0/abcdef123456.py"

    def test_postgres_registry_schema_sql(self):
        sql = PostgresCapabilityRegistry.SCHEMA_SQL
        assert "CREATE TABLE IF NOT EXISTS {schema}.capabilities" in sql
        assert "CREATE TABLE IF NOT EXISTS {schema}.verification_history" in sql


class TestPhase5SecurityAndObservability:
    """Phase 5: ED25519 Signing & OTel GenAI Semantics."""

    def test_ed25519_signing_and_verification(self):
        trust = TrustChain()
        cap = Capability(
            id="crypto_signed_cap",
            name="Crypto Cap",
            description="Testing ED25519 signing",
            code_body="def execute(inputs):\n    return {'status': 'SECURE'}",
        )

        sig = trust.sign(cap, algorithm="ed25519")
        assert sig.algorithm == "ed25519"
        assert sig.public_key_hex is not None
        assert len(sig.hmac_sig) > 0

        # Verify should pass on untouched code
        assert trust.verify(cap)

        # Tamper detection: modifying code causes TamperDetectedError
        tampered_cap = cap.model_copy(deep=True)
        tampered_cap.code_body = "def execute(inputs):\n    return {'status': 'TAMPERED'}"
        with pytest.raises(TamperDetectedError):
            trust.verify(tampered_cap)

    def test_otel_genai_semantics(self):
        assert GenAISemanticConventions.SYSTEM == "gen_ai.system"
        assert GenAISemanticConventions.REQUEST_MODEL == "gen_ai.request.model"

        span = record_llm_call(
            model="gemini-1.5-flash",
            system="gemini",
            temperature=0.2,
            input_tokens=150,
            output_tokens=75,
        )
        assert span.attributes[GenAISemanticConventions.SYSTEM] == "gemini"
        assert span.attributes[GenAISemanticConventions.USAGE_INPUT_TOKENS] == 150


class TestPhase6Exports:
    """Phase 6: Module top-level exports."""

    def test_lazy_exports(self):
        assert capforge.CapabilitySchema is not None
        assert capforge.FieldSchema is not None
        assert capforge.WasmSandboxRunner is not None
        assert capforge.get_sandbox_driver is not None
        assert capforge.PostgresCapabilityRegistry is not None
        assert capforge.S3ArtifactStore is not None
        assert capforge.GenAISemanticConventions is not None
