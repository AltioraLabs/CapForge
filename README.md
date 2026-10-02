# SkillForge

### Autonomous Capability Acquisition, Verification, and Evolution Runtime for AI Agents

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-red.svg)](https://docs.pydantic.dev/)

> **The Core Thesis**: Current agents repeatedly rediscover solutions or rely on static tool libraries. When encountering unfamiliar APIs, schemas, or complex multi-step procedures, they fail or produce fragile one-off hallucinations. **SkillForge** introduces **Capability Lifecycle Management (CLM)**: a runtime infrastructure layer that allows agents to detect capability deficiencies, acquire missing procedures and tool wrappers, construct structured capabilities, validate them against generated multi-gate test batteries in isolated sandboxes, version them with strict regression safeguards, and compose primitives over time—**all without modifying the underlying LLM weights.**

---

## 1. Executive Positioning & The 2026 Landscape

Existing research has explored singular segments of agent learning:
- **Reflexion (2023)**: Stores verbal feedback in episodic memory to avoid repeating mistakes, but does not construct permanent executable capabilities.
- **Voyager (2023)**: Continuously acquires executable code skills inside Minecraft, but is tightly coupled to an embodied game simulator and lacks generalized API/tool lifecycles.
- **Trace2Skill (2026)**: Distills execution traces into skill patches and unified skills, focusing on trajectory mining rather than proactive gap discovery and sandbox validation.
- **SkillOpt (2026)**: Optimizes existing skill prompt documents as trainable parameters via held-out validation, assuming the skill already exists.
- **SkillMaster (2026)**: Explores autonomous skill mastery via trajectory probe tasks as an offline training framework.
- **OpenSkill (2026)**: Discovers open-world knowledge and drafts skills with self-built verifiers, but lacks persistent lifecycle governance, multi-version regression guarantees, and modular composition.
- **SkillSmith (2026)**: Co-evolves skills and tools, but leaves open runtime capability lifecycle management, backward-compatibility regression suites, and production deployment boundaries.

### Comparative Positioning Matrix

| System | Primary Paradigm | Capability Gap Detection | Tool Acquisition / Wrapper | Multi-Gate Sandbox Verification | Versioning & Regression Protection | Lifelong Composition |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Reflexion** | Episodic verbal reflection | ❌ | ❌ | ❌ (Outcome-only) | ❌ | ❌ |
| **Voyager** | Lifelong code synthesis | Domain events | Minecraft primitives | ✅ (Simulator feedback) | Minimal (vector append) | ⚠️ (Code reuse) |
| **Trace2Skill** | Trajectory distillation | ❌ (Post-hoc) | ❌ | ⚠️ (Held-out trajectories) | ❌ | ⚠️ (Hierarchical) |
| **SkillOpt** | Skill document optimization | ❌ | ❌ | ✅ (Held-out tasks) | ⚠️ (Validation loss) | ❌ |
| **SkillMaster** | Skill exploration training | ⚠️ (Probe tasks) | ❌ | ✅ (Probe score) | ❌ | ❌ |
| **OpenSkill** | Open-world acquisition | ⚠️ (Task failure) | ⚠️ (Indirect) | ✅ (Self-built virtual tests) | ❌ | ❌ |
| **SkillSmith** | Co-evolution (Skill + Tool) | ⚠️ | ✅ (Create/wrap/split) | ✅ (Execution logs) | ⚠️ (Tool memory) | ⚠️ |
| **SkillForge (Ours)**| **Capability Lifecycle Management (CLM)** | **✅ (Proactive decomposition)** | **✅ (Schema discovery & wrapping)** | **✅ (Multi-test generated gates)** | **✅ (Deterministic regression suite)** | **✅ (Dependency graph composition)** |

---

## 2. Core Architecture: The Capability Lifecycle Loop

```
┌──────────────────────────────────────────────┐
│             CAPABILITY LIFECYCLE             │
│                                              │
│  Discover → Acquire → Construct → Validate   │
│     ↑                                 ↓      │
│     │                              Deploy    │
│     │                                 ↓      │
│  └────── Learn ← Execute ← Monitor    │
│                                       │
│          Version / Rollback / Retire         │
└──────────────────────────────────────────────┘
```

```
USER TASK
  │
  ▼
┌───────────────────────┐
│  Capability Analyzer  │
└───────────┬───────────┘
            │ What is missing?
            ▼
┌───────────────────────┐
│  Capability Registry  │
└───────────┬───────────┘
            │
      ┌─────┴─────┐
      │           │
   EXISTS    DOESN'T EXIST
      │           │
      │           ▼
      │    Acquisition Engine
      │    ┌──────┼──────┐
      │    ▼      ▼      ▼
      │   Web    Docs  GitHub
      │    │      │      │
      │    └──────┼──────┘
      │           ▼
      │    Candidate Skill
      │           ▼
      │     Tool Discovery
      │           ▼
      │   Test Generator
      │           ▼
      │  Execution Sandbox
      │           ▼
      │  Capability Evaluator
      │     ┌─────┴─────┐
      │     ▼           ▼
      │   PASS        FAIL
      │     │           │
      │     ▼           ▼
      │  Register v1  Diagnose
      │     │           │
      │     ▼           ▼
      │  Production   Repair Loop
      │     │
      │     ▼
      │  Capability Memory
      │     │
      │     ▼
      │  Version Manager & Regression Battery (v1 -> v2 -> v3)
      │
      ▼
┌──────────────┐
│  Execution   │
└──────────────┘
```

---

## 3. The Core Abstraction: Structured Capability Object

Instead of unstructured prompt markdown or loose scripts, SkillForge defines capabilities as validated, versioned Pydantic objects:

```yaml
id: cap_github_dependency_audit
name: GitHub Dependency Vulnerability & Freshness Auditor
version: "1.2.0"
status: ACTIVE # EXPERIMENTAL | ACTIVE | DEPRECATED | QUARANTINED
created_at: "2026-10-03T00:00:00Z"
updated_at: "2026-10-03T00:12:00Z"

metadata:
  domain: "software_engineering.security"
  author: "SkillForge.AcquisitionEngine"
  confidence_score: 0.94
  avg_execution_latency_ms: 1420
  success_rate: 0.96

dependencies:
  capabilities:
    - id: "cap_http_rest_client"
      version_constraint: ">=1.0.0"
    - id: "cap_manifest_parser"
      version_constraint: ">=2.1.0"
  system_tools:
    - name: "bash_sandbox"
      permissions: ["network_egress", "read_fs"]
    - name: "python_interpreter"
      version: ">=3.11"

interface:
  inputs:
    repo_url:
      type: "string"
      format: "uri"
      description: "Target repository URL"
    manifest_types:
      type: "array"
      items: ["requirements.txt", "pyproject.toml", "package.json"]
      default: ["pyproject.toml"]
    fail_on_vulnerability:
      type: "boolean"
      default: false
  outputs:
    total_dependencies: "integer"
    outdated_count: "integer"
    vulnerabilities: "array"
    report_markdown: "string"

procedure:
  execution_mode: "CODE" # CODE | PROMPT | HYBRID
  entrypoint_function: "execute"
  code_body: |
    def execute(inputs: dict) -> dict:
        # Validated execution logic
        ...

verification:
  test_cases:
    - id: "test_poetry_pyproject"
      test_type: "HAPPY_PATH"
      inputs: {"repo_url": "mock://repos/standard_poetry"}
      assert_expression: "output['status'] == 'SUCCESS'"
    - id: "test_missing_manifest_handling"
      test_type: "EDGE_CASE"
      inputs: {"repo_url": "mock://repos/empty_repo"}
      assert_expression: "output['status'] == 'FAILED'"
    - id: "test_vulnerable_cve_flagging"
      test_type: "SECURITY_INVARIANT"
      inputs: {"repo_url": "mock://repos/cve_vulnerable_project"}
      assert_expression: "isinstance(output['vulnerabilities'], list)"
```

---

## 4. Key Subsystems

### 1. Capability Gap Detector (`skillforge.discovery`)
Proactively decomposes tasks into required primitives and cross-references active registry capabilities. Prevents catastrophic task execution failures before they happen.

### 2. Autonomous Acquisition Engine (`skillforge.acquisition`)
Fetches OpenAPI schemas, documentation, and SDK code. Synthesizes executable Python code, wraps HTTP tools, and formulates candidate parameter interfaces.

### 3. Verification & Sandbox Engine (`skillforge.verification`)
- **Automated Test Generator**: Synthesizes 3 distinct test classes: Happy Path, Boundary/Edge Cases, and Invariants.
- **Isolated Sandbox Runner**: Enforces strict execution containment, process separation, and execution timeout budgets.
- **Closed-Loop Auto-Repair**: Intercepts tracebacks and failure assertions, diagnoses root causes, and generates targeted code patches.

### 4. Versioning & Regression Protection (`skillforge.versioning`)
Enforces semantic versioning. When promoting a new version ($v_{n+1}$), the runner automatically executes the historical regression test battery of all earlier versions ($v_1 \dots v_n$). If a fix to Task 7 breaks Task 1, **promotion is blocked**.

### 5. Composition Engine (`skillforge.runtime.composition`)
Maintains a bank of verified primitives (`auth_bearer`, `cursor_pagination`, `rate_limit_backoff`, `anomaly_detector`). When subsequent unfamiliar tasks arrive, SkillForge composes existing primitives rather than rediscovering them from scratch.

---

## 5. Quickstart & Installation

Always use a Python virtual environment:

```bash
# 1. Clone repository
git clone https://github.com/your-org/SkillForge.git
cd SkillForge

# 2. Set up virtual environment
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Install dependencies and SkillForge in editable mode
pip install -r requirements.txt
pip install -e .
```

---

## 6. Running Tests & The Killer Demo

### Run Full Test Battery
```bash
pytest -v
```

### Run the Killer Demo
Demonstrates the full lifecycle across two unfamiliar external APIs:
```bash
python examples/killer_demo.py
```

### CLI Commands
```bash
# List all active registered capabilities
skillforge list

# Analyze a user task for capability gaps
skillforge analyze "Extract telemetry metrics and audit CPU anomaly thresholds from QuantumMetrics API"

# Run sandbox verification on a registered capability
skillforge test quantummetrics_telemetry_audit

# Launch the FastAPI REST Server
skillforge serve --port 8000
```

---

## 7. Experimental Evaluation Metrics

SkillForge provides a rigorous benchmarking framework:
1. **Capability Acquisition Rate**: Proportion of unfamiliar tasks successfully turned into active capabilities.
2. **Skill Transfer & Composition**: Speed and token-cost savings when composing previously learned primitives on unseen tasks.
3. **Regression Rate**: Frequency of updates breaking historical test batteries (targeted at 0%).
4. **Self-Healing Recovery Rate**: Percentage of failing candidate capabilities automatically repaired via closed-loop feedback.
5. **Lifelong Capability Preservation**: Long-term preservation of capability bank integrity across diverse task distributions.

---

## 8. License

Apache License 2.0. See [LICENSE](LICENSE) for details.
