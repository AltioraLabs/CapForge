"""CapForge Trace Privacy Filter & Data Sanitization Layer.

Implements the Trace Privacy Layer (discussion.mdx §13, §17; SPECIFICATION §17, §26 #13)
to detect and redact credentials, API keys, private tokens, and PII from
agent execution traces before they enter the learning, evaluation, or storage pipeline.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from capforge.core.models import AgentEvent


class TracePrivacyFilter:
    """Detects and redacts sensitive credentials and PII from traces, events, and text payloads."""

    # Regex patterns for API keys and secrets
    SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        # Anthropic API Keys (must precede generic sk- pattern)
        (re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
        # OpenAI API Keys
        (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "[REDACTED_OPENAI_KEY]"),
        # AWS Access Key ID
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
        # GitHub Personal Access Tokens
        (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"), "[REDACTED_GITHUB_TOKEN]"),
        (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), "[REDACTED_GITHUB_PAT]"),
        # Google / Gemini API Keys
        (re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b"), "[REDACTED_GOOGLE_KEY]"),
        # Generic Bearer tokens
        (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{25,}\b"), "Bearer [REDACTED_TOKEN]"),
        # Private Keys (RSA, EC, DSA, OpenSSH)
        (
            re.compile(
                r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
            ),
            "[REDACTED_PRIVATE_KEY]",
        ),
        # Database URIs with credentials
        (
            re.compile(r"(?:postgres|postgresql|mysql|mongodb|redis)://([^:\s]+):([^@\s]+)@"),
            r"\1:[REDACTED_DB_PASSWORD]@",
        ),
    ]

    # Regex patterns for PII
    PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        # Email Addresses
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
        # US Social Security Numbers
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
        # Credit Card Numbers (13-16 digits with dashes or spaces)
        (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CREDIT_CARD]"),
        # Phone numbers (US / E.164 formats)
        (re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"), "[REDACTED_PHONE]"),
        # IPv4 Addresses (private and public)
        (
            re.compile(
                r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
            ),
            "[REDACTED_IP]",
        ),
    ]

    # Sensitive dictionary key names (case-insensitive substring or exact match)
    SENSITIVE_KEYS: frozenset[str] = frozenset(
        {
            "password",
            "passwd",
            "secret",
            "api_key",
            "apikey",
            "token",
            "access_token",
            "refresh_token",
            "auth",
            "authorization",
            "private_key",
            "client_secret",
            "x-api-key",
            "bearer",
        }
    )

    def __init__(self, redact_pii: bool = True, redact_secrets: bool = True) -> None:
        self.redact_pii = redact_pii
        self.redact_secrets = redact_secrets

    def sanitize_text(self, text: str) -> str:
        """Sanitizes raw text by substituting detected secrets and PII."""
        if not text or not isinstance(text, str):
            return text

        result = text

        if self.redact_secrets:
            for pattern, replacement in self.SECRET_PATTERNS:
                result = pattern.sub(replacement, result)

        if self.redact_pii:
            for pattern, replacement in self.PII_PATTERNS:
                result = pattern.sub(replacement, result)

        return result

    def sanitize_data(self, data: Any) -> Any:
        """Recursively sanitizes nested dictionaries, lists, strings, and primitives."""
        if isinstance(data, str):
            return self.sanitize_text(data)

        if isinstance(data, dict):
            cleaned_dict: dict[str, Any] = {}
            for k, v in data.items():
                k_str = str(k).lower()
                # If value is a nested container, always recurse
                if isinstance(v, (dict, list, tuple, set)):
                    cleaned_dict[k] = self.sanitize_data(v)
                elif any(sk in k_str for sk in self.SENSITIVE_KEYS):
                    cleaned_dict[k] = "[REDACTED_SECRET]"
                else:
                    cleaned_dict[k] = self.sanitize_data(v)
            return cleaned_dict

        if isinstance(data, list):
            return [self.sanitize_data(item) for item in data]

        if isinstance(data, tuple):
            return tuple(self.sanitize_data(item) for item in data)

        if isinstance(data, set):
            return {self.sanitize_data(item) for item in data}

        return data

    def sanitize_event(self, event: AgentEvent) -> AgentEvent:
        """Returns a sanitized copy of an AgentEvent with all sensitive contents redacted."""
        clean_event = copy.deepcopy(event)

        if clean_event.input_data is not None:
            clean_event.input_data = self.sanitize_data(clean_event.input_data)

        if clean_event.output_data is not None:
            clean_event.output_data = self.sanitize_data(clean_event.output_data)

        if clean_event.error_message is not None:
            clean_event.error_message = self.sanitize_text(clean_event.error_message)

        if clean_event.metadata:
            clean_event.metadata = self.sanitize_data(clean_event.metadata)

        return clean_event


# Global default instance
privacy_filter = TracePrivacyFilter()
