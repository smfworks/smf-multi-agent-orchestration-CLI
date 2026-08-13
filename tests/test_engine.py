"""Tests for the pipeline engine."""

import asyncio

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


class FailingAgent(BaseAgent):
    """Agent that returns an error dict (like HttpAgent with no API key)."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        return {"error": "No API key configured", "agent": self.config.name}


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
        assert result.run_id
        assert len(result.steps) == 1
        assert result.steps[0].status == StepStatus.SUCCESS
        assert result.steps[0].output["echo"] == "Hello"

    def test_missing_agent_fails(self):
        registry = {}
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

    def test_fail_fast_skips_remaining(self):
        registry = {}
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
        assert all(s.status == StepStatus.FAILED for s in result.steps)

    def test_initial_context(self):
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "ctx-test",
            "steps": [{"name": "greet", "agent": "echo1", "prompt": "{{ prompt }}"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry, initial_context={"prompt": "from CLI"}))
        assert result.success
        assert result.steps[0].output["echo"] == "from CLI"

    def test_error_dict_treated_as_failure(self):
        config = AgentConfig(name="failing", type="echo")
        registry = {"failing": FailingAgent(config)}
        pipeline = {
            "name": "error-dict-test",
            "steps": [{"name": "step1", "agent": "failing", "prompt": "try me"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[0].status == StepStatus.FAILED
        assert "No API key" in result.steps[0].error

    def test_bad_template_fails_step(self):
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {
            "name": "tmpl",
            "steps": [{"name": "greet", "agent": "echo1", "prompt": "{{ nope.missing }}"}],
        }
        engine = PipelineEngine()
        result = asyncio.run(engine.run(pipeline, registry))
        assert not result.success
        assert result.steps[0].status == StepStatus.FAILED
        assert result.steps[0].error is not None
        assert "template" in result.steps[0].error.lower()

    def test_empty_pipeline(self):
        engine = PipelineEngine()
        pipeline = {"name": "empty", "steps": []}
        result = asyncio.run(engine.run(pipeline, {}))
        assert result.success
        assert len(result.steps) == 0
        assert result.run_id

    def test_to_dict_json_shape(self):
        registry = build_registry({"echo1": {"type": "echo"}})
        pipeline = {"name": "j", "steps": [{"name": "g", "agent": "echo1", "prompt": "x"}]}
        result = asyncio.run(PipelineEngine().run(pipeline, registry))
        payload = result.to_dict()
        assert payload["success"] is True
        assert payload["steps"][0]["status"] == "success"


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

    def test_hermes_agent(self):
        config = AgentConfig(name="hermes-test", type="hermes")
        agent = build_agent(config)
        assert isinstance(agent, HermesAgent)

    def test_hermes_agent_config(self):
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
