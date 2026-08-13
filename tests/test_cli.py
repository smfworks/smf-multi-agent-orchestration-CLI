"""CLI and default-template smoke tests."""

import json
from pathlib import Path

from click.testing import CliRunner

from smf_forge.cli import main


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "run" in result.output


def test_init_validate_run_without_secrets(tmp_path: Path):
    runner = CliRunner()
    init = runner.invoke(main, ["init", "--name", "smoke", "--directory", str(tmp_path)])
    assert init.exit_code == 0
    assert (tmp_path / "forge.yaml").is_file()

    validate = runner.invoke(main, ["validate", "--config", str(tmp_path / "forge.yaml")])
    assert validate.exit_code == 0
    assert "is valid" in validate.output

    agents = runner.invoke(main, ["agents", "--config", str(tmp_path / "forge.yaml")])
    assert agents.exit_code == 0
    assert "echo" in agents.output

    run = runner.invoke(
        main,
        ["run", "demo", "--config", str(tmp_path / "forge.yaml"), "--prompt", "hello", "--json"],
    )
    assert run.exit_code == 0, run.output
    payload = json.loads(run.output)
    assert payload["success"] is True
    assert payload["run_id"]
    assert payload["steps"][0]["output"]["echo"] == "hello"


def test_run_missing_pipeline(tmp_path: Path):
    runner = CliRunner()
    runner.invoke(main, ["init", "--directory", str(tmp_path)])
    result = runner.invoke(main, ["run", "nope", "--config", str(tmp_path / "forge.yaml")])
    assert result.exit_code == 1
    assert "not found" in result.output
