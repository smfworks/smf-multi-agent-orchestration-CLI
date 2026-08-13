"""Agent base class and built-in agent types.

Provides:
  - AgentConfig: dataclass for agent configuration
  - BaseAgent: abstract base class for all agents
  - EchoAgent, HttpAgent, ShellAgent, TransformAgent, HermesAgent: built-in types
  - build_agent(): factory function
  - build_registry(): build a complete agent registry from config
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Agent configuration
# --------------------------------------------------------------------------- #

@dataclass
class AgentConfig:
    """Configuration for a single agent.

    Attributes:
        name: Agent instance name (must match the key in the ``agents`` config section).
        type: Agent type — one of ``echo``, ``http``, ``shell``, ``transform``, ``hermes``.
        model: Model name (used by ``http`` and ``hermes`` agents).
        provider: Optional provider label (informational).
        base_url: Base URL for API calls (used by ``http`` and ``hermes`` agents).
        api_key: API key for authenticated endpoints.
        system_prompt: System prompt for LLM-based agents.
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Maximum tokens to generate.
        options: Type-specific options (e.g. ``command`` for shell, ``template`` for transform).
    """

    name: str
    type: str = "echo"
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> AgentConfig:
        """Build an :class:`AgentConfig` from a config dict, ignoring unknown keys.

        Args:
            name: Agent instance name.
            data: Raw config dictionary from the ``agents`` section.

        Returns:
            An :class:`AgentConfig` instance.
        """
        valid_fields = cls.__dataclass_fields__
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(name=name, **filtered)


# --------------------------------------------------------------------------- #
# Base agent
# --------------------------------------------------------------------------- #

class BaseAgent(ABC):
    """Abstract base class for all agents.

    Subclasses must implement :meth:`run`.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    @abstractmethod
    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> Any:
        """Execute the agent with *prompt* and optional *context*.

        Args:
            prompt: The rendered prompt string for this step.
            context: Pipeline context dict (outputs of previous steps).

        Returns:
            Agent output — typically a dict. If the dict contains an ``error``
            key and no ``response`` key, the engine treats it as a failure.
        """
        ...


# --------------------------------------------------------------------------- #
# Built-in agent types
# --------------------------------------------------------------------------- #

class EchoAgent(BaseAgent):
    """Simple echo agent — returns the prompt. Useful for testing pipelines."""

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "echo": prompt,
            "agent": self.config.name,
            "context_keys": list((context or {}).keys()),
        }


class HttpAgent(BaseAgent):
    """Calls an OpenAI-compatible chat completions endpoint.

    Uses ``config.base_url``, ``config.api_key``, ``config.model``,
    ``config.system_prompt``, ``config.temperature``, and ``config.max_tokens``.
    """

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        base_url = self.config.base_url or "https://api.openai.com/v1"
        api_key = self.config.api_key
        model = self.config.model or "gpt-4"

        if not api_key:
            return {"error": "No API key configured for HTTP agent", "agent": self.config.name}

        messages: list[dict[str, str]] = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_tokens,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return {"response": content, "agent": self.config.name, "model": model}
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                "agent": self.config.name,
            }
        except httpx.ConnectError as exc:
            return {"error": f"Connection error: {exc}", "agent": self.config.name}
        except Exception as exc:
            return {"error": str(exc), "agent": self.config.name}


class ShellAgent(BaseAgent):
    """Runs a configured command and returns stdout/stderr/exit code.

    Fail-closed: ``options.command`` is required (argv list or string).
    The step prompt is never executed.
    """

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        command = self.config.options.get("command")
        timeout = int(self.config.options.get("timeout", 60))
        if isinstance(command, list) and all(isinstance(x, str) for x in command) and command:
            argv = command
        elif isinstance(command, str) and command.strip():
            argv = shlex.split(command, posix=os.name != "nt")
        else:
            return {
                "error": "shell agent requires options.command (argv list or string); refusing to execute the prompt",
                "agent": self.config.name,
            }
        if not argv:
            return {
                "error": "shell agent options.command is empty after parse",
                "agent": self.config.name,
            }
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            payload: dict[str, Any] = {
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "exit_code": proc.returncode,
                "agent": self.config.name,
            }
            if proc.returncode != 0:
                payload["error"] = f"command exited {proc.returncode}"
            return payload
        except asyncio.TimeoutError:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return {"error": f"Command timed out after {timeout}s", "agent": self.config.name}
        except Exception:
            return {"error": "shell agent failed", "agent": self.config.name}


class TransformAgent(BaseAgent):
    """Applies a Jinja2 template transform to context data.

    The template is taken from ``config.options['template']`` (default: ``"{{ prompt }}"``).
    """

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        from jinja2 import Template

        template_str = self.config.options.get("template", "{{ prompt }}")
        try:
            rendered = Template(template_str).render(prompt=prompt, **(context or {}))
            return {"result": rendered, "agent": self.config.name}
        except Exception as exc:
            return {"error": str(exc), "agent": self.config.name}


class HermesAgent(BaseAgent):
    """Calls a Hermes/OpenClaw-compatible agent endpoint.

    Sends the prompt as a task to a running Hermes agent and returns the
    response. This is dogfooding — smf-forge agents talking to Hermes agents.

    Config options (in ``config.options``):
      - ``endpoint``: Hermes API base URL (default: ``http://localhost:8642``)
      - ``agent_name``: Name of the Hermes agent to invoke (default: ``"default"``)
      - ``timeout``: Request timeout in seconds (default: ``120``)
    """

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint = self.config.options.get(
            "endpoint", self.config.base_url or "http://localhost:8642"
        )
        agent_name = self.config.options.get("agent_name", "default")
        timeout = int(self.config.options.get("timeout", 120))
        api_key = self.config.api_key

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "agent": agent_name,
            "prompt": prompt,
            "context": context or {},
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{endpoint}/api/agent/run",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "response": data.get("response", data.get("output", str(data))),
                    "agent": self.config.name,
                    "hermes_agent": agent_name,
                    "raw": data,
                }
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"Hermes API HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                "agent": self.config.name,
            }
        except httpx.ConnectError:
            return {
                "error": f"Cannot connect to Hermes at {endpoint}. Is Hermes running?",
                "agent": self.config.name,
            }
        except Exception as exc:
            return {"error": str(exc), "agent": self.config.name}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

# Registry of built-in agent types
AGENT_TYPES: dict[str, type[BaseAgent]] = {
    "echo": EchoAgent,
    "http": HttpAgent,
    "shell": ShellAgent,
    "transform": TransformAgent,
    "hermes": HermesAgent,
}


def build_agent(config: AgentConfig) -> BaseAgent:
    """Instantiate an agent from its config.

    Args:
        config: Agent configuration dataclass.

    Returns:
        An instance of the appropriate :class:`BaseAgent` subclass.

    Raises:
        ValueError: If ``config.type`` is not a known agent type.
    """
    agent_cls = AGENT_TYPES.get(config.type)
    if agent_cls is None:
        raise ValueError(
            f"Unknown agent type '{config.type}'. Available: {list(AGENT_TYPES.keys())}"
        )
    return agent_cls(config)


def build_registry(agents_config: dict[str, dict[str, Any]]) -> dict[str, BaseAgent]:
    """Build a complete agent registry from a config dict.

    Args:
        agents_config: The ``agents`` section of forge.yaml.

    Returns:
        Mapping of agent name → :class:`BaseAgent` instance.
    """
    registry: dict[str, BaseAgent] = {}
    for name, cfg in agents_config.items():
        config = AgentConfig.from_dict(name, cfg)
        registry[name] = build_agent(config)
    return registry
