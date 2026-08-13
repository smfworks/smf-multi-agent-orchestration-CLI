"""Shell agent must never execute the prompt."""

from __future__ import annotations

import asyncio
import sys

from smf_forge.agents import AgentConfig, build_agent


def test_missing_command_does_not_execute_prompt():
    agent = build_agent(AgentConfig(name="sh", type="shell"))
    result = asyncio.run(agent.run("echo pwned && exit 42"))
    assert "error" in result
    assert "options.command" in result["error"]
    assert result.get("exit_code") is None


def test_explicit_argv_runs():
    agent = build_agent(
        AgentConfig(
            name="sh",
            type="shell",
            options={"command": [sys.executable, "-c", "print(7)"]},
        )
    )
    result = asyncio.run(agent.run("this must not run"))
    assert result.get("exit_code") == 0, result
    assert "7" in result.get("stdout", "")
