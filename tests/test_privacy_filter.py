"""Tests for CapForge Trace Privacy Filter & Data Sanitization Layer."""

from capforge.core.events import EventGateway
from capforge.core.models import AgentEvent, EventType
from capforge.security.privacy_filter import TracePrivacyFilter


def test_redact_api_keys_and_tokens():
    filter_ = TracePrivacyFilter()

    text = (
        "OpenAI: sk-proj-1234567890abcdef1234567890\n"
        "Anthropic: sk-ant-api03-1234567890abcdef1234567890\n"
        "AWS: AKIAIOSFODNN7EXAMPLE\n"
        "GitHub: ghp_1234567890abcdef1234567890abcdef123456\n"
        "Google: AIzaSyA1234567890abcdef1234567890abcdef"
    )

    clean = filter_.sanitize_text(text)
    assert "sk-proj" not in clean
    assert "[REDACTED_OPENAI_KEY]" in clean
    assert "sk-ant" not in clean
    assert "[REDACTED_ANTHROPIC_KEY]" in clean
    assert "AKIAIOSFODNN7EXAMPLE" not in clean
    assert "[REDACTED_AWS_KEY]" in clean
    assert "ghp_" not in clean
    assert "[REDACTED_GITHUB_TOKEN]" in clean
    assert "AIzaSy" not in clean
    assert "[REDACTED_GOOGLE_KEY]" in clean


def test_redact_pii():
    filter_ = TracePrivacyFilter()

    text = (
        "Contact alice.smith@example.org or bob@corp.internal. "
        "SSN is 000-12-3456. Card: 4111 2222 3333 4444. Phone: 555-867-5309."
    )

    clean = filter_.sanitize_text(text)
    assert "alice.smith@example.org" not in clean
    assert "[REDACTED_EMAIL]" in clean
    assert "000-12-3456" not in clean
    assert "[REDACTED_SSN]" in clean
    assert "4111 2222 3333 4444" not in clean
    assert "[REDACTED_CREDIT_CARD]" in clean
    assert "555-867-5309" not in clean
    assert "[REDACTED_PHONE]" in clean


def test_sanitize_nested_data_and_sensitive_keys():
    filter_ = TracePrivacyFilter()

    payload = {
        "user_email": "john.doe@company.com",
        "auth": {
            "api_key": "my-secret-token-123",
            "password": "SuperSecretPassword!",
            "normal_field": "public_data",
        },
        "query": "SELECT * FROM users WHERE email='victim@domain.com'",
        "items": ["token: sk-test1234567890abcdef123456", 42, True],
    }

    sanitized = filter_.sanitize_data(payload)

    assert sanitized["user_email"] == "[REDACTED_EMAIL]"
    assert sanitized["auth"]["api_key"] == "[REDACTED_SECRET]"
    assert sanitized["auth"]["password"] == "[REDACTED_SECRET]"
    assert sanitized["auth"]["normal_field"] == "public_data"
    assert "[REDACTED_EMAIL]" in sanitized["query"]
    assert "[REDACTED_OPENAI_KEY]" in sanitized["items"][0]
    assert sanitized["items"][1] == 42


def test_event_gateway_privacy_integration():
    gateway = EventGateway()

    raw_event = AgentEvent(
        event_type=EventType.TOOL_FAILED,
        agent_id="test_agent",
        tool_name="github_fetcher",
        input_data={"auth_token": "ghp_1234567890abcdef1234567890abcdef123456", "email": "dev@test.org"},
        error_message="Failed connecting with key sk-1234567890abcdef1234567890",
        metadata={"client_secret": "hidden_secret_123"},
    )

    received_events = []
    gateway.subscribe(EventType.TOOL_FAILED, lambda e: received_events.append(e))

    gateway.emit(raw_event)

    assert len(received_events) == 1
    event = received_events[0]
    assert event.input_data["auth_token"] == "[REDACTED_SECRET]"
    assert event.input_data["email"] == "[REDACTED_EMAIL]"
    assert "[REDACTED_OPENAI_KEY]" in event.error_message
    assert event.metadata["client_secret"] == "[REDACTED_SECRET]"
