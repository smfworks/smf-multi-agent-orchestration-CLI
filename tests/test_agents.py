"""Tests for built-in agent types."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from smf_forge.agents import (
    AgentConfig,
    EchoAgent,
    HermesAgent,
    HttpAgent,
    ShellAgent,
    TransformAgent,
    build_agent,
)


def test_echo_agent_returns_prompt():
    agent = EchoAgent(AgentConfig(name="e", type="echo"))
    result = asyncio.run(agent.run("hello", {"prompt": "hello"}))
    assert result["echo"] == "hello"
    assert result["agent"] == "e"
    assert "prompt" in result["context_keys"]


def test_http_agent_missing_key():
    agent = HttpAgent(AgentConfig(name="h", type="http"))
    result = asyncio.run(agent.run("hi"))
    assert "error" in result
    assert "API key" in result["error"]


def test_http_agent_success():
    agent = HttpAgent(AgentConfig(name="h", type="http", api_key="sk-test", model="unit"))
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "pong"}}]}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("smf_forge.agents.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(agent.run("ping"))
    assert result["response"] == "pong"
    assert result["model"] == "unit"


def test_http_agent_status_error():
    agent = HttpAgent(AgentConfig(name="h", type="http", api_key="sk-test"))
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(401, request=request, text="nope")

    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.HTTPStatusError("bad", request=request, response=response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("smf_forge.agents.httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(agent.run("ping"))
    assert result["error"].startswith("HTTP 401")


def test_shell_agent_requires_command():
    agent = ShellAgent(AgentConfig(name="s", type="shell"))
    result = asyncio.run(agent.run("rm -rf /"))
    assert "requires options.command" in result["error"]


def test_shell_agent_exec_argv():
    agent = ShellAgent(
        AgentConfig(name="s", type="shell", options={"command": ["python3", "-c", "print(40+2)"]})
    )
    result = asyncio.run(agent.run("ignored"))
    assert result["exit_code"] == 0
    assert result["stdout"] == "42"


def test_shell_agent_does_not_run_prompt():
    agent = ShellAgent(AgentConfig(name="s", type="shell", options={"command": ["true"]}))
    result = asyncio.run(agent.run("echo should-not-run"))
    assert result["exit_code"] == 0
    assert "should-not-run" not in result.get("stdout", "")


def test_shell_agent_timeout_kills():
    agent = ShellAgent(
        AgentConfig(
            name="s",
            type="shell",
            options={"command": ["python3", "-c", "import time; time.sleep(30)"], "timeout": 0.2},
        )
    )
    result = asyncio.run(agent.run("x"))
    assert "timed out" in result["error"]


def test_transform_agent():
    agent = TransformAgent(
        AgentConfig(name="t", type="transform", options={"template": "hi {{ prompt }}"})
    )
    result = asyncio.run(agent.run("world"))
    assert result["result"] == "hi world"


def test_hermes_connect_error():
    agent = HermesAgent(
        AgentConfig(name="h", type="hermes", base_url="http://127.0.0.1:1")
    )
    result = asyncio.run(agent.run("hi"))
    assert "Cannot connect to Hermes" in result["error"]


def test_build_unknown_type():
    with pytest.raises(ValueError, match="Unknown agent type"):
        build_agent(AgentConfig(name="x", type="nope"))
