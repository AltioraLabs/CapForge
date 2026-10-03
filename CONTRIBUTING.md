# Contributing to CapForge

Thank you for your interest in contributing to **CapForge**! CapForge is an open-source, framework-agnostic runtime for autonomous capability acquisition, verification, and evolution for AI agents.

Whether you are fixing bugs, adding new framework adapters (e.g., LlamaIndex, Semantic Kernel), improving security heuristics, or expanding documentation, your contributions are welcome.

---

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md) in all interactions within the project.

---

## Development Setup

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Git
- Optional: Docker (for testing container isolation sandbox)

### Step-by-Step Local Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/CapForge.git
   cd CapForge
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   # On macOS/Linux:
   source .venv/bin/activate
   # On Windows:
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

4. **Verify the installation:**
   ```bash
   python -m capforge.cli health
   ```

---

## Running Tests

CapForge maintains a strict **100% green pass rate** across its test suite.

```bash
# Run the full test battery (178 tests)
pytest tests/ -q

# Run security subsystem tests
pytest tests/test_security_modules.py -v

# Run verification and sandbox tests
pytest tests/test_verification_sandbox.py -v
```

---

## Code Style & Linting

We use [Ruff](https://github.com/astral-sh/ruff) for linting and code formatting:

```bash
# Check code for lint errors
ruff check capforge/

# Automatically fix linting issues
ruff check --fix capforge/

# Format code
ruff format capforge/
```

Before submitting a pull request, ensure:
1. `ruff check capforge/` reports **All checks passed!**
2. `pytest tests/` has **0 failures**.

---

## Adding a New Framework Adapter

CapForge is designed to connect to any agent framework. To implement a new adapter:

1. Create a new module in `capforge/adapter/<framework>_adapter.py`.
2. Inherit from `BaseAgentAdapter` defined in `capforge/adapter/base.py`.
3. Implement the core hooks:
   - `discover_tools()`: Expose local tools to the agent.
   - `invoke_skill()`: Safely execute a registered skill through the sandbox.
   - `extract_failure()`: Convert framework runtime exceptions into structured `AgentEvent` payloads.
4. Add unit tests in `tests/test_adapters_extended.py`.
5. Export the adapter in `capforge/adapter/__init__.py`.

---

## Submitting a Pull Request

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-new-feature
   ```
2. Commit your changes following conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `style:`):
   ```bash
   git commit -m "feat(adapter): add LlamaIndex tool adapter"
   ```
3. Push to your fork:
   ```bash
   git push origin feat/my-new-feature
   ```
4. Open a Pull Request against the `main` branch.
5. Provide a clear description using our Pull Request template.
