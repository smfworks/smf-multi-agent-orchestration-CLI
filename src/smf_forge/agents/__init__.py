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
import ipaddress
import logging
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Security helpers
# --------------------------------------------------------------------------- #

# Maximum size of any HTTP response body we'll read (1 MiB)
_MAX_RESPONSE_BYTES = 1_048_576

# Maximum config file size (1 MiB)
_MAX_CONFIG_FILE_BYTES = 1_048_576

# Private / internal IP ranges blocked to prevent SSRF
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),        # loopback
    ipaddress.ip_network("10.0.0.0/8"),         # private
    ipaddress.ip_network("172.16.0.0/12"),      # private
    ipaddress.ip_network("192.168.0.0/16"),     # private
    ipaddress.ip_network("169.254.0.0/16"),     # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),          # current network
    ipaddress.ip_network("100.64.0.0/10"),      # CGNAT
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if *ip_str* resolves to a private/internal IP (SSRF guard)."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # not a valid IP → block
    return any(addr in net for net in _BLOCKED_NETWORKS)


def validate_url(url: str, allow_localhost: bool = False) -> str:
    """Validate a URL for outbound HTTP requests (SSRF prevention).

    Args:
        url: The URL to validate.
        allow_localhost: If True, allow localhost/127.0.0.1 (for dev/testing).

    Returns:
        The validated URL string.

    Raises:
        ValueError: If the URL scheme is not http/https or the host resolves
            to a private/internal IP (unless *allow_localhost* is True).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'")

    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL must have a hostname")

    # Allow specific localhost hosts when permit is set
    if allow_localhost and host in ("localhost", "127.0.0.1", "::1"):
        return url

    # Check if host is a literal IP
    try:
        ipaddress.ip_address(str(host))
        if _is_blocked_ip(str(host)):
            raise ValueError(f"URL host '{host}' is a private/internal address")
        return url
    except ValueError:
        pass  # hostname is a DNS name, not a literal IP — resolve below

    # Resolve hostname and check all IPs
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname '{host}': {exc}") from exc

    for _family, _stype, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if _is_blocked_ip(str(ip)):
            raise ValueError(
                f"URL host '{host}' resolves to private/internal address '{ip}'"
            )

    return url


def _sanitize_error_message(msg: str, api_key: str | None) -> str:
    """Remove API key from error message if present."""
    if api_key and api_key in msg:
        return msg.replace(api_key, "[REDACTED]")
    return msg


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

        # SSRF protection: validate the URL before making the request
        try:
            validate_url(base_url)
        except ValueError as exc:
            logger.warning("URL validation failed for agent '%s': %s", self.config.name, exc)
            return {"error": f"Invalid base_url: {exc}", "agent": self.config.name}

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

                # Limit response body size to prevent memory exhaustion
                body_bytes = resp.content
                if len(body_bytes) > _MAX_RESPONSE_BYTES:
                    return {
                        "error": f"Response too large ({len(body_bytes)} bytes)",
                        "agent": self.config.name,
                    }

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return {"response": content, "agent": self.config.name, "model": model}
        except httpx.HTTPStatusError as exc:
            err_text = exc.response.text[:500]
            err_text = _sanitize_error_message(err_text, api_key)
            return {
                "error": f"HTTP {exc.response.status_code}: {err_text}",
                "agent": self.config.name,
            }
        except httpx.ConnectError as exc:
            return {"error": f"Connection error: {exc}", "agent": self.config.name}
        except asyncio.CancelledError:
            raise  # don't swallow cancellation
        except httpx.TimeoutException:
            return {"error": "Request timed out", "agent": self.config.name}
        except (KeyError, IndexError) as exc:
            return {"error": f"Malformed API response: {exc}", "agent": self.config.name}
        except httpx.HTTPError as exc:
            err_msg = _sanitize_error_message(str(exc), api_key)
            return {"error": err_msg, "agent": self.config.name}


class ShellAgent(BaseAgent):
    """Runs a shell command and returns stdout/stderr/exit code.

    The command MUST be specified in ``config.options['command']``.
    The rendered prompt is NOT used as a command (shell injection prevention).
    If no command is configured, the agent returns an error.

    Config options:
      - ``command`` (required): Shell command to execute.
      - ``timeout``: Timeout in seconds (default: 60, max: 600).
    """

    async def run(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        command = self.config.options.get("command")
        if not command:
            return {
                "error": (
                    "ShellAgent requires 'command' in options "
                    "(prompt-as-command is disabled for security)"
                ),
                "agent": self.config.name,
            }

        # Validate timeout
        try:
            timeout = int(self.config.options.get("timeout", 60))
            if timeout <= 0 or timeout > 600:
                return {
                    "error": f"Invalid timeout {timeout}: must be 1–600 seconds",
                    "agent": self.config.name,
                }
        except (ValueError, TypeError):
            return {
                "error": "Timeout must be a positive integer",
                "agent": self.config.name,
            }

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "exit_code": proc.returncode,
                "agent": self.config.name,
            }
        except asyncio.TimeoutError:
            # Kill the subprocess on timeout to prevent orphaned processes
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass  # already exited
            return {"error": f"Command timed out after {timeout}s", "agent": self.config.name}
        except asyncio.CancelledError:
            # On cancellation, kill any running subprocess
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            raise
        except (OSError, ValueError) as exc:
            return {"error": str(exc), "agent": self.config.name}


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
        except asyncio.CancelledError:
            raise
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
        try:
            timeout = int(self.config.options.get("timeout", 120))
            if timeout <= 0:
                return {"error": "Timeout must be positive", "agent": self.config.name}
        except (ValueError, TypeError):
            return {"error": "Timeout must be a positive integer", "agent": self.config.name}

        api_key = self.config.api_key

        # SSRF protection — allow localhost since Hermes typically runs locally
        try:
            validate_url(endpoint, allow_localhost=True)
        except ValueError as exc:
            logger.warning("URL validation failed for Hermes agent '%s': %s", self.config.name, exc)
            return {"error": f"Invalid endpoint: {exc}", "agent": self.config.name}

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

                # Limit response body size
                body_bytes = resp.content
                if len(body_bytes) > _MAX_RESPONSE_BYTES:
                    return {
                        "error": f"Response too large ({len(body_bytes)} bytes)",
                        "agent": self.config.name,
                    }

                data = resp.json()
                return {
                    "response": data.get("response", data.get("output", str(data))),
                    "agent": self.config.name,
                    "hermes_agent": agent_name,
                    "raw": data,
                }
        except httpx.HTTPStatusError as exc:
            err_text = exc.response.text[:500]
            err_text = _sanitize_error_message(err_text, api_key)
            return {
                "error": f"Hermes API HTTP {exc.response.status_code}: {err_text}",
                "agent": self.config.name,
            }
        except httpx.ConnectError:
            return {
                "error": f"Cannot connect to Hermes at {endpoint}. Is Hermes running?",
                "agent": self.config.name,
            }
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException:
            return {"error": "Hermes request timed out", "agent": self.config.name}
        except httpx.HTTPError as exc:
            err_msg = _sanitize_error_message(str(exc), api_key)
            return {"error": err_msg, "agent": self.config.name}


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
