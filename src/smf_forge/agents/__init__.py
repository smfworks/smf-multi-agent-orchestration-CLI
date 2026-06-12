"""Agent base class and built-in agent types."""

from __future__ import annotations

import asyncio
import json
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
    """Runs a shell command and returns stdout."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        command = self.config.options.get("command", prompt)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            return {
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "exit_code": proc.returncode,
                "agent": self.config.name,
            }
        except asyncio.TimeoutError:
            return {"error": "Command timed out after 60s", "agent": self.config.name}
        except Exception as exc:
            return {"error": str(exc), "agent": self.config.name}


class TransformAgent(BaseAgent):
    """Applies a Jinja2 template transform to context data."""

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        from jinja2 import Template

        template_str = self.config.options.get("template", "{{ prompt }}")
        try:
            rendered = Template(template_str).render(prompt=prompt, **(context or {}))
            return {"result": rendered, "agent": self.config.name}
        except Exception as exc:
            return {"error": str(exc), "agent": self.config.name}


# Registry of built-in agent types
AGENT_TYPES: dict[str, type[BaseAgent]] = {
    "echo": EchoAgent,
    "http": HttpAgent,
    "shell": ShellAgent,
    "transform": TransformAgent,
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