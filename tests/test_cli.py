"""Tests for the smf-forge CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from smf_forge.cli import main
from smf_forge.config import CONFIG_FILENAME

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def write_config(directory: Path, data: dict) -> Path:
    path = directory / CONFIG_FILENAME
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def valid_project(tmp_path: Path) -> Path:
    """Create a valid forge.yaml project in tmp_path."""
    write_config(tmp_path, {
        "project": "test-project",
        "agents": {
            "echo": {"type": "echo"},
        },
        "pipelines": {
            "test-pipe": {
                "name": "test-pipe",
                "steps": [
                    {"name": "step1", "agent": "echo", "prompt": "{{ prompt }}"},
                ],
            },
        },
    })
    return tmp_path


# --------------------------------------------------------------------------- #
# Version
# --------------------------------------------------------------------------- #

class TestVersion:
    def test_version_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "1.0.1" in result.output


# --------------------------------------------------------------------------- #
# init command
# --------------------------------------------------------------------------- #

class TestInit:
    def test_creates_config(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(main, ["init", "--name", "my-proj", "-d", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / CONFIG_FILENAME).exists()
        content = (tmp_path / CONFIG_FILENAME).read_text()
        assert "my-proj" in content

    def test_init_force_overwrites(self, runner: CliRunner, tmp_path: Path) -> None:
        write_config(tmp_path, {"project": "old"})
        result = runner.invoke(main, ["init", "--name", "new", "-d", str(tmp_path), "--force"])
        assert result.exit_code == 0
        content = (tmp_path / CONFIG_FILENAME).read_text()
        assert "new" in content

    def test_init_prompts_on_existing(self, runner: CliRunner, tmp_path: Path) -> None:
        write_config(tmp_path, {"project": "old"})
        result = runner.invoke(main, ["init", "--name", "new", "-d", str(tmp_path)], input="n\n")
        assert result.exit_code == 0
        # Should not have overwritten
        content = (tmp_path / CONFIG_FILENAME).read_text()
        assert "old" in content


    def test_init_run_demo_without_secrets(self, runner: CliRunner, tmp_path: Path) -> None:
        init = runner.invoke(main, ["init", "--name", "smoke", "-d", str(tmp_path)])
        assert init.exit_code == 0
        validate = runner.invoke(main, ["validate", "--config", str(tmp_path / CONFIG_FILENAME)])
        assert validate.exit_code == 0
        assert "Config is valid" in " ".join(validate.output.split())
        agents = runner.invoke(main, ["agents", "--config", str(tmp_path / CONFIG_FILENAME)])
        assert agents.exit_code == 0
        run = runner.invoke(
            main,
            ["run", "demo", "--config", str(tmp_path / CONFIG_FILENAME), "--prompt", "hello"],
        )
        assert run.exit_code == 0, run.output
        assert "hello" in run.output or "succeeded" in run.output.lower() or "✓" in run.output


# --------------------------------------------------------------------------- #
# validate command
# --------------------------------------------------------------------------- #

class TestValidate:
    def test_valid_config(self, runner: CliRunner, valid_project: Path) -> None:
        result = runner.invoke(main, ["validate", "--config", str(valid_project / CONFIG_FILENAME)])
        assert result.exit_code == 0
        assert "valid" in result.output

    def test_invalid_config(self, runner: CliRunner, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "agents": {"bad": {"model": "gpt-4"}},  # missing type
        })
        result = runner.invoke(main, ["validate", "--config", str(tmp_path / CONFIG_FILENAME)])
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_no_config_found(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(main, ["validate", "--config", str(tmp_path / "nonexistent.yaml")])
        assert result.exit_code == 1


# --------------------------------------------------------------------------- #
# agents command
# --------------------------------------------------------------------------- #

class TestAgentsCommand:
    def test_lists_agents(self, runner: CliRunner, valid_project: Path) -> None:
        result = runner.invoke(main, ["agents", "--config", str(valid_project / CONFIG_FILENAME)])
        assert result.exit_code == 0
        assert "echo" in result.output

    def test_shows_builtin_types(self, runner: CliRunner, valid_project: Path) -> None:
        result = runner.invoke(main, ["agents", "--config", str(valid_project / CONFIG_FILENAME)])
        assert result.exit_code == 0
        assert "echo" in result.output
        assert "http" in result.output


# --------------------------------------------------------------------------- #
# pipelines command
# --------------------------------------------------------------------------- #

class TestPipelinesCommand:
    def test_lists_pipelines(self, runner: CliRunner, valid_project: Path) -> None:
        cfg = str(valid_project / CONFIG_FILENAME)
        result = runner.invoke(main, ["pipelines", "--config", cfg])
        assert result.exit_code == 0
        assert "test-pipe" in result.output
        assert "step1" in result.output

    def test_no_pipelines(self, runner: CliRunner, tmp_path: Path) -> None:
        write_config(tmp_path, {"agents": {"echo": {"type": "echo"}}})
        result = runner.invoke(main, ["pipelines", "--config", str(tmp_path / CONFIG_FILENAME)])
        assert result.exit_code == 0
        assert "No pipelines" in result.output


# --------------------------------------------------------------------------- #
# run command
# --------------------------------------------------------------------------- #

class TestRunCommand:
    def test_run_success(self, runner: CliRunner, valid_project: Path) -> None:
        cfg = str(valid_project / CONFIG_FILENAME)
        result = runner.invoke(
            main,
            ["run", "test-pipe", "--config", cfg, "--prompt", "hello"],
        )
        assert result.exit_code == 0
        assert "succeeded" in result.output

    def test_run_pipeline_not_found(self, runner: CliRunner, valid_project: Path) -> None:
        result = runner.invoke(
            main,
            ["run", "nonexistent", "--config", str(valid_project / CONFIG_FILENAME)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_run_with_continue_on_error(self, runner: CliRunner, tmp_path: Path) -> None:
        # http agent with no API key returns an error dict → step fails
        write_config(tmp_path, {
            "agents": {
                "echo": {"type": "echo"},
                "nokey": {"type": "http", "model": "gpt-4"},
            },
            "pipelines": {
                "fail-pipe": {
                    "name": "fail-pipe",
                    "steps": [
                        {"name": "s1", "agent": "nokey", "prompt": "x"},
                        {"name": "s2", "agent": "echo", "prompt": "y"},
                    ],
                },
            },
        })
        cfg = str(tmp_path / CONFIG_FILENAME)
        result = runner.invoke(
            main,
            ["run", "fail-pipe", "--config", cfg, "--continue-on-error"],
        )
        assert result.exit_code == 1  # failure exit code
        assert "Failed" in result.output

    def test_run_fail_fast(self, runner: CliRunner, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "agents": {
                "echo": {"type": "echo"},
                "nokey": {"type": "http", "model": "gpt-4"},
            },
            "pipelines": {
                "fail-pipe": {
                    "name": "fail-pipe",
                    "steps": [
                        {"name": "s1", "agent": "nokey", "prompt": "x"},
                        {"name": "s2", "agent": "echo", "prompt": "y", "depends_on": ["s1"]},
                    ],
                },
            },
        })
        result = runner.invoke(
            main,
            ["run", "fail-pipe", "--config", str(tmp_path / CONFIG_FILENAME)],
        )
        assert result.exit_code == 1

    def test_run_invalid_config_exits_1(self, runner: CliRunner, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "agents": {"bad": {"model": "gpt-4"}},  # missing type
        })
        result = runner.invoke(
            main,
            ["run", "any", "--config", str(tmp_path / CONFIG_FILENAME)],
        )
        assert result.exit_code == 1
