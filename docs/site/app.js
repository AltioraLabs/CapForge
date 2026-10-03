/**
 * CapForge Interactive Documentation Engine
 * Handles theme toggling, search modal (Ctrl+K), multi-language code tabs,
 * copy-to-clipboard, scrollspy navigation, reading progress, and the
 * Live Capability Evolution & Synthesis Simulator.
 */

(function () {
  'use strict';

  // =========================================================================
  // 1. Theme Management (Dark / Light)
  // =========================================================================
  const root = document.documentElement;
  const themeToggle = document.getElementById('themeToggle');

  function initTheme() {
    const saved = localStorage.getItem('capforge-theme');
    if (saved) {
      root.setAttribute('data-theme', saved);
    } else {
      const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
      root.setAttribute('data-theme', prefersLight ? 'light' : 'dark');
    }
    updateThemeIcon();
  }

  function updateThemeIcon() {
    if (!themeToggle) return;
    const isDark = root.getAttribute('data-theme') === 'dark';
    themeToggle.innerHTML = isDark
      ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
      : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  }

  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const current = root.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      localStorage.setItem('capforge-theme', next);
      updateThemeIcon();
    });
  }

  initTheme();

  // =========================================================================
  // 2. Reading Progress Bar & Scrollspy
  // =========================================================================
  const scrollProgress = document.getElementById('scrollProgress');
  const sections = Array.from(document.querySelectorAll('section.doc-section, .hero'));
  const navLinks = Array.from(document.querySelectorAll('.nav-link'));
  
  function handleScroll() {
    // Progress bar
    if (scrollProgress) {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
      const progress = height > 0 ? (scrollTop / height) * 100 : 0;
      scrollProgress.style.width = progress + '%';
    }

    // Scrollspy
    const scrollPos = window.scrollY + 120;
    let currentId = '';

    for (let i = sections.length - 1; i >= 0; i--) {
      const sec = sections[i];
      if (sec.offsetTop <= scrollPos) {
        currentId = sec.id;
        break;
      }
    }

    if (currentId) {
      navLinks.forEach((link) => {
        const href = link.getAttribute('href');
        link.classList.toggle('active', href === '#' + currentId);
      });


    }
  }

  window.addEventListener('scroll', handleScroll, { passive: true });
  handleScroll();

  // =========================================================================
  // 3. Mobile Navigation Drawer & Backdrop UX
  // =========================================================================
  const menuToggle = document.getElementById('menuToggle');
  const sidebar = document.getElementById('sidebar');
  const sidebarClose = document.getElementById('sidebarClose');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');

  function openSidebar() {
    if (!sidebar) return;
    sidebar.classList.add('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('active');
    document.body.style.overflow = '';
  }

  if (menuToggle) menuToggle.addEventListener('click', openSidebar);
  if (sidebarClose) sidebarClose.addEventListener('click', closeSidebar);
  if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebar);

  if (sidebar) {
    sidebar.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', closeSidebar);
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar && sidebar.classList.contains('open')) {
      closeSidebar();
    }
  });

  // =========================================================================
  // 4. Sidebar Filter
  // =========================================================================
  const sidebarFilter = document.getElementById('sidebarFilter');
  if (sidebarFilter) {
    sidebarFilter.addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase().trim();
      const navGroups = document.querySelectorAll('.nav-group');

      navGroups.forEach((group) => {
        let hasMatch = false;
        const links = group.querySelectorAll('.nav-link');
        links.forEach((link) => {
          const text = link.textContent.toLowerCase();
          const match = text.includes(query);
          link.style.display = match ? 'flex' : 'none';
          if (match) hasMatch = true;
        });
        group.style.display = hasMatch ? 'block' : 'none';
      });
    });
  }

  // =========================================================================
  // 5. Code Tabs Switching
  // =========================================================================
  document.querySelectorAll('.code-box').forEach((box) => {
    const tabs = box.querySelectorAll('.code-tab-btn');
    const panes = box.querySelectorAll('.code-pane');

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        const targetId = tab.dataset.pane;
        tabs.forEach((t) => t.classList.remove('active'));
        panes.forEach((p) => p.classList.remove('active'));

        tab.classList.add('active');
        const targetPane = box.querySelector('#' + targetId);
        if (targetPane) targetPane.classList.add('active');
      });
    });
  });

  // =========================================================================
  // 6. Copy to Clipboard
  // =========================================================================
  document.querySelectorAll('.code-pane, pre[data-copy]').forEach((container) => {
    let btn = container.querySelector('.copy-button');
    if (!btn) {
      btn = document.createElement('button');
      btn.className = 'copy-button';
      btn.innerHTML =
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy';
      container.appendChild(btn);
    }

    btn.addEventListener('click', async () => {
      const codeEl = container.querySelector('code');
      const textToCopy = codeEl ? codeEl.innerText : container.innerText;

      try {
        await navigator.clipboard.writeText(textToCopy);
        btn.classList.add('copied');
        btn.innerHTML =
          '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
        setTimeout(() => {
          btn.classList.remove('copied');
          btn.innerHTML =
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy';
        }, 1800);
      } catch (err) {
        btn.innerText = 'Ctrl+C to copy';
      }
    });
  });

  // =========================================================================
  
  // Quick copy buttons with data-copy-text
  document.querySelectorAll('[data-copy-text]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const text = btn.dataset.copyText;
      const targetIconBtn = btn.classList.contains('hero-install-box')
        ? btn.querySelector('.hero-copy-btn')
        : btn;
      try {
        await navigator.clipboard.writeText(text);
        if (targetIconBtn) {
          targetIconBtn.classList.add('copied');
          const originalHtml = targetIconBtn.innerHTML;
          targetIconBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
          setTimeout(() => {
            targetIconBtn.classList.remove('copied');
            targetIconBtn.innerHTML = originalHtml;
          }, 1800);
        }
      } catch (err) {}
    });
  });

  // 7. Instant Search Modal (Ctrl+K)
  // =========================================================================
  const searchModal = document.getElementById('searchModal');
  const searchInput = document.getElementById('searchInput');
  const searchResults = document.getElementById('searchResults');
  const searchButtons = document.querySelectorAll('[data-search-open]');

  const searchIndex = [
    { title: 'Overview & Mission', cat: 'Concept', href: '#overview', desc: 'Autonomous capability evolution infrastructure for AI agents without retraining' },
    { title: '5-Minute Quickstart', cat: 'Guide', href: '#quickstart', desc: 'Decorate @capability, register, evaluate, promote, and execute in sandbox' },
    { title: 'Installation & Setup', cat: 'Guide', href: '#install', desc: 'Clone, virtual environment, pip install, Docker sandbox, Ollama / Gemini' },
    { title: 'Configuration (.env Reference)', cat: 'Reference', href: '#config', desc: 'LLM providers, sandbox driver, PostgreSQL, Redis, CORS origins, secrets' },
    { title: 'Three-Plane Architecture', cat: 'Architecture', href: '#architecture', desc: 'Execution Plane (Router + Firewall), Control Plane, Learning Plane (Synthesizer)' },
    { title: 'Capability Ontology & Manifest', cat: 'Concept', href: '#ontology', desc: 'TOOL, SKILL, WORKFLOW, COMPOSITION, EVALUATOR, ParameterSpec, YAML schema' },
    { title: '5-Level Verification Pipeline', cat: 'Verification', href: '#verification', desc: 'L0 Security AST Gate, L1 SMT Formal Invariants, L2 Sandbox, L3 Fuzzing, L4 Regression, L5 Mutation' },
    { title: 'Closed-Loop Self-Repair Engine', cat: 'Verification', href: '#repair', desc: '3-pass recovery: AST heuristics, LLM reflection with tracebacks, schema coercion' },
    { title: 'Runtime Profiling & Bottlenecks', cat: 'Optimize', href: '#profiler', desc: 'Telemetry-driven P50/P95/P99 latency tracking, memory churn, OPTIMIZATION_GAP' },
    { title: 'Python-to-Rust PyO3 Transpiler', cat: 'Optimize', href: '#transpiler', desc: 'Autonomous transpilation of hot-path Python loops into compiled PyO3 Rust extensions' },
    { title: 'Formal Verification with Z3 & SymPy', cat: 'Verification', href: '#formal', desc: 'SMT theorem proving for recursion bounds, non-negativity, monotonicity, termination' },
    { title: 'Continuous Mutation Testing', cat: 'Verification', href: '#mutation', desc: 'AST mutation operators, mutant kill rate > 80%, automated edge-case synthesis' },
    { title: 'Python SDK Client & Decorator', cat: 'SDK', href: '#sdk', desc: 'CapForgeClient, @capability decorator, batch_execute, local vs remote mode' },
    { title: 'LangGraph Framework Integration', cat: 'Integration', href: '#langgraph', desc: 'Dynamic StateGraph node creation with autonomous self-evolution fallback' },
    { title: 'CrewAI Framework Integration', cat: 'Integration', href: '#crewai', desc: 'Equipping CrewAI Agents with client.to_crewai_tool() and dynamic discovery' },
    { title: 'OpenAI Assistant & Anthropic Tools', cat: 'Integration', href: '#openai', desc: 'Exporting capabilities directly to OpenAI and Claude function calling schemas' },
    { title: 'Model Context Protocol (MCP) Server', cat: 'Integration', href: '#mcp', desc: 'STDIO & SSE transports, dynamic tool discovery, Claude Desktop & Cursor setup' },
    { title: 'Enterprise Storage & Deployment', cat: 'Deploy', href: '#deploy', desc: 'PostgreSQL distributed registry, S3/MinIO artifact storage, Redis pub/sub streams' },
    { title: 'OpenTelemetry & Prometheus Metrics', cat: 'Operate', href: '#telemetry', desc: 'GenAI distributed tracing spans, latency histograms, /metrics endpoint' },
    { title: 'REST API Complete Reference', cat: 'API', href: '#rest', desc: 'Interactive endpoint cards: capabilities, execute, verify, optimize, mutate, webhooks' },
    { title: 'CLI Command Cheatsheet', cat: 'CLI', href: '#cli', desc: 'capforge init, serve, synth, verify, optimize, mcp, audit, health' },
    { title: 'Security, Firewall & RBAC', cat: 'Security', href: '#security', desc: 'CodeGuardian OWASP AST rules, SSRF guardian, RBAC roles, audit logs, HMAC trust' },
    { title: 'Troubleshooting & FAQ', cat: 'Guide', href: '#faq', desc: 'Sandbox timeouts, template fallbacks, Docker permissions, private webhook routing' },
  ];

  let selectedIndex = 0;

  function openSearch() {
    if (!searchModal) return;
    searchModal.classList.add('open');
    searchInput.value = '';
    searchInput.focus();
    renderSearchResults('');
  }

  function closeSearch() {
    if (!searchModal) return;
    searchModal.classList.remove('open');
  }

  function renderSearchResults(query) {
    if (!searchResults) return;
    const q = query.toLowerCase().trim();
    const filtered = q
      ? searchIndex.filter(
          (item) =>
            item.title.toLowerCase().includes(q) ||
            item.desc.toLowerCase().includes(q) ||
            item.cat.toLowerCase().includes(q)
        )
      : searchIndex.slice(0, 8);

    selectedIndex = 0;

    if (filtered.length === 0) {
      searchResults.innerHTML =
        '<div style="padding:24px; text-align:center; color:var(--text-muted); font-size:14px;">No matching documentation sections found for "' +
        query +
        '"</div>';
      return;
    }

    searchResults.innerHTML = filtered
      .map(
        (item, idx) => `
        <button class="search-item ${idx === 0 ? 'selected' : ''}" data-href="${item.href}">
          <div class="search-item-header">
            <span class="search-item-title">${item.title}</span>
            <span class="search-item-cat">${item.cat}</span>
          </div>
          <div class="search-item-desc">${item.desc}</div>
        </button>
      `
      )
      .join('');

    searchResults.querySelectorAll('.search-item').forEach((itemEl) => {
      itemEl.addEventListener('click', () => {
        const href = itemEl.dataset.href;
        closeSearch();
        window.location.hash = href;
      });
    });
  }

  searchButtons.forEach((btn) => btn.addEventListener('click', openSearch));

  if (searchInput) {
    searchInput.addEventListener('input', (e) => renderSearchResults(e.target.value));

    searchInput.addEventListener('keydown', (e) => {
      const items = searchResults.querySelectorAll('.search-item');
      if (!items.length) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        items[selectedIndex]?.classList.remove('selected');
        selectedIndex = (selectedIndex + 1) % items.length;
        items[selectedIndex]?.classList.add('selected');
        items[selectedIndex]?.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        items[selectedIndex]?.classList.remove('selected');
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        items[selectedIndex]?.classList.add('selected');
        items[selectedIndex]?.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter') {
        e.preventDefault();
        items[selectedIndex]?.click();
      } else if (e.key === 'Escape') {
        closeSearch();
      }
    });
  }

  // Keyboard shortcut Ctrl+K or Cmd+K
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (searchModal.classList.contains('open')) closeSearch();
      else openSearch();
    } else if (e.key === 'Escape' && searchModal && searchModal.classList.contains('open')) {
      closeSearch();
    }
  });

  if (searchModal) {
    searchModal.addEventListener('click', (e) => {
      if (e.target === searchModal) closeSearch();
    });
  }

  // =========================================================================
  // 8. Live Capability Evolution & Synthesis Lab Simulator
  // =========================================================================
  const simSelect = document.getElementById('simSelect');
  const simRunBtn = document.getElementById('simRunBtn');
  const simEditor = document.getElementById('simEditor');
  const simResults = document.getElementById('simResults');
  const simStages = document.querySelectorAll('.sim-stage');
  const simLatency = document.getElementById('simLatency');
  const simStatus = document.getElementById('simStatus');

  const SIMULATION_PRESETS = {
    monte_carlo_var: {
      name: 'Monte Carlo Value-at-Risk (VaR) Simulator',
      domain: 'finance',
      gapReason: 'Agent lacks capability to compute Value-at-Risk under non-Gaussian price distributions',
      pythonCode: `@capability(
    id="monte_carlo_var",
    domain="finance",
    risk_level="MEDIUM",
    tests=[
        {"id": "t1", "inputs": {"portfolio_value": 1000000, "confidence": 0.95, "simulations": 10000}, "expected_keys": ["var_amount", "cvar", "p95_loss"]}
    ]
)
def compute_var(portfolio_value: float, confidence: float = 0.95, simulations: int = 10000) -> dict:
    import numpy as np
    returns = np.random.normal(0.0005, 0.015, int(simulations))
    losses = -portfolio_value * returns
    var = float(np.percentile(losses, confidence * 100))
    cvar = float(np.mean(losses[losses >= var]))
    return {
        "portfolio_value": portfolio_value,
        "var_amount": round(var, 2),
        "cvar": round(cvar, 2),
        "confidence": confidence,
        "simulations": simulations
    }`,
      rustKernel: `// Auto-Transpiled PyO3 Rust Hot-Path Extension
#[pyfunction]
pub fn fast_monte_carlo_var(val: f64, conf: f64, sims: usize) -> PyResult<(f64, f64)> {
    let mut rng = rand::thread_rng();
    let norm = rand_distr::Normal::new(0.0005, 0.015).unwrap();
    let mut losses: Vec<f64> = (0..sims).map(|_| -val * norm.sample(&mut rng)).collect();
    losses.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let idx = ((conf * sims as f64) as usize).min(sims - 1);
    let var = losses[idx];
    let tail: &[f64] = &losses[idx..];
    let cvar = tail.iter().sum::<f64>() / (tail.len() as f64);
    Ok((var, cvar))
} // 48.2x Speedup vs Pure Python`,
      output: {
        portfolio_value: 1000000.0,
        var_amount: 24380.45,
        cvar: 29810.12,
        confidence: 0.95,
        simulations: 10000,
        telemetry: {
          execution_mode: 'RUST_PYO3_COMPILED',
          p50_latency_ms: 0.42,
          p95_latency_ms: 0.68,
          speedup_factor: '48.2x',
          formal_invariants: 'PROVEN (Z3 VaR >= 0 & Monotonicity)',
          mutation_score: '93.3% (14/15 mutants killed)',
          trust_signature: 'hmac-sha256:7f8a12e399c0d18b...',
        },
      },
    },
    csv_sanitizer: {
      name: 'PII Data Redactor & Schema Sanitizer',
      domain: 'security',
      gapReason: 'Agent attempted to load unvalidated CSV payload containing raw SSNs and API keys',
      pythonCode: `@capability(
    id="sanitize_pii_csv",
    domain="security",
    risk_level="LOW",
    tests=[
        {"id": "t1", "inputs": {"raw_text": "Alice, 123-45-6789, key: sk-live-99"}, "expected_keys": ["sanitized_text", "redactions_count"]}
    ]
)
def sanitize_pii_csv(raw_text: str) -> dict:
    import re
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    key_pattern = r'sk-[a-zA-Z0-9]{20,}'
    
    redactions = len(re.findall(ssn_pattern, raw_text)) + len(re.findall(key_pattern, raw_text))
    cleaned = re.sub(ssn_pattern, '[REDACTED_SSN]', raw_text)
    cleaned = re.sub(key_pattern, '[REDACTED_KEY]', cleaned)
    
    return {
        "sanitized_text": cleaned,
        "redactions_count": redactions,
        "is_safe": True
    }`,
      rustKernel: `// Regex Sanitizer Kernel (Optimized with Rust Regex Set)
use regex::RegexSet;
pub fn sanitize_fast(input: &str) -> (String, usize) {
    // Compiled regex state machine running at zero-copy throughput
    ...
} // 19.5x Speedup`,
      output: {
        sanitized_text: 'Alice, [REDACTED_SSN], key: [REDACTED_KEY]',
        redactions_count: 2,
        is_safe: true,
        telemetry: {
          execution_mode: 'SANDBOX_CONTAINED',
          p50_latency_ms: 0.18,
          p95_latency_ms: 0.31,
          formal_invariants: 'PROVEN (Regex bounded match time)',
          mutation_score: '88.9% (8/9 mutants killed)',
          trust_signature: 'hmac-sha256:3b42c98d01ef67a...',
        },
      },
    },
    sql_optimizer: {
      name: 'SQL Dialect Transpiler & Injection Guard',
      domain: 'database',
      gapReason: 'Host agent attempted raw string concatenation in Postgres query generation',
      pythonCode: `@capability(
    id="sql_transpile_guard",
    domain="database",
    risk_level="MEDIUM",
    tests=[
        {"id": "t1", "inputs": {"query": "SELECT * FROM users WHERE id = 10; DROP TABLE users;"}, "expected_keys": ["is_valid", "sanitized_sql"]}
    ]
)
def sql_transpile_guard(query: str, target_dialect: str = "postgres") -> dict:
    import sqlparse
    parsed = sqlparse.parse(query)
    has_dangerous_statements = any(stmt.get_type() in ("DROP", "ALTER", "TRUNCATE") for stmt in parsed)
    
    return {
        "is_valid": not has_dangerous_statements,
        "statement_count": len(parsed),
        "target_dialect": target_dialect,
        "sanitized_sql": query if not has_dangerous_statements else "BLOCKED_UNSAFE_SQL"
    }`,
      rustKernel: `// AST SQL Parser (Zero-Allocation Tokenizer)
pub fn parse_sql_tree(query: &str) -> Result<ParsedAST, SecurityError> {
    ...
} // 31.0x Speedup`,
      output: {
        is_valid: false,
        statement_count: 2,
        target_dialect: 'postgres',
        sanitized_sql: 'BLOCKED_UNSAFE_SQL',
        telemetry: {
          execution_mode: 'SANDBOX_CONTAINED',
          firewall_action: 'AST_INJECTION_RULE_TRIGGERED',
          formal_invariants: 'PROVEN (Absence of multiple root statements)',
          mutation_score: '100.0% (11/11 mutants killed)',
          trust_signature: 'hmac-sha256:91bc820de45f12a...',
        },
      },
    },
  };

  function updatePreset() {
    if (!simSelect || !simEditor || !simResults) return;
    const key = simSelect.value;
    const preset = SIMULATION_PRESETS[key] || SIMULATION_PRESETS.monte_carlo_var;
    simEditor.textContent = preset.pythonCode;
    simResults.textContent =
      '// Click "Synthesize & Run Evolution Pipeline" to execute CapForge autonomous acquisition flow...';
    if (simStatus) simStatus.innerText = 'Ready to evolve';
    if (simLatency) simLatency.innerText = '0.00 ms';
    simStages.forEach((s) => {
      s.classList.remove('active', 'passed');
    });
  }

  if (simSelect) {
    simSelect.addEventListener('change', updatePreset);
    updatePreset();
  }

  if (simRunBtn) {
    simRunBtn.addEventListener('click', async () => {
      const key = simSelect.value;
      const preset = SIMULATION_PRESETS[key] || SIMULATION_PRESETS.monte_carlo_var;
      simRunBtn.disabled = true;
      simRunBtn.innerText = 'Evolving...';

      // Reset stages
      simStages.forEach((s) => s.classList.remove('active', 'passed'));

      // Stage 1: Gap Detection
      simStages[0]?.classList.add('active');
      simStatus.innerText = 'Detecting capability gap in Control Plane...';
      simResults.textContent =
        `[CONTROL PLANE] Querying CapabilityRegistry for '${key}'...
` +
        `[GAP DETECTED] Cache Miss: '${preset.gapReason}'
` +
        `[JOB QUEUED] Emitting CAPABILITY_GAP event to Learning Plane worker pool...`;
      await new Promise((r) => setTimeout(r, 450));
      simStages[0]?.classList.replace('active', 'passed');

      // Stage 2: Synthesis
      simStages[1]?.classList.add('active');
      simStatus.innerText = 'Synthesizing code with AST self-repair...';
      simResults.textContent +=
        `

[SYNTHESIZER] Prompting LLM code model with typed ParameterSpec contract...
` +
        `[AST REPAIR] Pass 1: Parsing Abstract Syntax Tree... OK
` +
        `[AST REPAIR] Pass 2: Type annotation validation... OK (Pydantic v2 compliant)`;
      await new Promise((r) => setTimeout(r, 450));
      simStages[1]?.classList.replace('active', 'passed');

      // Stage 3: 5-Level Verification
      simStages[2]?.classList.add('active');
      simStatus.innerText = 'Running 5-Level Verification Gate...';
      simResults.textContent +=
        `

[VERIFICATION BATTERY]
` +
        `  -> L0 CodeGuardian AST: Zero forbidden imports (os.system/eval safe) [PASS]
` +
        `  -> L1 SMT Formal Invariants: Z3 Theorem Prover certified constraints [PASS]
` +
        `  -> L2 Isolated Sandbox: Executed in Docker container (CPU: 0.5, Mem: 128MB) [PASS]
` +
        `  -> L3 Property Fuzzing: 50 randomized boundary tests evaluated [PASS]
` +
        `  -> L4 Zero-Regression: Backward compatibility preserved [PASS]
` +
        `  -> L5 Continuous Mutation: ${preset.output.telemetry.mutation_score} [PASS]`;
      await new Promise((r) => setTimeout(r, 550));
      simStages[2]?.classList.replace('active', 'passed');

      // Stage 4: Hot-Path Rust Transpilation
      simStages[3]?.classList.add('active');
      simStatus.innerText = 'Profiling hot-paths & compiling PyO3 Rust extension...';
      simEditor.textContent = preset.rustKernel;
      simResults.textContent +=
        `

[OPTIMIZATION PROFILER] Bottleneck detected: Computational loop with heavy operations.
` +
        `[PYO3 TRANSPILER] Synthesizing native Rust kernel blueprint...
` +
        `[CARGO SANDBOX] Compiling crate into shared library artifact (.so/.pyd)... OK
` +
        `[BENCHMARK] Verified functional parity! Speedup: ${preset.output.telemetry.speedup_factor || '28x'}`;
      await new Promise((r) => setTimeout(r, 500));
      simStages[3]?.classList.replace('active', 'passed');

      // Stage 5: Trust Chain & Promotion
      simStages[4]?.classList.add('active');
      simStatus.innerText = 'Signing manifest & promoting to ACTIVE...';
      simResults.textContent +=
        `

[SECURITY] Generating cryptographic HMAC-SHA256 signature...
` +
        `[REGISTRY] Promoted status: EXPERIMENTAL -> ACTIVE (v1.0.0)
` +
        `[MCP HUB] Dynamically broadcasted new tool declaration to all MCP clients!

` +
        `=== FINAL EXECUTION RESPONSE ===
` +
        JSON.stringify(preset.output, null, 2);
      await new Promise((r) => setTimeout(r, 400));
      simStages[4]?.classList.replace('active', 'passed');

      simLatency.innerText = preset.output.telemetry.p50_latency_ms + ' ms';
      simStatus.innerText = 'Evolution Complete - Capability ACTIVE';
      simRunBtn.disabled = false;
      simRunBtn.innerText = 'Run Pipeline Again';
    });
  }
})();
