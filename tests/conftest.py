"""Shared pytest fixtures for the CapForge core test suite.

The API enforces authentication by default (401 without X-CapForge-Key).
The suite exercises business logic — not the auth gate itself, which has
dedicated tests in test_auth_enforcement.py — so tests run in dev mode,
where unauthenticated local requests are tolerated. Auth-negative tests
monkeypatch settings.dev_mode=False explicitly.
"""

import os

os.environ.setdefault("CAPFORGE_DEV_MODE", "true")
