"""Pipeline engine — executes agent DAGs with dependency resolution."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from jinja2 import Template
from jinja2.exceptions import TemplateError
from rich.console import Console
from rich.tree import Tree

console = Console()


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Output from a single pipeline step."""

    step_name: str
    agent_name: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class PipelineResult:
    """Aggregated output from a full pipeline run."""

    pipeline_name: str
    steps: list[StepResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    success: bool = True
    run_id: str = ""

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "steps": [s.to_dict() for s in self.steps],
        }


class PipelineEngine:
    """Executes a pipeline DAG respecting step dependencies.

    Supports:
    - Sequential execution (default)
    - Parallel execution for independent steps
    - Context passing between steps
    - Fail-fast or continue-on-error modes
    """

    def __init__(self, fail_fast: bool = True, verbose: bool = False):
        self.fail_fast = fail_fast
        self.verbose = verbose

    def _resolve_order(self, steps: list[dict]) -> list[list[str]]:
        """Topological sort returning execution layers.

        Each inner list contains steps that can run in parallel.
        Returns layers from dependencies → dependents.
        """
        name_to_step = {s["name"]: s for s in steps}
        deps = {s["name"]: set(s.get("depends_on", [])) for s in steps}

        all_names = set(name_to_step.keys())
        for name, dep_set in deps.items():
            missing = dep_set - all_names
            if missing:
                raise ValueError(f"Step '{name}' depends on unknown steps: {missing}")

        visited: set[str] = set()
        in_stack: set[str] = set()

        def has_cycle(node: str) -> bool:
            if node in in_stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            in_stack.add(node)
            for dep in deps[node]:
                if has_cycle(dep):
                    return True
            in_stack.remove(node)
            return False

        for name in name_to_step:
            if has_cycle(name):
                raise ValueError("Pipeline has circular dependencies")

        layers: list[list[str]] = []
        remaining = dict(deps)
        while remaining:
            ready = sorted(n for n, d in remaining.items() if not d)
            if not ready:
                raise ValueError("Pipeline has unresolvable dependencies (possible cycle)")
            layers.append(ready)
            for n in ready:
                del remaining[n]
            for n in remaining:
                remaining[n] -= set(ready)

        return layers

    async def _run_step(
        self,
        step: dict,
        agent_registry: dict,
        context: dict,
    ) -> StepResult:
        """Execute a single pipeline step."""
        start = time.monotonic()
        agent_name = step["agent"]
        agent = agent_registry.get(agent_name)

        if agent is None:
            return StepResult(
                step_name=step["name"],
                agent_name=agent_name,
                status=StepStatus.FAILED,
                error=f"Agent '{agent_name}' not found in registry",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        prompt_template = step.get("prompt", "")
        try:
            prompt = Template(prompt_template).render(**context)
        except TemplateError as exc:
            return StepResult(
                step_name=step["name"],
                agent_name=agent_name,
                status=StepStatus.FAILED,
                error=f"Prompt template error: {exc}",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        try:
            output = await agent.run(prompt, context)
            duration = (time.monotonic() - start) * 1000

            if isinstance(output, dict) and "error" in output and "response" not in output:
                return StepResult(
                    step_name=step["name"],
                    agent_name=agent_name,
                    status=StepStatus.FAILED,
                    error=output["error"],
                    output=output,
                    duration_ms=duration,
                )

            return StepResult(
                step_name=step["name"],
                agent_name=agent_name,
                status=StepStatus.SUCCESS,
                output=output,
                duration_ms=duration,
            )
        except Exception as exc:  # noqa: BLE001 — last-resort step isolation
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                step_name=step["name"],
                agent_name=agent_name,
                status=StepStatus.FAILED,
                error=str(exc),
                duration_ms=duration,
            )

    async def run(
        self,
        pipeline: dict,
        agent_registry: dict,
        initial_context: dict | None = None,
    ) -> PipelineResult:
        """Execute a full pipeline."""
        pipeline_name = pipeline.get("name", "unnamed")
        steps = pipeline.get("steps", [])
        run_id = uuid.uuid4().hex[:12]

        if not steps:
            return PipelineResult(pipeline_name=pipeline_name, run_id=run_id)

        layers = self._resolve_order(steps)
        start = time.monotonic()
        context: dict[str, Any] = dict(initial_context or {})
        results: list[StepResult] = []
        has_failure = False

        for layer in layers:
            if has_failure and self.fail_fast:
                for name in layer:
                    step = next(s for s in steps if s["name"] == name)
                    results.append(
                        StepResult(
                            step_name=name,
                            agent_name=step["agent"],
                            status=StepStatus.SKIPPED,
                            error="Skipped due to prior failure",
                        )
                    )
                continue

            layer_steps = [next(s for s in steps if s["name"] == name) for name in layer]
            tasks = [self._run_step(s, agent_registry, context) for s in layer_steps]
            layer_results = await asyncio.gather(*tasks)
            results.extend(layer_results)

            for r in layer_results:
                context[r.step_name] = r.output or {}
                if r.status == StepStatus.FAILED:
                    has_failure = True

        duration = (time.monotonic() - start) * 1000
        return PipelineResult(
            pipeline_name=pipeline_name,
            steps=results,
            total_duration_ms=duration,
            success=not has_failure,
            run_id=run_id,
        )

    def print_result(self, result: PipelineResult) -> None:
        """Pretty-print pipeline results using rich."""
        status_emoji = {
            StepStatus.SUCCESS: "[green]✓[/green]",
            StepStatus.FAILED: "[red]✗[/red]",
            StepStatus.SKIPPED: "[yellow]⊘[/yellow]",
            StepStatus.RUNNING: "[blue]⟳[/blue]",
            StepStatus.PENDING: "[dim]·[/dim]",
        }

        title = f"[bold]Pipeline: {result.pipeline_name}[/bold]"
        if result.run_id:
            title += f" [dim]run {result.run_id}[/dim]"
        tree = Tree(title)
        for step in result.steps:
            icon = status_emoji.get(step.status, "?")
            dur = f"({step.duration_ms:.0f}ms)" if step.duration_ms else ""
            label = f"{icon} {step.step_name} [dim]{step.agent_name}[/dim] {dur}"
            branch = tree.add(label)
            if step.error:
                branch.add(f"[red]{step.error}[/red]")
            if self.verbose and step.output:
                branch.add(f"[dim]{str(step.output)[:200]}[/dim]")

        console.print(tree)

        if result.failed_steps:
            console.print(f"\n[red]Failed steps: {len(result.failed_steps)}[/red]")
        else:
            console.print(f"\n[green]All {len(result.steps)} steps succeeded[/green]")
        console.print(f"Total: {result.total_duration_ms:.0f}ms")
