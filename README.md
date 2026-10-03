# CapForge

### Framework-Agnostic Capability Evolution, Verification, and Evaluation Platform for AI Agents

[![CI](https://github.com/abhay-2108/CapForge/actions/workflows/ci.yml/badge.svg)](https://github.com/abhay-2108/CapForge/actions/workflows/ci.yml)
[![Version: 1.1.0](https://img.shields.io/badge/version-1.1.0-blue.svg)](versions.mdx)
[![Python: 3.10 | 3.11 | 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tests: 178/178 Passed](https://img.shields.io/badge/tests-178%2F178%20Passed%20(100%25)-brightgreen.svg)](tests/)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-red.svg)](https://docs.pydantic.dev/)
[![MCP Native](https://img.shields.io/badge/MCP-JSON--RPC%202.0-purple.svg)](capforge/mcp/)

> **"CapForge turns static AI agents into continuously evolving systems that can discover, acquire, construct, verify, reuse, evaluate, and safely improve their capabilities without retraining their underlying foundation model."**

---

## Table of Contents

- [1. Executive Summary & Positioning](#1-executive-summary--positioning)
  - [The Fundamental Problem](#the-fundamental-problem)
  - [What CapForge IS vs What CapForge IS NOT](#what-capforge-is-vs-what-capforge-is-not)
  - [2026 Competitive Landscape Matrix](#2026-competitive-landscape-matrix)
- [2. Quickstart & Installation (5-Minute Onboarding)](#2-quickstart--installation-5-minute-onboarding)
- [3. The Flagship Killer Demonstration](#3-the-flagship-killer-demonstration)
- [4. Multi-Framework Integration & Adapters](#4-multi-framework-integration--adapters)
  - [OpenAI Agents SDK Adapter](#openai-agents-sdk-adapter)
  - [CrewAI Multi-Agent Adapter](#crewai-multi-agent-adapter)
  - [Standard / LangGraph Agent Adapter](#standard--langgraph-agent-adapter)
  - [Native Model Context Protocol (MCP) Server](#native-model-context-protocol-mcp-server)
- [5. Glassmorphism Control Center Dashboard & REST API](#5-glassmorphism-control-center-dashboard--rest-api)
- [6. Canonical Three-Plane Architecture](#6-canonical-three-plane-architecture)
  - [Plane 1: Execution Plane](#plane-1-execution-plane)
  - [Plane 2: Capability Control Plane](#plane-2-capability-control-plane)
  - [Plane 3: Learning & Verification Plane](#plane-3-learning--verification-plane)
  - [Production vs. Learning Runtime Separation](#production-vs-learning-runtime-separation)
- [7. Capability Ontology & Machine-Readable Manifests](#7-capability-ontology--machine-readable-manifests)
  - [The Five Capability Primitives](#the-five-capability-primitives)
  - [A Skill Is NOT Just a Prompt](#a-skill-is-not-just-a-prompt)
  - [Canonical YAML Manifest Specification](#canonical-yaml-manifest-specification)
- [8. Four-Level Verification Battery](#8-four-level-verification-battery)
- [9. Capability Firewall & Immutable Governance](#9-capability-firewall--immutable-governance)
  - [Runtime Capability Firewall](#runtime-capability-firewall)
  - [Risk Engine & Policy Gates](#risk-engine--policy-gates)
  - [The Core Safety Invariant](#the-core-safety-invariant)
  - [Interactive Human Review Portal](#interactive-human-review-portal)
- [10. Distributed Event Streaming & Resilient Workflows](#10-distributed-event-streaming--resilient-workflows)
  - [Universal Event Model](#universal-event-model)
  - [Distributed Event Stream Broker](#distributed-event-stream-broker)
  - [Durable Resilient Workflow State Machine](#durable-resilient-workflow-state-machine)
- [11. Enterprise RBAC & Dense Vector Hybrid Search](#11-enterprise-rbac--dense-vector-hybrid-search)
  - [Cryptographic API Key Mesh](#cryptographic-api-key-mesh)
  - [Dense Vector Embeddings & Hybrid Search](#dense-vector-embeddings--hybrid-search)
- [12. Production CLI Reference](#12-production-cli-reference)
- [13. Automated Test Battery (109/109 Green)](#13-automated-test-battery-109109-green)
- [14. Repository Layout & Architecture Mapping](#14-repository-layout--architecture-mapping)
- [15. Theoretical Foundations & Research Agenda](#15-theoretical-foundations--research-agenda)
  - [Dual System Loops](#dual-system-loops)
  - [Independent Evaluation Layer](#independent-evaluation-layer)
  - [Research Metrics](#research-metrics)
- [16. License & Community](#16-license--community)

---

## 1. Executive Summary & Positioning

### The Fundamental Problem

Today's agent frameworks (**LangGraph, OpenAI Agents SDK, CrewAI, AutoGen, Microsoft Agent Framework**) excel at reasoning, planning, calling tools, and managing memory. However, **their capabilities are largely determined at deployment time**.

When an agent encounters an unfamiliar API, schema, command-line tool, or diagnostic problem:

```text
Agent  ──>  New Task  ──>  Capability Gap  ──>  Fragile Trial-and-Error  ──>  Task Ends (Lost Experience)
```

The experience is almost never converted into a **verified, reusable, and version-controlled capability**.

CapForge bridges this architectural chasm:

```text
Existing Agent  +  CapForge  ──>  Continuously Evolving Agent
```

CapForge acts as an autonomous capability evolution layer that sits alongside existing agents without requiring fine-tuning or retraining of the underlying foundation models.

---

### What CapForge IS vs What CapForge IS NOT

| CapForge IS | CapForge IS NOT |
| :--- | :--- |
| **Capability acquisition infrastructure** | Not a foundation model or LLM replacement |
| **Closed-loop skill & tool verification** | Not an agent orchestration framework (LangGraph, CrewAI) |
| **Four-Level evaluation & regression protection** | Not merely a prompt library or marketplace |
| **Capability DAG composition & durable workflows** | Not merely a vector database |
| **Runtime Capability Firewall & governance gates** | Not an unconstrained, self-modifying code execution security hazard |
| **Framework-agnostic adapter mesh (OpenAI, CrewAI, MCP, A2A)** | Not tightly coupled to a single vendor |

The host agent remains responsible for **Reasoning + Planning + Task Execution**.  
CapForge becomes responsible for **Capability Discovery + Acquisition + Verification + Governance + Evolution**.

---

### 2026 Competitive Landscape Matrix

| System | Primary Paradigm | Proactive Gap Detection | Isolated Sandbox Verification | Four-Level Evaluation | Versioning & Zero-Regression Gate | Dependency Graph & Impact Analysis | Multi-Framework Adapters |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Reflexion** (2023) | Verbal reflection memory | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Voyager** (2023) | Lifelong code synthesis | Game-bound | Simulator only | ⚠️ Single run | Minimal (vector append) | ❌ | ❌ |
| **Trace2Skill** (2026) | Trajectory distillation | ❌ (Post-hoc) | ⚠️ Trajectory replay | ⚠️ Held-out only | ❌ | ⚠️ Hierarchical | ❌ |
| **SkillOpt** (2026) | Prompt optimization | ❌ | ❌ | ⚠️ Held-out tasks | ⚠️ Validation loss | ❌ | ❌ |
| **OpenSkill** (2026) | Open-world acquisition | ⚠️ Failure trigger | ⚠️ Virtual test | ⚠️ Self-built verifier | ❌ | ❌ | ❌ |
| **SkillSmith** (2026) | Co-evolution (Skill + Tool) | ⚠️ | ⚠️ In-process exec | ⚠️ Test logs | ⚠️ Tool memory | ⚠️ | ❌ |
| **CapForge (v1.0.0 GA)**| **Capability Lifecycle Management (CLM)** | **✅ (Proactive AST decomposition)** | **✅ (Subprocess & Container Isolation)** | **✅ (L1 Struct, L2 Func, L3 Gen, L4 Reg)** | **✅ (SemVer + Zero Regression Gate)** | **✅ (Transitive impact & cycle detection)** | **✅ (OpenAI, CrewAI, LangGraph, MCP, A2A)** |

---

## 2. Quickstart & Installation (5-Minute Onboarding)

### Prerequisites
- Python 3.10, 3.11, or 3.12
- Recommended: Windows, macOS, or Linux with standard CPython runtime

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/abhay-2108/CapForge.git
cd CapForge

# Create and activate virtual environment
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

### 2. Install Dependencies

You can install CapForge directly from GitHub:

```bash
# Install directly via pip
pip install git+https://github.com/abhay-2108/CapForge.git

# Or install locally for development
pip install -r requirements.txt
pip install -e ".[dev]"
```

> **Quickstart Example**: See [`examples/integration_quickstart.py`](examples/integration_quickstart.py) for runnable code demonstrating all 4 developer integration paths in under 60 lines.

### 3. Run Production Health Diagnostics

```bash
# Verify system integrity, WAL database concurrency, and sandbox execution
capforge health
```

Output:
```text
+--------------------------------------------------+
| CapForge Enterprise Diagnostics & Health Suite |
+--------------------------------------------------+
+-----------------------------------------------------------------------------+
| Subsystem          | Status | Details                                       |
|--------------------+--------+-----------------------------------------------|
| SQLite Storage     | PASS   | Path: capforge.db, Journal Mode: WAL        |
| Subprocess Sandbox | PASS   | Execution verified in 214.2ms                 |
| Docker Sandbox     | INFO   | Docker daemon inactive; fallback to sandbox   |
| Stream Broker      | PASS   | In-memory ring buffer operational             |
| Governance Queue   | PASS   | 0 tickets pending human review                |
+-----------------------------------------------------------------------------+
```

---

## 3. The Flagship Killer Demonstration

The flagship demonstration proves the complete **autonomous capability acquisition, instant reuse, generalization transfer, and self-healing evolution loop** for software engineering agents:

```bash
# Run via CLI
capforge demo

# Or execute script directly
python examples/killer_demo.py
```

```text
╭──────────────────────────────────────────────────────────────────────────────╮
│ CapForge Killer Demonstration                                              │
│ Autonomous Capability Acquisition & Evolution for Software Engineering Agents │
╰──────────────────────────────────────────────────────────────────────────────╯

Initial Agent Capabilities:
  [OK] Python Code Analysis (v1.0.0)
  [OK] Code Testing
  [X] Kubernetes Incident Analysis (MISSING)

╭────────────────────────── Step 1: Gap Encountered ───────────────────────────╮
│ Task 1: "Analyze this Kubernetes incident and identify the root cause."      │
╰──────────────────────────────────────────────────────────────────────────────╯
--> Gap Detected: Missing primitives: ['http_request_handler', 'response_parser', 'generic_service_general']
--> Autonomous Acquisition Triggered: Collecting evidence from cluster diagnostic patterns...
--> Four-Level Verification Result: Passed: True (L1: 100%, L2: 100%, L3: 100%, L4: 100%)
--> Risk Gate Passed: Risk=LOW, Auto-Promote=True
--> PROMOTED TO REGISTRY: k8s_incident_rca v1.0.0
╭──────────────────────── Task 1 Resolved Successfully ────────────────────────╮
│ Root Cause: CONTAINER_OOM_KILLED (Confidence: 0.95, Latency: 209.3ms)        │
╰──────────────────────────────────────────────────────────────────────────────╯

╭──────────────────────────── Step 2: Skill Reuse ─────────────────────────────╮
│ Task 2: "Diagnose pod stuck in CrashLoopBackOff in checkout service"         │
╰──────────────────────────────────────────────────────────────────────────────╯
--> Gap Detected: FALSE -- Registry match found: k8s_incident_rca (v1.0.0)
--> Immediate Reuse: No re-synthesis needed! Reusing verified capability.
╭───────────────────────── Task 2 Resolved via Reuse ──────────────────────────╮
│ Root Cause: CRASH_LOOP_BACKOFF (Status: SUCCESS in 229.4ms)                  │
╰──────────────────────────────────────────────────────────────────────────────╯

╭────────────────────── Step 3: Transfer Generalization ───────────────────────╮
│ Task 3: "Diagnose worker pod killed during batch data pipeline"              │
╰──────────────────────────────────────────────────────────────────────────────╯
--> Transfer Success: Diagnosed NODE_MEMORY_PRESSURE (Confidence: 0.88)

╭────────────── Step 4: Failure Encounter & Evolution (v1 -> v2) ──────────────╮
│ Task 4: "Diagnose deployment failure with webhook admission rejection"       │
╰──────────────────────────────────────────────────────────────────────────────╯
--> Initial v1 Execution on Novel Problem: Output root_cause=UNKNOWN
--> Experience Filter: Novel failure detected. Should evolve capability: True
--> Self-Healing Evolution Pipeline Triggered: Synthesizing k8s_incident_rca v2.0.0...
--> Level 4 Historical Regression Test: Passed: True (All v1.0.0 tests still pass!)
--> PROMOTED TO ACTIVE: k8s_incident_rca v2.0.0
╭────────────── Task 4 Resolved by Evolved Capability (v2.0.0)! ───────────────╮
│ Root Cause: ADMISSION_WEBHOOK_TIMEOUT (Confidence: 0.96, Latency: 254.8ms)    │
╰──────────────────────────────────────────────────────────────────────────────╯

======================================================================
KILLER DEMONSTRATION COMPLETE: Full Evolution Loop Proven!
======================================================================
```

---

## 4. Multi-Framework Integration & Adapters

CapForge operates independently of the host agent framework via standardized adapters.

### OpenAI Agents SDK Adapter

CapForge capabilities are automatically translated into OpenAI function tool definitions:

```python
from capforge.adapter.openai_adapter import OpenAIAgentAdapter
from capforge.registry.store import CapabilityRegistry

registry = CapabilityRegistry()
adapter = OpenAIAgentAdapter(registry=registry)

# Generate OpenAI function calling definitions
tools = adapter.get_openai_tools()

# Handle incoming OpenAI tool calls
response_message = adapter.handle_tool_call({
    "id": "call_12345",
    "type": "function",
    "function": {
        "name": "sentiment_analyzer",
        "arguments": '{"text": "CapForge is remarkable!"}'
    }
})
```

---

### CrewAI Multi-Agent Adapter

Expose verified capabilities as native CrewAI tools for autonomous agent crews:

```python
from capforge.adapter.crewai_adapter import CrewAIAgentAdapter
from capforge.registry.store import CapabilityRegistry

registry = CapabilityRegistry()
adapter = CrewAIAgentAdapter(registry=registry)

# Retrieve CrewAI-compatible BaseTool instances
crew_tools = adapter.get_crewai_tools()

# Direct execution or pass to CrewAI Agent(tools=crew_tools)
result = crew_tools[0].run(text="Service degraded")
```

---

### Standard / LangGraph Agent Adapter

Wrap Python agent loops and provide dynamic capability injection:

```python
from capforge.adapter.standard import StandardAgentAdapter
from capforge.runtime.agent_adapter import CapForgeAgent

sf_agent = CapForgeAgent()
adapter = StandardAgentAdapter(capforge_agent=sf_agent)

# Execute task with automatic gap detection, acquisition, and verification
response = adapter.run_task_with_evolution(
    task_intent="Analyze repository dependencies for vulnerabilities",
    inputs={"repository": "https://github.com/example/repo"}
)
```

---

### Native Model Context Protocol (MCP) Server

CapForge provides a built-in JSON-RPC 2.0 MCP server supporting both stdio transport (for Claude Desktop, Cursor, and Antigravity) and FastAPI REST mounts:

```bash
# Launch stdio MCP transport
python -m capforge.mcp.server
```

Exposed MCP Tools:
- `capforge_search_capabilities`: Semantic and lexical discovery.
- `capforge_execute_capability`: Execute verified capabilities inside the sandbox.
- `capforge_synthesize_capability`: Trigger closed-loop acquisition for capability gaps.
- `capforge_get_manifest`: Retrieve YAML contract and dependency graph.
- `capforge_list_capabilities`: Query registry by namespace and status.

---

## 5. Glassmorphism Control Center Dashboard & REST API

Launch the real-time Control Center Dashboard and API server:

```bash
capforge serve --port 8000
```

- **Control Center UI**: [`http://localhost:8000/dashboard`](http://localhost:8000/dashboard)
  - Real-time active capability counter, connected agents, and firewall status.
  - Interactive Capability Registry browser with code inspection and dependency graphs.
  - Learning Job monitor with live progress indicators.
  - Four-Level Evaluation telemetry visualizer (Structural, Functional, Generalization, Regression).
  - OpenTelemetry distributed span waterfalls and Universal Event Gateway feed.
  - Interactive Human Review Governance Portal.
- **Interactive OpenAPI Documentation**: [`http://localhost:8000/docs`](http://localhost:8000/docs)

---

## 6. Canonical Three-Plane Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PLANE 1: EXECUTION PLANE                           │
│                                                                             │
│   Host Agent (LangGraph / OpenAI Agents / CrewAI / AutoGen / MCP / A2A)     │
│                                     │                                       │
│                                     ▼                                       │
│                     CapForge Capability Router                            │
│                                     │                                       │
│                                     ▼                                       │
│                       Runtime Capability Firewall                           │
│                                     │                                       │
│                                     ▼                                       │
│              Verified Capability Execution (Isolated Sandbox)               │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ Normalized Events & Traces
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PLANE 2: CAPABILITY CONTROL PLANE                        │
│                                                                             │
│   Event & Trace Gateway (W3C OpenTelemetry)                                 │
│   Capability Registry (SQLite WAL Mode & Multi-Tenancy)                     │
│   Capability Dependency Graph (Cycle Detection & Blast Radius Analysis)     │
│   Risk Engine & Immutable Governance Mesh                                   │
│   Semantic Version Manager (SemVer Lineage & Auto-Rollback)                 │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ Experience Filter (Novel Failures & Gaps)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 PLANE 3: LEARNING & VERIFICATION PLANE                      │
│                                                                             │
│   Asynchronous Learning Job Worker Pool                                     │
│   Knowledge & Evidence Engine (Docs, Code, Trajectories)                    │
│   Synthesizer & Auto-Repair Engine (Closed-Loop AST Repair)                 │
│   Four-Level Verification Battery (L1 Struct, L2 Func, L3 Gen, L4 Reg)      │
│   Hardware Container Isolation (Docker / Subprocess Fallback)               │
│   Zero-Regression Promotion Gate                                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Production vs. Learning Runtime Separation

A core architectural invariant of CapForge is the **strict separation between production execution and capability learning**:
- **Production Execution**: Low-latency, deterministic, read-mostly, and protected by the Capability Firewall.
- **Learning & Verification**: Asynchronous, isolated, resource-controlled, and executed in sandboxes without production credentials.

---

## 7. Capability Ontology & Machine-Readable Manifests

### The Five Capability Primitives

1. **`TOOL`**: A primitive callable operation (e.g. `filesystem.read`, `database.query`, `python.execute`).
2. **`SKILL`**: A reusable procedure combining tools, reasoning steps, or existing capabilities (e.g. `github.security_analysis`).
3. **`WORKFLOW`**: A structured sequence of tasks across multiple agents or execution stages.
4. **`COMPOSITION`**: Existing capabilities dynamically chained into a new capability DAG.
5. **`EVALUATOR`**: A verified assertion module used to benchmark other capabilities or agents.

---

### A Skill Is NOT Just a Prompt

A CapForge skill is a structured capability package containing:
- Explicit typed inputs and outputs ([`ParameterSpec`](capforge/core/models.py#L93-L100))
- Code bodies or deterministic procedures
- Declared tool dependencies and preconditions
- Security permissions and risk classification
- Concrete verification test suites (happy-path, edge cases, invariants)
- Provenance and version lineage

---

### Canonical YAML Manifest Specification

Every capability exports and imports via a standardized, machine-readable YAML contract:

```yaml
capability_id: k8s_incident_rca
name: Kubernetes Incident Root Cause Analyzer
version: 1.0.0
type: SKILL
description: Analyze container logs and pod statuses to diagnose root causes
domain: kubernetes
tags: [kubernetes, k8s, incident, diagnostics]
status: ACTIVE
inputs:
  incident_logs:
    type: string
    description: Raw stdout/stderr or cluster events
    required: true
  pod_status:
    type: string
    description: Pod lifecycle phase
    required: false
procedure:
  execution_mode: CODE
  entrypoint: execute
  code: |
    def execute(inputs):
        logs = inputs.get("incident_logs", "")
        if "OOMKilled" in logs:
            return {"root_cause": "CONTAINER_OOM_KILLED", "confidence": 0.95}
        return {"root_cause": "UNKNOWN", "confidence": 0.20}
tools:
  - kubectl.get_events
  - kubectl.logs
permissions:
  filesystem: none
  network: restricted
risk:
  level: LOW
provenance:
  source: kubernetes_docs
  trust_level: 0.95
```

---

## 8. Four-Level Verification Battery

A capability is never promoted to production simply because it executes once without throwing an exception. CapForge enforces a four-level verification battery:

```text
Candidate Capability
         ↓
Level 1: Structural Validation      ──> AST syntax tree, entrypoint presence, schema types
         ↓
Level 2: Functional Evaluation      ──> Task correctness, assertions, regex/substring match
         ↓
Level 3: Generalization Evaluation   ──> Unseen permutations and adversarial edge cases
         ↓
Level 4: Regression Evaluation       ──> 100% pass rate across ALL historical version test suites
         ↓
Zero-Regression Promotion Gate
```

If an updated capability version fails even a single historical test case, **promotion is blocked and the candidate is rejected**.

---

## 9. Capability Firewall & Immutable Governance

### Runtime Capability Firewall

At execution time, the host agent cannot bypass security controls. The [`CapabilityFirewall`](capforge/core/governance.py#L125-L168) inspects:
1. **Agent Identity**: Is the requesting agent authorized for this capability?
2. **Tenant Namespace**: Does the request violate tenant isolation boundaries?
3. **Permissions & AST Security**: Does the capability attempt undeclared filesystem or network access?
4. **Circuit Breaker Status**: Has this capability tripped its failure threshold?

---

### The Core Safety Invariant

> **CapForge may autonomously expand what an agent can do, but it cannot autonomously redefine what the platform considers safe or permitted.**

CapForge can evolve skills, tools, and workflows. It cannot autonomously modify:
- Authentication & Authorization
- Risk thresholds & Promotion rules
- Sandbox boundaries & Network restrictions
- Audit logging & Governance policies

---

### Interactive Human Review Portal

Capabilities classified as `RiskLevel.HIGH` or flagged by dynamic AST anomaly detection (e.g. undeclared dynamic execution like `eval` or unauthorized imports like `socket`) generate a [`HumanReviewTicket`](capforge/core/governance.py#L42-L60).

Tickets can be inspected, approved, or rejected via the dashboard or REST API:
- `POST /v1/governance/tickets/{id}/approve` &rarr; Transitions capability to `ACTIVE`.
- `POST /v1/governance/tickets/{id}/reject` &rarr; Flags capability as `QUARANTINED`.

---

## 10. Distributed Event Streaming & Resilient Workflows

### Universal Event Model

All agent operations are normalized into structured [`AgentEvent`](capforge/core/models.py#L113-L135) envelopes containing event type, timestamps, agent ID, run ID, tool calls, and error stack traces.

---

### Distributed Event Stream Broker

The [`BaseEventBroker`](capforge/events/broker.py#L32-L61) provides pub/sub messaging and historical replay:
- [`InMemoryStreamBroker`](capforge/events/broker.py#L64-L135): Thread-safe ring buffer with topic pattern filtering (`events.*`, `events.tool_*`).
- [`RedisStreamBroker`](capforge/events/broker.py#L138-L215): Redis Streams client with zero-dependency in-memory fallback.
- Stream query endpoint: `GET /v1/events/stream?topic_pattern=events.*&limit=50`.

---

### Durable Resilient Workflow State Machine

The [`DurableWorkflowEngine`](capforge/runtime/durable_workflow.py#L65-L270) coordinates multi-step DAG workflows with durable checkpoints:
- **Idempotent Step Checkpoints**: Completed steps are recorded and never re-executed upon retry.
- **Exponential Backoff**: Automatic retries for transient upstream tool failures.
- **Pause-and-Resume**: Unhandled failures pause the workflow (`WorkflowStatus.PAUSED`). Once the underlying capability is repaired, `POST /v1/workflows/{run_id}/resume` resumes execution from the exact failed step.

---

## 11. Enterprise RBAC & Dense Vector Hybrid Search

### Cryptographic API Key Mesh

CapForge v1.0.0 introduces an enterprise authentication mesh ([`capforge.server.auth`](capforge/server/auth.py)):
- SHA256 hashed API keys (`sf_live_...`)
- Role segregation: `ADMIN`, `OPERATOR`, `AGENT_RUNNER`, `AUDITOR`
- Multi-tenant namespace enforcement via HTTP headers (`X-CapForge-Key`, `X-Tenant-Namespace`)

---

### Dense Vector Embeddings & Hybrid Search

CapForge includes a zero-external-dependency 128-dimensional dense vector embedding engine ([`DenseVectorEmbeddingEngine`](capforge/registry/vector_store.py#L18-L56)) and vector index ([`SemanticVectorIndex`](capforge/registry/vector_store.py#L59-L127)):
- Blends lexical sub-token trigram matching with dense vector cosine similarity.
- REST endpoint: `POST /v1/capabilities/hybrid-search` (parameter `alpha` balances lexical vs. semantic weight).

---

## 12. Production CLI Reference

| Command | Syntax | Description |
| :--- | :--- | :--- |
| `health` / `check` | `capforge health` | Run production diagnostics on SQLite WAL, sandbox, broker, and governance |
| `version` | `capforge version` | Display engine version, Python runtime, and host OS platform |
| `demo` | `capforge demo` | Run the 4-step killer demonstration end-to-end |
| `list` | `capforge list [-d domain]` | List all registered capabilities with status, version, risk, and test count |
| `analyze` | `capforge analyze "<task>"` | Analyze natural language task for capability gaps and missing primitives |
| `test` | `capforge test <id>` | Run 4-level verification battery on a capability |
| `risk` | `capforge risk <id>` | Inspect risk classification and policy promotion gates |
| `graph` | `capforge graph <id>` | Print capability dependency tree and compute transitive blast radius |
| `export-manifest` | `capforge export-manifest <id> [-o file]` | Export capability definition to canonical YAML manifest |
| `import-manifest` | `capforge import-manifest <file>` | Import capability from YAML manifest into registry |
| `jobs` | `capforge jobs` | List recent autonomous learning and acquisition jobs |
| `serve` | `capforge serve [--port 8000]` | Launch FastAPI REST API server and Control Center Dashboard |

---

## 13. Automated Test Battery (178/178 Green)

All 178 automated tests execute with a 100% green pass rate:

```bash
pytest tests/ -q
```

```text
============================= test session starts =============================
platform win32 -- Python 3.11.0rc2, pytest-9.1.1, pluggy-1.6.0
rootdir: P:\Agentic Projects\CapForge, configfile: pyproject.toml
collected 178 items

tests\test_adapter.py ....                                               [  2%]
tests\test_adapters_extended.py ...                                      [  3%]
tests\test_api.py ....................                                   [ 15%]
tests\test_auth_enforcement.py .......                                   [ 19%]
tests\test_capability_graph.py ........                                  [ 24%]
tests\test_durable_workflow.py ....                                      [ 26%]
tests\test_e2e_demo.py ....                                              [ 28%]
tests\test_events.py .........                                           [ 33%]
tests\test_fault_injection.py ........                                   [ 38%]
tests\test_gap_detector.py ..                                            [ 39%]
tests\test_governance.py .............                                   [ 46%]
tests\test_governance_lifecycle.py ..                                    [ 47%]
tests\test_job_worker.py .                                               [ 48%]
tests\test_learning_jobs.py .                                            [ 48%]
tests\test_manifest.py ...                                               [ 50%]
tests\test_mcp_server.py ......                                          [ 53%]
tests\test_multi_tenancy.py ..                                           [ 55%]
tests\test_pipeline.py ...                                               [ 56%]
tests\test_registry.py ....                                              [ 58%]
tests\test_security_modules.py .............................................. [ 84%]
tests\test_stream_broker.py ......                                       [ 88%]
tests\test_telemetry.py ...                                              [ 89%]
tests\test_v1_enterprise_ga.py .....                                     [ 92%]
tests\test_verification_sandbox.py ........                              [ 97%]
tests\test_versioning_regression.py ....                                 [100%]

============================= 178 passed in 68.4s =============================
```

---

## 14. Repository Layout & Architecture Mapping

```text
CapForge/
├── capforge/
│   ├── core/                  # Plane 2: Models, config, events, governance, telemetry
│   │   ├── models.py          # Capability, ParameterSpec, EventType, RiskLevel
│   │   ├── events.py          # EventGateway & ExperienceFilter
│   │   ├── governance.py      # CapabilityFirewall, RiskEngine, AST analysis
│   │   ├── telemetry.py       # W3C OpenTelemetry distributed tracing
│   │   └── manifest.py        # YAML manifest serialization/deserialization
│   ├── registry/              # Plane 2: Capability storage and retrieval
│   │   ├── store.py           # SQLite WAL registry with multi-tenant namespaces
│   │   ├── search.py          # Lexical trigram and keyword matching
│   │   └── vector_store.py    # Dense vector embedding & hybrid retrieval
│   ├── discovery/             # Plane 2: Discovery and impact analysis
│   │   ├── gap_detector.py    # AST and task capability gap detection
│   │   └── capability_graph.py# Dependency graph, cycle detection, blast radius
│   ├── acquisition/           # Plane 3: Autonomous capability learning
│   │   ├── engine.py          # Evidence extraction and code synthesis
│   │   ├── jobs.py            # LearningJob state machine
│   │   └── worker.py          # Background worker polling daemon
│   ├── verification/          # Plane 3: Sandbox and closed-loop evaluation
│   │   ├── sandbox.py         # Subprocess isolation runner with env sanitization
│   │   ├── sandbox_docker.py  # Containerized Docker runner with resource limits
│   │   ├── evaluator.py       # 4-level evaluation engine
│   │   ├── test_generator.py  # Automatic test enrichment
│   │   └── repair.py          # Closed-loop self-healing repair engine
│   ├── versioning/            # Plane 2: Release and rollback management
│   │   └── manager.py         # Semantic version promotion and rollback
│   ├── runtime/               # Plane 1: Capability execution and pipelines
│   │   ├── executor.py        # CapabilityExecutor with circuit breaker
│   │   ├── agent_adapter.py   # CapForgeAgent controller
│   │   ├── pipeline.py        # Dynamic capability DAG composition
│   │   └── durable_workflow.py# Resilient checkpointed workflow state machine
│   ├── events/                # Distributed event streaming
│   │   └── broker.py          # InMemoryStreamBroker & RedisStreamBroker
│   ├── adapter/               # Framework-agnostic agent bridges
│   │   ├── standard.py        # Generic Python / LangGraph adapter
│   │   ├── openai_adapter.py  # OpenAI Agents SDK function calling adapter
│   │   └── crewai_adapter.py  # CrewAI BaseTool multi-agent adapter
│   ├── mcp/                   # Model Context Protocol
│   │   └── server.py          # Native JSON-RPC 2.0 MCP server
│   ├── server/                # FastAPI REST API & Web Dashboard
│   │   ├── app.py             # REST API routes and dependencies
│   │   ├── auth.py            # Enterprise RBAC & API key authentication
│   │   └── dashboard.html     # Glassmorphism real-time Control Center UI
│   └── cli.py                 # Developer & production CLI (Typer + Rich)
├── examples/
│   └── killer_demo.py         # 4-step autonomous evolution loop demonstration
├── tests/                     # 15 test suites with 109 automated tests
├── versions.mdx               # Release history & GSD evolution ledger
├── discussion.mdx             # Canonical technical specification
└── pyproject.toml             # Project build configuration (v1.0.0 GA)
```

---

## 15. Theoretical Foundations & Research Agenda

### Dual System Loops

CapForge operates through two coordinated feedback loops:

```text
               RUNTIME LOOP                               EVOLUTION LOOP
               (Synchronous)                              (Asynchronous)

                   TASK                                     EXPERIENCE
                    ↓                                           ↓
                 ANALYZE                                 EXPERIENCE FILTER
                    ↓                                           ↓
                 RETRIEVE                                 CAPABILITY GAP
                    ↓                                           ↓
                  ROUTE                                      ACQUIRE
                    ↓                                           ↓
           CAPABILITY FIREWALL                              CONSTRUCT
                    ↓                                           ↓
                 EXECUTE                                     SANDBOX
                    ↓                                           ↓
                 MONITOR                                  4-LEVEL VERIFY
                    ↓                                           ↓
                 RESULT                                    RISK & GOVERN
                                                                ↓
                                                             PROMOTE
                                                                ↓
                                                             REGISTER
```

---

### Independent Evaluation Layer

CapForge's evaluation infrastructure can operate independently from autonomous acquisition. An enterprise can connect existing agents to CapForge strictly for **third-party capability auditing, regression benchmarking, and security verification** without enabling automatic code generation.

---

### Research Metrics

When evaluating CapForge experimentally against baseline agents:
- **Capability Acquisition Rate**: Proportion of detected capability gaps successfully synthesized and verified.
- **Skill Reuse Rate**: Frequency with which previously forged capabilities are successfully reused on subsequent tasks ($0\,\text{ms}$ acquisition latency).
- **Transfer Generalization Rate**: Pass rate of synthesized capabilities on unseen problem variants.
- **Zero-Regression Rate**: Frequency with which capability updates preserve all historical functionality ($100\%$ required by gate).
- **Time-to-Capability**: Wall-clock seconds required from gap encounter to production-verified promotion.

---

## 16. License & Community

CapForge is open-source software licensed under the **[Apache License 2.0](LICENSE)**.

Contributions, feature requests, and discussions are welcome. Please read our architectural specification in [`discussion.mdx`](discussion.mdx) and our release ledger in [`versions.mdx`](versions.mdx) prior to submitting pull requests.
