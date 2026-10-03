"""CapForge Grammar-Constrained Token Generation Engine.

Enforces strict syntactic and semantic grammar constraints during LLM code synthesis.
Prevents conversational preamble, markdown fence leaking, invalid function signatures,
and mismatched return types by constraining token generation via:
  1. GBNF (GGML / llama.cpp / Ollama) grammar definitions
  2. JSON Schema structured output grammar
  3. AST Grammar validation and syntax normalization
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from capforge.core.schemas import CapabilitySchema

logger = logging.getLogger("capforge.grammar")


# ---------------------------------------------------------------------------
# 1. GBNF Grammar Definition (GGML / llama.cpp / Ollama)
# ---------------------------------------------------------------------------

GBNF_PYTHON_CAPABILITY_GRAMMAR = r'''
# CapForge Capability Python Function Grammar (GBNF)
root ::= (import_stmt "\n")* function_def

import_stmt ::= "import " identifier (" as " identifier)?
              | "from " identifier " import " identifier (" as " identifier)?

function_def ::= "def execute(inputs: dict) -> dict:\n" body

body ::= (indent statement "\n")+

statement ::= assign_stmt | if_stmt | return_stmt | expr_stmt | try_stmt

indent ::= "    "
assign_stmt ::= identifier " = " expr
if_stmt ::= "if " expr ":\n" (indent indent statement "\n")+
return_stmt ::= "return " dict_expr
expr_stmt ::= expr

dict_expr ::= "{" (ws? string_lit ws? ":" ws? expr ws? ("," ws? string_lit ws? ":" ws? expr)*)? ws? "}"

identifier ::= [a-zA-Z_][a-zA-Z0-9_]*
expr ::= [^\n]+
string_lit ::= "\"" [^\"\n]* "\"" | "'" [^'\n]* "'"
ws ::= [ \t]+
'''


# ---------------------------------------------------------------------------
# 2. JSON Schema Grammar for Structured Output
# ---------------------------------------------------------------------------


def build_capability_json_grammar(schema: CapabilitySchema | None = None) -> dict[str, Any]:
    """Build a JSON Schema grammar for LLM structured output / constrained generation."""
    properties: dict[str, Any] = {
        "status": {
            "type": "string",
            "enum": ["SUCCESS", "FAILED"],
            "description": "Execution status indicator",
        },
        "version": {
            "type": "string",
            "description": "Capability version string e.g. 1.0.0 or 1.1.0",
        },
    }

    if schema:
        for f in schema.output_fields:
            type_map = {
                "string": "string",
                "float": "number",
                "int": "integer",
                "list": "array",
                "dict": "object",
                "bool": "boolean",
            }
            properties[f.name] = {
                "type": type_map.get(f.field_type, "string"),
                "description": f.description or f"Field {f.name}",
            }
    else:
        properties["result"] = {
            "description": "Computed capability result payload",
        }

    return {
        "type": "object",
        "properties": properties,
        "required": ["status"],
    }


# ---------------------------------------------------------------------------
# 3. AST Grammar Validation & Normalization
# ---------------------------------------------------------------------------


@dataclass
class GrammarValidationResult:
    """Outcome of grammar checking on synthesized code."""

    valid: bool
    entrypoint_found: bool = False
    signature_valid: bool = False
    returns_dict: bool = False
    ast_valid: bool = False
    errors: list[str] = field(default_factory=list)
    normalized_code: str = ""


class GrammarConstrainedSynthesizer:
    """Enforces grammar constraints on synthesized capability code."""

    @classmethod
    def clean_markdown_fences(cls, raw_text: str) -> str:
        """Strip conversational preamble and markdown code fences."""
        text = raw_text.strip()
        # Extract content between python code fences if present
        fence_match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            # Strip single fences if partial
            text = re.sub(r"^```(?:python)?\s*\n?", "", text, flags=re.MULTILINE)
            text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)

        # Remove leading explanations before def or import
        lines = text.splitlines()
        first_code_idx = 0
        for i, line_str in enumerate(lines):
            stripped = line_str.strip()
            if stripped.startswith(("def ", "import ", "from ", "#", '"""', "'''")):
                first_code_idx = i
                break
        return "\n".join(lines[first_code_idx:]).strip()

    @classmethod
    def validate_grammar(cls, code: str, expected_entrypoint: str = "execute") -> GrammarValidationResult:
        """Validate code strictly conforms to CapForge Capability Grammar."""
        clean_code = cls.clean_markdown_fences(code)
        res = GrammarValidationResult(valid=False, normalized_code=clean_code)

        if not clean_code:
            res.errors.append("Code body is empty.")
            return res

        try:
            tree = ast.parse(clean_code)
            res.ast_valid = True
        except SyntaxError as e:
            res.errors.append(f"SyntaxError against Python grammar at line {e.lineno}: {e.msg}")
            return res

        # Check for expected function definition
        entrypoint_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == expected_entrypoint:
                entrypoint_node = node
                res.entrypoint_found = True
                break

        if not entrypoint_node:
            res.errors.append(f"Grammar violation: Entrypoint function '{expected_entrypoint}' not defined.")
            return res

        # Validate function signature: must accept at least one argument ('inputs')
        args = entrypoint_node.args.args
        if not args:
            res.errors.append(f"Grammar violation: '{expected_entrypoint}' must accept 'inputs' dictionary parameter.")
        else:
            res.signature_valid = True

        # Validate return statements return dicts
        has_return = False
        returns_valid = True
        for node in ast.walk(entrypoint_node):
            if isinstance(node, ast.Return):
                has_return = True
                if node.value is not None:
                    # If returning a literal, verify it's a Dict
                    if isinstance(node.value, (ast.Constant, ast.List, ast.Tuple)):
                        returns_valid = False
                        res.errors.append("Grammar violation: execute() must return a dictionary, not scalar or list.")

        res.returns_dict = returns_valid and has_return
        res.valid = res.ast_valid and res.entrypoint_found and res.signature_valid and res.returns_dict
        return res

    @classmethod
    def apply_grammar_normalization(
        cls,
        code: str,
        expected_entrypoint: str = "execute",
        version: str = "1.0.0",
    ) -> str:
        """Normalize code to strictly satisfy the Capability grammar."""
        cleaned = cls.clean_markdown_fences(code)

        # Ensure def execute exists
        if f"def {expected_entrypoint}" not in cleaned:
            cleaned = f"def {expected_entrypoint}(inputs: dict) -> dict:\n" + "\n".join("    " + line for line in cleaned.splitlines())

        # Ensure inputs parameter exists in definition
        cleaned = re.sub(
            rf"def {expected_entrypoint}\(\s*\):",
            f"def {expected_entrypoint}(inputs: dict) -> dict:",
            cleaned,
        )

        return cleaned
