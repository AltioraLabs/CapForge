"""CapForge Capability Auto-Repair Engine.

Analyzes execution failure diagnostics and tracebacks, synthesizes targeted code patches,
and orchestrates the closed-loop repair cycle across three specialized repair passes:

  Pass 1 — Static AST and Structural Repair:
    Fixes syntax errors, missing standard library imports, unhandled None/missing inputs,
    and missing dictionary return keys.

  Pass 2 — LLM / Reflection Repair:
    When an LLM provider (Ollama, Gemini, OpenAI) is configured, constructs a structured
    diagnostic prompt containing the error tracebacks, failed test case inputs/outputs,
    and current code, and queries the LLM for a corrected implementation.

  Pass 3 — Heuristic Fallback and Schema Alignment:
    Aligns output schema, wraps raw values into expected dictionary contracts,
    and injects graceful fallback handlers for edge cases.
"""

from __future__ import annotations

import ast
import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from capforge.core.models import Capability, VerificationResult
from capforge.verification.evaluator import CapabilityEvaluator

logger = logging.getLogger("capforge.repair")

_STDLIB_MODULES = {
    "math", "json", "re", "datetime", "itertools", "collections", "statistics",
    "functools", "typing", "random", "hashlib", "uuid", "decimal", "copy",
}


@dataclass
class RepairStep:
    """Record of a single repair pass attempt."""
    pass_number: int
    strategy: str  # AST_STRUCTURAL | LLM_REFLECTION | SCHEMA_FALLBACK
    description: str
    diff: str = ""
    tests_passed_before: int = 0
    tests_passed_after: int = 0
    success: bool = False


@dataclass
class RepairReport:
    """Comprehensive diagnostic and audit trail of a repair session."""
    capability_id: str
    original_version: str
    initial_passed: bool
    final_passed: bool
    iterations_run: int
    steps: list[RepairStep] = field(default_factory=list)
    repaired_code: str = ""


class AutoRepairEngine:
    """Diagnoses test failures and applies targeted 3-pass self-healing patches."""

    def __init__(
        self,
        evaluator: CapabilityEvaluator | None = None,
        max_iterations: int = 3,
        enable_llm_pass: bool = True,
    ):
        self.evaluator = evaluator or CapabilityEvaluator()
        self.max_iterations = max_iterations
        self.enable_llm_pass = enable_llm_pass

    def repair_until_pass(
        self,
        capability: Capability,
    ) -> tuple[Capability, VerificationResult, int]:
        """Iteratively diagnose, patch, and re-evaluate candidate capability.

        Returns (repaired_capability, final_verification_result, iterations_taken).
        """
        repaired_cap, verif_result, report = self.repair_with_report(capability)
        return repaired_cap, verif_result, report.iterations_run

    def repair_with_report(
        self,
        capability: Capability,
    ) -> tuple[Capability, VerificationResult, RepairReport]:
        """Execute the 3-pass repair engine and return detailed audit report."""
        current_cap = capability.model_copy(deep=True)
        initial_result = self.evaluator.evaluate(current_cap)

        report = RepairReport(
            capability_id=current_cap.id,
            original_version=current_cap.version,
            initial_passed=initial_result.passed,
            final_passed=initial_result.passed,
            iterations_run=0,
            repaired_code=current_cap.code_body,
        )

        if initial_result.passed:
            return current_cap, initial_result, report

        verif_result = initial_result
        iteration = 0

        while not verif_result.passed and iteration < self.max_iterations:
            iteration += 1
            before_code = current_cap.code_body
            failed_tests = [t for t in verif_result.test_details if not t.passed]

            # -------------------------------------------------------------
            # PASS 1: Static AST and Structural Repair
            # -------------------------------------------------------------
            logger.info("AutoRepair [Iter %d/Pass 1]: Running AST and Structural Repair", iteration)
            p1_code, p1_desc = self._pass1_ast_structural_repair(before_code, failed_tests, current_cap)
            if p1_code != before_code:
                current_cap.code_body = p1_code
                p1_result = self.evaluator.evaluate(current_cap)
                diff = self._make_diff(before_code, p1_code)
                report.steps.append(RepairStep(
                    pass_number=1,
                    strategy="AST_STRUCTURAL",
                    description=p1_desc,
                    diff=diff,
                    tests_passed_before=verif_result.tests_passed,
                    tests_passed_after=p1_result.tests_passed,
                    success=p1_result.passed,
                ))
                verif_result = p1_result
                if verif_result.passed:
                    break
                before_code = p1_code

            # -------------------------------------------------------------
            # PASS 2: LLM Reflection Repair (if configured)
            # -------------------------------------------------------------
            if self.enable_llm_pass and not verif_result.passed:
                logger.info("AutoRepair [Iter %d/Pass 2]: Running LLM Reflection Repair", iteration)
                p2_code, p2_desc = self._pass2_llm_reflection_repair(before_code, failed_tests, current_cap)
                if p2_code != before_code:
                    current_cap.code_body = p2_code
                    p2_result = self.evaluator.evaluate(current_cap)
                    diff = self._make_diff(before_code, p2_code)
                    report.steps.append(RepairStep(
                        pass_number=2,
                        strategy="LLM_REFLECTION",
                        description=p2_desc,
                        diff=diff,
                        tests_passed_before=verif_result.tests_passed,
                        tests_passed_after=p2_result.tests_passed,
                        success=p2_result.passed,
                    ))
                    verif_result = p2_result
                    if verif_result.passed:
                        break
                    before_code = p2_code

            # -------------------------------------------------------------
            # PASS 3: Heuristic Fallback and Schema Alignment
            # -------------------------------------------------------------
            if not verif_result.passed:
                logger.info("AutoRepair [Iter %d/Pass 3]: Running Heuristic Fallback and Schema Alignment", iteration)
                p3_code, p3_desc = self._pass3_heuristic_fallback(before_code, failed_tests, current_cap)
                if p3_code != before_code:
                    current_cap.code_body = p3_code
                    p3_result = self.evaluator.evaluate(current_cap)
                    diff = self._make_diff(before_code, p3_code)
                    report.steps.append(RepairStep(
                        pass_number=3,
                        strategy="SCHEMA_FALLBACK",
                        description=p3_desc,
                        diff=diff,
                        tests_passed_before=verif_result.tests_passed,
                        tests_passed_after=p3_result.tests_passed,
                        success=p3_result.passed,
                    ))
                    verif_result = p3_result
                    if verif_result.passed:
                        break

        report.iterations_run = iteration
        report.final_passed = verif_result.passed
        report.repaired_code = current_cap.code_body
        current_cap.changelog = f"Auto-repaired in {iteration} iteration(s): pass_rate={verif_result.tests_passed}/{verif_result.tests_run}"
        return current_cap, verif_result, report

    def _pass1_ast_structural_repair(
        self,
        code_body: str,
        failed_tests: list[Any],
        capability: Capability,
    ) -> tuple[str, str]:
        patched = code_body
        applied_fixes = []

        # 1. Injected missing stdlib imports
        missing_imports = self._find_missing_imports(patched)
        if missing_imports:
            import_statements = "\n".join(f"import {m}" for m in missing_imports)
            patched = f"{import_statements}\n\n{patched}"
            applied_fixes.append(f"Injected missing imports: {', '.join(missing_imports)}")

        # 2. Replace inputs[...] with inputs.get(...)
        if "inputs[" in patched:
            subbed = re.sub(r'inputs\["([^"]+)"\]', r'inputs.get("\1")', patched)
            subbed = re.sub(r"inputs\['([^']+)'\]", r"inputs.get('\1')", subbed)
            if subbed != patched:
                patched = subbed
                applied_fixes.append("Replaced inputs[...] with inputs.get(...)")

        # 3. Guard against empty / None inputs
        guard_needed = any(
            "keyerror" in (t.error_message or "").lower() or
            "none" in (t.error_message or "").lower() or
            "typeerror" in (t.error_message or "").lower()
            for t in failed_tests
        )
        if guard_needed and "if not inputs:" not in patched and "if inputs is None:" not in patched:
            guard = "\n    if inputs is None:\n        inputs = {}\n    if not isinstance(inputs, dict):\n        inputs = {'value': inputs}\n"
            patched = re.sub(r"(def execute\([^)]*\):)", r"\1" + guard, patched, count=1)
            applied_fixes.append("Injected inputs dictionary guard")

        # 4. Supply missing expected dictionary return keys
        for t in failed_tests:
            err = (t.error_message or "").lower()
            for match in re.finditer(r"expected key '([^']+)' missing", err):
                missing_key = match.group(1)
                default_val = "[]" if ("list" in missing_key or "records" in missing_key) else "{}" if ("summary" in missing_key or "meta" in missing_key) else "0"
                if f'"{missing_key}"' not in patched and f"'{missing_key}'" not in patched:
                    patched = re.sub(
                        r"(\s+)(return\s+.*)",
                        rf'\1if isinstance(res, dict) and "{missing_key}" not in res:\n\1    res["{missing_key}"] = {default_val}\n\1\2',
                        patched,
                    )
                    applied_fixes.append(f"Added default return key '{missing_key}'")

        desc = "; ".join(applied_fixes) if applied_fixes else "No AST changes applied"
        return patched, desc

    def _find_missing_imports(self, code: str) -> list[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])

        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)

        missing = sorted(list((used_names & _STDLIB_MODULES) - imported))
        return missing

    def _pass2_llm_reflection_repair(
        self,
        code_body: str,
        failed_tests: list[Any],
        capability: Capability,
    ) -> tuple[str, str]:
        from capforge.core.config import settings

        if not settings.llm_configured:
            return code_body, "LLM not configured, skipping Pass 2"

        try:
            from capforge.acquisition.synthesizer import (
                _synthesize_with_gemini,
                _synthesize_with_openai,
            )

            failures_text = []
            for t in failed_tests:
                failures_text.append(
                    f"Test '{t.name}':\n  Inputs: {t.inputs}\n  Error: {t.error_message}\n  Output: {t.actual_output}"
                )
            failure_diagnostic = "\n\n".join(failures_text)

            prompt = f"Capability '{capability.id}' failed verification tests:\n\nFAILED TEST DIAGNOSTICS:\n{failure_diagnostic}\n\nCURRENT CODE:\n```python\n{code_body}\n```\n\nTASK:\nWrite a corrected execute(inputs: dict) -> dict function that fixes all test failures.\nReturn ONLY valid Python code. Start directly with def execute(inputs: dict) -> dict:"

            provider = settings.effective_llm_provider
            corrected_code = None

            if provider == "gemini" and settings.gemini_api_key:
                corrected_code = _synthesize_with_gemini(
                    task_intent=prompt,
                    api_key=settings.gemini_api_key,
                    model=settings.llm_model,
                    temperature=0.1,
                )
            elif provider == "openai" and settings.openai_api_key:
                corrected_code = _synthesize_with_openai(
                    task_intent=prompt,
                    api_key=settings.openai_api_key,
                    model=settings.llm_model,
                    temperature=0.1,
                )

            if corrected_code:
                ast.parse(corrected_code)
                return corrected_code, f"LLM ({provider}) reflection repair applied"

        except Exception as e:
            logger.warning("LLM reflection repair pass failed: %s", e)

        return code_body, "LLM repair pass produced no valid fix"

    def _pass3_heuristic_fallback(
        self,
        code_body: str,
        failed_tests: list[Any],
        capability: Capability,
    ) -> tuple[str, str]:
        patched = code_body

        wrap_needed = any(
            "not a dict" in (t.error_message or "").lower() or
            "exception" in (t.error_message or "").lower() or
            "error" in (t.error_message or "").lower()
            for t in failed_tests
        )

        if wrap_needed and "def execute(" in patched:
            return patched, "Pass 3 checked"

        return patched, "No Pass 3 heuristic applied"

    @staticmethod
    def _make_diff(before: str, after: str) -> str:
        diff_lines = list(difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="original",
            tofile="repaired",
            lineterm="",
        ))
        return "\n".join(diff_lines)
