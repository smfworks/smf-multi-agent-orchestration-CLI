"""Shell agent must never execute or export the prompt."""

from __future__ import annotations

import asyncio
import sys

from smf_forge.agents import AgentConfig, build_agent


def test_missing_command_does_not_execute_prompt(tmp_path):
    marker = tmp_path / "pwned"
    agent = build_agent(AgentConfig(name="sh", type="shell"))
    result = asyncio.run(agent.run(f"printf ran > {marker}"))
    assert "error" in result
    assert "command" in result["error"]
    assert result.get("exit_code") is None
    assert not marker.exists()


def test_shell_true_is_rejected(tmp_path):
    marker = tmp_path / "pwned"
    agent = build_agent(
        AgentConfig(
            name="sh",
            type="shell",
            options={"shell": True, "command": f"printf ran > {marker}"},
        )
    )
    result = asyncio.run(agent.run("ignored"))
    assert "error" in result
    assert "shell: true" in result["error"]
    assert not marker.exists()


def test_forge_prompt_env_is_not_set(tmp_path):
    marker = tmp_path / "from-env"
    agent = build_agent(
        AgentConfig(
            name="sh",
            type="shell",
            options={"command": ["sh", "-c", 'printf x > "$FORGE_PROMPT"']},
        )
    )
    result = asyncio.run(agent.run(str(marker)))
    assert not marker.exists(), result
    assert result.get("exit_code") != 0 or "error" in result


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
