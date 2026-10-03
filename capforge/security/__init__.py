"""CapForge Security Package.

Three modules that tackle the three unsolved problems of autonomous
code execution systems:

  CodeGuardian    -- Multi-layer static analysis of synthesized code
                     before it is ever stored or executed (5 layers).

  AdversarialTester -- Production parity testing: determinism, environment
                     blindness (sandbox evasion detection), chaos inputs.

  TrustChain      -- Cryptographic code signing and quorum-based promotion
                     gate to prevent learning loop poisoning.

All imports in this __init__ are LAZY (via __getattr__) to prevent the
circular import chain:
  adversarial_tester -> sandbox -> verification/__init__ -> evaluator -> security/__init__
"""

# Maps public name -> module where it lives
_LAZY = {
    "CodeGuardian": "capforge.security.code_guardian",
    "GuardianScanResult": "capforge.security.code_guardian",
    "SecurityViolation": "capforge.security.code_guardian",
    "AdversarialTester": "capforge.security.adversarial_tester",
    "AdversarialTestResult": "capforge.security.adversarial_tester",
    "TrustChain": "capforge.security.trust_chain",
    "TamperDetectedError": "capforge.security.trust_chain",
    "PromotionBlockedError": "capforge.security.trust_chain",
    "get_trust_chain": "capforge.security.trust_chain",
    "TracePrivacyFilter": "capforge.security.privacy_filter",
    "privacy_filter": "capforge.security.privacy_filter",
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module = importlib.import_module(_LAZY[name])
        obj = getattr(module, name)
        # Cache so subsequent access doesn't go through __getattr__ again
        globals()[name] = obj
        return obj
    raise AttributeError(f"module 'capforge.security' has no attribute {name!r}")


__all__ = list(_LAZY.keys())
