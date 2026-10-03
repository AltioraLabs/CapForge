"""CapForge Autonomous Acquisition Engine.

Coordinates discovery of missing capabilities, harvesting OpenAPI/schema docs,
synthesizing candidate capabilities, and packaging them for validation.
"""

from __future__ import annotations

from typing import Any

from capforge.acquisition.synthesizer import CapabilitySynthesizer
from capforge.core.models import Capability, CapabilityGap


class AcquisitionEngine:
    """Acquires missing capabilities from schemas, specs, and knowledge sources."""

    def __init__(self):
        self.synthesizer = CapabilitySynthesizer()

    def acquire_from_spec(self, spec: dict[str, Any], gap: CapabilityGap | None = None) -> Capability:
        """Construct a candidate capability from an API specification dictionary."""
        service_name = spec.get("name", "Unknown Service")
        cap_id = spec.get("id") or service_name.lower().replace(" ", "_")
        description = spec.get("description", f"Automated integration for {service_name}")
        base_url = spec.get("base_url", "http://localhost:8080")
        domain = spec.get("domain", "api_integration")
        endpoints = spec.get("endpoints", [{"path": "/metrics"}])
        auth_type = spec.get("auth_type", "Bearer")
        code_override = spec.get("code_body")

        return self.synthesizer.synthesize_api_capability(
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
