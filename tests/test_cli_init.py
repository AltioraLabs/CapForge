"""Tests for CapForge CLI init and webhook commands."""

from typer.testing import CliRunner

from capforge.cli import app

runner = CliRunner()


def test_cli_init_command(tmp_path):
    """Test capforge init command generates expected project files and directories."""
    target_dir = tmp_path / "new_project"
    result = runner.invoke(app, ["init", "--name", "TestProject", str(target_dir)])

    assert result.exit_code == 0
    assert "Initialized CapForge project 'TestProject'" in result.stdout

    # Verify generated files
    assert (target_dir / "capforge.yaml").exists()
    assert (target_dir / "capabilities").is_dir()
    assert (target_dir / "capabilities" / "sample_capability.py").exists()
    assert (target_dir / "capabilities" / "register_all.py").exists()
    assert (target_dir / "tests").is_dir()
    assert (target_dir / "tests" / "test_capabilities.py").exists()

    # Check contents of capforge.yaml
    yaml_text = (target_dir / "capforge.yaml").read_text(encoding="utf-8")
    assert 'project_name: "TestProject"' in yaml_text
    assert "server:" in yaml_text
    assert "security:" in yaml_text


def test_cli_webhook_commands():
    """Test capforge webhook-add, webhooks, and webhook-remove commands."""
    # 1. Add webhook
    result = runner.invoke(
        app,
        [
            "webhook-add",
            "https://hooks.slack.com/services/test",
            "-e",
            "skill_promoted,task_failed",
            "-d",
            "Slack Alerts",
        ],
    )
    assert result.exit_code == 0
    assert "Registered webhook" in result.stdout

    # Extract ID from output
    # e.g. "Registered webhook <UUID> -> https://..."
    words = result.stdout.split()
    webhook_idx = words.index("webhook")
    webhook_id = words[webhook_idx + 1]

    # 2. List webhooks
    result = runner.invoke(app, ["webhooks"])
    assert result.exit_code == 0
    assert "CapForge Webhook Subscriptions" in result.stdout
    assert webhook_id[:6] in result.stdout
    assert "YES" in result.stdout

    # 3. Remove webhook
    result = runner.invoke(app, ["webhook-remove", webhook_id])
    assert result.exit_code == 0
    assert f"Unregistered webhook {webhook_id}" in result.stdout
