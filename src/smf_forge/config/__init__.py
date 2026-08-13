"""Config loading and validation for smf-forge projects."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "forge.yaml"


class ConfigError(Exception):
    """Raised when config is invalid or missing."""


def find_config(start: Path | None = None) -> Path:
    """Walk up from start dir to find forge.yaml."""
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            raise ConfigError(
                f"No {CONFIG_FILENAME} found in {start or Path.cwd()} or any parent directory"
            )
        current = parent


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and parse a forge.yaml config file."""
    config_path = path or find_config()
    with open(config_path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping")

    return data


def validate_config(data: dict[str, Any]) -> list[str]:
    """Validate a parsed config dict. Returns list of error strings (empty = valid)."""
    from smf_forge.agents import AGENT_TYPES

    errors: list[str] = []
    known_types = set(AGENT_TYPES.keys())

    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        errors.append("'agents' must be a mapping of agent_name → config")
        agent_names: set[str] = set()
    else:
        agent_names = set(agents.keys())
        for name, cfg in agents.items():
            if not isinstance(cfg, dict):
                errors.append(f"Agent '{name}' config must be a mapping")
                continue
            agent_type = cfg.get("type")
            if not agent_type:
                errors.append(f"Agent '{name}' missing required 'type' field")
            elif agent_type not in known_types:
                errors.append(
                    f"Agent '{name}' has unknown type '{agent_type}'. "
                    f"Available: {sorted(known_types)}"
                )

    pipelines = data.get("pipelines", {})
    if not isinstance(pipelines, dict):
        errors.append("'pipelines' must be a mapping of pipeline_name → config")
        return errors

    for pname, pconfig in pipelines.items():
        if not isinstance(pconfig, dict):
            errors.append(f"Pipeline '{pname}' config must be a mapping")
            continue
        steps = pconfig.get("steps", [])
        if not isinstance(steps, list):
            errors.append(f"Pipeline '{pname}' steps must be a list")
            continue
        if not steps:
            errors.append(f"Pipeline '{pname}' has no steps")
            continue

        step_names: set[str] = set()
        parsed_steps: list[tuple[str, dict]] = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Pipeline '{pname}' step {i} must be a mapping")
                continue
            sname = step.get("name")
            if not sname:
                errors.append(f"Pipeline '{pname}' step {i} missing 'name'")
            elif sname in step_names:
                errors.append(f"Pipeline '{pname}' has duplicate step name '{sname}'")
            else:
                step_names.add(sname)

            agent_ref = step.get("agent")
            if not agent_ref:
                errors.append(f"Pipeline '{pname}' step '{sname}' missing 'agent' reference")
            elif agent_names and agent_ref not in agent_names:
                errors.append(
                    f"Pipeline '{pname}' step '{sname}' references unknown agent '{agent_ref}'"
                )

            depends = step.get("depends_on", [])
            if not isinstance(depends, list):
                errors.append(f"Pipeline '{pname}' step '{sname}' depends_on must be a list")
            parsed_steps.append((sname or f"step-{i}", step))

        for sname, step in parsed_steps:
            depends = step.get("depends_on", [])
            if not isinstance(depends, list):
                continue
            for dep in depends:
                if dep not in step_names:
                    errors.append(
                        f"Pipeline '{pname}' step '{sname}' depends on unknown step '{dep}'"
                    )

    return errors


def resolve_env_vars(data: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Resolve ${ENV_VAR} and ${ENV_VAR:default} references in string values.

    Supports two syntaxes:
    - ${VAR} — resolves from environment; raises if unset and strict=True, else ""
    - ${VAR:default_value} — resolves from environment, uses default if not set
    """

    def _resolve(value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith("${") and value.endswith("}"):
                inner = value[2:-1]
                if ":" in inner:
                    env_name, default = inner.split(":", 1)
                    return os.environ.get(env_name, default)
                env_name = inner
                env_val = os.environ.get(env_name)
                if env_val is None:
                    if strict:
                        raise ConfigError(f"Environment variable '{env_name}' not set")
                    return ""
                return env_val
            return value
        if isinstance(value, dict):
            return {k: _resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve(item) for item in value]
        return value

    return _resolve(data)
