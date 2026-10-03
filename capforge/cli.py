"""CapForge Developer CLI.

Provides rich terminal commands for inspecting capabilities, analyzing tasks,
running test batteries, assessing risk, rolling back versions, viewing the
capability graph, and launching the REST API.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from capforge.core.config import setup_logging
from capforge.core.governance import RiskEngine
from capforge.core.models import CapabilityStatus, RiskLevel
from capforge.discovery.capability_graph import CapabilityGraph
from capforge.discovery.gap_detector import CapabilityGapDetector
from capforge.registry.store import CapabilityRegistry
from capforge.verification.evaluator import CapabilityEvaluator

app = typer.Typer(
    name="capforge",
    help="CapForge: Autonomous Capability Acquisition & Evolution Runtime for AI Agents",
)
console = Console()


@app.command("list")
def list_capabilities(domain: str = typer.Option(None, "--domain", "-d")):
    """List all registered capabilities in the Capability Registry."""
    registry = CapabilityRegistry()
    caps = registry.list_capabilities(domain=domain)

    if not caps:
        console.print("[yellow]No capabilities found in registry.[/yellow]")
        return

    table = Table(title="CapForge Capability Registry", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Type")
    table.add_column("Status", style="bold")
    table.add_column("Risk")
    table.add_column("Domain")
    table.add_column("Name")
    table.add_column("Tests", justify="right")

    risk_colors = {RiskLevel.LOW: "green", RiskLevel.MEDIUM: "yellow", RiskLevel.HIGH: "red"}

    for c in caps:
        status_color = "green" if c.status == CapabilityStatus.ACTIVE else "yellow"
        risk_color = risk_colors.get(c.risk_level, "white")
        table.add_row(
            c.id,
            c.version,
            c.capability_type.value,
            f"[{status_color}]{c.status.value}[/{status_color}]",
            f"[{risk_color}]{c.risk_level.value}[/{risk_color}]",
            c.domain,
            c.name,
            str(len(c.verification_tests)),
        )

    console.print(table)


@app.command("analyze")
def analyze_task(task_prompt: str = typer.Argument(..., help="The natural language task to analyze")):
    """Analyze a task to detect missing capabilities and required primitives."""
    registry = CapabilityRegistry()
    detector = CapabilityGapDetector(registry)

    with console.status("[bold cyan]Analyzing task capability requirements..."):
        gap = detector.evaluate_task(task_prompt)

    if gap.gap_detected:
        console.print(
            Panel(
                f"[bold red]CAPABILITY GAP DETECTED[/bold red]\n\n"
                f"[bold]Task:[/bold] {task_prompt}\n"
                f"[bold]Missing Primitives:[/bold] {gap.missing_primitives}\n"
                f"[bold]Available Primitives:[/bold] {gap.available_primitives}\n"
                f"[bold]Suggested Sources:[/bold] {gap.suggested_acquisition_sources}\n\n"
                f"[italic]{gap.rationale}[/italic]",
                title="CapForge Gap Detector",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]CAPABILITY AVAILABLE[/bold green]\n\n"
                "All required primitives exist in the registry. Direct execution authorized.",
                title="CapForge Gap Detector",
                border_style="green",
            )
        )


@app.command("test")
def test_capability(capability_id: str = typer.Argument(..., help="ID of capability to test")):
    """Run verification tests against a registered capability in the sandbox."""
    registry = CapabilityRegistry()
    evaluator = CapabilityEvaluator()
    cap = registry.get(capability_id)

    if not cap:
        console.print(f"[red]Capability '{capability_id}' not found in registry.[/red]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]Running sandbox verification on '{cap.name}' (v{cap.version})...[/bold cyan]")
    result = evaluator.evaluate(cap)

    table = Table(title=f"Verification Report: {cap.id} v{cap.version}")
    table.add_column("Test ID", style="cyan")
    table.add_column("Type")
    table.add_column("Result")
    table.add_column("Time (ms)", justify="right")
    table.add_column("Error")

    for t in result.test_details:
        res_str = "[bold green]PASS[/bold green]" if t.passed else "[bold red]FAIL[/bold red]"
        table.add_row(t.test_id, t.test_type.value, res_str, f"{t.execution_time_ms:.1f}", t.error_message or "-")

    console.print(table)
    summary_color = "green" if result.passed else "red"
    console.print(f"[{summary_color}]Passed: {result.tests_passed}/{result.tests_run} tests.[/{summary_color}]")


@app.command("risk")
def assess_risk(capability_id: str = typer.Argument(..., help="ID of capability to assess")):
    """Assess the risk level of a registered capability."""
    registry = CapabilityRegistry()
    risk_engine = RiskEngine()
    cap = registry.get(capability_id)

    if not cap:
        console.print(f"[red]Capability '{capability_id}' not found in registry.[/red]")
        raise typer.Exit(1)

    assessment = risk_engine.assess(cap)

    risk_colors = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}
    color = risk_colors.get(assessment.risk_level.value, "white")

    console.print(
        Panel(
            f"[bold {color}]RISK: {assessment.risk_level.value}[/bold {color}]  "
            f"(score: {assessment.risk_score:.3f})\n\n"
            f"[bold]Auto-Promote:[/bold] {'✅' if assessment.auto_promote_allowed else '❌'}\n"
            f"[bold]Human Approval:[/bold] {'⚠️ Required' if assessment.requires_human_approval else '✅ Not required'}\n\n"
            f"[bold]Risk Factors:[/bold]\n" + "\n".join(f"  • {f}" for f in assessment.factors)
            if assessment.factors
            else "  (none)",
            title=f"Risk Assessment: {cap.id} v{cap.version}",
            border_style=color,
        )
    )


@app.command("graph")
def show_graph(capability_id: str = typer.Argument(..., help="ID of capability to show graph for")):
    """Show the dependency and impact graph for a capability."""
    registry = CapabilityRegistry()
    graph = CapabilityGraph(registry)
    graph.build_from_registry()

    report = graph.impact_analysis(capability_id)

    tree = Tree(f"[bold cyan]{capability_id}[/bold cyan]")

    if report.directly_affected:
        direct_branch = tree.add("[bold yellow]Direct Dependents[/bold yellow]")
        for dep in report.directly_affected:
            direct_branch.add(f"[yellow]{dep}[/yellow]")

    if report.transitively_affected:
        transitive_branch = tree.add("[bold red]Transitive Impact[/bold red]")
        for dep in report.transitively_affected:
            transitive_branch.add(f"[red]{dep}[/red]")

    if not report.directly_affected and not report.transitively_affected:
        tree.add("[green]No dependent capabilities[/green]")

    console.print(Panel(tree, title=f"Impact Analysis: {capability_id}", border_style="cyan"))
    console.print(f"Total impact count: [bold]{report.total_impact_count}[/bold]")


@app.command("demo")
def demo_command():
    """Run the CapForge Software Engineering Agent Killer Demonstration (discussion.mdx §39)."""
    from examples.killer_demo import run_killer_demo

    run_killer_demo()


@app.command("export-manifest")
def export_manifest(
    capability_id: str = typer.Argument(..., help="ID of capability to export"),
    output_path: str = typer.Option(None, "--output", "-o", help="File path to save YAML manifest"),
):
    """Export a capability as a canonical YAML manifest (discussion.mdx §12)."""
    from capforge.core.manifest import capability_to_yaml

    registry = CapabilityRegistry()
    cap = registry.get(capability_id)
    if not cap:
        console.print(f"[red]Capability '{capability_id}' not found in registry.[/red]")
        raise typer.Exit(1)

    yaml_str = capability_to_yaml(cap)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(yaml_str)
        console.print(f"[green]Exported manifest for '{capability_id}' to {output_path}[/green]")
    else:
        console.print(yaml_str)


@app.command("import-manifest")
def import_manifest(
    manifest_path: str = typer.Argument(..., help="Path to YAML capability manifest file"),
):
    """Import a capability definition from a YAML manifest into the registry."""
    from capforge.core.manifest import manifest_yaml_to_capability

    try:
        with open(manifest_path, encoding="utf-8") as f:
            content = f.read()
        cap = manifest_yaml_to_capability(content)
        registry = CapabilityRegistry()
        registered = registry.register(cap)
        console.print(
            f"[green]Successfully imported capability '{registered.id}' (v{registered.version}) into registry.[/green]"
        )
    except Exception as e:
        console.print(f"[red]Failed to import manifest: {e}[/red]")
        raise typer.Exit(1)


@app.command("jobs")
def list_jobs():
    """List recent autonomous learning jobs."""
    from capforge.acquisition.jobs import LearningJobManager

    mgr = LearningJobManager()
    jobs = mgr.list_jobs()
    if not jobs:
        console.print("[yellow]No learning jobs recorded yet.[/yellow]")
        return

    table = Table(title="CapForge Learning Jobs", show_header=True, header_style="bold magenta")
    table.add_column("Job ID", style="cyan")
    table.add_column("Intent")
    table.add_column("Status")
    table.add_column("Step")
    table.add_column("Progress", justify="right")
    table.add_column("Capability")

    for j in jobs:
        status_color = "green" if j.status == "COMPLETED" else ("red" if j.status == "FAILED" else "yellow")
        table.add_row(
            j.job_id,
            j.task_intent[:40] + ("..." if len(j.task_intent) > 40 else ""),
            f"[{status_color}]{j.status}[/{status_color}]",
            j.step,
            f"{j.progress_pct}%",
            j.capability_id or "-",
        )
    console.print(table)


@app.command("serve")
def start_server(
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
):
    """Launch the CapForge FastAPI REST server and Control Center Dashboard."""
    import uvicorn

    setup_logging()
    console.print(f"[bold green]Starting CapForge API server at http://{host}:{port}...[/bold green]")
    console.print(
        f"[bold cyan]CapForge Control Center Dashboard available at http://{host}:{port}/dashboard[/bold cyan]"
    )
    uvicorn.run("capforge.server.app:app", host=host, port=port, reload=False)


@app.command("version")
def show_version():
    """Print the active CapForge version and platform information."""
    import platform
    import sys

    import capforge

    console.print(f"[bold cyan]CapForge Engine:[/bold cyan] [green]v{capforge.__version__}[/green]")
    console.print(
        f"[cyan]Python Runtime:[/cyan] {sys.version.split()[0]} on {platform.system()} ({platform.machine()})"
    )
    console.print("[dim]Enterprise Capability Acquisition, Verification, and Evolution Platform[/dim]")


@app.command("health")
@app.command("check")
def run_health_check():
    """Run production readiness diagnostics on storage, sandbox, broker, and governance."""
    import sqlite3

    from capforge.core.governance import RiskEngine
    from capforge.events.broker import InMemoryStreamBroker
    from capforge.verification.sandbox import SandboxRunner
    from capforge.verification.sandbox_docker import DockerSandboxRunner

    console.print(Panel.fit("[bold green]CapForge Enterprise Diagnostics & Health Suite[/bold green]"))

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Subsystem", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    # 1. Database & WAL mode
    reg = CapabilityRegistry()
    wal_status = "UNKNOWN"
    try:
        with sqlite3.connect(reg.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            row = cursor.fetchone()
            if row:
                wal_status = row[0].upper()
        table.add_row("SQLite Storage", "[green]PASS[/green]", f"Path: {reg.db_path.name}, Journal Mode: {wal_status}")
    except Exception as e:
        table.add_row("SQLite Storage", "[red]FAIL[/red]", str(e))

    # 2. Subprocess Sandbox
    try:
        runner = SandboxRunner()
        res = runner.execute_code("def execute(inputs): return {'ok': True}", "execute", {})
        if res.get("success"):
            table.add_row(
                "Subprocess Sandbox",
                "[green]PASS[/green]",
                f"Execution verified in {res.get('execution_time_ms', 0)}ms",
            )
        else:
            table.add_row("Subprocess Sandbox", "[red]FAIL[/red]", str(res.get("error")))
    except Exception as e:
        table.add_row("Subprocess Sandbox", "[red]FAIL[/red]", str(e))

    # 3. Docker Container Sandbox
    docker_runner = DockerSandboxRunner()
    if docker_runner.is_docker_enabled():
        table.add_row("Docker Sandbox", "[green]PASS[/green]", "Docker daemon active & container isolation ready")
    else:
        table.add_row(
            "Docker Sandbox", "[yellow]INFO[/yellow]", "Docker daemon inactive; fallback to subprocess sandbox"
        )

    # 4. Stream Broker
    try:
        InMemoryStreamBroker()
        table.add_row("Stream Broker", "[green]PASS[/green]", "In-memory ring buffer operational")
    except Exception as e:
        table.add_row("Stream Broker", "[red]FAIL[/red]", str(e))

    # 5. Governance Queue
    try:
        risk = RiskEngine()
        pending = len(risk.list_tickets(status="PENDING"))
        table.add_row("Governance Queue", "[green]PASS[/green]", f"{pending} tickets pending human review")
    except Exception as e:
        table.add_row("Governance Queue", "[red]FAIL[/red]", str(e))

    console.print(table)


# ---------------------------------------------------------------------------
# Project Scaffolding: capforge init
# ---------------------------------------------------------------------------


@app.command("init")
def init_project(
    project_dir: str = typer.Argument(".", help="Directory to initialize (defaults to current)"),
    project_name: str = typer.Option(None, "--name", "-n", help="Project name"),
):
    """Initialize a new CapForge-integrated project with sample capabilities, tests, and config."""
    import os

    target = os.path.abspath(project_dir)
    name = project_name or os.path.basename(target) or "my_capforge_project"

    dirs_to_create = [
        os.path.join(target, "capabilities"),
        os.path.join(target, "capabilities", "manifests"),
        os.path.join(target, "tests"),
    ]
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)

    config_path = os.path.join(target, "capforge.yaml")
    if not os.path.exists(config_path):
        config_content = f"""# CapForge Project Configuration
project_name: "{name}"
version: "1.0.0"

# Server settings
server:
  host: "127.0.0.1"
  port: 8000

# Security settings
security:
  enable_trust_chain: false
  block_on_critical: true
  auto_evaluate: true

# Evolution settings
evolution:
  enabled: false
  max_llm_calls_per_hour: 50
  max_cost_per_day_usd: 10.0

# Database
storage:
  db_path: "data/capforge.db"
"""
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

    sample_cap_path = os.path.join(target, "capabilities", "sample_capability.py")
    if not os.path.exists(sample_cap_path):
        sample_content = '''"""Sample CapForge capability demonstrating the @capability decorator."""

from capforge import capability


@capability(
    id="text_word_count",
    name="Text Word Counter",
    domain="nlp",
    risk_level="LOW",
    tags=["text", "utility"],
    tests=[
        {
            "id": "test_basic",
            "name": "Basic word count",
            "inputs": {"text": "hello world foo"},
            "expected_keys": ["word_count"],
            "assert_expression": "output['word_count'] == 3",
        },
        {
            "id": "test_empty",
            "name": "Empty input",
            "inputs": {"text": ""},
            "expected_keys": ["word_count"],
            "assert_expression": "output['word_count'] == 0",
        },
    ],
)
def text_word_count(text: str = "") -> dict:
    """Count the number of words in the given text."""
    words = text.split()
    return {
        "word_count": len(words),
        "characters": len(text),
        "words": words,
    }
'''
        with open(sample_cap_path, "w", encoding="utf-8") as f:
            f.write(sample_content)

    integration_path = os.path.join(target, "capabilities", "register_all.py")
    if not os.path.exists(integration_path):
        integration_content = '''"""Register all project capabilities with CapForge."""

from capforge import CapForgeClient
from capabilities.sample_capability import text_word_count


def main():
    client = CapForgeClient(enable_security_scan=True, auto_evaluate=True)

    cap = client.register(text_word_count, promote=True)
    print(f"Registered: {cap.id} v{cap.version} (status={cap.status.value})")

    health = client.health_check()
    print(f"Health: {health}")


if __name__ == "__main__":
    main()
'''
        with open(integration_path, "w", encoding="utf-8") as f:
            f.write(integration_content)

    test_path = os.path.join(target, "tests", "test_capabilities.py")
    if not os.path.exists(test_path):
        test_content = '''"""Test suite for project capabilities."""

from capforge import CapForgeClient


def test_word_count_registration():
    """Test that the sample capability registers and evaluates correctly."""
    from capabilities.sample_capability import text_word_count

    client = CapForgeClient(enable_security_scan=False, auto_evaluate=True)
    cap = client.register(text_word_count, promote=True)
    assert cap.status.value == "ACTIVE"

    result = client.execute("text_word_count", {"text": "hello world"})
    assert result.status == "SUCCESS"
    assert result.output["word_count"] == 2
'''
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_content)

    console.print(f"\n[bold green]Initialized CapForge project '{name}' at {target}[/bold green]\n")
    console.print("[cyan]Created:[/cyan]")
    console.print("  [dim]capforge.yaml[/dim]                    - Project configuration")
    console.print("  [dim]capabilities/[/dim]                     - Capability source directory")
    console.print("  [dim]capabilities/sample_capability.py[/dim] - Sample @capability decorator")
    console.print("  [dim]capabilities/register_all.py[/dim]     - Registration script")
    console.print("  [dim]tests/test_capabilities.py[/dim]         - Sample test suite")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. [cyan]cd {target}[/cyan]")
    console.print("  2. [cyan]capforge check[/cyan]                  - Verify environment and dependencies")
    console.print("  3. [cyan]python capabilities/register_all.py[/cyan] - Register capabilities")
    console.print("  4. [cyan]capforge list[/cyan]                   - View registered capabilities")


# ---------------------------------------------------------------------------
# Webhooks CLI: capforge webhooks, webhook-add, webhook-remove
# ---------------------------------------------------------------------------


@app.command("webhooks")
def list_webhooks():
    """List all registered webhook subscriptions and delivery status."""
    from capforge.events.webhooks import webhook_manager

    subs = webhook_manager.list_subscriptions(active_only=False)
    if not subs:
        console.print("[yellow]No webhook subscriptions registered.[/yellow]")
        return

    table = Table(title="CapForge Webhook Subscriptions")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("URL", style="cyan")
    table.add_column("Events", style="magenta")
    table.add_column("Active", justify="center")
    table.add_column("Failures", justify="right")
    table.add_column("Description")

    for s in subs:
        table.add_row(
            s.id[:8] + "...",
            s.url,
            ", ".join(s.events) if s.events else "(all)",
            "[green]YES[/green]" if s.active else "[red]NO[/red]",
            str(s.failure_count),
            s.description or "-",
        )

    console.print(table)


@app.command("webhook-add")
def add_webhook(
    url: str = typer.Argument(..., help="Callback destination URL"),
    events: str = typer.Option("", "--events", "-e", help="Comma-separated event names (empty = all)"),
    secret: str = typer.Option(None, "--secret", "-s", help="HMAC secret for signature verification"),
    description: str = typer.Option("", "--desc", "-d", help="Description of webhook target"),
):
    """Register a new webhook callback URL."""
    from capforge.events.webhooks import WebhookSubscription, webhook_manager

    event_list = [ev.strip() for ev in events.split(",") if ev.strip()] if events else []
    sub = WebhookSubscription(
        url=url,
        events=event_list,
        secret=secret,
        description=description,
    )
    registered = webhook_manager.register(sub)
    console.print(f"[bold green]Registered webhook {registered.id} -> {registered.url}[/bold green]")


@app.command("webhook-remove")
def remove_webhook(
    webhook_id: str = typer.Argument(..., help="ID of webhook to remove"),
):
    """Remove a webhook subscription by ID."""
    from capforge.events.webhooks import webhook_manager

    removed = webhook_manager.unregister(webhook_id)
    if removed:
        console.print(f"[green]Unregistered webhook {webhook_id}[/green]")
    else:
        console.print(f"[red]Webhook {webhook_id} not found[/red]")


if __name__ == "__main__":
    app()
