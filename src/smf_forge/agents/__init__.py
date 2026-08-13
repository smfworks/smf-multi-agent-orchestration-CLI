"""Agent base class and built-in agent types."""

from __future__ import annotations

import asyncio
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
    async def run(self, prompt: str, context: dict | None = None) -> Any: ...


class EchoAgent(BaseAgent):
    """Simple echo agent — returns the prompt. Useful for testing pipelines."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        return {
            "echo": prompt,
            "agent": self.config.name,
            "context_keys": list((context or {}).keys()),
        }


class HttpAgent(BaseAgent):
    """Calls an OpenAI-compatible chat completions endpoint."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        base_url = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        api_key = self.config.api_key
        model = self.config.model or "gpt-4o-mini"

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
            return {
                "error": f"HTTP {exc.response.status_code}: {exc.response.text[:500]}",
                "agent": self.config.name,
            }
        except httpx.HTTPError as exc:
            return {"error": f"HTTP client error: {exc}", "agent": self.config.name}
        except (KeyError, IndexError, TypeError) as exc:
            return {"error": f"Unexpected API response: {exc}", "agent": self.config.name}


class ShellAgent(BaseAgent):
    """Runs a configured command and returns stdout.

    Security: the command comes from agent options, never from the step prompt.
    `shell: false` (default) uses argv execution. `shell: true` is opt-in and
    runs through the system shell — only use with trusted static commands.
    """

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        options = self.config.options or {}
        command = options.get("command")
        if not command:
            return {
                "error": "Shell agent requires options.command; the prompt is never executed",
                "agent": self.config.name,
            }

        use_shell = bool(options.get("shell", False))
        timeout = float(options.get("timeout", 60))

        try:
            if use_shell:
                if not isinstance(command, str):
                    return {
                        "error": "shell: true requires options.command to be a string",
                        "agent": self.config.name,
                    }
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_prompt_env(prompt),
                )
            else:
                argv = command if isinstance(command, list) else shlex.split(str(command))
                if not argv:
                    return {"error": "Shell agent command is empty", "agent": self.config.name}
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_prompt_env(prompt),
                )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                await _kill_process(proc)
                return {
                    "error": f"Command timed out after {timeout:.0f}s",
                    "agent": self.config.name,
                }
            return {
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "exit_code": proc.returncode,
                "agent": self.config.name,
            }
        except OSError as exc:
            return {"error": f"Failed to start command: {exc}", "agent": self.config.name}


def _prompt_env(prompt: str) -> dict[str, str]:
    """Child env with FORGE_PROMPT set. Does not inherit a mutated global env."""
    import os

    env = os.environ.copy()
    env["FORGE_PROMPT"] = prompt
    return env


async def _kill_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.kill()
    try:
        await asyncio.wait_for(proc.communicate(), timeout=5)
    except asyncio.TimeoutError:
        pass


class TransformAgent(BaseAgent):
    """Applies a Jinja2 template transform to context data."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        from jinja2 import Template
        from jinja2.exceptions import TemplateError

        template_str = self.config.options.get("template", "{{ prompt }}")
        try:
            rendered = Template(template_str).render(prompt=prompt, **(context or {}))
            return {"result": rendered, "agent": self.config.name}
        except TemplateError as exc:
            return {"error": f"Template error: {exc}", "agent": self.config.name}


class HermesAgent(BaseAgent):
    """Calls a Hermes-compatible agent endpoint.

    Config options:
      endpoint / base_url: Hermes API base URL (default: http://localhost:8642)
      agent_name: Name of the Hermes agent to invoke (default: "default")
      timeout: Request timeout in seconds (default: 120)
    """

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        endpoint = (
            self.config.options.get("endpoint")
            or self.config.base_url
            or "http://localhost:8642"
        ).rstrip("/")
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
        except httpx.HTTPError as exc:
            return {"error": f"Hermes HTTP client error: {exc}", "agent": self.config.name}


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
        available = list(AGENT_TYPES.keys())
        raise ValueError(f"Unknown agent type '{config.type}'. Available: {available}")
    return agent_cls(config)


def build_registry(agents_config: dict[str, dict]) -> dict[str, BaseAgent]:
    """Build a complete agent registry from config dict."""
    registry: dict[str, BaseAgent] = {}
    for name, cfg in agents_config.items():
        config = AgentConfig.from_dict(name, cfg)
        registry[name] = build_agent(config)
    return registry
