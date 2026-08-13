"""Tests for built-in agent types — echo, shell, transform, http, hermes.

Network-dependent agents (http, hermes) are tested for error paths only,
not actual API calls.
"""

from __future__ import annotations

import asyncio

import pytest

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
    validate_url,
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

    def test_uses_prompt_as_command_disabled(self) -> None:
        """ShellAgent must NOT use the prompt as a command (security)."""
        config = AgentConfig(name="sh1", type="shell")
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("echo from-prompt"))
        assert "error" in result
        assert "requires 'command'" in result["error"]

    def test_command_failure(self) -> None:
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "false"}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("x"))
        assert result["exit_code"] != 0

    def test_invalid_timeout(self) -> None:
        """ShellAgent with invalid timeout should return error."""
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "echo hi", "timeout": "abc"}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("x"))
        assert "error" in result
        assert "positive integer" in result["error"]

    def test_negative_timeout(self) -> None:
        """ShellAgent with negative timeout should return error."""
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "echo hi", "timeout": -5}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("x"))
        assert "error" in result
        assert "Invalid timeout" in result["error"]

    def test_timeout_too_large(self) -> None:
        """ShellAgent with timeout > 600 should return error."""
        config = AgentConfig(
            name="sh1", type="shell", options={"command": "echo hi", "timeout": 601}
        )
        agent = ShellAgent(config)
        result = asyncio.run(agent.run("x"))
        assert "error" in result
        assert "Invalid timeout" in result["error"]

    def test_command_timeout(self) -> None:
        """ShellAgent should timeout and kill the subprocess."""
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
        # localhost is blocked by SSRF guard, so we get a validation error
        assert "Invalid base_url" in result["error"] or "Connection error" in result["error"]

    def test_ssrf_blocked_localhost(self) -> None:
        """HttpAgent must reject localhost URLs (SSRF protection)."""
        config = AgentConfig(
            name="h1", type="http",
            base_url="http://127.0.0.1:8080",
            api_key="fake-key",
            model="gpt-4",
        )
        agent = HttpAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "private/internal" in result["error"]

    def test_ssrf_blocked_metadata_endpoint(self) -> None:
        """HttpAgent must reject 169.254.169.254 (cloud metadata)."""
        config = AgentConfig(
            name="h1", type="http",
            base_url="http://169.254.169.254",
            api_key="fake-key",
            model="gpt-4",
        )
        agent = HttpAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "private/internal" in result["error"]

    def test_ssrf_blocked_invalid_scheme(self) -> None:
        """HttpAgent must reject non-http(s) schemes."""
        config = AgentConfig(
            name="h1", type="http",
            base_url="file:///etc/passwd",
            api_key="fake-key",
            model="gpt-4",
        )
        agent = HttpAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "scheme" in result["error"].lower()

    def test_api_key_not_in_error(self) -> None:
        """API key must not appear in error messages."""
        secret = "sk-test-secret-key-12345"
        config = AgentConfig(
            name="h1", type="http",
            base_url="https://8.8.8.8/v1",
            api_key=secret,
            model="gpt-4",
        )
        agent = HttpAgent(config)
        result = asyncio.run(agent.run("hello"))
        # This will fail (no real API), but the key must not be in the error
        if "error" in result:
            assert secret not in result["error"]


# --------------------------------------------------------------------------- #
# URL validation (SSRF prevention)
# --------------------------------------------------------------------------- #

class TestValidateUrl:
    def test_valid_https_url(self) -> None:
        # Use a literal external IP to avoid DNS dependency in tests
        assert validate_url("https://8.8.8.8/v1") == "https://8.8.8.8/v1"

    def test_valid_http_url(self) -> None:
        assert validate_url("http://8.8.8.8") == "http://8.8.8.8"

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_url("file:///etc/passwd")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_url("ftp://evil.com")

    def test_rejects_no_scheme(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_url("not-a-url")

    def test_rejects_localhost(self) -> None:
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://127.0.0.1:8080")

    def test_rejects_10_private(self) -> None:
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://10.0.0.1")

    def test_rejects_192_168_private(self) -> None:
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://192.168.1.1")

    def test_rejects_172_16_private(self) -> None:
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://172.16.0.1")

    def test_rejects_metadata_endpoint(self) -> None:
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://169.254.169.254")

    def test_rejects_no_hostname(self) -> None:
        with pytest.raises(ValueError, match="hostname"):
            validate_url("https:///path")

    def test_allows_localhost_when_permitted(self) -> None:
        assert validate_url("http://localhost:8642", allow_localhost=True) == "http://localhost:8642"

    def test_allows_127_when_permitted(self) -> None:
        assert validate_url("http://127.0.0.1:8080", allow_localhost=True) == "http://127.0.0.1:8080"

    def test_rejects_unresolvable_hostname(self) -> None:
        """Unresolvable hostnames should be rejected."""
        with pytest.raises(ValueError, match="Cannot resolve"):
            validate_url("http://this-host-definitely-does-not-exist-12345.invalid")

    def test_rejects_0_0_0_0(self) -> None:
        """0.0.0.0 should be blocked."""
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://0.0.0.0")

    def test_rejects_cgnat(self) -> None:
        """100.64.0.0/10 (CGNAT) should be blocked."""
        with pytest.raises(ValueError, match="private/internal"):
            validate_url("http://100.64.0.1")

    def test_hermes_ssrf_blocked_external_private(self) -> None:
        """HermesAgent should still block external private IPs (not localhost)."""
        config = AgentConfig(
            name="h1", type="hermes",
            options={"endpoint": "http://10.0.0.1", "timeout": 5},
        )
        agent = HermesAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "private/internal" in result["error"] or "Invalid endpoint" in result["error"]

    def test_hermes_invalid_timeout(self) -> None:
        """HermesAgent with invalid timeout should return error."""
        config = AgentConfig(
            name="h1", type="hermes",
            options={"endpoint": "http://localhost:8642", "timeout": "abc"},
        )
        agent = HermesAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "positive integer" in result["error"]

    def test_hermes_negative_timeout(self) -> None:
        """HermesAgent with negative timeout should return error."""
        config = AgentConfig(
            name="h1", type="hermes",
            options={"endpoint": "http://localhost:8642", "timeout": -1},
        )
        agent = HermesAgent(config)
        result = asyncio.run(agent.run("hello"))
        assert "error" in result
        assert "positive" in result["error"]


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
