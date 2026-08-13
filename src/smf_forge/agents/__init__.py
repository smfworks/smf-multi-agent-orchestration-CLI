"""Agent base class and built-in agent types."""

from __future__ import annotations

import asyncio
import os
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class AgentConfig:
    """Configuration for a single agent."""

    name: str
    type: str = "echo"
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    options: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict) -> AgentConfig:
        return cls(name=name, **{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BaseAgent(ABC):
    """Abstract base for all agents."""

    def __init__(self, config: AgentConfig):
        self.config = config

    @abstractmethod
    async def run(self, prompt: str, context: dict | None = None) -> Any:
        ...


class EchoAgent(BaseAgent):
    """Simple echo agent — returns the prompt. Useful for testing pipelines."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        return {"echo": prompt, "agent": self.config.name, "context_keys": list((context or {}).keys())}


class HttpAgent(BaseAgent):
    """Calls an OpenAI-compatible chat completions endpoint."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        base_url = self.config.base_url or "https://api.openai.com/v1"
        api_key = self.config.api_key
        model = self.config.model or "gpt-4"

        if not api_key:
            return {"error": "No API key configured for HTTP agent", "agent": self.config.name}

        messages = []
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
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:500]}", "agent": self.config.name}
        except Exception as exc:
            return {"error": str(exc), "agent": self.config.name}


class ShellAgent(BaseAgent):
    """Runs a configured shell command and returns stdout.

    Fail-closed: the command MUST be set in ``options.command``.
    The step prompt is never executed as a shell string.
    """

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        command = self.config.options.get("command")
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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            payload = {
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
            return {"error": "Command timed out after 60s", "agent": self.config.name}
        except Exception:
            return {"error": "shell agent failed", "agent": self.config.name}


class TransformAgent(BaseAgent):
    """Applies a Jinja2 template transform to context data."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        from jinja2.sandbox import SandboxedEnvironment

        template_str = self.config.options.get("template", "{{ prompt }}")
        try:
            env = SandboxedEnvironment()
            rendered = env.from_string(template_str).render(prompt=prompt, **(context or {}))
            return {"result": rendered, "agent": self.config.name}
        except Exception:
            return {"error": "transform template failed", "agent": self.config.name}


class HermesAgent(BaseAgent):
    """Calls a Hermes/OpenClaw-compatible agent endpoint.

    Sends the prompt as a task to a running Hermes agent and returns the
    response. This is dogfooding — smf-forge agents talking to Hermes agents.

    Config options:
      endpoint: Hermes API base URL (default: http://localhost:8642)
      agent_name: Name of the Hermes agent to invoke (default: "default")
      timeout: Request timeout in seconds (default: 120)
    """

    async def run(self, prompt: str, context: dict | None = None) -> dict:
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


# Registry of built-in agent types
AGENT_TYPES: dict[str, type[BaseAgent]] = {
    "echo": EchoAgent,
    "http": HttpAgent,
    "shell": ShellAgent,
    "transform": TransformAgent,
    "hermes": HermesAgent,
}


def build_agent(config: AgentConfig) -> BaseAgent:
    """Instantiate an agent from its config."""
    agent_cls = AGENT_TYPES.get(config.type)
    if agent_cls is None:
        raise ValueError(f"Unknown agent type '{config.type}'. Available: {list(AGENT_TYPES.keys())}")
    return agent_cls(config)


def build_registry(agents_config: dict[str, dict]) -> dict[str, BaseAgent]:
    """Build a complete agent registry from config dict."""
    registry: dict[str, BaseAgent] = {}
    for name, cfg in agents_config.items():
        config = AgentConfig.from_dict(name, cfg)
        registry[name] = build_agent(config)
    return registry