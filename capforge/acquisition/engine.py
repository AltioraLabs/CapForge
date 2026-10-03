"""CapForge Autonomous Acquisition Engine.

Coordinates discovery of missing capabilities, harvesting OpenAPI/schema docs,
synthesizing candidate capabilities, and packaging them for validation.
"""

from __future__ import annotations

from typing import Any

from capforge.acquisition.synthesizer import CapabilitySynthesizer
from capforge.core.models import Capability, CapabilityGap, ParameterSpec, TestCase, TestType


class AcquisitionEngine:
    """Acquires missing capabilities from schemas, specs, and knowledge sources."""

    def __init__(self):
        self.synthesizer = CapabilitySynthesizer()

    def acquire_from_spec(self, spec: dict[str, Any], gap: CapabilityGap | None = None) -> Capability:
        """Construct a candidate capability from an API or code specification dictionary."""
        service_name = spec.get("name", "Unknown Service")
        cap_id = spec.get("id") or service_name.lower().replace(" ", "_")
        description = spec.get("description", f"Automated integration for {service_name}")
        base_url = spec.get("base_url", "http://localhost:8080")
        domain = spec.get("domain", "api_integration")
        endpoints = spec.get("endpoints", [{"path": "/metrics"}])
        auth_type = spec.get("auth_type", "Bearer")
        code_override = spec.get("code_body") or spec.get("code_override")

        cap = self.synthesizer.synthesize_api_capability(
            capability_id=cap_id,
            name=service_name,
            description=description,
            domain=domain,
            base_url=base_url,
            endpoints=endpoints,
            auth_type=auth_type,
            tags=spec.get("tags"),
            code_override=code_override,
        )

        # Handle features metadata
        cap.features = list(spec.get("features", []))

        # Handle custom inputs specification
        if "inputs" in spec and spec["inputs"]:
            parsed_inputs = {}
            for k, v in spec["inputs"].items():
                if isinstance(v, ParameterSpec):
                    parsed_inputs[k] = v
                elif isinstance(v, dict):
                    parsed_inputs[k] = ParameterSpec(**v)
            cap.inputs = parsed_inputs
        elif code_override and "api_key" not in code_override:
            cap.inputs = {
                "returns": ParameterSpec(
                    name="returns",
                    type="list",
                    description="Return series observations",
                    required=False,
                    default=[],
                ),
                "confidence": ParameterSpec(
                    name="confidence",
                    type="float",
                    description="Confidence level",
                    required=False,
                    default=0.95,
                ),
                "method": ParameterSpec(
                    name="method",
                    type="string",
                    description="Calculation method",
                    required=False,
                    default="historical",
                ),
            }

        # Handle custom outputs specification
        if "outputs" in spec and spec["outputs"]:
            parsed_outputs = {}
            for k, v in spec["outputs"].items():
                if isinstance(v, ParameterSpec):
                    parsed_outputs[k] = v
                elif isinstance(v, dict):
                    parsed_outputs[k] = ParameterSpec(**v)
            cap.outputs = parsed_outputs

        # Handle custom verification tests
        custom_tests = spec.get("verification_tests") or spec.get("tests")
        if custom_tests:
            parsed_tests = []
            for t in custom_tests:
                if isinstance(t, TestCase):
                    parsed_tests.append(t)
                elif isinstance(t, dict):
                    parsed_tests.append(TestCase(**t))
            if parsed_tests:
                cap.verification_tests = parsed_tests
        elif code_override and "api_key" not in code_override:
            # Non-API computational capability: provide general smoke test
            cap.verification_tests = [
                TestCase(
                    id=f"test_{cap_id}_smoke",
                    name=f"Smoke execution for {cap_id}",
                    test_type=TestType.SMOKE,
                    inputs=spec.get("sample_inputs", {}),
                    assert_expression="output is not None and ('status' in output or isinstance(output, dict))",
                )
            ]

        return cap
