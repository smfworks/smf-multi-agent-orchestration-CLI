"""Tests for built-in agent types — echo, shell, transform, http, hermes.

Network-dependent agents (http, hermes) are tested for error paths only,
not actual API calls.
"""

from __future__ import annotations

import asyncio

from smf_forge.agents import (
    AGENT_TYPES,
    AgentConfig,
    BaseAgent,
    EchoAgent,
    HermesAgent,
    HttpAgent,
    ShellAgent,
    TransformAgent,
    build_agent,
    build_registry,
)

# --------------------------------------------------------------------------- #
# EchoAgent
# --------------------------------------------------------------------------- #

class TestEchoAgent:
    def test_returns_prompt(self) -> None:
        config = AgentConfig(name="echo1", type="echo")
        agent = EchoAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert result["echo"] == "hello"
        assert result["agent"] == "echo1"

    def test_returns_context_keys(self) -> None:
        config = AgentConfig(name="echo1", type="echo")
        agent = EchoAgent(config)
        result = asyncio.run(agent.run("test", {"a": 1, "b": 2}))
        assert set(result["context_keys"]) == {"a", "b"}

    def test_none_context(self) -> None:
        config = AgentConfig(name="echo1", type="echo")
        agent = EchoAgent(config)
        result = asyncio.run(agent.run("test", None))
        assert result["context_keys"] == []


# --------------------------------------------------------------------------- #
# ShellAgent
# --------------------------------------------------------------------------- #

class TestShellAgent:
    def test_runs_command_from_options(self) -> None:
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "echo hello123"}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("ignored"))
        assert result["exit_code"] == 0
        assert "hello123" in result["stdout"]

    def test_uses_prompt_as_command(self) -> None:
        config = AgentConfig(name="sh1", type="shell")
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("echo from-prompt"))
        assert result["exit_code"] == 0
        assert "from-prompt" in result["stdout"]

    def test_command_failure(self) -> None:
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "false"}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("x"))
        assert result["exit_code"] != 0

    def test_command_timeout(self) -> None:
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "sleep 10", "timeout": 1}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("x"))
        assert "error" in result
        assert "timed out" in result["error"]


# --------------------------------------------------------------------------- #
# TransformAgent
# --------------------------------------------------------------------------- #

class TestTransformAgent:
    def test_default_template(self) -> None:
        config = AgentConfig(name="t1", type="transform")
        agent = TransformAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert result["result"] == "hello"

    def test_custom_template(self) -> None:
        config = AgentConfig(
            name="t1", type="transform",
            options={"template": "Output: {{ prompt | upper }}"},
        )
        agent = TransformAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert result["result"] == "Output: HELLO"

    def test_template_with_context(self) -> None:
        config = AgentConfig(
            name="t1", type="transform",
            options={"template": "{{ first.echo }} + {{ prompt }}"},
        )
        agent = TransformAgent(config)
        result = asyncio.run(agent.run("second", {"first": {"echo": "first-val"}}))
        assert result["result"] == "first-val + second"

    def test_template_error(self) -> None:
        config = AgentConfig(
            name="t1", type="transform",
            options={"template": "{{ undefined.attr }}"},
        )
        agent = TransformAgent(config)
        result = asyncio.run(agent.run("x"))
        assert "error" in result


# --------------------------------------------------------------------------- #
# HttpAgent (error paths only — no real API calls)
# --------------------------------------------------------------------------- #

class TestHttpAgent:
    def test_no_api_key_returns_error(self) -> None:
        config = AgentConfig(name="h1", type="http", model="gpt-4")
        agent = HttpAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "No API key" in result["error"]

    def test_connection_error(self) -> None:
        config = AgentConfig(
            name="h1", type="http",
            base_url="http://localhost:1",  # unreachable port
            api_key="fake-key",
            model="gpt-4",
        )
        agent = HttpAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        # Should be a connection error, not an unhandled exception
        assert "Connection error" in result["error"] or "error" in result["error"]


# --------------------------------------------------------------------------- #
# HermesAgent (error paths only)
# --------------------------------------------------------------------------- #

class TestHermesAgent:
    def test_connection_error(self) -> None:
        config = AgentConfig(
            name="h1", type="hermes",
            options={"endpoint": "http://localhost:1", "timeout": 5},
        )
        agent = HermesAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "Cannot connect" in result["error"]

    def test_default_endpoint(self) -> None:
        config = AgentConfig(name="h1", type="hermes")
        agent = HermesAgent(config)
        # Should use default endpoint
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "localhost:8642" in result["error"]


# --------------------------------------------------------------------------- #
# Agent registry
# --------------------------------------------------------------------------- #

class TestAgentRegistry:
    def test_all_types_registered(self) -> None:
        assert set(AGENT_TYPES.keys()) == {"echo", "http", "shell", "transform", "hermes"}

    def test_build_agent_each_type(self) -> None:
        for agent_type in AGENT_TYPES:
            config = AgentConfig(name=f"test-{agent_type}", type=agent_type)
            agent = build_agent(config)
            assert isinstance(agent, BaseAgent)

    def test_build_registry_multiple(self) -> None:
        cfg = {
            "echo1": {"type": "echo"},
            "echo2": {"type": "echo"},
            "transform1": {"type": "transform", "options": {"template": "{{ prompt }}"}},
        }
        registry = build_registry(cfg)
        assert len(registry) == 3
        assert isinstance(registry["echo1"], EchoAgent)
        assert isinstance(registry["transform1"], TransformAgent)

    def test_agent_config_from_dict(self) -> None:
        config = AgentConfig.from_dict("test", {
            "type": "http",
            "model": "gpt-4",
            "api_key": "secret",
            "temperature": 0.5,
            "max_tokens": 2048,
            "unknown_field": "ignored",
        })
        assert config.name == "test"
        assert config.type == "http"
        assert config.model == "gpt-4"
        assert config.api_key == "secret"
        assert config.temperature == 0.5
        assert config.max_tokens == 2048
