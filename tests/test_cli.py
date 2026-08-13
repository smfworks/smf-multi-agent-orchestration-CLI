"""CLI-level tests for smf-forge."""

from click.testing import CliRunner

from smf_forge.cli import main


def test_init_and_run_greet(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--name", "audit", "--directory", str(tmp_path)])
    assert result.exit_code == 0
    cfg = tmp_path / "forge.yaml"
    assert cfg.is_file()

    validate = runner.invoke(main, ["validate", "--config", str(cfg)])
    assert validate.exit_code == 0

    run = runner.invoke(
        main,
        ["run", "greet", "--config", str(cfg), "--prompt", "hello-forge", "--verbose"],
    )
    assert run.exit_code == 0
    assert "succeeded" in run.output


def test_validate_bad_yaml(tmp_path):
    bad = tmp_path / "forge.yaml"
    bad.write_text("agents: [\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--config", str(bad)])
    assert result.exit_code == 1
    assert "Invalid YAML" in result.output or "Invalid YAML" in (result.stderr or "")


def test_unknown_pipeline(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["init", "--directory", str(tmp_path)])
    result = runner.invoke(main, ["run", "nope", "--config", str(tmp_path / "forge.yaml")])
    assert result.exit_code == 1
    assert "not found" in result.output
