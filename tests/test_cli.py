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


def test_init_validate_run_without_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    runner = CliRunner()
    init = runner.invoke(main, ["init", "--name", "smoke", "--directory", str(tmp_path)])
    assert init.exit_code == 0
    assert (tmp_path / "forge.yaml").is_file()

    validate = runner.invoke(main, ["validate", "--config", str(tmp_path / "forge.yaml")])
    assert validate.exit_code == 0
    collapsed = " ".join(validate.output.split())
    assert "Config is valid" in collapsed
    assert "1 agent" in collapsed

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


def test_validate_missing_config(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--config", str(tmp_path / "missing.yaml")])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_validate_cycle(tmp_path: Path):
    (tmp_path / "forge.yaml").write_text(
        "agents:\n  echo:\n    type: echo\n"
        "pipelines:\n  loop:\n    name: loop\n    steps:\n"
        "      - name: a\n        agent: echo\n        depends_on: [b]\n"
        "      - name: b\n        agent: echo\n        depends_on: [a]\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["run", "loop", "--config", str(tmp_path / "forge.yaml")])
    assert result.exit_code == 1
    assert "circular" in result.output.lower()


def test_version_matches_package():
    from importlib.metadata import version

    from smf_forge import __version__

    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
    assert version("smf-forge") == __version__
