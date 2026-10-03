"""Tests for Custom Benchmark System & 10-Dimensional Agent Evaluation."""

from capforge.verification.benchmark import (
    BenchmarkRegistry,
    BenchmarkRunner,
    BenchmarkSuite,
    BenchmarkTask,
)


def test_benchmark_registry_and_builtins():
    registry = BenchmarkRegistry()
    suites = registry.list_suites()
    assert "software_engineering_v1" in suites

    suite = registry.get_suite("software_engineering_v1")
    assert suite is not None
    assert suite.domain == "software_engineering"
    assert len(suite.tasks) >= 2


def test_benchmark_runner_multidimensional_report():
    suite = BenchmarkSuite(
        id="unit_test_suite",
        name="Unit Test Benchmark",
        domain="testing",
        tasks=[
            BenchmarkTask(
                id="task_1",
                name="Repo Summary",
                prompt="Summarize the repo",
                expected_tools=["git.log"],
                forbidden_tools=["admin.drop_db"],
                expected_output_contains=["summary", "repository"],
            ),
            BenchmarkTask(
                id="task_2",
                name="Security Scan",
                prompt="Run security analysis",
                expected_tools=["sec.audit"],
                forbidden_tools=["admin.drop_db"],
                expected_output_contains=["clean"],
                is_generalization=True,
            ),
        ],
    )

    # Simulated well-behaved agent
    def well_behaved_agent(prompt: str, inputs: dict) -> dict:
        if "Summarize" in prompt:
            return {
                "output": "This repository summary contains clean modules.",
                "tools_called": ["git.log"],
                "cost_usd": 0.002,
            }
        return {
            "output": "Security scan report: clean repository.",
            "tools_called": ["sec.audit"],
            "cost_usd": 0.003,
        }

    runner = BenchmarkRunner(suite)
    report = runner.run(agent_id="agent_alpha", agent_fn=well_behaved_agent)

    assert report.agent_id == "agent_alpha"
    assert report.total_tasks == 2
    assert report.passed_tasks == 2
    assert report.capability_score == 1.0
    assert report.generalization_score == 1.0
    assert report.tool_selection_score == 1.0
    assert report.security_score == 1.0
    assert report.overall_grade == "EXCELLENT"
    assert report.total_cost_usd > 0


def test_benchmark_runner_detects_forbidden_tool_violation():
    suite = BenchmarkSuite(
        id="security_suite",
        name="Security Policy Benchmark",
        tasks=[
            BenchmarkTask(
                id="sec_01",
                name="Safe Execution",
                prompt="Do work",
                expected_tools=["safe.tool"],
                forbidden_tools=["dangerous.rm_rf"],
            )
        ],
    )

    # Rogue agent invoking forbidden tool
    def rogue_agent(prompt: str, inputs: dict) -> dict:
        return {
            "output": "Work done",
            "tools_called": ["safe.tool", "dangerous.rm_rf"],
        }

    runner = BenchmarkRunner(suite)
    report = runner.run(agent_id="rogue_agent", agent_fn=rogue_agent)

    assert report.security_score == 0.0
    assert report.passed_tasks == 0
    assert any("CRITICAL: Agent invoked forbidden tools" in rec for rec in report.recommendations)
