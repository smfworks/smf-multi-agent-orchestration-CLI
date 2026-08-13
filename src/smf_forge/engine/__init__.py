"""Pipeline engine — executes agent DAGs with dependency resolution.

Provides:
  - StepStatus: enum for step lifecycle states
  - StepResult: dataclass for a single step's output
  - PipelineResult: aggregated output from a full pipeline run
  - PipelineEngine: executes a pipeline DAG respecting step dependencies
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rich.console import Console
from rich.tree import Tree

logger = logging.getLogger(__name__)

console = Console()


class StepStatus(str, Enum):
    """Lifecycle state of a pipeline step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Output from a single pipeline step.

    Attributes:
        step_name: Name of the step.
        agent_name: Name of the agent that executed the step.
        status: Final :class:`StepStatus`.
        output: Agent output (typically a dict).
        error: Error message if the step failed.
        duration_ms: Wall-clock execution time in milliseconds.
        metadata: Additional metadata.
    """

    step_name: str
    agent_name: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Aggregated output from a full pipeline run.

    Attributes:
        pipeline_name: Name of the pipeline.
        steps: List of :class:`StepResult` for each step.
        total_duration_ms: Total wall-clock execution time in milliseconds.
        success: ``True`` if all steps succeeded.
    """

    pipeline_name: str
    steps: list[StepResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    success: bool = True

    @property
    def failed_steps(self) -> list[StepResult]:
        """List of steps that failed."""
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def succeeded_steps(self) -> list[StepResult]:
        """List of steps that succeeded."""
        return [s for s in self.steps if s.status == StepStatus.SUCCESS]

    @property
    def skipped_steps(self) -> list[StepResult]:
        """List of steps that were skipped."""
        return [s for s in self.steps if s.status == StepStatus.SKIPPED]


class PipelineEngine:
    """Executes a pipeline DAG respecting step dependencies.

    Supports:
      - Sequential execution (default)
      - Parallel execution for independent steps in the same layer
      - Context passing between steps (output of step N feeds step N+1)
      - Fail-fast or continue-on-error modes
    """

    def __init__(self, fail_fast: bool = True, verbose: bool = False) -> None:
        self.fail_fast = fail_fast
        self.verbose = verbose

    # ------------------------------------------------------------------ #
    # Dependency resolution
    # ------------------------------------------------------------------ #

    def _resolve_order(self, steps: list[dict[str, Any]]) -> list[list[str]]:
        """Topological sort returning execution layers.

        Each inner list contains step names that can run in parallel.
        Returns layers from dependencies → dependents.

        Args:
            steps: List of step config dicts (each must have ``name`` and ``agent``).

        Returns:
            List of layers (each layer is a list of step names).

        Raises:
            ValueError: If a step references an unknown dependency or a cycle is detected.
        """
        name_to_step = {s["name"]: s for s in steps}
        deps: dict[str, set[str]] = {
            s["name"]: set(s.get("depends_on", [])) for s in steps
        }

        # Validate: all referenced deps must exist
        all_names = set(name_to_step.keys())
        for name, dep_set in deps.items():
            missing = dep_set - all_names
            if missing:
                raise ValueError(f"Step '{name}' depends on unknown steps: {missing}")

        # Detect cycles via DFS
        visited: set[str] = set()
        in_stack: set[str] = set()

        def _has_cycle(node: str) -> bool:
            if node in in_stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            in_stack.add(node)
            for dep in deps[node]:
                if _has_cycle(dep):
                    return True
            in_stack.discard(node)
            return False

        for name in name_to_step:
            if _has_cycle(name):
                raise ValueError("Pipeline has circular dependencies")

        # Kahn's algorithm — produce layers
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

    # ------------------------------------------------------------------ #
    # Step execution
    # ------------------------------------------------------------------ #

    async def _run_step(
        self,
        step: dict[str, Any],
        agent_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> StepResult:
        """Execute a single pipeline step.

        Args:
            step: Step config dict.
            agent_registry: Map of agent name → agent instance.
            context: Current pipeline context.

        Returns:
            :class:`StepResult` with the outcome.
        """
        start = time.monotonic()
        step_name = step["name"]
        agent_name = step["agent"]
        agent = agent_registry.get(agent_name)

        if agent is None:
            return StepResult(
                step_name=step_name,
                agent_name=agent_name,
                status=StepStatus.FAILED,
                error=f"Agent '{agent_name}' not found in registry",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        # Render prompt template with context
        prompt_template = step.get("prompt", "")
        try:
            from jinja2 import Template

            prompt = Template(prompt_template).render(**context)
        except Exception as exc:
            logger.warning("Template render failed for step '%s': %s", step_name, exc)
            prompt = prompt_template

        try:
            output = await agent.run(prompt, context)
            duration = (time.monotonic() - start) * 1000

            # Check if agent returned an error dict — treat as failure
            if isinstance(output, dict) and "error" in output and "response" not in output:
                return StepResult(
                    step_name=step_name,
                    agent_name=agent_name,
                    status=StepStatus.FAILED,
                    error=str(output["error"]),
                    output=output,
                    duration_ms=duration,
                )

            return StepResult(
                step_name=step_name,
                agent_name=agent_name,
                status=StepStatus.SUCCESS,
                output=output,
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.error("Step '%s' raised exception: %s", step_name, exc)
            return StepResult(
                step_name=step_name,
                agent_name=agent_name,
                status=StepStatus.FAILED,
                error=str(exc),
                duration_ms=duration,
            )

    # ------------------------------------------------------------------ #
    # Pipeline execution
    # ------------------------------------------------------------------ #

    async def run(
        self,
        pipeline: dict[str, Any],
        agent_registry: dict[str, Any],
        initial_context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Execute a full pipeline.

        Args:
            pipeline: Pipeline config dict with ``name`` and ``steps``.
            agent_registry: Map of agent name → agent instance.
            initial_context: Optional initial context (e.g. ``{"prompt": "..."}``)
                available to all steps via Jinja2 templating.

        Returns:
            :class:`PipelineResult` with per-step outcomes.
        """
        pipeline_name = pipeline.get("name", "unnamed")
        steps = pipeline.get("steps", [])

        if not steps:
            return PipelineResult(pipeline_name=pipeline_name)

        layers = self._resolve_order(steps)
        start = time.monotonic()
        context: dict[str, Any] = dict(initial_context or {})
        results: list[StepResult] = []
        has_failure = False

        for layer in layers:
            if has_failure and self.fail_fast:
                # Mark remaining steps as skipped
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

            # Run all steps in this layer concurrently
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
        )

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #

    def print_result(self, result: PipelineResult) -> None:
        """Pretty-print pipeline results using rich.

        Args:
            result: The :class:`PipelineResult` to display.
        """
        status_emoji = {
            StepStatus.SUCCESS: "[green]✓[/green]",
            StepStatus.FAILED: "[red]✗[/red]",
            StepStatus.SKIPPED: "[yellow]⊘[/yellow]",
            StepStatus.RUNNING: "[blue]⟳[/blue]",
            StepStatus.PENDING: "[dim]·[/dim]",
        }

        tree = Tree(f"[bold]Pipeline: {result.pipeline_name}[/bold]")
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
