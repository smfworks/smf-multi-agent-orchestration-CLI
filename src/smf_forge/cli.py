"""SMF Forge CLI — multi-agent orchestration from the terminal.

Commands:
  init       Initialize a new smf-forge project with a forge.yaml template
  run        Run a named pipeline
  agents     List configured agents
  pipelines  List configured pipelines and their steps
  validate   Validate forge.yaml config without running anything
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from smf_forge import __version__
from smf_forge.agents import AGENT_TYPES, build_registry
from smf_forge.config import (
    CONFIG_FILENAME,
    ConfigError,
    find_config,
    load_config,
    resolve_env_vars,
    validate_config,
)
from smf_forge.engine import PipelineEngine

console = Console()
err_console = Console(stderr=True)

logger = logging.getLogger(__name__)


def _load_project_config(path: Path | None = None, *, strict_env: bool = True) -> dict[str, Any]:
    """Load, env-resolve, and validate config. Exits on error.

    Args:
        path: Optional path to forge.yaml. If ``None``, uses :func:`find_config`.
        strict_env: When true, unset ``${VAR}`` (no default) is a config error.
            Listing commands pass ``False`` so unused secrets are not required.

    Returns:
        Validated config dictionary.
    """
    try:
        config_path = path or find_config()
        raw = load_config(config_path)
        data = resolve_env_vars(raw, strict=strict_env)
        errors = validate_config(data)
        if errors:
            err_console.print("[red]Config validation errors:[/red]")
            for e in errors:
                err_console.print(f"  • {e}")
            sys.exit(1)
        return data
    except ConfigError as exc:
        err_console.print(f"[red]Config error:[/red] {exc}")
        sys.exit(1)


@click.group()
@click.version_option(__version__, prog_name="smf-forge")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """SMF Forge — lightweight multi-agent orchestration CLI.

    Define agents and pipelines in forge.yaml, then run them.

    \b
    Quick start:
      smf-forge init --name my-project
      smf-forge run <pipeline> --prompt "Hello"
      smf-forge validate
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")


@main.command()
@click.option("--name", default="my-project", help="Project name for the template.")
@click.option("--directory", "-d", default=".", help="Directory to create config in.")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config without prompting.")
def init(name: str, directory: str, force: bool) -> None:
    """Initialize a new smf-forge project with a forge.yaml template.

    Creates a forge.yaml file with example agents and a pipeline.

    \b
    Examples:
      smf-forge init --name my-project
      smf-forge init -d ./projects/research --name research-bot
    """
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / CONFIG_FILENAME

    if config_path.exists() and not force:
        err_console.print(f"[yellow]{CONFIG_FILENAME} already exists at {config_path}[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    # Read template and substitute project name
    template_path = Path(__file__).parent / "templates" / "forge.yaml"
    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        content = content.replace("${FORGE_PROJECT:my-project}", name)
    else:
        content = (
            f'project: {name}\nversion: "0.1.0"\n\n'
            f"agents:\n  echo:\n    type: echo\n\npipelines: {{}}\n"
        )

    config_path.write_text(content, encoding="utf-8")
    console.print(
        Panel(f"Created [bold]{config_path}[/bold]", title="smf-forge init", border_style="green")
    )
    console.print(
        f"\nNext steps:\n"
        f"  1. Edit {config_path} to define your agents and pipelines\n"
        f"  2. Run [bold]smf-forge run <pipeline>[/bold]"
    )


@main.command()
@click.argument("pipeline_name")
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml.")
@click.option("--prompt", default="", help="Input prompt for the pipeline.")
@click.option(
    "--fail-fast/--continue-on-error",
    default=True,
    help="Stop on first failure (default) or continue on error.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show step outputs.")
@click.option(
    "--timeout",
    type=float,
    default=None,
    help="Overall pipeline timeout in seconds.",
)
def run(
    pipeline_name: str,
    config_path: Path | None,
    prompt: str,
    fail_fast: bool,
    verbose: bool,
    timeout: float | None,
) -> None:
    """Run a named pipeline.

    PIPELINE_NAME is the name of the pipeline to execute (as defined in forge.yaml).

    \\b
    Examples:
      smf-forge run research-summarize --prompt "Explain quantum computing"
      smf-forge run deploy --config ./custom.yaml --continue-on-error
      smf-forge run long-task --timeout 300
    """
    data = _load_project_config(config_path)
    pipelines = data.get("pipelines", {})

    if pipeline_name not in pipelines:
        err_console.print(f"[red]Pipeline '{pipeline_name}' not found.[/red]")
        available = ", ".join(pipelines.keys()) or "(none)"
        err_console.print(f"Available: {available}")
        sys.exit(1)

    pipeline = pipelines[pipeline_name]
    agents_config = data.get("agents", {})

    # Build agent registry
    try:
        registry = build_registry(agents_config)
    except ValueError as exc:
        err_console.print(f"[red]Agent error:[/red] {exc}")
        sys.exit(1)

    # Build initial context — include prompt if provided so steps can template it
    initial_context: dict[str, Any] = {}
    if prompt:
        initial_context["prompt"] = prompt

    engine = PipelineEngine(fail_fast=fail_fast, verbose=verbose)

    console.print(f"\n[bold]Running pipeline:[/bold] {pipeline_name}\n")

    # Execute with Ctrl-C / timeout handling
    try:
        result = asyncio.run(
            engine.run(pipeline, registry, initial_context=initial_context, timeout=timeout)
        )
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Pipeline interrupted by user (Ctrl-C).[/yellow]")
        sys.exit(130)  # 128 + SIGINT(2)
    except asyncio.TimeoutError:
        err_console.print("\n[red]Pipeline timed out.[/red]")
        sys.exit(1)

    engine.print_result(result)

    if not result.success:
        sys.exit(1)


@main.command(name="agents")
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml.")
def list_agents(config_path: Path | None) -> None:
    """List configured agents.

    Shows all agents defined in forge.yaml with their type, model, and provider.
    """
    data = _load_project_config(config_path, strict_env=False)
    agents = data.get("agents", {})

    table = Table(title="Agents")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Model")
    table.add_column("Provider")

    for name, cfg in agents.items():
        table.add_row(
            name,
            cfg.get("type", "?"),
            cfg.get("model", "—"),
            cfg.get("provider", "—"),
        )

    console.print(table)
    console.print(f"\n[dim]Built-in types: {', '.join(AGENT_TYPES.keys())}[/dim]")


@main.command()
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml.")
def pipelines(config_path: Path | None) -> None:
    """List configured pipelines and their steps.

    Shows each pipeline with its step count, agent assignments, and dependencies.
    """
    data = _load_project_config(config_path, strict_env=False)
    pipe_cfg = data.get("pipelines", {})

    if not pipe_cfg:
        console.print("[dim]No pipelines configured.[/dim]")
        return

    for pname, pconfig in pipe_cfg.items():
        steps = pconfig.get("steps", [])
        console.print(f"\n[bold]{pname}[/bold] ({len(steps)} steps)")
        for step in steps:
            deps = step.get("depends_on", [])
            dep_str = f" ← {', '.join(deps)}" if deps else ""
            console.print(f"  {step.get('name', '?')} → {step.get('agent', '?')}{dep_str}")


@main.command()
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml.")
def validate(config_path: Path | None) -> None:
    """Validate forge.yaml config without running anything.

    Checks structural validity: agent types, step names, dependencies, and cycles.
    """
    try:
        cfg_path = config_path or find_config()
        raw = load_config(cfg_path)
        errors = validate_config(raw)
        if errors:
            console.print("[red]Validation failed:[/red]")
            for e in errors:
                console.print(f"  • {e}")
            sys.exit(1)
        else:
            console.print(f"[green]✓ {cfg_path} is valid[/green]")
            agents = raw.get("agents", {})
            pipes = raw.get("pipelines", {})
            console.print(f"  {len(agents)} agent(s), {len(pipes)} pipeline(s)")
    except ConfigError as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
