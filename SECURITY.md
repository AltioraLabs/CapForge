# Security Policy

CapForge provides runtime governance, security guardrails, and cryptographic provenance for autonomous AI agents. We take security seriously.

---

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.1.x   | :white_check_mark: |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## Security Architecture Overview

CapForge enforces defense-in-depth security at runtime:

1. **Static AST Analysis (`CodeGuardian`)**: All synthesized or acquired capability code is scanned against AST patterns (e.g. forbidden builtins `exec`/`eval`, unauthorized network calls, dangerous imports, environment fingerprinting).
2. **Subprocess & Container Isolation (`SandboxRunner`)**: Code is executed in unprivileged subshells or isolated Docker scratch containers with memory, process, and execution time ceilings.
3. **Adversarial & Chaos Testing (`AdversarialTester`)**: Probes capabilities with blind payload fuzzing, timeout latency injection, and simulated environment variation.
4. **Cryptographic Signatures (`TrustChain`)**: Every approved capability is hashed (SHA-256) and signed with HMAC-SHA256 (`CAPFORGE_SIGNING_KEY`). Any on-disk modification triggers an immediate `TamperDetectedError` before execution.

---

## Reporting a Vulnerability

If you discover a potential security vulnerability in CapForge:

1. **Do NOT report security issues via public GitHub Issues.**
2. Send an email to: **security@capforge.dev** (or contact the maintainer directly via GitHub Security Advisory).
3. Include:
   - Description of the vulnerability.
   - Minimal proof-of-concept (PoC) or reproduction steps.
   - Assessment of potential impact.

### Response Timeline
- **Acknowledgement**: Within 48 hours.
- **Triage & Reproduction**: Within 5 business days.
- **Patch & Advisory**: Coordinated disclosure within 30 days of confirmed fix.
