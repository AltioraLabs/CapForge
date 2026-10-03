"""SSRF Guard for outbound server-side requests (webhook subscriptions).

Validates webhook target URLs at registration time so the CapForge server can
never be turned into a request-forgery proxy:
  - Only http:// and https:// schemes are allowed.
  - Hostnames are DNS-resolved and every resolved IP must be globally routable,
    unless private/loopback nets are explicitly permitted via
    CAPFORGE_WEBHOOK_ALLOW_PRIVATE=true (local development and tests).
  - Cloud metadata endpoints are ALWAYS blocked, even when private nets are
    permitted (169.254.169.254, metadata.google.internal, etc.).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger("capforge.security.ssrf")

_ALWAYS_BLOCKED_IPS = {
    "169.254.169.254",  # AWS / GCP / Azure instance metadata
    "169.254.169.123",  # alternate metadata service
    "100.100.100.200",  # Alibaba Cloud metadata
}
_ALWAYS_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "instance-data-compute",
}


class SSRFBlockedError(ValueError):
    """Raised when a webhook target URL fails SSRF validation."""


def redact_url(url: str) -> str:
    """Strip query strings and fragments for safe logging.

    Query parameters routinely carry tokens (e.g. ?token=...); the full URL
    is still used for delivery, but logs and audit records must not retain it.
    """
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        if not parts.query and not parts.fragment:
            return url
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return "[unparseable-url]"


def _all_ips_private_ok() -> bool:
    """Local import to avoid circulars: read the operator setting lazily."""
    from capforge.core.config import settings

    return settings.webhook_allow_private_nets


def validate_webhook_url(url: str, allow_private: bool | None = None) -> str:
    """Validate a webhook subscription URL. Returns the URL if safe.

    Raises SSRFBlockedError with a non-leaking reason otherwise.
    """
    if not isinstance(url, str) or not url.strip():
        raise SSRFBlockedError("webhook url must be a non-empty string")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(f"webhook url scheme must be http or https, got '{parsed.scheme}'")
    if parsed.username or parsed.password:
        # Credentials embedded in URLs end up in logs, delivery records, and
        # error messages. Use the HMAC secret field instead.
        raise SSRFBlockedError("webhook url must not embed userinfo credentials; use the secret field")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise SSRFBlockedError("webhook url has no hostname")
    if host in _ALWAYS_BLOCKED_HOSTS:
        raise SSRFBlockedError("webhook url targets a blocked cloud metadata host")

    try:
        addrinfo = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except OSError:
        raise SSRFBlockedError("webhook url hostname does not resolve") from None

    allow_private = _all_ips_private_ok() if allow_private is None else allow_private
    for family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFBlockedError("webhook url resolves to an invalid address") from None
        if ip_str in _ALWAYS_BLOCKED_IPS:
            raise SSRFBlockedError("webhook url targets a blocked cloud metadata address")
        if not ip.is_global:
            if not allow_private:
                raise SSRFBlockedError(
                    "webhook url resolves to a non-public address; "
                    "set CAPFORGE_WEBHOOK_ALLOW_PRIVATE=true for local receivers"
                )
            logger.debug("SSRF guard permitting private webhook target %s (explicitly allowed)", ip_str)
    return url.strip()
