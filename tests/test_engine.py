"""Tests for the pipeline engine."""

import asyncio
import pytest

from smf_forge.agents import AgentConfig, EchoAgent, BaseAgent, build_agent, build_registry
from smf_forge.engine import PipelineEngine, PipelineResult, StepStatus


class TestPipelineOrdering:
    def test_simple_sequential(self):
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo"},
            {"name": "b", "agent": "echo", "depends_on": ["a"]},
        ]
        layers = engine._resolve_order(steps)
        assert layers == [["a"], ["b"]]

    def test_parallel_independent(self):
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo"},
            {"name": "b", "agent": "echo"},
            {"name": "c", "agent": "echo", "depends_on": ["a", "b"]},
        ]
        layers = engine._resolve_order(steps)
        assert layers[0] == ["a", "b"]
        assert layers[1] == ["c"]

    def test_unknown_dependency(self):
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo", "depends_on": ["ghost"]},
        ]
        with pytest.raises(ValueError, match="unknown steps"):
            engine._resolve_order(steps)

    def test_circular_dependency(self):
        engine = PipelineEngine()
        steps = [
            {"name": "a", "agent": "echo", "depends_on": ["b"]},
            {"name": "b", "agent": "echo", "depends_on": ["a"]},
        ]
        with pytest.raises(ValueError, match="circular"):
            engine._resolve_order(steps)


class TestPipelineExecution:
    def test_echo_pipeline(self):
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

    def test_missing_agent_fails(self):
        registry = {}  # empty — no agents
        pipeline = {
            "name": "fail",
            "steps": [{"name": "step1", "agent": "nonexistent", "prompt": "x"}],
        }
        engine = PipelineEngine(fail_fast=True)
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[0].status == StepStatus.FAILED
        assert "not found" in result.steps[0].error

    def test_context_passing(self):
        registry = build_registry({
            "echo1": {"type": "echo"},
            "echo2": {"type": "echo"},
        })
        pipeline = {
            "name": "chain",
            "steps": [
                {"name": "first", "agent": "echo1", "prompt": "start"},
                {"name": "second", "agent": "echo2", "prompt": "{{ first.echo }}", "depends_on": ["first"]},
            ],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert result.success
        assert result.steps[1].output["echo"] == "start"

    def test_fail_fast_skips_remaining(self):
        registry = {}  # no agents — all steps fail
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

    def test_continue_on_error(self):
        registry = {}
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
        # Both should attempt to run (not skipped)
        assert all(s.status == StepStatus.FAILED for s in result.steps)


class TestAgentBuilder:
    def test_echo_agent(self):
        config = AgentConfig(name="test", type="echo")
        agent = build_agent(config)
        assert isinstance(agent, EchoAgent)

    def test_unknown_type_raises(self):
        config = AgentConfig(name="bad", type="nonexistent")
        with pytest.raises(ValueError, match="Unknown agent type"):
            build_agent(config)

    def test_build_registry(self):
        cfg = {"echo1": {"type": "echo"}, "echo2": {"type": "echo"}}
        registry = build_registry(cfg)
        assert len(registry) == 2
        assert "echo1" in registry
        assert "echo2" in registry