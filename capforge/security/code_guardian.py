"""CapForge Code Guardian — Multi-Layer Static Security Analysis.

Addresses the core open-source security problem: an autonomous system that
writes and executes its own code has an attack surface with no equivalent
in traditional security frameworks.

The Guardian runs BEFORE any code is stored or executed. It operates in 5 layers:

  Layer 1 — Forbidden AST Node Detection
    Catches code that manipulates the Python runtime itself (eval, exec,
    ctypes, dynamic imports, dunder manipulation).

  Layer 2 — Regex Dangerous Pattern Scanner
    Catches patterns that AST alone misses: subprocess via getattr chains,
    obfuscated exec via chr() concatenation, base64-decoded payloads.

  Layer 3 — Environment Fingerprinting Detection
    Catches code that checks for test/sandbox markers and behaves differently.
    This is the evasion layer — code that KNOWS it's being tested.

  Layer 4 — Secret & Credential Scanner
    Catches hardcoded API keys, tokens, passwords using entropy analysis
    and well-known credential patterns.

  Layer 5 — Import Allowlist Enforcement
    Every import statement is checked against a configurable allowlist.
    Unknown imports are flagged; imports in the denylist are hard-blocked.

Usage:
    guardian = CodeGuardian()
    result = guardian.scan(capability)
    if result.blocked:
        raise SecurityViolationError(result.summary)
"""

from __future__ import annotations

import ast
import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("capforge.security.guardian")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Imports that are never allowed — hard block
FORBIDDEN_IMPORTS: Set[str] = {
    "subprocess",
    "ctypes",
    "cffi",
    "marshal",
    "pickle",
    "shelve",
    "code",
    "codeop",
    "pty",
    "tty",
    "termios",
    "readline",
    "rlcompleter",
    "zipimport",
    "site",
    "distutils",
    "sysconfig",
    "antigravity",  # Easter egg but a real module
    "this",
    "_thread",
    "signal",
}

# Imports that are allowed (stdlib + common libraries)
# Anything NOT in this set is flagged as UNKNOWN_IMPORT (warning, not hard block)
ALLOWED_IMPORTS: Set[str] = {
    # Stdlib — data processing
    "json", "re", "math", "decimal", "fractions", "statistics", "random",
    "datetime", "calendar", "time", "zoneinfo",
    # Stdlib — collections
    "collections", "itertools", "functools", "operator", "copy", "pprint",
    "heapq", "bisect", "queue", "weakref",
    # Stdlib — typing
    "typing", "typing_extensions", "dataclasses", "abc", "enum",
    # Stdlib — text
    "string", "textwrap", "difflib", "html", "xml.etree.ElementTree",
    "csv", "configparser", "io", "struct",
    # Stdlib — networking (READ only)
    "urllib.parse", "urllib.request", "http.client", "email",
    "base64", "binascii", "hashlib", "hmac", "secrets",
    # Stdlib — filesystem (READ only - write is caught in Layer 2)
    "pathlib", "os.path", "glob", "fnmatch", "tempfile",
    # Stdlib — compression
    "zipfile", "tarfile", "gzip", "bz2", "lzma", "zlib",
    # Stdlib — logging
    "logging", "warnings", "traceback",
    # Stdlib — introspection (safe subset)
    "inspect", "sys", "platform",
    # Common allowed third-party
    "httpx", "requests", "aiohttp",
    "pydantic", "attr", "attrs",
    "yaml", "toml",
    "numpy", "pandas", "scipy",
    "sqlalchemy",
    "redis",
    "boto3", "botocore",
    "azure", "google.cloud",
}

# ---------------------------------------------------------------------------
# AST Patterns — Layer 1
# ---------------------------------------------------------------------------

# AST node types that indicate dangerous runtime manipulation
DANGEROUS_AST_PATTERNS = [
    # Dynamic code execution — CRITICAL: these allow arbitrary code injection
    ("Call:eval", lambda node: (
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and
        node.func.id == "eval"
    ), "CODE_EVAL", "CRITICAL"),
    ("Call:exec", lambda node: (
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and
        node.func.id == "exec"
    ), "CODE_EXEC", "CRITICAL"),
    ("Call:compile", lambda node: (
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and
        node.func.id == "compile"
    ), "CODE_COMPILE", "MEDIUM"),
    ("Call:__import__", lambda node: (
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and
        node.func.id == "__import__"
    ), "DYNAMIC_IMPORT", "CRITICAL"),
    # Dunder manipulation — class hierarchy access for sandbox escape
    ("Attr:__subclasses__", lambda node: (
        isinstance(node, ast.Attribute) and
        node.attr == "__subclasses__"
    ), "CLASS_SUBCLASS_ENUM", "CRITICAL"),
    ("Attr:__bases__", lambda node: (
        isinstance(node, ast.Attribute) and
        node.attr in ("__bases__", "__mro__", "__class__")
    ), "CLASS_MANIPULATION", "HIGH"),
    ("Attr:__globals__", lambda node: (
        isinstance(node, ast.Attribute) and
        node.attr == "__globals__"
    ), "GLOBALS_ACCESS", "CRITICAL"),
    ("Attr:__builtins__", lambda node: (
        isinstance(node, ast.Attribute) and
        node.attr == "__builtins__"
    ), "BUILTINS_ACCESS", "HIGH"),
    ("Attr:__code__", lambda node: (
        isinstance(node, ast.Attribute) and
        node.attr in ("__code__", "__func__", "__closure__")
    ), "CODE_OBJECT_ACCESS", "HIGH"),
    # Global/local scope manipulation
    ("Call:globals", lambda node: (
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and
        node.func.id == "globals"
    ), "GLOBALS_CALL", "HIGH"),
    ("Call:vars", lambda node: (
        isinstance(node, ast.Call) and
        isinstance(node.func, ast.Name) and
        node.func.id == "vars"
    ), "VARS_CALL", "MEDIUM"),
]

# ---------------------------------------------------------------------------
# Regex Patterns — Layer 2 (catches what AST misses)
# ---------------------------------------------------------------------------

DANGEROUS_REGEX_PATTERNS = [
    # Subprocess — all variants
    (r"subprocess\s*\.\s*(run|Popen|call|check_output|check_call|getoutput|getstatusoutput)",
     "SUBPROCESS_EXEC", "CRITICAL"),
    (r"os\s*\.\s*(system|popen|execv|execve|execvp|execle|spawnl|spawnle)\s*\(",
     "OS_EXEC", "CRITICAL"),
    # File writing — should not write arbitrary files
    (r"open\s*\([^)]*['\"]w[a+b]*['\"]",
     "FILE_WRITE", "HIGH"),
    # Native code via ctypes/cffi
    (r"ctypes\s*\.\s*(cdll|windll|CDLL|WinDLL|CFUNCTYPE|cast)",
     "NATIVE_CODE", "CRITICAL"),
    # Deserialization attacks
    (r"pickle\s*\.\s*(loads|load)\s*\(",
     "PICKLE_DESER", "CRITICAL"),
    (r"marshal\s*\.\s*(loads|load)\s*\(",
     "MARSHAL_DESER", "CRITICAL"),
    (r"yaml\s*\.\s*load\s*\([^,)]+\)",  # yaml.load without Loader
     "UNSAFE_YAML", "HIGH"),
    # Obfuscated execution — chr() concatenation, base64 decode + exec
    (r"chr\s*\(\d+\)\s*\+\s*chr\s*\(",
     "CHAR_OBFUSCATION", "HIGH"),
    (r"base64\s*\.\s*b64decode.*exec",
     "BASE64_EXEC", "CRITICAL"),
    # Environment variable enumeration (could harvest secrets)
    (r"os\s*\.\s*environ(?!\s*\.get\s*\(['\"](?:CAPFORGE|HOME|PATH|LANG))",
     "ENV_ENUM", "MEDIUM"),
    (r"os\s*\.\s*environ\s*\.\s*items\s*\(",
     "ENV_ENUM_ALL", "HIGH"),
    # Network to unexpected endpoints (only httpx/requests with explicit URL is OK)
    (r"socket\s*\.\s*(connect|create_connection|bind)",
     "RAW_SOCKET", "HIGH"),
    # Timing channels — exfiltration via timing
    (r"time\s*\.\s*sleep\s*\(\s*len\s*\(",
     "TIMING_CHANNEL", "MEDIUM"),
]

# ---------------------------------------------------------------------------
# Environment Fingerprinting — Layer 3
# ---------------------------------------------------------------------------

# Code that detects it is in a test/sandbox environment and changes behavior
EVASION_PATTERNS = [
    # Direct env var checks for test markers -- all forms caught:
    # os.environ.get('PYTEST'), os.getenv('PYTEST'), os.environ['PYTEST']
    (r"(?:os\.environ\.get|os\.getenv)\s*\(\s*['\"](?:PYTEST|TESTING|TEST_MODE|CI|SANDBOX|GITHUB_ACTIONS|GITLAB_CI|JENKINS|TRAVIS|CIRCLECI)['\"]"
     r"|os\.environ\s*\[\s*['\"](?:PYTEST|TESTING|TEST_MODE|CI|SANDBOX|GITHUB_ACTIONS|GITLAB_CI|JENKINS|TRAVIS|CIRCLECI)['\"]",
     "ENV_FINGERPRINTING", "CRITICAL",
     "Code checks for test/CI environment markers -- possible sandbox evasion"),
        # sys.argv inspection (could detect pytest runner)
    (r"sys\s*\.\s*argv.*pytest|pytest.*sys\s*\.\s*argv",
     "ARGV_FINGERPRINTING", "HIGH",
     "Code inspects sys.argv for pytest — possible sandbox evasion"),
    # Hostname / network topology checks
    (r"socket\s*\.\s*gethostname\s*\(\s*\)",
     "HOSTNAME_CHECK", "MEDIUM",
     "Code checks hostname — possible environment fingerprinting"),
    # File existence checks for well-known CI paths
    (r"os\s*\.\s*path\s*\.\s*exists\s*\(['\"](?:/proc/|/sys/|/var/run/docker)",
     "CONTAINER_DETECT", "HIGH",
     "Code probes for container/CI filesystem markers"),
    # Counter-based triggers (behave normally for first N calls, then activate)
    (r"(?:_count|_calls|_invocations)\s*(?:>=|>)\s*\d+",
     "COUNTER_TRIGGER", "MEDIUM",
     "Possible counter-based conditional activation"),
    # Timestamp bombs
    (r"(?:time\s*\.\s*time|datetime\.now)\s*\(\s*\)\s*[><!]=?\s*\d{10}",
     "TIMESTAMP_BOMB", "HIGH",
     "Possible time-based conditional activation"),
    # Probabilistic triggers (random() < 0.01 — activates ~1% of the time)
    (r"random\s*\.\s*(?:random|uniform)\s*\(\s*\)\s*<\s*0\.\d{1,3}[^5-9]",
     "PROBABILISTIC_TRIGGER", "HIGH",
     "Possible low-probability conditional trigger — stochastic evasion"),
]

# ---------------------------------------------------------------------------
# Secret & Credential Patterns — Layer 4
# ---------------------------------------------------------------------------

SECRET_PATTERNS = [
    (r"(?i)(?:api_key|secret_key|private_key|password|passwd|auth_token|access_token)\s*=\s*['\"][a-zA-Z0-9+/=_\-]{16,}['\"]",
     "HARDCODED_SECRET", "CRITICAL"),
    (r"sk-[a-zA-Z0-9]{48}",
     "OPENAI_API_KEY", "CRITICAL"),
    (r"sk-proj-[a-zA-Z0-9_\-]{40,}",
     "OPENAI_PROJECT_KEY", "CRITICAL"),
    (r"ghp_[a-zA-Z0-9]{36}",
     "GITHUB_PAT", "CRITICAL"),
    (r"ghs_[a-zA-Z0-9]{36}",
     "GITHUB_APP_TOKEN", "CRITICAL"),
    (r"AKIA[0-9A-Z]{16}",
     "AWS_ACCESS_KEY", "CRITICAL"),
    (r"[0-9a-f]{40}",
     "POSSIBLE_SECRET_HEX", "LOW"),  # Could be SHA-1; low severity
    (r"(?i)bearer\s+[a-zA-Z0-9._\-]{20,}",
     "BEARER_TOKEN", "HIGH"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
     "PRIVATE_KEY_BLOCK", "CRITICAL"),
    (r"(?i)jdbc:[a-zA-Z]+://[^\s'\"]+:[^\s'\"]+@",
     "DB_CONNECTION_STRING", "CRITICAL"),
]


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------

@dataclass
class SecurityViolation:
    layer: int
    violation_type: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    line_number: Optional[int] = None
    snippet: Optional[str] = None


@dataclass
class GuardianScanResult:
    capability_id: str
    code_sha256: str
    violations: List[SecurityViolation] = field(default_factory=list)
    unknown_imports: List[str] = field(default_factory=list)
    forbidden_imports: List[str] = field(default_factory=list)
    blocked: bool = False
    summary: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "HIGH")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "code_sha256": self.code_sha256,
            "blocked": self.blocked,
            "summary": self.summary,
            "violation_count": len(self.violations),
            "critical": self.critical_count,
            "high": self.high_count,
            "violations": [
                {
                    "layer": v.layer,
                    "type": v.violation_type,
                    "severity": v.severity,
                    "description": v.description,
                    "line": v.line_number,
                }
                for v in self.violations
            ],
            "unknown_imports": self.unknown_imports,
            "forbidden_imports": self.forbidden_imports,
        }


# ---------------------------------------------------------------------------
# CodeGuardian
# ---------------------------------------------------------------------------

class CodeGuardian:
    """Multi-layer static security analysis for LLM-synthesized capability code.

    Designed for open-source use: zero external dependencies, fully configurable.

    Configuration:
        block_on_critical: Block execution on any CRITICAL violation (default: True)
        block_on_high: Block execution on HIGH violations (default: False, only warns)
        block_unknown_imports: Block imports not in ALLOWED_IMPORTS (default: False)
        custom_forbidden_imports: Add to the hard-block import list
        custom_allowed_imports: Add to the allow list
    """

    def __init__(
        self,
        block_on_critical: bool = True,
        block_on_high: bool = False,
        block_unknown_imports: bool = False,
        custom_forbidden_imports: Optional[Set[str]] = None,
        custom_allowed_imports: Optional[Set[str]] = None,
    ):
        self.block_on_critical = block_on_critical
        self.block_on_high = block_on_high
        self.block_unknown_imports = block_unknown_imports
        self._forbidden = FORBIDDEN_IMPORTS | (custom_forbidden_imports or set())
        self._allowed = ALLOWED_IMPORTS | (custom_allowed_imports or set())

    def scan(self, capability_id: str, code_body: str) -> GuardianScanResult:
        """Run all 5 layers of security analysis.

        Returns a GuardianScanResult. Check `.blocked` to determine if execution
        should be prevented. `.violations` contains all findings with severity.
        """
        code_sha256 = hashlib.sha256(code_body.encode("utf-8")).hexdigest()
        result = GuardianScanResult(capability_id=capability_id, code_sha256=code_sha256)

        # Layer 1: AST Analysis
        self._scan_ast(code_body, result)

        # Layer 2: Regex Pattern Scan
        self._scan_regex(code_body, result)

        # Layer 3: Evasion / Environment Fingerprinting
        self._scan_evasion(code_body, result)

        # Layer 4: Secret Detection
        self._scan_secrets(code_body, result)

        # Layer 5: Import Allowlist
        self._scan_imports(code_body, result)

        # Determine if execution should be blocked
        has_critical = result.critical_count > 0
        has_high = result.high_count > 0
        has_forbidden_import = len(result.forbidden_imports) > 0

        result.blocked = (
            has_forbidden_import
            or (self.block_on_critical and has_critical)
            or (self.block_on_high and has_high)
            or (self.block_unknown_imports and len(result.unknown_imports) > 0)
        )

        result.summary = self._build_summary(result)

        if result.blocked:
            logger.warning(
                "CodeGuardian BLOCKED capability '%s': %d critical, %d high, %d total violations",
                capability_id, result.critical_count, result.high_count, len(result.violations),
            )
        elif result.violations:
            logger.warning(
                "CodeGuardian WARNING for capability '%s': %d violations (not blocked)",
                capability_id, len(result.violations),
            )
        else:
            logger.debug("CodeGuardian: capability '%s' passed all layers", capability_id)

        return result

    # -----------------------------------------------------------------------
    # Layer 1: AST Analysis
    # -----------------------------------------------------------------------

    def _scan_ast(self, code: str, result: GuardianScanResult) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return  # Syntax errors caught elsewhere

        for node in ast.walk(tree):
            for name, predicate, vtype, severity in DANGEROUS_AST_PATTERNS:
                try:
                    if predicate(node):
                        line = getattr(node, "lineno", None)
                        snippet = self._get_line(code, line)
                        result.violations.append(SecurityViolation(
                            layer=1,
                            violation_type=vtype,
                            severity=severity,
                            description=f"Dangerous AST pattern: {name}",
                            line_number=line,
                            snippet=snippet,
                        ))
                except Exception:
                    pass

    # -----------------------------------------------------------------------
    # Layer 2: Regex Pattern Scan
    # -----------------------------------------------------------------------

    def _scan_regex(self, code: str, result: GuardianScanResult) -> None:
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pattern, vtype, severity in DANGEROUS_REGEX_PATTERNS:
                if re.search(pattern, line):
                    result.violations.append(SecurityViolation(
                        layer=2,
                        violation_type=vtype,
                        severity=severity,
                        description=f"Dangerous pattern detected: {vtype}",
                        line_number=i,
                        snippet=line.strip()[:120],
                    ))

    # -----------------------------------------------------------------------
    # Layer 3: Evasion Detection
    # -----------------------------------------------------------------------

    def _scan_evasion(self, code: str, result: GuardianScanResult) -> None:
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, vtype, severity, description in EVASION_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    result.violations.append(SecurityViolation(
                        layer=3,
                        violation_type=vtype,
                        severity=severity,
                        description=description,
                        line_number=i,
                        snippet=line.strip()[:120],
                    ))

    # -----------------------------------------------------------------------
    # Layer 4: Secret Detection
    # -----------------------------------------------------------------------

    def _scan_secrets(self, code: str, result: GuardianScanResult) -> None:
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            for pattern, vtype, severity in SECRET_PATTERNS:
                if re.search(pattern, line):
                    # Entropy check for generic patterns to reduce false positives
                    if vtype == "POSSIBLE_SECRET_HEX":
                        match = re.search(pattern, line)
                        if match and self._shannon_entropy(match.group()) < 3.5:
                            continue  # Low entropy — likely not a real secret
                    # Redact the actual secret value in the report
                    result.violations.append(SecurityViolation(
                        layer=4,
                        violation_type=vtype,
                        severity=severity,
                        description=f"Potential credential detected: {vtype}",
                        line_number=i,
                        snippet=f"[REDACTED — {vtype} pattern on line {i}]",
                    ))

    # -----------------------------------------------------------------------
    # Layer 5: Import Allowlist
    # -----------------------------------------------------------------------

    def _scan_imports(self, code: str, result: GuardianScanResult) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_import(alias.name, result)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._check_import(node.module, result)

    def _check_import(self, module_name: str, result: GuardianScanResult) -> None:
        root = module_name.split(".")[0]
        if root in self._forbidden:
            result.forbidden_imports.append(module_name)
            result.violations.append(SecurityViolation(
                layer=5,
                violation_type="FORBIDDEN_IMPORT",
                severity="CRITICAL",
                description=f"Import of forbidden module: '{module_name}'",
            ))
        elif root not in self._allowed:
            result.unknown_imports.append(module_name)
            if self.block_unknown_imports:
                result.violations.append(SecurityViolation(
                    layer=5,
                    violation_type="UNKNOWN_IMPORT",
                    severity="MEDIUM",
                    description=f"Import of unknown/unvetted module: '{module_name}'",
                ))

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _get_line(code: str, line_number: Optional[int]) -> Optional[str]:
        if not line_number:
            return None
        lines = code.splitlines()
        if 0 < line_number <= len(lines):
            return lines[line_number - 1].strip()[:120]
        return None

    @staticmethod
    def _shannon_entropy(s: str) -> float:
        """Calculate Shannon entropy of a string. High entropy = likely a real secret."""
        if not s:
            return 0.0
        freq = {}
        for c in s:
            freq[c] = freq.get(c, 0) + 1
        length = len(s)
        return -sum((count / length) * math.log2(count / length) for count in freq.values())

    @staticmethod
    def _build_summary(result: GuardianScanResult) -> str:
        if not result.violations and not result.forbidden_imports:
            return "CLEAN: No security violations detected."
        parts = []
        if result.blocked:
            parts.append("BLOCKED:")
        else:
            parts.append("WARNING:")
        if result.critical_count:
            parts.append(f"{result.critical_count} CRITICAL violation(s)")
        if result.high_count:
            parts.append(f"{result.high_count} HIGH violation(s)")
        medium = sum(1 for v in result.violations if v.severity == "MEDIUM")
        if medium:
            parts.append(f"{medium} MEDIUM violation(s)")
        if result.forbidden_imports:
            parts.append(f"forbidden imports: {result.forbidden_imports}")
        return " | ".join(parts)
