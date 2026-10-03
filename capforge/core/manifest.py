"""CapForge Capability Manifest Parser and Exporter (discussion.mdx §12).

Provides machine-readable YAML manifest serialization and deserialization
for version-controlled, auditable capability definitions.
"""

from __future__ import annotations

from typing import Any

import yaml

from capforge.core.models import (
    Capability,
    CapabilityDependency,
    CapabilityStatus,
    CapabilityType,
    ParameterSpec,
    Provenance,
    RiskLevel,
    TestCase,
    TestType,
    ToolPermissions,
    ToolRequirement,
)


def capability_to_manifest_dict(cap: Capability) -> dict[str, Any]:
    """Convert a Capability model to a canonical manifest dictionary per §12."""
    inputs_dict = {
        name: {
            "type": param.type_name,
            "description": param.description,
            "required": param.required,
            **({"default": param.default} if param.default is not None else {}),
        }
        for name, param in cap.inputs.items()
    }

    outputs_dict = {
        name: {
            "type": param.type_name,
            "description": param.description,
        }
        for name, param in cap.outputs.items()
    }

    manifest = {
        "capability_id": cap.id,
        "name": cap.name,
        "version": cap.version,
        "type": cap.capability_type.value,
        "description": cap.description.strip(),
        "domain": cap.domain,
        "tags": cap.tags,
        "status": cap.status.value,
        "parent_version": cap.parent_version,
        "confidence": cap.confidence_score,
        "success_rate": cap.success_rate,
        "inputs": inputs_dict,
        "outputs": outputs_dict,
        "procedure": {
            "execution_mode": cap.execution_mode.value,
            "entrypoint": cap.entrypoint_function,
            "code": cap.code_body,
            **({"prompt_template": cap.prompt_template} if cap.prompt_template else {}),
        },
        "tools": [t.name for t in cap.tools_required],
        "dependencies": [
            {
                "capability_id": d.capability_id,
                "version_constraint": d.version_constraint,
                **({"primitive_type": d.primitive_type} if d.primitive_type else {}),
            }
            for d in cap.dependencies
        ],
        "permissions": {
            "filesystem": cap.permissions.filesystem,
            "network": cap.permissions.network,
            "github": cap.permissions.github,
            "database": cap.permissions.database,
            "external_apis": cap.permissions.external_apis,
        },
        "risk": {
            "level": cap.risk_level.value,
        },
        "provenance": {
            "source": cap.provenance.source,
            "source_url": cap.provenance.source_url,
            "trust_level": cap.provenance.trust_level,
            "evidence_summary": cap.provenance.evidence_summary,
            "license_info": cap.provenance.license_info,
            "extraction_method": cap.provenance.extraction_method,
        },
        "verification_tests": [
            {
                "id": t.id,
                "name": t.name,
                "test_type": t.test_type.value,
                "inputs": t.inputs,
                "expected_keys": t.expected_keys,
                "expected_output_contains": t.expected_output_contains,
                "assert_expression": t.assert_expression,
                "max_timeout_sec": t.max_timeout_sec,
            }
            for t in cap.verification_tests
        ],
        "changelog": cap.changelog,
    }
    return manifest


def capability_to_yaml(cap: Capability) -> str:
    """Serialize a Capability to canonical YAML manifest."""
    manifest_dict = capability_to_manifest_dict(cap)
    return yaml.dump(manifest_dict, sort_keys=False, indent=2, allow_unicode=True)


def manifest_dict_to_capability(data: dict[str, Any]) -> Capability:
    """Parse a manifest dictionary into a validated Capability instance."""
    cap_id = data.get("capability_id") or data.get("id")
    if not cap_id:
        raise ValueError("Manifest missing required 'capability_id' field.")

    name = data.get("name", cap_id.replace("_", " ").title())
    version = str(data.get("version", "1.0.0"))

    # Capability type
    raw_type = str(data.get("type", "skill")).upper()
    try:
        cap_type = CapabilityType(raw_type)
    except ValueError:
        cap_type = CapabilityType.SKILL

    # Status
    raw_status = str(data.get("status", "experimental")).upper()
    try:
        status = CapabilityStatus(raw_status)
    except ValueError:
        status = CapabilityStatus.EXPERIMENTAL

    # Risk level
    risk_info = data.get("risk", {})
    raw_risk = (risk_info.get("level", "low") if isinstance(risk_info, dict) else str(risk_info)).upper()
    try:
        risk_level = RiskLevel(raw_risk)
    except ValueError:
        risk_level = RiskLevel.LOW

    # Permissions
    perm_dict = data.get("permissions", {})
    permissions = ToolPermissions(
        filesystem=perm_dict.get("filesystem", "none"),
        network=perm_dict.get("network", "none"),
        github=perm_dict.get("github", "none"),
        database=perm_dict.get("database", "none"),
        external_apis=perm_dict.get("external_apis", "none"),
    )

    # Provenance
    prov_dict = data.get("provenance", {})
    provenance = Provenance(
        source=prov_dict.get("source", "manual"),
        source_url=prov_dict.get("source_url"),
        trust_level=float(prov_dict.get("trust_level", 1.0)),
        evidence_summary=prov_dict.get("evidence_summary", ""),
        license_info=prov_dict.get("license_info"),
        extraction_method=prov_dict.get("extraction_method", "human"),
    )

    # Inputs & Outputs
    inputs: dict[str, ParameterSpec] = {}
    for k, v in data.get("inputs", {}).items():
        if isinstance(v, dict):
            inputs[k] = ParameterSpec(
                name=k,
                type_name=v.get("type", "string"),
                description=v.get("description", ""),
                required=v.get("required", True),
                default=v.get("default"),
            )
        else:
            inputs[k] = ParameterSpec(name=k, type_name=str(v), required=True)

    outputs: dict[str, ParameterSpec] = {}
    for k, v in data.get("outputs", {}).items():
        if isinstance(v, dict):
            outputs[k] = ParameterSpec(
                name=k,
                type_name=v.get("type", "any"),
                description=v.get("description", ""),
            )
        else:
            outputs[k] = ParameterSpec(name=k, type_name=str(v))

    # Procedure
    proc = data.get("procedure", {})
    code_body = proc.get("code") or data.get("code_body") or "def execute(**kwargs):\n    return kwargs\n"
    entrypoint = proc.get("entrypoint") or data.get("entrypoint_function") or "execute"
    prompt_template = proc.get("prompt_template") or data.get("prompt_template")

    # Tools
    tools_list = data.get("tools", [])
    tools_required = [ToolRequirement(name=t if isinstance(t, str) else t.get("name", str(t))) for t in tools_list]

    # Dependencies
    deps_list = data.get("dependencies", [])
    dependencies = []
    for d in deps_list:
        if isinstance(d, str):
            dependencies.append(CapabilityDependency(capability_id=d))
        elif isinstance(d, dict):
            dependencies.append(
                CapabilityDependency(
                    capability_id=d.get("capability_id", ""),
                    version_constraint=d.get("version_constraint", ">=1.0.0"),
                    primitive_type=d.get("primitive_type"),
                )
            )

    # Verification tests
    tests_list = data.get("verification_tests", [])
    verification_tests = []
    for t in tests_list:
        test_type_str = t.get("test_type", "smoke").lower()
        try:
            ttype = TestType(test_type_str)
        except ValueError:
            ttype = TestType.SMOKE
        verification_tests.append(
            TestCase(
                id=t.get("id", f"test_{len(verification_tests) + 1}"),
                name=t.get("name", "Verification Test"),
                test_type=ttype,
                inputs=t.get("inputs", {}),
                expected_keys=t.get("expected_keys", []),
                expected_output_contains=t.get("expected_output_contains", []),
                assert_expression=t.get("assert_expression"),
                max_timeout_sec=float(t.get("max_timeout_sec", 10.0)),
            )
        )

    return Capability(
        id=cap_id,
        name=name,
        version=version,
        status=status,
        capability_type=cap_type,
        description=data.get("description", ""),
        domain=data.get("domain", "general"),
        tags=data.get("tags", []),
        dependencies=dependencies,
        tools_required=tools_required,
        permissions=permissions,
        risk_level=risk_level,
        provenance=provenance,
        inputs=inputs,
        outputs=outputs,
        code_body=code_body,
        entrypoint_function=entrypoint,
        prompt_template=prompt_template,
        verification_tests=verification_tests,
        confidence_score=float(data.get("confidence", 0.90)),
        success_rate=float(data.get("success_rate", 1.0)),
        parent_version=data.get("parent_version"),
        changelog=data.get("changelog", "Imported from manifest"),
    )


def manifest_yaml_to_capability(yaml_content: str) -> Capability:
    """Parse raw YAML manifest content into a validated Capability."""
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict):
        raise ValueError("Invalid YAML: expected a mapping dictionary at top level.")
    return manifest_dict_to_capability(data)
