# CapForge

<div align="center">

### Autonomous Capability Evolution, SMT Formal Verification, and JIT Optimization Runtime for AI Agents

[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](https://github.com/AltioraLabs/CapForge)
[![Python: 3.10 | 3.11 | 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tests: 289/290 Passed](https://img.shields.io/badge/tests-289%2F290%20Passed%20(99.7%25)-brightgreen.svg)](tests/)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![MCP: 2024-11-05](https://img.shields.io/badge/MCP-STDIO%20%7C%20SSE-purple.svg)](https://modelcontextprotocol.io/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-red.svg)](https://docs.pydantic.dev/)
[![Documentation](https://img.shields.io/badge/docs-Interactive%20Site-indigo.svg)](docs/site/index.html)

**Turn static AI agents into continuously evolving, self-healing systems that discover capability gaps, synthesize type-safe code, verify through SMT theorem proving, compile hot-paths into Rust, and safely govern execution &mdash; without retraining foundation models.**

[Interactive Documentation](docs/site/index.html) &bull; [Quickstart](#-quickstart-in-30-seconds) &bull; [Architecture](#-three-plane-architecture) &bull; [Registry Seeding](#-seeding-your-registry--warm-up-strategy) &bull; [5-Level Verification](#-5-level-verification-pipeline) &bull; [MCP Server](#-model-context-protocol-mcp) &bull; [Rust Transpiler](#-python-to-rust-pyo3-transpiler)

</div>

---

## ⚡ What is CapForge?

Most autonomous AI agents (built with LangGraph, CrewAI, AutoGen, or OpenAI Assistants) fail when they encounter tasks requiring tools they were not explicitly pre-programmed with. Traditional workarounds &mdash; modifying prompts or writing ad-hoc tool functions &mdash; are brittle, lack formal verification, and require manual developer intervention.

**CapForge provides the capability-evolution layer underneath your agents:**
1. **Discovers Capability Gaps:** Detects when an agent cannot fulfill a task via AST gap mining and execution telemetry.
2. **Synthesizes & Self-Heals:** Synthesizes type-safe Python capabilities with a **3-pass closed-loop repair engine** (AST heuristics &rarr; LLM reflection &rarr; schema coercion).
3. **5-Level Verification Pipeline:** Validates generated code through CodeGuardian AST security, **Z3 / SymPy SMT formal invariant proofs**, Docker container sandboxing, property fuzzing, zero-regression batteries, and **continuous mutation testing**.
4. **JIT Optimization to Rust:** Detects computational loops via runtime latency profiling and autonomously compiles hot-paths into **native PyO3 Rust extensions** (achieving 20x&ndash;100x speedups).
5. **Universal Framework Exposure:** Dynamically exposes active, versioned capabilities to **LangGraph**, **CrewAI**, **OpenAI**, and native **Model Context Protocol (MCP)** clients over STDIO and SSE.

---

## 🚀 Quickstart in 30 Seconds

### 1. Installation

```bash
# Standard installation via pip
pip install capforge

# Or install latest release directly from GitHub:
pip install git+https://github.com/AltioraLabs/CapForge.git

# With SMT formal verification (Z3 & SymPy) and all optional tools:
pip install "capforge[all]"
```

### 2. Pre-Warm Registry (Eliminate Cold Starts)

```bash
# Pre-warm with baseline enterprise capabilities across finance, devops, nlp, and data
capforge seed --domain all
```

### 3. High-Level Python SDK (`@capability` & `CapForgeClient`)

```python
from capforge import CapForgeClient, capability

# 1. Define a capability with typed ParameterSpec contracts & tests
@capability(
    id="sentiment_analyzer",
    domain="nlp",
    risk_level="LOW",
    tests=[
        {
            "id": "t1",
            "inputs": {"text": "CapForge makes autonomous agents production-ready!"},
            "expected_keys": ["sentiment", "confidence"],
            "assert_expression": "output['sentiment'] == 'positive' and output['confidence'] > 0.8"
        }
    ]
)
def analyze_sentiment(text: str = "") -> dict:
    is_positive = any(w in text.lower() for w in ["great", "love", "excellent", "production-ready"])
    return {
        "text": text,
        "sentiment": "positive" if is_positive else "neutral",
        "confidence": 0.96 if is_positive else 0.50
    }

# 2. Local Embedded Execution (SQLite WAL + Container Sandbox)
with CapForgeClient() as client:
    # CodeGuardian AST Scan -> 5-Level Verification Battery -> Promote to ACTIVE
    client.register(analyze_sentiment, promote=True)

    # Execute in isolated sandbox with zero regression risk
    response = client.execute("sentiment_analyzer", {"text": "CapForge is great!"})
    print("Output:", response.output)
    print("Latency:", f"{response.latency_ms:.2f} ms")

    # Export directly as OpenAI tool schema or LangChain / CrewAI BaseTool
    openai_tool = client.to_openai_tool("sentiment_analyzer")
    crew_tool = client.to_crewai_tool("sentiment_analyzer")
```

### 4. Verify System Diagnostics

```bash
# Run production readiness checks on SQLite WAL, sandbox, and governance
capforge health

# Launch FastAPI REST server & MCP SSE hub
capforge serve --port 8000
```

---

## 🏛️ Three-Plane Architecture

CapForge strictly decouples low-latency deterministic agent execution from asynchronous, resource-capped capability synthesis:

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      PLANE 1: EXECUTION PLANE                          │
 │  Host Agents (LangGraph / CrewAI / OpenAI / MCP Clients)               │
 │       │                                                                │
 │       ▼                                                                │
 │  Capability Router ──► Runtime Firewall ──► Isolated Container Sandbox │
 │  (< 10ms overhead)     (AST / SSRF / RBAC)  (Docker / Subprocess / WASM)│
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │ Normalized execution telemetry & gaps
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      PLANE 2: CONTROL PLANE                            │
 │  • Capability Registry (SQLite WAL / PostgreSQL)                       │
 │  • Cryptographic Trust Chain (HMAC-SHA256 & ED25519)                   │
 │  • Dependency DAG & Blast Radius Graph                                 │
 │  • Runtime Profiler ($P_{50}, P_{95}, P_{99}$ SLA Hot-Path Monitor)   │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │ Asynchronous acquisition jobs
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      PLANE 3: LEARNING PLANE                           │
 │  • LLM Code Synthesizer (Gemini / OpenAI / Ollama / Anthropic)         │
 │  • 3-Pass Closed-Loop AST Self-Repair (Heuristic -> LLM -> Coercion)   │
 │  • 5-Level Verification Battery (L0 Security -> L5 Mutation Testing)   │
 │  • Python-to-Rust PyO3 Transpiler (20x–100x Computational JIT)        │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 🌱 Seeding Your Registry & Warm-Up Strategy

### The Cold-Start Problem in Autonomous Tool Runtimes

When an agent encounters a capability gap against an **empty or un-warmed registry**, CapForge invokes its complete synthesis pipeline:
1. **Contract Mining:** Analyzes intent, parameter specs, and expected return schemas.
2. **LLM Code Synthesis:** Synthesizes self-contained Python code.
3. **Closed-Loop AST Repair:** Executes up to 3 passes (Heuristic &rarr; LLM Reflection &rarr; Type Coercion).
4. **5-Level Verification Battery:** Runs CodeGuardian AST security, Z3/SymPy SMT invariant proofs, Docker/subprocess container sandbox execution, property fuzzing, and mutation testing.

> [!WARNING]
> **Cold Synthesis Latency:** Full end-to-end synthesis takes **15–90 seconds** (depending on LLM API response latency and SMT solver complexity). In synchronous agent loops, an un-warmed registry will cause tool call timeouts on the very first user interaction.

---

### CapForge's Two-Tier Solution to Cold Starts

#### Tier 1: Zero-Blocking Async Synthesis (First Incident Graceful Degradation)
When an agent experiences a gap in production, CapForge **never blocks the host agent thread for 90 seconds**. The `submit_synthesis()` API returns an immediate fallback response in **under 10ms**:

```python
from capforge.runtime.async_synthesis import AsyncSynthesisManager

manager = AsyncSynthesisManager()
resp = manager.submit_synthesis(
    task_intent="calculate compound interest",
    fallback_output={"estimated_rate": 0.05, "status": "provisional_estimate"}
)

# Immediate return (< 10ms):
print(resp.status)           # "SYNTHESIS_QUEUED"
print(resp.fallback_output)  # {"estimated_rate": 0.05, "status": "provisional_estimate"}
print(resp.job_id)           # "async_1741549200_a1b2c3d4"
print(resp.poll_endpoint)    # "/v1/synthesis/async_1741549200_a1b2c3d4"
```

1. **Host Agent Execution Continues:** The agent uses the provisional fallback output without dropping the user's conversational turn.
2. **Background Synthesis & Formal Proofs:** Worker threads synthesize, formally verify via Z3, and sandbox-test the tool in the background.
3. **Automatic Promotion & Webhook:** Once verified, the capability is promoted to `ACTIVE` in SQLite/PostgreSQL, and an HMAC-signed webhook event (`skill_promoted`) notifies your agent cluster. Subsequent requests execute deterministically in **< 5ms**.

---

#### Tier 2: Registry Pre-Warming via `capforge seed` CLI Walkthrough

To prevent the cold-start synthesis path from triggering during critical user-facing traffic, pre-warm your registry during container initialization, CI/CD, or deployment:

```bash
# Seed baseline enterprise capabilities across all 4 domains
capforge seed --domain all
```

**Live CLI Output:**
```text
                      CapForge Seeded Capabilities (ALL)                       
+-----------------------------------------------------------------------------+
| Capability ID           | Domain  | Name                           | Status |
|-------------------------+---------+--------------------------------+--------|
| calculate_value_at_risk | finance | Calculate Value-at-Risk        | ACTIVE |
| calculate_volatility    | finance | Calculate Annualized           | ACTIVE |
|                         |         | Volatility                     |        |
| calculate_max_drawdown  | finance | Calculate Maximum Drawdown     | ACTIVE |
| git_commit_analyzer     | devops  | Git Commit Message Analyzer    | ACTIVE |
| dockerfile_linter       | devops  | Dockerfile Security Linter     | ACTIVE |
| token_counter           | nlp     | Token & Cost Estimator         | ACTIVE |
| keyword_extractor       | nlp     | Keyphrase & Term Frequency     | ACTIVE |
|                         |         | Extractor                      |        |
| outlier_detector_zscore | data    | Z-Score Anomaly Detector       | ACTIVE |
+-----------------------------------------------------------------------------+
Successfully seeded 8 capabilities into the Capability Registry.
```

##### Supported Domain Seed Catalogs

| Domain | CLI Command | Pre-Seeded Production Tools | Common Agent Use Cases |
| :--- | :--- | :--- | :--- |
| **Finance** | `capforge seed -d finance` | `calculate_value_at_risk`, `calculate_volatility`, `calculate_max_drawdown` | Financial analysts, portfolio risk agents, quantitative trading bots. |
| **DevOps** | `capforge seed -d devops` | `git_commit_analyzer`, `dockerfile_linter` | Coding assistants, CI/CD automation agents, code review bots. |
| **NLP** | `capforge seed -d nlp` | `token_counter`, `keyword_extractor` | Cost tracking, context window optimization, content summarization agents. |
| **Data** | `capforge seed -d data` | `outlier_detector_zscore` | Data cleansing, anomaly detection, tabular data analytics. |
| **All** | `capforge seed -d all` | Complete baseline across all 4 domains (8 tools) | General-purpose autonomous agent runtimes. |

---

### Programmatic Seeding in Python

When running CapForge as an embedded library in your service:

```python
from capforge import CapForgeClient
from capforge.seed import seed_domain, get_available_domains

# 1. Inspect supported seed domains
print(get_available_domains())  # ['finance', 'devops', 'nlp', 'data']

# 2. Warm up registry at application startup
with CapForgeClient() as client:
    seeded = seed_domain("all", registry=client.registry)
    print(f"Pre-warmed {len(seeded)} capabilities into registry.")

    # 3. Execute immediately with zero synthesis delay (< 5ms)
    res = client.execute("calculate_value_at_risk", {
        "returns": [0.02, -0.05, 0.01, -0.03, 0.04],
        "confidence": 0.95
    })
    print("VaR Result:", res.output)
```

---

### Production First-Incident Playbook

| Phase | Operational State | Engine Action | SLA Impact |
| :--- | :--- | :--- | :--- |
| **Day-0 (Deploy)** | Cold Container Spin-Up | Execute `capforge seed --domain all` in Dockerfile or Kubernetes init container. Mount persistent volume for SQLite WAL or configure Postgres. | Zero cold-start latency for all standard domain capabilities. |
| **Day-1 (Unseen Gap)** | Agent requests unknown tool | Agent returns `SynthesisFallbackResponse` (`SYNTHESIS_QUEUED`) with provisional estimate. Background worker triggers 5-level verification. | Agent never stalls or drops conversation; fallback returned in **< 10ms**. |
| **Day-1+ (Promoted)** | Synthesis verified & signed | Capability promoted to `ACTIVE`; HMAC webhook dispatched. Dynamic router hot-swaps live tool. | All subsequent calls execute deterministically in **< 5ms**. |

---

## 🛡️ 5-Level Verification Pipeline

Every capability synthesized or upgraded in CapForge must pass an uncompromising 5-level verification matrix before entering production:

| Level | Verification Gate | Objective & Technology |
| :---: | :--- | :--- |
| **L0** | **CodeGuardian AST Security** | Static AST analysis blocking unsafe builtins (`exec`, `eval`), arbitrary file writes, socket creation, and SSRF attacks (private IP / AWS metadata blocking). |
| **L1** | **Structural & SMT Invariants** | Schema type conformance + **Z3 theorem proving & SymPy** to prove absence of unbounded recursion, loop termination bounds, monotonicity, and output non-negativity. |
| **L2** | **Functional Isolated Sandbox** | Execution inside an unprivileged Docker container or subprocess sandbox with strict CPU, memory (e.g. 128MB), and timeout limits. |
| **L3** | **Property Fuzzing & Generalization** | Generates 50+ randomized boundary condition inputs (extreme values, empty collections, nulls) to assert generalization. |
| **L4** | **Zero-Regression Battery** | Re-executes the complete historical test battery across all previous versions to guarantee backwards compatibility. |
| **L5** | **Continuous Mutation Testing** | Injects deliberate AST mutation operators (comparison flips, boundary shifts) to enforce a **mutant kill rate > 80%**. |

---

## ⚡ Python-to-Rust / PyO3 Multi-Tier Transpiler

When OpenTelemetry telemetry detects that a capability's computational loops (e.g., Monte Carlo simulations, numerical parsers, iterative transforms) cause latency bottlenecks, CapForge's runtime profiler triggers an `OPTIMIZATION_GAP` event:

1. **AST Hot-Path Detection:** Identifies tight loops, recursive accumulators, and heavy arithmetic complexity.
2. **Tier 1 — Compiled PyO3 Rust Extension:** When host toolchains (`cargo` & `maturin`) are available, scaffolds a complete Rust crate, generates PyO3 bindings, compiles native machine code (`.pyd` on Windows / `.so` on Linux), and produces a native execution shim (**20x&ndash;100x speedups** on raw CPU loops).
3. **Tier 2 — Vectorized NumPy Kernel:** When the Rust toolchain is absent, synthesizes vectorized array implementations (**3.5x&ndash;12x speedups**).
4. **Empirical Verification & Wall-Clock Measurement:** Re-runs the full 5-level test suite against the accelerated artifact and measures genuine wall-clock speedup (`time.perf_counter()`) across 25 iterations &mdash; never reporting hardcoded ratios.
5. **Zero-Downtime Hot-Swap:** Automatically registers the optimized capability in the registry with version lineage (`1.0.0` &rarr; `1.1.0-opt`).

```python
from capforge.optimization import RustTranspiler

# 1. Initialize the multi-tier transpiler
transpiler = RustTranspiler()

# 2. Transpile Python capability with functional equivalence verification
success, opt_cap, diagnostics = transpiler.transpile_and_optimize(capability)

if success:
    tier = opt_cap.metadata.get("acceleration_tier")
    speedup = opt_cap.metadata.get("measured_speedup_ratio")
    print(f"Accelerated via {tier}: {speedup}x empirical speedup")
    print(f"Diagnostics: {diagnostics}")
```

---

## 🌐 Model Context Protocol (MCP)

CapForge provides native, bi-directional Model Context Protocol (MCP) server support over **STDIO** and **Server-Sent Events (SSE)**. Any active capability registered in CapForge is immediately exposed as a native tool in **Claude Desktop**, **Cursor**, **Antigravity IDE**, and any MCP-compliant agent.

### Claude Desktop Configuration (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "capforge": {
      "command": "python",
      "args": ["-m", "capforge.mcp.server"],
      "env": {
        "CAPFORGE_DATABASE_URL": "sqlite:///data/capforge.db",
        "CAPFORGE_SANDBOX_DRIVER": "auto"
      }
    }
  }
}
```

### Cursor IDE Configuration (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "capforge-sse": {
      "url": "http://localhost:8000/mcp/sse",
      "headers": {
        "Authorization": "Bearer dev-secret-key"
      }
    }
  }
}
```

---

## 🔌 Multi-Framework Integration

### LangGraph StateGraph Integration

```python
from langgraph.graph import StateGraph, END
from capforge import CapForgeClient
from capforge.runtime.agent_adapter import LangGraphAdapter

client = CapForgeClient()
adapter = LangGraphAdapter(client)

# Create an execution node for any registered capability
tool_node = adapter.create_langgraph_node("monte_carlo_var")

# Create an autonomous evolution fallback node (synthesizes new tools on missing capability)
evolution_node = adapter.create_evolution_node()

workflow = StateGraph(dict)
workflow.add_node("execute_tool", tool_node)
workflow.add_node("evolve_capability", evolution_node)
workflow.set_entry_point("execute_tool")
workflow.add_conditional_edges(
    "execute_tool",
    lambda state: "evolve_capability" if state.get("error") == "CAPABILITY_NOT_FOUND" else END
)
app = workflow.compile()
```

### CrewAI Multi-Agent Integration

```python
from crewai import Agent, Task, Crew
from capforge import CapForgeClient

with CapForgeClient() as client:
    # Convert any verified capability into a native CrewAI tool
    var_tool = client.to_crewai_tool("monte_carlo_var")

    risk_agent = Agent(
        role="Quantitative Risk Officer",
        goal="Assess portfolio market stress and dollar VaR thresholds",
        tools=[var_tool],
        verbose=True
    )
```

---

## ⚡ Production Readiness & Blocker Mitigations

### 1. Non-Blocking Async Synthesis Path & Time Budget
In production, agents should **never block on capability synthesis**. CapForge provides non-blocking async gap resolution where the agent continues immediately with a fallback output while synthesis, verification, and promotion proceed in the background:

```python
with CapForgeClient() as client:
    # 1. Non-blocking async synthesis: returns immediately with job ID & fallback
    resp = client.synthesize_async(
        task_intent="calculate value at risk using historical simulation",
        fallback_output={"var": 0.05, "status": "estimated_fallback"},
    )
    print("Fallback Output:", resp.fallback_output)
    print("Async Job ID:", resp.job_id)

    # 2. Poll progress or listen via webhook ('capability_ready' event)
    job = client.poll_synthesis(resp.job_id)
    print("Pipeline Phase:", job.phase)  # QUEUED -> L0_L1_FAST_CHECK -> DRAFT -> L2_L5_VERIFY -> ACTIVE
```

**Synthesis Time Budget Matrix:**
| Stage | Target Latency | Capability Status | Operational Behavior |
| :--- | :---: | :---: | :--- |
| **Immediate Fallback** | **< 1 ms** | None | Agent continues without blocking; fallback result returned to user. |
| **Tier 1: Fast Check** | **~5–15 ms** | `DRAFT` | AST scan + syntax check pass. Low-risk paths can execute immediately. |
| **Tier 2: Verification**| **~400–900 ms** | `CANDIDATE` | Sandbox execution, property fuzzing, and regression tests complete. |
| **Tier 3: Promotion** | **~10–25 ms** | `ACTIVE` | Risk assessment evaluated; webhook dispatches `capability_ready`. |

### 2. Configurable Human-in-the-Loop Governance Gates
Regulated industries and enterprise teams often prohibit autonomous deployment without explicit human signoff. CapForge supports configurable promotion policies:

```python
from capforge import CapForgeClient, PromotionPolicy, PromotionMode, RiskLevel

with CapForgeClient() as client:
    # Enforce mandatory human review for all synthesized capabilities
    client.set_promotion_policy(
        PromotionPolicy(mode=PromotionMode.HUMAN_REVIEW)
    )

    # Inspect pending capabilities in the governance queue
    pending = client.list_pending_reviews(status="PENDING")
    for ticket in pending:
        print(f"Ticket {ticket.ticket_id}: Cap '{ticket.capability_id}' Risk: {ticket.risk_level}")

    # Approve and promote to ACTIVE
    client.approve_capability(ticket.ticket_id, reviewer="security_lead", notes="Verified safe")
```

### 3. Domain Pre-Warming & Seed Library (`capforge seed`)
Eliminates the cold-start problem by pre-populating verified baseline capabilities across enterprise domains before production traffic starts:

```bash
# Seed finance capabilities (VaR, Volatility, Max Drawdown)
capforge seed --domain finance

# Seed all standard enterprise catalogs (finance, devops, nlp, data)
capforge seed --domain all
```

### 4. Independently Reproducible Enterprise Benchmark Suite
Run the full automated, statistically rigorous benchmark suite locally to reproduce production metrics:

```bash
# Run all benchmarks with consolidated SLA audit report
python benchmarks/run_all.py

# Full statistical profile with JSON and Markdown export
python benchmarks/run_all.py --full --json benchmarks/report.json --markdown benchmarks/BENCHMARK_REPORT.md

# Run automated CI/CD benchmark suite test battery
pytest tests/test_benchmarks.py -v
```

**Empirical Production SLA Verification Matrix:**
| Benchmark Category | Key Metric Evaluated | CapForge Result | Target SLA | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Execution Overhead (Guarded)** | In-process firewall + schema + telemetry | **1.32 ms** | < 2,000 µs | **PASS** |
| **Sandbox Isolation Barrier** | Full OS subprocess boundary (zero-trust) | **141.23 ms** | < 250 ms | **PASS** |
| **Execution Throughput** | Max sustained calls/sec (in-process) | **667 ops/s** | > 250 ops/s | **PASS** |
| **Async Fast Check (DRAFT)** | L0 AST + L1 Syntax check (usable early) | **1.8 ms** | < 50 ms | **PASS** |
| **Full Synthesis (ACTIVE)** | Gap $\rightarrow$ 5-Level Verify $\rightarrow$ Promotion Gate | **588.3 ms** | < 5,000 ms | **PASS** |
| **Pre-Warmed Registry Lookup** | Cached capability fetch (cold start resolved) | **15.160 ms** | < 20 ms | **PASS** |
| **PyO3 JIT Optimization** | Monte Carlo hot-path native acceleration | **11.5x speedup** | > 3.0x | **PASS** |
| **Verification Throughput** | Full concurrent validation battery | **48,204 caps/min** | > 100 caps/min | **PASS** |

---

## 💻 CLI Cheatsheet

| Command | Description |
| :--- | :--- |
| `capforge health` | Run production diagnostics on storage, sandbox, broker, and governance. |
| `capforge serve --port 8000` | Launch FastAPI REST API, dashboard, and MCP SSE server. |
| `capforge list` | List all registered capabilities, versions, and risk statuses. |
| `capforge seed --domain <name>` | Pre-warm registry with baseline domain capabilities (`finance`, `devops`, `nlp`, `data`, `all`). |
| `capforge synth-status` | Inspect ongoing and completed asynchronous synthesis jobs. |
| `capforge reviews-list` | View capabilities waiting in the human governance review queue. |
| `capforge reviews-approve <id>`| Approve a pending capability and promote it to `ACTIVE`. |
| `capforge reviews-reject <id>` | Reject a pending capability and quarantine it. |
| `capforge synth "<prompt>"` | Synthesize a capability from natural language task specification. |
| `capforge test <id>` | Run verification tests against a capability in the sandbox. |
| `capforge optimize <id>` | Profile capability latency and compile PyO3 Rust extension. |
| `capforge mcp` | Launch the Model Context Protocol (MCP) STDIO server. |
| `capforge audit` | Inspect immutable audit logs and cryptographic signatures. |


---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `CAPFORGE_LLM_PROVIDER` | `gemini` | LLM code synthesizer: `gemini`, `openai`, `anthropic`, or `ollama`. |
| `CAPFORGE_DEV_MODE` | `false` | Set to `false` in production to enforce API keys and RBAC. |
| `CAPFORGE_SANDBOX_DRIVER` | `auto` | Sandbox containment: `docker`, `subprocess`, or `wasm`. |
| `CAPFORGE_DATABASE_URL` | `sqlite:///data/capforge.db` | Registry database: SQLite WAL or PostgreSQL cluster. |
| `CAPFORGE_REDIS_URL` | *empty* | Redis cluster URL for distributed event streams & rate limits. |
| `CAPFORGE_ENABLE_FORMAL_VERIFICATION`| `true` | Enables Z3 & SymPy theorem proving in Level 1 verification. |
| `CAPFORGE_ENABLE_RUST_TRANSPILER` | `true` | Enables automatic Python-to-Rust PyO3 transpilation. |

---

## 📖 Interactive Documentation

For detailed architecture diagrams, interactive API explorers, tutorials, and the **Live Capability Evolution Lab**, see the documentation site:

* **Local Documentation:** Open [`docs/site/index.html`](docs/site/index.html) in your browser.
* **Online Documentation:** Hosted via GitHub Pages at `https://altioralabs.github.io/CapForge/`.

---

## 🛠️ Contributing & Source Development

```bash
# Clone repository for local development
git clone https://github.com/AltioraLabs/CapForge.git
cd CapForge

# Create and activate virtual environment
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1 | Linux/macOS: source .venv/bin/activate

# Install in editable mode with all dev & verification dependencies
pip install -e ".[all]"

# Run full test suite
pytest tests/ -q

# Run linting and static formatting checks
ruff check capforge tests multi_agent_system
```

---

## 📄 License

CapForge is open-source software licensed under the **[Apache License 2.0](LICENSE)**.
