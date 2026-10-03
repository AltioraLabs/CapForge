# CapForge

<div align="center">

### Autonomous Capability Evolution, SMT Formal Verification, and JIT Optimization Runtime for AI Agents

[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](https://github.com/abhay-2108/CapForge)
[![Python: 3.10 | 3.11 | 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Tests: 234/234 Passed](https://img.shields.io/badge/tests-234%2F234%20Passed%20(100%25)-brightgreen.svg)](tests/)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![MCP: 2024-11-05](https://img.shields.io/badge/MCP-STDIO%20%7C%20SSE-purple.svg)](https://modelcontextprotocol.io/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-red.svg)](https://docs.pydantic.dev/)
[![Documentation](https://img.shields.io/badge/docs-Interactive%20Site-indigo.svg)](docs/site/index.html)

**Turn static AI agents into continuously evolving, self-healing systems that discover capability gaps, synthesize type-safe code, verify through SMT theorem proving, compile hot-paths into Rust, and safely govern execution &mdash; without retraining foundation models.**

[Interactive Documentation](docs/site/index.html) &bull; [Quickstart](#-quickstart-in-30-seconds) &bull; [Architecture](#-three-plane-architecture) &bull; [5-Level Verification](#-5-level-verification-pipeline) &bull; [MCP Server](#-model-context-protocol-mcp) &bull; [Rust Transpiler](#-python-to-rust-pyo3-transpiler)

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
pip install git+https://github.com/abhay-2108/CapForge.git

# With SMT formal verification (Z3 & SymPy) and all optional tools:
pip install "capforge[all]"
```

### 2. High-Level Python SDK (`@capability` & `CapForgeClient`)

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

### 3. Verify System Diagnostics

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

## ⚡ Python-to-Rust PyO3 Transpiler

When OpenTelemetry telemetry detects that a capability's computational loops (e.g., Monte Carlo simulations, numerical parsers, iterative transforms) cause latency bottlenecks, CapForge's runtime profiler triggers an `OPTIMIZATION_GAP` event:

1. **AST Hot-Path Detection:** Identifies tight loops and heavy arithmetic.
2. **PyO3 Rust Kernel Synthesis:** Synthesizes a native Rust extension module with memory-safe concurrency.
3. **Parity Verification:** Re-runs the full 5-level test suite against the compiled Rust artifact.
4. **Zero-Downtime Swap:** Automatically routes future executions to the compiled `.so` / `.pyd` module, delivering **20x&ndash;100x lower latency**.

```python
from capforge.optimization.profiler import RuntimeProfiler
from capforge.optimization.transpiler import HotPathTranspiler

# 1. Profile telemetry and flag bottlenecks
profiler = RuntimeProfiler(target_p95_ms=10.0)
gap = profiler.check_optimization_gap("monte_carlo_var", "1.0.0")

# 2. Transpile Python source into native PyO3 Rust extension
transpiler = HotPathTranspiler()
optimized_artifact = transpiler.transpile_and_compile(gap.capability_id)
print("Speedup Achieved:", optimized_artifact.speedup_factor)  # e.g., '48.2x'
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

## 💻 CLI Cheatsheet

| Command | Description |
| :--- | :--- |
| `capforge health` | Run production diagnostics on storage, sandbox, broker, and governance. |
| `capforge serve --port 8000` | Launch FastAPI REST API, dashboard, and MCP SSE server. |
| `capforge list` | List all registered capabilities, versions, and risk statuses. |
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
* **Online Documentation:** Hosted via GitHub Pages at `https://abhay-2108.github.io/CapForge/`.

---

## 🛠️ Contributing & Source Development

```bash
# Clone repository for local development
git clone https://github.com/abhay-2108/CapForge.git
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
