"""SMF Forge CLI — multi-agent orchestration from the terminal."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import click
import yaml
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
from smf_forge.engine import PipelineEngine, StepStatus

console = Console()
err_console = Console(stderr=True)


def _load_project_config(path: Path | None = None) -> dict:
    """Load, env-resolve, and validate config. Exits on error."""
    try:
        config_path = path or find_config()
        raw = load_config(config_path)
        data = resolve_env_vars(raw)
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
def main():
    """SMF Forge — lightweight multi-agent orchestration CLI.

    Define agents and pipelines in forge.yaml, then run them.
    """
    pass


@main.command()
@click.option("--name", default="my-project", help="Project name")
@click.option("--directory", default=".", help="Directory to create config in")
def init(name: str, directory: str):
    """Initialize a new smf-forge project with a forge.yaml template."""
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / CONFIG_FILENAME

    if config_path.exists():
        err_console.print(f"[yellow]{CONFIG_FILENAME} already exists at {config_path}[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    # Read template and substitute project name
    template_path = Path(__file__).parent / "templates" / "forge.yaml"
    if template_path.exists():
        content = template_path.read_text()
        content = content.replace("${FORGE_PROJECT:my-project}", name)
    else:
        content = f"""project: {name}\nversion: "0.1.0"\n\nagents:\n  echo:\n    type: echo\n\npipelines: {{}}\n"""

    config_path.write_text(content)
    console.print(Panel(f"Created [bold]{config_path}[/bold]", title="smf-forge init", border_style="green"))
    console.print(f"\nNext steps:\n  1. Edit {config_path} to define your agents and pipelines\n  2. Run [bold]smf-forge run <pipeline>[/bold]")


@main.command()
@click.argument("pipeline_name")
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml")
@click.option("--prompt", default="", help="Input prompt for the pipeline")
@click.option("--fail-fast/--continue-on-error", default=True, help="Stop on first failure")
@click.option("--verbose", "-v", is_flag=True, help="Show step outputs")
def run(pipeline_name: str, config_path: Path | None, prompt: str, fail_fast: bool, verbose: bool):
    """Run a named pipeline."""
    data = _load_project_config(config_path)
    pipelines = data.get("pipelines", {})

    if pipeline_name not in pipelines:
        err_console.print(f"[red]Pipeline '{pipeline_name}' not found.[/red]")
        err_console.print(f"Available: {', '.join(pipelines.keys()) or '(none)'}")
        sys.exit(1)

    pipeline = pipelines[pipeline_name]
    agents_config = data.get("agents", {})

    # Build agent registry
    try:
        registry = build_registry(agents_config)
    except ValueError as exc:
        err_console.print(f"[red]Agent error:[/red] {exc}")
        sys.exit(1)

    # Inject prompt into context if provided
    context = {}
    if prompt:
        context["prompt"] = prompt

    engine = PipelineEngine(fail_fast=fail_fast, verbose=verbose)

    console.print(f"\n[bold]Running pipeline:[/bold] {pipeline_name}\n")

    result = asyncio.run(engine.run(pipeline, registry))

    # If prompt was given, inject it into step context
    if prompt:
        for step in result.steps:
            if step.status == StepStatus.SUCCESS and step.output is None:
                step.output = {"prompt": prompt}

    engine.print_result(result)

    if not result.success:
        sys.exit(1)


@main.command(name="agents")
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml")
def list_agents(config_path: Path | None):
    """List configured agents."""
    data = _load_project_config(config_path)
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
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml")
def pipelines(config_path: Path | None):
    """List configured pipelines and their steps."""
    data = _load_project_config(config_path)
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
@click.option("--config", "config_path", type=Path, default=None, help="Path to forge.yaml")
def validate(config_path: Path | None):
    """Validate forge.yaml config without running anything."""
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