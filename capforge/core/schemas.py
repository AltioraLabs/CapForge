"""CapForge Capability I/O Schema Contracts.

Provides Pydantic-based runtime type validation for capability inputs and outputs.
Each synthesized capability gets a formal input/output schema that is enforced at
execution time, eliminating KeyError crashes from LLM-generated code returning
unexpected key names.

Features:
  - Auto-generate Pydantic models from ParameterSpec definitions
  - Runtime input validation before capability execution
  - Output coercion with flexible key matching (alias support)
  - JSON Schema export for cross-agent contract negotiation
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from capforge.core.models import ParameterSpec

logger = logging.getLogger("capforge.schemas")


# ---------------------------------------------------------------------------
# 1. Schema Definition Models
# ---------------------------------------------------------------------------


class FieldSchema(BaseModel):
    """Single field within a capability I/O schema."""

    name: str
    field_type: str = "any"  # "string", "float", "int", "list", "dict", "bool", "any"
    description: str = ""
    required: bool = True
    default: Any = None
    aliases: list[str] = Field(default_factory=list)


class CapabilitySchema(BaseModel):
    """Complete input/output contract for a capability."""

    capability_id: str
    version: str
    input_fields: list[FieldSchema] = Field(default_factory=list)
    output_fields: list[FieldSchema] = Field(default_factory=list)

    def to_json_schema(self) -> dict[str, Any]:
        """Export as JSON Schema for cross-agent contract negotiation."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{self.capability_id}_v{self.version}_contract",
            "type": "object",
            "properties": {
                "input": {
                    "type": "object",
                    "properties": _fields_to_json_schema(self.input_fields),
                },
                "output": {
                    "type": "object",
                    "properties": _fields_to_json_schema(self.output_fields),
                },
            },
        }


# ---------------------------------------------------------------------------
# 2. Type Mapping
# ---------------------------------------------------------------------------

_PYTHON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "str": str,
    "float": float,
    "number": float,
    "int": int,
    "integer": int,
    "list": list,
    "array": list,
    "dict": dict,
    "object": dict,
    "bool": bool,
    "boolean": bool,
    "any": object,
}

_JSON_SCHEMA_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "str": "string",
    "float": "number",
    "number": "number",
    "int": "integer",
    "integer": "integer",
    "list": "array",
    "array": "array",
    "dict": "object",
    "object": "object",
    "bool": "boolean",
    "boolean": "boolean",
    "any": "string",
}


def _fields_to_json_schema(fields: list[FieldSchema]) -> dict[str, Any]:
    """Convert field list to JSON Schema properties object."""
    properties = {}
    for f in fields:
        prop: dict[str, Any] = {
            "type": _JSON_SCHEMA_TYPE_MAP.get(f.field_type, "string"),
            "description": f.description,
        }
        if f.default is not None:
            prop["default"] = f.default
        properties[f.name] = prop
    return properties


# ---------------------------------------------------------------------------
# 3. Schema Generation from ParameterSpec
# ---------------------------------------------------------------------------


def generate_schema_from_specs(
    capability_id: str,
    version: str,
    input_specs: dict[str, ParameterSpec] | None = None,
    output_specs: dict[str, ParameterSpec] | None = None,
) -> CapabilitySchema:
    """Generate a formal CapabilitySchema from ParameterSpec dictionaries.

    This is the bridge between CapForge's existing informal spec system
    and the new strict Pydantic-based contracts.
    """
    input_fields = []
    if input_specs:
        for name, spec in input_specs.items():
            input_fields.append(
                FieldSchema(
                    name=spec.name or name,
                    field_type=spec.type or "any",
                    description=spec.description or "",
                    required=spec.required if spec.required is not None else True,
                    default=spec.default,
                )
            )

    output_fields = []
    if output_specs:
        for name, spec in output_specs.items():
            output_fields.append(
                FieldSchema(
                    name=spec.name or name,
                    field_type=spec.type or "any",
                    description=spec.description or "",
                    required=spec.required if spec.required is not None else False,
                    default=spec.default,
                )
            )

    return CapabilitySchema(
        capability_id=capability_id,
        version=version,
        input_fields=input_fields,
        output_fields=output_fields,
    )


# ---------------------------------------------------------------------------
# 4. Dynamic Pydantic Model Generation
# ---------------------------------------------------------------------------


def build_pydantic_model(
    model_name: str,
    fields: list[FieldSchema],
) -> type[BaseModel]:
    """Dynamically create a Pydantic model from FieldSchema definitions.

    This enables runtime validation of arbitrary capability I/O structures
    without pre-defining model classes.
    """
    pydantic_fields: dict[str, Any] = {}

    for field in fields:
        python_type = _PYTHON_TYPE_MAP.get(field.field_type, object)

        if not field.required or field.default is not None:
            default_val = field.default
            pydantic_fields[field.name] = (
                python_type | None if default_val is None else python_type,
                Field(default=default_val, description=field.description),
            )
        else:
            pydantic_fields[field.name] = (
                python_type,
                Field(description=field.description),
            )

    return create_model(model_name, __config__=ConfigDict(extra="allow"), **pydantic_fields)


# ---------------------------------------------------------------------------
# 5. Runtime Validation Engine
# ---------------------------------------------------------------------------


class SchemaValidator:
    """Validates capability inputs/outputs against their formal schemas.

    Provides flexible matching with alias support for LLM-generated outputs
    that may use different key names than expected.
    """

    def __init__(self):
        self._model_cache: dict[str, type[BaseModel]] = {}

    def validate_inputs(
        self,
        schema: CapabilitySchema,
        inputs: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], list[str]]:
        """Validate and coerce inputs against the schema.

        Returns:
            (is_valid, coerced_inputs, error_messages)
        """
        model_key = f"{schema.capability_id}_{schema.version}_input"
        if model_key not in self._model_cache:
            self._model_cache[model_key] = build_pydantic_model(
                f"{schema.capability_id}_Input",
                schema.input_fields,
            )

        model_cls = self._model_cache[model_key]
        try:
            instance = model_cls(**inputs)
            return True, instance.model_dump(), []
        except ValidationError as e:
            errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
            logger.warning(
                "Input validation failed for %s: %s",
                schema.capability_id,
                errors,
            )
            return False, inputs, errors

    def validate_outputs(
        self,
        schema: CapabilitySchema,
        outputs: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], list[str]]:
        """Validate outputs with flexible alias matching.

        LLM-generated code often returns keys under different names
        (e.g., 'var_pct' vs 'var_95_pct'). This method attempts to
        match output fields using aliases before reporting validation failures.

        Returns:
            (is_valid, normalized_outputs, error_messages)
        """
        normalized = dict(outputs)
        errors = []

        for field in schema.output_fields:
            if field.name in normalized:
                continue

            matched = False
            for alias in field.aliases:
                if alias in normalized:
                    normalized[field.name] = normalized[alias]
                    matched = True
                    logger.debug(
                        "Output alias match: %s -> %s for %s",
                        alias,
                        field.name,
                        schema.capability_id,
                    )
                    break

            if not matched and field.required and field.default is None:
                errors.append(
                    f"Missing required output field '{field.name}' "
                    f"(aliases checked: {field.aliases})"
                )

            if not matched and field.default is not None:
                normalized[field.name] = field.default

        if errors:
            logger.warning(
                "Output validation issues for %s: %s",
                schema.capability_id,
                errors,
            )
            return False, normalized, errors

        return True, normalized, []

    def export_json_schema(self, schema: CapabilitySchema) -> str:
        """Export the schema as a JSON string for cross-agent negotiation."""
        return json.dumps(schema.to_json_schema(), indent=2)

    def clear_cache(self) -> None:
        """Clear the Pydantic model cache."""
        self._model_cache.clear()


# ---------------------------------------------------------------------------
# 6. Global Singleton
# ---------------------------------------------------------------------------

_schema_validator: SchemaValidator | None = None


def get_schema_validator() -> SchemaValidator:
    """Get or create the global SchemaValidator instance."""
    global _schema_validator
    if _schema_validator is None:
        _schema_validator = SchemaValidator()
    return _schema_validator


def create_input_validator(schema: CapabilitySchema):
    """Factory creating an input validator function for a CapabilitySchema."""
    validator = get_schema_validator()
    def _validate(inputs: dict[str, Any]) -> dict[str, Any]:
        is_valid, data, errors = validator.validate_inputs(schema, inputs)
        if not is_valid:
            raise ValueError(f"Input validation failed: {errors}")
        return data
    return _validate


def coerce_output(output: dict[str, Any], schema: CapabilitySchema) -> dict[str, Any]:
    """Coerce output dictionary fields according to schema aliases and defaults."""
    validator = get_schema_validator()
    _, normalized, _ = validator.validate_outputs(schema, output)
    return normalized
