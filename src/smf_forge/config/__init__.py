"""Config loading, validation, and environment-variable resolution for smf-forge projects.

This module handles all forge.yaml parsing and validation logic:
  - find_config(): walk up the directory tree to locate forge.yaml
  - load_config(): read and parse a YAML config file
  - validate_config(): structural validation of agents and pipelines
  - resolve_env_vars(): ${VAR} / ${VAR:default} substitution from the environment
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "forge.yaml"

# Regex for ${VAR} or ${VAR:default} — must match the entire string value
_ENV_VAR_PATTERN = re.compile(r"^\$\{([^}]+)\}$")

# Known agent types (mirrors smf_forge.agents.AGENT_TYPES, defined here to avoid
# circular imports during validation)
KNOWN_AGENT_TYPES = {"echo", "http", "shell", "transform", "hermes"}


class ConfigError(Exception):
    """Raised when config is invalid, missing, or cannot be parsed."""


# --------------------------------------------------------------------------- #
# Config discovery
# --------------------------------------------------------------------------- #

def find_config(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find ``forge.yaml``.

    Args:
        start: Directory to begin searching from. Defaults to ``Path.cwd()``.

    Returns:
        Resolved path to the first ``forge.yaml`` found.

    Raises:
        ConfigError: If no config file is found in *start* or any parent.
    """
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.is_file():
            logger.debug("Found config at %s", candidate)
            return candidate
        parent = current.parent
        if parent == current:
            raise ConfigError(
                f"No {CONFIG_FILENAME} found in {start or Path.cwd()} or any parent directory"
            )
        current = parent


# --------------------------------------------------------------------------- #
# Config loading
# --------------------------------------------------------------------------- #

def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and parse a ``forge.yaml`` config file.

    Args:
        path: Path to the config file. If ``None``, uses :func:`find_config`.

    Returns:
        Parsed YAML as a dictionary.

    Raises:
        ConfigError: If the file does not exist, is empty, or does not contain
            a YAML mapping at the top level.
    """
    config_path = path or find_config()

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML parse error in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc

    if data is None:
        raise ConfigError(f"{config_path} is empty")
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping (got {type(data).__name__})")

    logger.debug("Loaded config from %s with keys: %s", config_path, list(data.keys()))
    return data


# --------------------------------------------------------------------------- #
# Config validation
# --------------------------------------------------------------------------- #

def validate_config(data: dict[str, Any]) -> list[str]:
    """Validate a parsed config dict.

    Performs structural validation of the ``agents`` and ``pipelines`` sections,
    including: agent type presence, step name uniqueness, agent references,
    dependency references, and dependency cycle detection.

    Args:
        data: Parsed config dictionary.

    Returns:
        List of error strings. An empty list means the config is valid.
    """
    errors: list[str] = []

    # ---- top-level keys ----
    if not isinstance(data, dict):
        return ["Config root must be a mapping"]

    # ---- agents section ----
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        errors.append("'agents' must be a mapping of agent_name → config")
        agents = {}
    else:
        for name, cfg in agents.items():
            if not isinstance(cfg, dict):
                errors.append(f"Agent '{name}' config must be a mapping")
                continue
            agent_type = cfg.get("type")
            if not agent_type:
                errors.append(f"Agent '{name}' missing required 'type' field")
            elif not isinstance(agent_type, str):
                errors.append(
                    f"Agent '{name}' type must be a string, got {type(agent_type).__name__}"
                )
            elif agent_type not in KNOWN_AGENT_TYPES:
                errors.append(
                    f"Agent '{name}' has unknown type '{agent_type}'. "
                    f"Known types: {', '.join(sorted(KNOWN_AGENT_TYPES))}"
                )

    # ---- pipelines section ----
    pipelines = data.get("pipelines", {})
    if not isinstance(pipelines, dict):
        errors.append("'pipelines' must be a mapping of pipeline_name → config")
        pipelines = {}
    else:
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
            agent_names = set(agents.keys())

            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    errors.append(f"Pipeline '{pname}' step {i} must be a mapping")
                    continue

                sname = step.get("name")
                if not sname:
                    errors.append(f"Pipeline '{pname}' step {i} missing 'name'")
                elif not isinstance(sname, str):
                    errors.append(f"Pipeline '{pname}' step {i} name must be a string")
                elif sname in step_names:
                    errors.append(f"Pipeline '{pname}' has duplicate step name '{sname}'")
                else:
                    step_names.add(sname)

                agent_ref = step.get("agent")
                if not agent_ref:
                    label = sname or f"step {i}"
                    errors.append(f"Pipeline '{pname}' step '{label}' missing 'agent' reference")
                elif not isinstance(agent_ref, str):
                    label = sname or f"step {i}"
                    errors.append(f"Pipeline '{pname}' step '{label}' agent must be a string")
                elif agent_ref not in agent_names and agents:
                    errors.append(
                        f"Pipeline '{pname}' step '{sname}' references unknown agent '{agent_ref}'"
                    )

                # depends_on validation
                depends = step.get("depends_on", [])
                if not isinstance(depends, list):
                    label = sname or f"step {i}"
                    errors.append(f"Pipeline '{pname}' step '{label}' depends_on must be a list")
                else:
                    for dep in depends:
                        if not isinstance(dep, str):
                            errors.append(
                                f"Pipeline '{pname}' step '{sname}' "
                                "depends_on entries must be strings"
                            )
                        elif dep not in step_names and dep != sname:
                            # dep may reference a later step; we do a second pass below
                            pass

            # Second pass: verify all depends_on references point to existing steps
            all_step_names = step_names
            for step in steps:
                if not isinstance(step, dict):
                    continue
                sname = step.get("name", "?")
                depends = step.get("depends_on", [])
                if isinstance(depends, list):
                    for dep in depends:
                        if isinstance(dep, str) and dep not in all_step_names:
                            errors.append(
                                f"Pipeline '{pname}' step '{sname}' depends on unknown step '{dep}'"
                            )

            # Cycle detection
            _detect_cycles(pname, steps, errors)

    return errors


def _detect_cycles(pipeline_name: str, steps: list[dict], errors: list[str]) -> None:
    """Detect circular dependencies among pipeline steps and append errors."""
    name_to_deps: dict[str, list[str]] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        sname = step.get("name")
        if sname is None:
            continue
        deps = step.get("depends_on", [])
        if isinstance(deps, list):
            name_to_deps[sname] = [d for d in deps if isinstance(d, str)]
        else:
            name_to_deps[sname] = []

    visited: set[str] = set()
    in_stack: set[str] = set()

    def _has_cycle(node: str) -> bool:
        if node in in_stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        for dep in name_to_deps.get(node, []):
            if _has_cycle(dep):
                return True
        in_stack.discard(node)
        return False

    for name in name_to_deps:
        if _has_cycle(name):
            errors.append(f"Pipeline '{pipeline_name}' has circular dependencies")
            return


# --------------------------------------------------------------------------- #
# Environment variable resolution
# --------------------------------------------------------------------------- #

def resolve_env_vars(data: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Resolve ``${ENV_VAR}`` and ``${ENV_VAR:default}`` references in string values.

    Supports two syntaxes:
      - ``${VAR}`` — resolves from environment; raises :class:`ConfigError` if not set.
      - ``${VAR:default_value}`` — resolves from environment; uses *default_value* if not set.

    Only values that are **entirely** a ``${...}`` expression are resolved.
    Embedded references (e.g. ``"prefix-${VAR}"``) are left as-is.

    Args:
        data: Parsed config dictionary.

    Returns:
        New dictionary with environment variables resolved.

    Raises:
        ConfigError: If a ``${VAR}`` (without default) references an unset variable.
    """

    def _resolve(value: Any) -> Any:
        if isinstance(value, str):
            match = _ENV_VAR_PATTERN.match(value)
            if match:
                inner = match.group(1)
                # Check for default value syntax: ${VAR:default}
                if ":" in inner:
                    env_name, default = inner.split(":", 1)
                    return os.environ.get(env_name, default)
                else:
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
