# CapForge — Detailed Project Report & Specification

## 1. Project Overview

**CapForge** is a framework-independent **continuous capability evolution and evaluation platform for AI agents**.

The core idea is not to build another standalone AI agent. Instead, CapForge integrates with an **existing agentic system** and provides an additional intelligence and infrastructure layer that allows the system to:

* understand what capabilities it currently has,
* detect capability gaps,
* acquire knowledge and tools,
* create new skills,
* improve existing skills,
* improve newly created skills,
* test capabilities in an isolated sandbox,
* evaluate their quality,
* perform security and regression checks,
* version capabilities,
* safely promote validated improvements,
* continuously monitor real-world usage,
* and trigger further evolution when meaningful evidence appears.

The central philosophy is:

> **Agents should be able to evolve their capabilities, but that evolution must be evidence-based, evaluated, governed, and reversible.**

CapForge therefore aims to create a **controlled continuous capability-evolution loop**, rather than an uncontrolled self-modifying agent.

---

# 2. The Core Problem

Current agentic systems can already:

* reason using LLMs,
* plan tasks,
* call tools,
* use memory,
* communicate with other agents,
* execute workflows.

However, their capabilities are usually relatively static.

For example, an agent may have:

```text
Agent
├── Web Search
├── GitHub
├── Python
├── Database
└── Code Execution
```

Now imagine the agent encounters a task it cannot perform:

> "Analyze this Kubernetes incident and determine the root cause."

The agent may try several approaches, fail, and eventually stop.

The problem is that the system does not necessarily have a structured mechanism to turn that experience into:

```text
Experience
    ↓
Capability Gap
    ↓
New Capability
    ↓
Verified Capability
    ↓
Reusable Capability
```

Even when a capability already exists, the agent may discover that it is not sufficiently reliable.

Therefore, there are actually **two problems**:

### Problem A — Capability Acquisition
The agent does not have the required capability.

### Problem B — Capability Evolution
The agent has the capability, but the capability can be improved.

CapForge addresses both.

---

# 3. Core Vision

CapForge supports this closed lifecycle loop:

```text
                 EXISTING AGENT
                       │
                       ↓
                    OBSERVE
                       │
                       ↓
                 UNDERSTAND TASK
                       │
                       ↓
             IDENTIFY CAPABILITIES
                       │
                       ↓
               CAPABILITY GAP?
                  /          \
                NO            YES
                │              │
                │              ↓
                │          ACQUIRE
                │              │
                │          CONSTRUCT
                │              │
                │              ↓
                │           SANDBOX
                │              │
                │              ↓
                │          EVALUATE
                │              │
                │              ↓
                │          PROMOTE
                │
                ↓
             EXECUTE
                │
                ↓
             OBSERVE
                │
                ↓
        IMPROVEMENT OPPORTUNITY?
             /          \
           NO            YES
           │              │
           │              ↓
           │           IMPROVE
           │              │
           │           SANDBOX
           │              │
           │          EVALUATE
           │              │
           │         REGRESSION
           │              │
           │          SECURITY
           │              │
           │          PROMOTE
           │
           └──────────────┘
```

This means CapForge does not only **create skills**.
It continuously manages the **lifecycle of capabilities**.

---

# 4. CapForge Is Not a New Agent

This distinction is fundamental:

CapForge does not replace:
* LangGraph
* OpenAI Agents SDK
* CrewAI
* AutoGen
* Microsoft Agent Framework
* Custom agent runtimes
* MCP
* A2A

Instead:

```text
Existing Agent
      │
      ↓
   CapForge
      │
      ├── Capability Discovery
      ├── Capability Evaluation
      ├── Capability Acquisition
      ├── Capability Creation
      ├── Capability Improvement
      ├── Security
      ├── Governance
      └── Versioning
```

The existing agent remains responsible for reasoning, planning, execution, memory, interaction with users, and orchestration.
CapForge becomes the **capability infrastructure around the agent**.

---

# 5. How a Developer Uses CapForge

A developer does not need to rebuild their existing agent.

They integrate:

```text
MyAgent
   ↓
CapForge SDK / Adapter
   ↓
CapForge Platform
```

The SDK/adapter captures:
* tasks
* agent execution
* tool calls
* tool failures
* outcomes
* capability usage
* performance
* traces

Heavy components such as sandbox, evaluation engine, registry, learning workers, and governance run as CapForge services.

---

# 6. SDK + Runtime Architecture

```text
                 Developer Application
                         │
                         ↓
                  Existing Agent
                         │
              ┌──────────┴──────────┐
              ↓                     ↓
          Agent SDK              Tools
              │
              ↓
        CapForge Adapter
              │
              ↓
       CapForge Platform
```

The developer primarily interacts with first-class primitives:
* Agent
* Capability
* Benchmark
* Evaluation
* Policy
* Result

---

# 7. Framework Independence

```text
                    CapForge Core
                         │
                  Adapter Interface
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
  LangGraph       OpenAI Agents SDK       MCP
       ↓                 ↓                 ↓
    CrewAI             AutoGen           Custom
       ↓                 ↓                 ↓
 Microsoft Agent Framework               A2A
```

The core platform contains zero framework-specific assumptions. Adapters translate framework-specific execution into the **Universal CapForge Event Model**.

---

# 8. Universal Event Model

CapForge normalizes events across frameworks:

```json
{
  "event": "tool_failed",
  "run_id": "run_8472",
  "task_id": "task_2381",
  "agent_id": "agent_security",
  "framework": "langgraph",
  "tool": {
    "name": "github.get_repository",
    "version": "2.1"
  },
  "input": {
    "repository": "example/repo"
  },
  "output": null,
  "error": {
    "type": "AUTHENTICATION_ERROR",
    "message": "Token expired"
  }
}
```

Standard Event Types:
* `agent_started`, `agent_finished`
* `task_started`, `task_completed`, `task_failed`
* `tool_called`, `tool_succeeded`, `tool_failed`
* `skill_selected`, `skill_started`, `skill_completed`, `skill_failed`
* `capability_gap_detected`
* `skill_candidate_created`, `skill_evaluated`, `skill_promoted`, `skill_rejected`, `skill_rollback`

---

# 9. Capability Ontology

```text
CAPABILITY
│
├── TOOL         (Primitive operation: github.get_repository, db.query, etc.)
├── SKILL        (Reusable procedure combining tools and reasoning)
├── WORKFLOW     (Larger structured multi-step process)
├── COMPOSITION  (Multiple existing capabilities combined into a new capability)
└── EVALUATOR    (Capability used to evaluate another capability or agent)
```

---

# 10. Skills Are Living Artifacts

Skills are not static code files:

```text
Skill v1 → Production Usage → Observed Weakness → Improvement → Skill v2
```

---

# 11. Two Types of Evolution

1. **New Capability Evolution**: Gap → Acquire Knowledge → Construct Skill → Sandbox → Evaluate → Promote.
2. **Existing Capability Improvement**: Existing Skill → Real-world Usage → Failure/Weakness → Improvement Hypothesis → New Version → Sandbox → Regression & Security Verification → Promote/Reject.

---

# 12. Capability Gap Detection

Task decomposition checks missing primitives against the Capability Registry:

```text
Repository Access              ✓
Source Code Analysis           ✓
Dependency Analysis            ✓
Vulnerability Detection       ✗  --> CAPABILITY GAP
Security Report Generation     ✓
```

---

# 13. Capability Acquisition

Approved sources:
* Official documentation
* GitHub repositories
* Web resources & specifications
* Internal company documentation
* Existing tools & MCP servers
* Past agent experiences & evaluation logs

Every capability maintains immutable cryptographic **provenance** (source, URL, content hash, retrieval timestamp, license, trust level, extraction method).

---

# 14. Skill and Tool Creation

CapForge synthesizes skills, workflows, compositions, and controlled tools. Generated tools never automatically receive unrestricted production permissions.

---

# 15. Sandbox

Mandatory isolated execution environment (Docker containers with non-root privileges, read-only root filesystems, drop-all capabilities, memory/CPU quotas, strict execution timeouts, and restricted network egress).

---

# 16. Evaluation System

Multi-layer evaluation battery:
1. **Structural Evaluation**: Manifest schema, dependencies, I/O parameters, permissions.
2. **Functional Evaluation**: Happy path and edge case test suites.
3. **Generalization Evaluation**: Unseen test case variations to rule out memorization.
4. **Regression Evaluation**: Automated comparison against baseline version benchmarks.
5. **Security Evaluation**: Static AST analysis (`CodeGuardian`), secret leakage scans, and adversarial fuzzing (`AdversarialTester`).

---

# 17. Security & Compliance Challenges

* **Security Boundaries**: Never grant autonomous root/production permissions.
* **Data Leakage**: Automated trace redaction of PII, API keys, credentials, and confidential tokens.
* **Unsafe Code**: Strict AST linting, dangerous import bans (`os.system`, `subprocess`, `ctypes`, `socket`).
* **Compliance**: Immutable audit logs, HMAC-SHA256 signature chains (`TrustChain`), and human approval gates.

---

# 18. The Core Safety Invariant

> **Self-evolving, but not uncontrolled self-modifying.**

CapForge may evolve skills, tools, workflows, compositions, and evaluators.
It CANNOT autonomously modify authentication, authorization, security policies, governance rules, approval gates, or sandbox boundaries.

---

# 19. Capability Firewall

Runtime access control gate:

```text
Agent → Capability Router → Capability Firewall → Permission Check → Verified Capability → Tool
```

---

# 20. Risk-Based Promotion

* **LOW RISK** (e.g. Read-only doc summarization): Automated promotion after full test suite pass.
* **MEDIUM RISK** (e.g. Code refactoring, test generation): Automated promotion with rate limiting and strict sandbox restrictions.
* **HIGH RISK** (e.g. Production database write, deployment API, financial execution): Mandatory human review ticket before promotion.

---

# 21. Production vs Learning Separation

* **Production Plane**: Ultra-low latency, deterministic, sandboxed, observable, immutable execution.
* **Learning Plane**: Asynchronous, isolated, budget-controlled, multi-step verification.
* *Production execution never blocks waiting for an unfinished learning job.*

---

# 22. The LLM API Cost Problem & Tiered Architecture

CapForge avoids redundant LLM calls using 5 tiers:
* **Level 0 — Deterministic Monitoring**: 0 LLM calls (latency, success/failure counts).
* **Level 1 — Lightweight Trigger Detection**: Statistical sliding windows (`failure_rate > threshold`).
* **Level 2 — LLM Diagnosis**: Root cause diagnosis only upon confirmed trigger.
* **Level 3 — Capability Evolution**: Synthesis only when diagnosis warrants evolution.
* **Level 4 — Validation**: Multi-layer verification.

---

# 23. Evolution Budget Manager

Enforces resource and cost ceilings:
* Maximum LLM calls per hour / day
* Maximum cost ($ USD) per day
* Maximum sandbox executions
* Minimum expected improvement threshold
* Priority-weighted capability evolution allocation

---

# 24. Capability Registry & Graph

* Central registry tracking identity, ontology, versions, tests, evaluations, permissions, and lifecycle status.
* Capability Dependency Graph tracks transitive tool dependencies and triggers targeted re-evaluation when underlying primitives change.

---

# 25. Independent Evaluation Layer & Custom Benchmarks

Organizations can use CapForge strictly as an independent evaluation and benchmarking infrastructure without enabling autonomous synthesis:

```text
Company Agent → CapForge Adapter → Evaluation Engine → Benchmark Suite → Multi-Dimensional Report
```

Evaluates agents across 10 distinct dimensions:
1. Task Success Rate / Capability
2. Reliability & Determinism
3. Generalization on Unseen Tasks
4. Tool Selection Accuracy
5. Planning & Decomposition
6. Error Recovery & Self-Correction
7. Safety & Policy Compliance
8. Security & Permission Boundaries
9. Latency Profile (mean, p95)
10. Cost & Resource Efficiency

---

# 26. Problems → Proposed Solutions Master Matrix

| # | Core Problem | CapForge Architectural Solution |
|---|--------------|--------------------------------|
| 1 | Agents have static capabilities | Capability Gap Detection via task decomposition and registry comparison |
| 2 | Acquiring missing capabilities | Capability Acquisition Engine with immutable source provenance |
| 3 | Creating structured skills | Skill/Tool Synthesizer synthesizing code, tests, and schemas |
| 4 | Missing required tools | Controlled Tool Creation with restricted sandbox privileges |
| 5 | Generated capabilities are unsafe | Mandatory isolated sandbox execution with resource quotas |
| 6 | Verifying skill correctness | Multi-layer evaluation (Structural, Functional, Generalization, Regression, Security) |
| 7 | New version breaking old behavior | Automated Regression Engine testing against historical baseline suites |
| 8 | Existing skills become outdated | Continuous Skill Improvement triggered by production telemetry |
| 9 | Newly created skills need iteration | Post-deployment Evolution Loop |
| 10 | Uncontrolled self-modification | Immutable security governance boundaries |
| 11 | High-risk capability deployment | Risk-Based Governance with human approval gates |
| 12 | Agent bypassing permissions | Runtime Capability Firewall |
| 13 | Agent traces contain sensitive data | Automated Trace Privacy Filter with PII and credential redaction |
| 14 | Excessive LLM API cost | Event-Driven Evolution and Trigger Engine |
| 15 | Determining when evolution is justified | Statistical Trigger Engine tracking failure rate acceleration |
| 16 | Budget runaway during learning | Evolution Budget Manager with daily token and cost caps |
| 17 | Production blocked by learning | Asynchronous separation of Production and Learning Planes |
| 18 | Framework API differences | Framework-Agnostic Adapter SDK and Universal Event Model |
| 19 | Cascading dependency changes | Capability Dependency Graph with automated impact analysis |
| 20 | Irreversible capability changes | SemVer Version Management with instant rollback |
| 21 | Unknown capability origins | Cryptographic Provenance Tracking (HMAC-SHA256 TrustChain) |
| 22 | Enterprises avoiding autonomous code | Independent Evaluation Layer for evaluation-only deployments |
| 23 | Development CI/CD feedback | Pull Request Evaluation and Regression Testing Gate |
| 24 | Post-deployment degradation | Continuous Production Monitoring and Telemetry |
| 25 | Inadequate single-number scores | 10-Dimensional Agent Quality Report |
| 26 | Varying organizational benchmarks | Custom Benchmark Registry for domain-specific evaluation suites |
| 27 | Long-running learning job failures | Durable Workflow Engine with persistent state checkpoints |
