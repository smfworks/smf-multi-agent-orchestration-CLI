"""Tests for the pipeline engine."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from smf_forge.agents import (
    AgentConfig,
    BaseAgent,
    EchoAgent,
    HermesAgent,
    build_agent,
    build_registry,
)
from smf_forge.engine import PipelineEngine, StepStatus

# --------------------------------------------------------------------------- #
# Test helpers
# --------------------------------------------------------------------------- #

class FailingAgent(BaseAgent):
    """Agent that returns an error dict (like HttpAgent with no API key)."""

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"error": "No API key configured", "agent": self.config.name}


class ExceptionAgent(BaseAgent):
    """Agent that raises an exception."""

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> Any:
        raise RuntimeError("Agent exploded")


class DelayedEchoAgent(BaseAgent):
    """Echo agent with a small delay to test concurrency."""

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"echo": prompt, "agent": self.config.name}


# --------------------------------------------------------------------------- #
# Pipeline ordering / topological sort
# --------------------------------------------------------------------------- #

class TestPipelineOrdering:
    def test_simple_sequential(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo"},
            {"name": "b", "agent": "echo", "depends_on": ["a"]},
        ]
        layers = engine._resolve_order(steps)
        assert layers == [["a"], ["b"]]

    def test_parallel_independent(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo"},
            {"name": "b", "agent": "echo"},
            {"name": "c", "agent": "echo", "depends_on": ["a", "b"]},
        ]
        layers = engine._resolve_order(steps)
        assert layers[0] == ["a", "b"]
        assert layers[1] == ["c"]

    def test_diamond_dependency(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo"},
            {"name": "b", "agent": "echo", "depends_on": ["a"]},
            {"name": "c", "agent": "echo", "depends_on": ["a"]},
            {"name": "d", "agent": "echo", "depends_on": ["b", "c"]},
        ]
        layers = engine._resolve_order(steps)
        assert layers[0] == ["a"]
        assert layers[1] == ["b", "c"]
        assert layers[2] == ["d"]

    def test_unknown_dependency(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo", "depends_on": ["ghost"]},
        ]
        with pytest.raises(ValueError, match="unknown steps"):
            engine._resolve_order(steps)

    def test_circular_dependency(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo", "depends_on": ["b"]},
            {"name": "b", "agent": "echo", "depends_on": ["a"]},
        ]
        with pytest.raises(ValueError, match="circular"):
            engine._resolve_order(steps)

    def test_self_dependency(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo", "depends_on": ["a"]},
        ]
        with pytest.raises(ValueError, match="circular"):
            engine._resolve_order(steps)

    def test_no_dependencies_all_parallel(self) -> None:
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo"},
            {"name": "b", "agent": "echo"},
            {"name": "c", "agent": "echo"},
        ]
        layers = engine._resolve_order(steps)
        assert layers == [["a", "b", "c"]]


# --------------------------------------------------------------------------- #
# Pipeline execution
# --------------------------------------------------------------------------- #

class TestPipelineExecution:
    def test_echo_pipeline(self) -> None:
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "test",
            "steps": [{"name": "greet", "agent": "echo1", "prompt": "Hello"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert result.success
        assert len(result.steps) == 1
        assert result.steps[0].status == StepStatus.SUCCESS
        assert result.steps[0].output["echo"] == "Hello"

    def test_missing_agent_fails(self) -> None:
        registry: dict[str, BaseAgent] = {}
        pipeline = {
            "name": "fail",
            "steps": [{"name": "step1", "agent": "nonexistent", "prompt": "x"}],
        }
        engine = PipelineEngine(fail_fast=True)
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[0].status == StepStatus.FAILED
        assert "not found" in (result.steps[0].error or "")

    def test_context_passing(self) -> None:
        registry = build_registry({
            "echo1": {"type": "echo"},
            "echo2": {"type": "echo"},
        })
        pipeline = {
            "name": "chain",
            "steps": [
                {"name": "first", "agent": "echo1", "prompt": "start"},
                {
                    "name": "second",
                    "agent": "echo2",
                    "prompt": "{{ first.echo }}",
                    "depends_on": ["first"],
                },
            ],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert result.success
        assert result.steps[1].output["echo"] == "start"

    def test_fail_fast_skips_remaining(self) -> None:
        registry: dict[str, BaseAgent] = {}
        pipeline = {
            "name": "skip-test",
            "steps": [
                {"name": "s1", "agent": "missing", "prompt": "x"},
                {"name": "s2", "agent": "missing", "prompt": "y", "depends_on": ["s1"]},
            ],
        }
        engine = PipelineEngine(fail_fast=True)
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[1].status == StepStatus.SKIPPED

    def test_continue_on_error(self) -> None:
        registry: dict[str, BaseAgent] = {}
        pipeline = {
            "name": "continue",
            "steps": [
                {"name": "s1", "agent": "missing", "prompt": "x"},
                {"name": "s2", "agent": "missing", "prompt": "y"},
            ],
        }
        engine = PipelineEngine(fail_fast=False)
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert all(s.status == StepStatus.FAILED for s in result.steps)

    def test_initial_context(self) -> None:
        """initial_context should be available to step templates."""
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "ctx-test",
            "steps": [{"name": "greet", "agent": "echo1", "prompt": "{{ prompt }}"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, initial_context={"prompt": "from CLI"}))
        assert result.success
        assert result.steps[0].output["echo"] == "from CLI"

    def test_error_dict_treated_as_failure(self) -> None:
        """Agents returning {error: ...} should be FAILED, not SUCCESS."""
        config = AgentConfig(name="failing", type="echo")
        registry: dict[str, BaseAgent] = {"failing": FailingAgent(config)}
        pipeline = {
            "name": "error-dict-test",
            "steps": [{"name": "step1", "agent": "failing", "prompt": "try me"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[0].status == StepStatus.FAILED
        assert "No API key" in (result.steps[0].error or "")

    def test_exception_treated_as_failure(self) -> None:
        """Agents that raise exceptions should be FAILED."""
        config = AgentConfig(name="exploder", type="echo")
        registry: dict[str, BaseAgent] = {"exploder": ExceptionAgent(config)}
        pipeline = {
            "name": "exception-test",
            "steps": [{"name": "step1", "agent": "exploder", "prompt": "go"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[0].status == StepStatus.FAILED
        assert "exploded" in (result.steps[0].error or "")

    def test_empty_pipeline(self) -> None:
        engine = PipelineEngine()
        pipeline = {"name": "empty", "steps": []}
        result = asyncio.run(engine.run(pipeline, {}))
        assert result.success
        assert len(result.steps) == 0

    def test_pipeline_result_properties(self) -> None:
        """PipelineResult.failed_steps / succeeded_steps / skipped_steps."""
        registry: dict[str, BaseAgent] = {}
        pipeline = {
            "name": "mixed",
            "steps": [
                {"name": "s1", "agent": "missing", "prompt": "x"},
                {"name": "s2", "agent": "missing", "prompt": "y", "depends_on": ["s1"]},
            ],
        }
        engine = PipelineEngine(fail_fast=True)
        result = asyncio.run(engine.run(pipeline, registry))
        assert len(result.failed_steps) == 1
        assert len(result.skipped_steps) == 1
        assert len(result.succeeded_steps) == 0

    def test_parallel_execution_concurrent(self) -> None:
        """Independent steps should run concurrently."""
        config = AgentConfig(name="delayed", type="echo")
        registry: dict[str, BaseAgent] = {
            "d1": DelayedEchoAgent(config),
            "d2": DelayedEchoAgent(AgentConfig(name="d2", type="echo")),
        }
        pipeline = {
            "name": "parallel",
            "steps": [
                {"name": "a", "agent": "d1", "prompt": "hello"},
                {"name": "b", "agent": "d2", "prompt": "world"},
            ],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert result.success
        # If truly concurrent, total time should be ~10ms, not ~20ms
        assert result.total_duration_ms < 20

    def test_duration_is_positive(self) -> None:
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "timing",
            "steps": [{"name": "s1", "agent": "echo1", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert result.total_duration_ms > 0
        assert result.steps[0].duration_ms > 0

    def test_template_render_fallback(self) -> None:
        """If Jinja2 template fails, the raw prompt should be used."""
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "bad-template",
            "steps": [{"name": "s1", "agent": "echo1", "prompt": "{{ undefined_var }}"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        # Jinja2 renders undefined variables as empty string, not error
        assert result.success
        # The echo should contain whatever the template rendered to
        assert "echo" in result.steps[0].output

    def test_unnamed_pipeline(self) -> None:
        """Pipeline without a 'name' key should default to 'unnamed'."""
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "steps": [{"name": "s1", "agent": "echo1", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert result.pipeline_name == "unnamed"
        assert result.success


# --------------------------------------------------------------------------- #
# Pipeline timeout and cancellation
# --------------------------------------------------------------------------- #

class TestPipelineTimeout:
    def test_pipeline_timeout_short(self) -> None:
        """Pipeline with a very short timeout should mark steps as TIMEOUT."""
        config = AgentConfig(name="slow", type="echo")
        registry: dict[str, BaseAgent] = {"slow": DelayedEchoAgent(config)}
        pipeline = {
            "name": "timeout-test",
            "steps": [{"name": "s1", "agent": "slow", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, timeout=0.001))
        # With 1ms timeout, the 10ms delayed agent should time out
        assert not result.success

    def test_pipeline_timeout_none(self) -> None:
        """Pipeline with no timeout should run normally."""
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "no-timeout",
            "steps": [{"name": "s1", "agent": "echo1", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, timeout=None))
        assert result.success

    def test_pipeline_timeout_sufficient(self) -> None:
        """Pipeline with a sufficient timeout should complete normally."""
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "enough-timeout",
            "steps": [{"name": "s1", "agent": "echo1", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, timeout=30))
        assert result.success

    def test_pipeline_timeout_cancels_hung_agent(self) -> None:
        """Pipeline timeout should cancel a hung agent."""
        class HungAgent(BaseAgent):
            async def run(self, prompt: str, context: dict[str, Any] | None = None) -> Any:
                await asyncio.sleep(100)  # will be cancelled

        config = AgentConfig(name="hung", type="echo")
        registry: dict[str, BaseAgent] = {"hung": HungAgent(config)}
        pipeline = {
            "name": "hung-test",
            "steps": [{"name": "s1", "agent": "hung", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, timeout=0.1))
        assert not result.success

    def test_timeout_status_in_results(self) -> None:
        """When pipeline times out, steps should have TIMEOUT status."""
        class HungAgent(BaseAgent):
            async def run(self, prompt: str, context: dict[str, Any] | None = None) -> Any:
                await asyncio.sleep(100)

        config = AgentConfig(name="hung", type="echo")
        registry: dict[str, BaseAgent] = {"hung": HungAgent(config)}
        pipeline = {
            "name": "timeout-status",
            "steps": [{"name": "s1", "agent": "hung", "prompt": "x"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, timeout=0.05))
        assert any(s.status == StepStatus.TIMEOUT for s in result.steps)


class TestPipelineCancellation:
    def test_cancelled_step_does_not_hang(self) -> None:
        """A cancelled step should not cause the pipeline to hang."""
        class SlowAgent(BaseAgent):
            async def run(self, prompt: str, context: dict[str, Any] | None = None) -> Any:
                try:
                    await asyncio.sleep(0.5)
                    return {"echo": prompt}
                except asyncio.CancelledError:
                    raise

        config = AgentConfig(name="slow", type="echo")
        registry: dict[str, BaseAgent] = {"slow": SlowAgent(config)}
        pipeline = {
            "name": "cancel-test",
            "steps": [
                {"name": "s1", "agent": "slow", "prompt": "x"},
                {"name": "s2", "agent": "slow", "prompt": "y", "depends_on": ["s1"]},
            ],
        }
        engine = PipelineEngine()
        # Use a short timeout to trigger cancellation
        result = asyncio.run(engine.run(pipeline, registry, timeout=0.1))
        assert not result.success


# --------------------------------------------------------------------------- #
# Agent builder
# --------------------------------------------------------------------------- #

class TestAgentBuilder:
    def test_echo_agent(self) -> None:
        config = AgentConfig(name="test", type="echo")
        agent = build_agent(config)
        assert isinstance(agent, EchoAgent)

    def test_unknown_type_raises(self) -> None:
        config = AgentConfig(name="bad", type="nonexistent")
        with pytest.raises(ValueError, match="Unknown agent type"):
            build_agent(config)

    def test_build_registry(self) -> None:
        cfg = {"echo1": {"type": "echo"}, "echo2": {"type": "echo"}}
        registry = build_registry(cfg)
        assert len(registry) == 2
        assert "echo1" in registry
        assert "echo2" in registry

    def test_hermes_agent(self) -> None:
        config = AgentConfig(name="hermes-test", type="hermes")
        agent = build_agent(config)
        assert isinstance(agent, HermesAgent)

    def test_hermes_agent_config(self) -> None:
        config = AgentConfig(
            name="hermes-test",
            type="hermes",
            base_url="http://localhost:9999",
            options={"agent_name": "liam", "timeout": 60},
        )
        agent = build_agent(config)
        assert isinstance(agent, HermesAgent)
        assert agent.config.options["agent_name"] == "liam"
        assert agent.config.options["timeout"] == 60

    def test_agent_config_from_dict_filters_unknown_keys(self) -> None:
        """AgentConfig.from_dict should ignore unknown keys."""
        config = AgentConfig.from_dict("test", {
            "type": "echo",
            "unknown_key": "should be ignored",
        })
        assert config.type == "echo"
        assert config.name == "test"

    def test_agent_config_defaults(self) -> None:
        config = AgentConfig(name="test")
        assert config.type == "echo"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.options == {}

    def test_build_registry_empty(self) -> None:
        registry = build_registry({})
        assert registry == {}


# --------------------------------------------------------------------------- #
# EchoAgent behavior
# --------------------------------------------------------------------------- #

class TestEchoAgent:
    def test_echo_returns_prompt(self) -> None:
        config = AgentConfig(name="echo1", type="echo")
        agent = EchoAgent(config)
        result = asyncio.run(agent.run("hello world"))
        assert result["echo"] == "hello world"
        assert result["agent"] == "echo1"

    def test_echo_returns_context_keys(self) -> None:
        config = AgentConfig(name="echo1", type="echo")
        agent = EchoAgent(config)
        result = asyncio.run(agent.run("test", {"key1": "val1", "key2": "val2"}))
        assert "key1" in result["context_keys"]
        assert "key2" in result["context_keys"]

    def test_echo_with_none_context(self) -> None:
        config = AgentConfig(name="echo1", type="echo")
        agent = EchoAgent(config)
        result = asyncio.run(agent.run("test", None))
        assert result["context_keys"] == []
