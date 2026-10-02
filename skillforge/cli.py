"""SkillForge Developer CLI.

Provides rich terminal commands for inspecting capabilities, analyzing tasks,
running test batteries, rolling back versions, and launching the REST API.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from skillforge.core.models import CapabilityStatus
from skillforge.registry.store import CapabilityRegistry
from skillforge.discovery.gap_detector import CapabilityGapDetector
from skillforge.verification.evaluator import CapabilityEvaluator
from skillforge.versioning.manager import VersionManager

app = typer.Typer(
    name="skillforge",
    help="SkillForge: Autonomous Capability Acquisition & Evolution Runtime for AI Agents"
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

    table = Table(title="SkillForge Capability Registry", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Status", style="bold")
    table.add_column("Domain")
    table.add_column("Name")
    table.add_column("Tests", justify="right")

    for c in caps:
        status_color = "green" if c.status == CapabilityStatus.ACTIVE else "yellow"
        table.add_row(
            c.id,
            c.version,
            f"[{status_color}]{c.status.value}[/{status_color}]",
            c.domain,
            c.name,
            str(len(c.verification_tests))
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
        console.print(Panel(
            f"[bold red]CAPABILITY GAP DETECTED[/bold red]\n\n"
            f"[bold]Task:[/bold] {task_prompt}\n"
            f"[bold]Missing Primitives:[/bold] {gap.missing_primitives}\n"
            f"[bold]Available Primitives:[/bold] {gap.available_primitives}\n"
            f"[bold]Suggested Sources:[/bold] {gap.suggested_acquisition_sources}\n\n"
            f"[italic]{gap.rationale}[/italic]",
            title="SkillForge Gap Detector",
            border_style="red"
        ))
    else:
        console.print(Panel(
            f"[bold green]CAPABILITY AVAILABLE[/bold green]\n\n"
            f"All required primitives exist in the registry. Direct execution authorized.",
            title="SkillForge Gap Detector",
            border_style="green"
        ))


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


@app.command("serve")
def start_server(
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p")
):
    """Launch the SkillForge FastAPI REST server."""
    import uvicorn
    console.print(f"[bold green]Starting SkillForge API server at http://{host}:{port}...[/bold green]")
    uvicorn.run("skillforge.server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
