"""Tests for smf-forge config module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from smf_forge.config import (
    CONFIG_FILENAME,
    ConfigError,
    find_config,
    load_config,
    resolve_env_vars,
    validate_config,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def write_config(directory: Path, data: dict) -> Path:
    """Write a forge.yaml file in *directory* and return its path."""
    path = directory / CONFIG_FILENAME
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


# --------------------------------------------------------------------------- #
# find_config
# --------------------------------------------------------------------------- #

class TestFindConfig:
    def test_finds_in_cwd(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"agents": {}})
        assert find_config(tmp_path) == tmp_path / CONFIG_FILENAME

    def test_finds_in_parent(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"agents": {}})
        child = tmp_path / "subdir"
        child.mkdir()
        assert find_config(child) == tmp_path / CONFIG_FILENAME

    def test_finds_in_grandparent(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"agents": {}})
        grandchild = tmp_path / "a" / "b"
        grandchild.mkdir(parents=True)
        assert find_config(grandchild) == tmp_path / CONFIG_FILENAME

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="No forge.yaml found"):
            find_config(tmp_path / "nonexistent")

    def test_uses_cwd_when_no_arg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        write_config(tmp_path, {"agents": {}})
        monkeypatch.chdir(tmp_path)
        assert find_config() == tmp_path / CONFIG_FILENAME


# --------------------------------------------------------------------------- #
# load_config
# --------------------------------------------------------------------------- #

class TestLoadConfig:
    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        path = write_config(tmp_path, {"project": "test", "agents": {}})
        data = load_config(path)
        assert data["project"] == "test"

    def test_rejects_non_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / CONFIG_FILENAME
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ConfigError, match="YAML mapping"):
            load_config(path)

    def test_rejects_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / CONFIG_FILENAME
        path.write_text("")
        with pytest.raises(ConfigError, match="empty"):
            load_config(path)

    def test_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_rejects_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / CONFIG_FILENAME
        path.write_text("agents: [\n  {invalid yaml")
        with pytest.raises(ConfigError, match="YAML parse error"):
            load_config(path)

    def test_loads_without_path_uses_find(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_config(tmp_path, {"project": "auto"})
        monkeypatch.chdir(tmp_path)
        data = load_config()
        assert data["project"] == "auto"

    def test_rejects_oversized_file(self, tmp_path: Path) -> None:
        """Config files larger than 1 MiB should be rejected (YAML bomb)."""
        path = tmp_path / CONFIG_FILENAME
        # Create a file larger than 1 MiB
        with open(path, "w") as f:
            f.write("project: " + "x" * 1_048_577 + "\n")
        with pytest.raises(ConfigError, match="too large"):
            load_config(path)


# --------------------------------------------------------------------------- #
# validate_config
# --------------------------------------------------------------------------- #

class TestValidateConfig:
    def test_valid_config(self) -> None:
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "test": {
                    "steps": [
                        {"name": "step1", "agent": "echo"},
                    ]
                }
            },
        }
        errors = validate_config(data)
        assert errors == []

    def test_valid_config_with_dependencies(self) -> None:
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "test": {
                    "steps": [
                        {"name": "a", "agent": "echo"},
                        {"name": "b", "agent": "echo", "depends_on": ["a"]},
                        {"name": "c", "agent": "echo", "depends_on": ["a", "b"]},
                    ]
                }
            },
        }
        errors = validate_config(data)
        assert errors == []

    def test_empty_config_is_valid(self) -> None:
        errors = validate_config({})
        assert errors == []

    def test_missing_agent_type(self) -> None:
        data = {"agents": {"bad": {"model": "gpt-4"}}}
        errors = validate_config(data)
        assert any("missing required 'type'" in e for e in errors)

    def test_unknown_agent_type(self) -> None:
        data = {"agents": {"bad": {"type": "nonexistent_type"}}}
        errors = validate_config(data)
        assert any("unknown type" in e for e in errors)

    def test_agent_config_not_mapping(self) -> None:
        data = {"agents": {"bad": "not a dict"}}
        errors = validate_config(data)
        assert any("config must be a mapping" in e for e in errors)

    def test_agents_not_mapping(self) -> None:
        data = {"agents": ["not", "a", "dict"]}
        errors = validate_config(data)
        assert any("'agents' must be a mapping" in e for e in errors)

    def test_duplicate_step_names(self) -> None:
        data = {
            "pipelines": {
                "dup": {
                    "steps": [
                        {"name": "s1", "agent": "echo"},
                        {"name": "s1", "agent": "echo"},
                    ]
                }
            }
        }
        errors = validate_config(data)
        assert any("duplicate step" in e for e in errors)

    def test_step_missing_agent(self) -> None:
        data = {
            "pipelines": {
                "bad": {
                    "steps": [{"name": "step1"}]
                }
            }
        }
        errors = validate_config(data)
        assert any("missing 'agent'" in e for e in errors)

    def test_step_missing_name(self) -> None:
        data = {
            "pipelines": {
                "bad": {
                    "steps": [{"agent": "echo"}]
                }
            }
        }
        errors = validate_config(data)
        assert any("missing 'name'" in e for e in errors)

    def test_empty_pipeline(self) -> None:
        data = {"pipelines": {"empty": {"steps": []}}}
        errors = validate_config(data)
        assert any("no steps" in e for e in errors)

    def test_pipeline_no_steps_key(self) -> None:
        data = {"pipelines": {"nokey": {}}}
        errors = validate_config(data)
        assert any("no steps" in e for e in errors)

    def test_depends_on_not_list(self) -> None:
        data = {
            "pipelines": {
                "bad": {
                    "steps": [
                        {"name": "s1", "agent": "echo", "depends_on": "oops"},
                    ]
                }
            }
        }
        errors = validate_config(data)
        assert any("depends_on must be a list" in e for e in errors)

    def test_depends_on_unknown_step(self) -> None:
        data = {
            "pipelines": {
                "bad": {
                    "steps": [
                        {"name": "s1", "agent": "echo", "depends_on": ["ghost"]},
                    ]
                }
            }
        }
        errors = validate_config(data)
        assert any("depends on unknown step" in e for e in errors)

    def test_circular_dependency(self) -> None:
        data = {
            "pipelines": {
                "cyc": {
                    "steps": [
                        {"name": "a", "agent": "echo", "depends_on": ["b"]},
                        {"name": "b", "agent": "echo", "depends_on": ["a"]},
                    ]
                }
            }
        }
        errors = validate_config(data)
        assert any("circular" in e for e in errors)

    def test_pipelines_not_mapping(self) -> None:
        data = {"pipelines": ["not", "a", "dict"]}
        errors = validate_config(data)
        assert any("'pipelines' must be a mapping" in e for e in errors)

    def test_pipeline_config_not_mapping(self) -> None:
        data = {"pipelines": {"bad": "not a dict"}}
        errors = validate_config(data)
        assert any("config must be a mapping" in e for e in errors)

    def test_step_not_mapping(self) -> None:
        data = {
            "pipelines": {
                "bad": {
                    "steps": ["not a dict"],
                }
            }
        }
        errors = validate_config(data)
        assert any("step 0 must be a mapping" in e for e in errors)

    def test_agent_ref_unknown_agent(self) -> None:
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "bad": {
                    "steps": [{"name": "s1", "agent": "nonexistent_agent"}],
                }
            },
        }
        errors = validate_config(data)
        assert any("references unknown agent" in e for e in errors)

    def test_self_dependency_is_cycle(self) -> None:
        data = {
            "pipelines": {
                "self": {
                    "steps": [
                        {"name": "s1", "agent": "echo", "depends_on": ["s1"]},
                    ]
                }
            }
        }
        errors = validate_config(data)
        assert any("circular" in e for e in errors)


# --------------------------------------------------------------------------- #
# resolve_env_vars
# --------------------------------------------------------------------------- #

class TestResolveEnvVars:
    def test_resolves_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_KEY", "secret123")
        data = {"agents": {"bot": {"api_key": "${TEST_KEY}"}}}
        result = resolve_env_vars(data)
        assert result["agents"]["bot"]["api_key"] == "secret123"

    def test_raises_on_missing_env(self) -> None:
        data = {"key": "${NONEXISTENT_VAR_XYZ}"}
        with pytest.raises(ConfigError, match="not set"):
            resolve_env_vars(data)

    def test_passes_through_normal_strings(self) -> None:
        data = {"name": "hello"}
        assert resolve_env_vars(data) == data

    def test_nested_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_URL", "http://localhost:8080")
        data = {"agents": {"a": {"base_url": "${MY_URL}"}}}
        result = resolve_env_vars(data)
        assert result["agents"]["a"]["base_url"] == "http://localhost:8080"

    def test_default_value_when_env_not_set(self) -> None:
        """${VAR:default} syntax should use default when env var not set."""
        data = {"project": "${NONEXISTENT_PROJECT:my-default}"}
        result = resolve_env_vars(data)
        assert result["project"] == "my-default"

    def test_default_value_overridden_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env var IS set, default should be ignored."""
        monkeypatch.setenv("MY_PROJECT", "from-env")
        data = {"project": "${MY_PROJECT:fallback}"}
        result = resolve_env_vars(data)
        assert result["project"] == "from-env"

    def test_default_value_with_url(self) -> None:
        """${VAR:https://...} should work with colons in defaults."""
        data = {"agents": {"a": {"base_url": "${MISSING_URL:https://api.openai.com/v1}"}}}
        result = resolve_env_vars(data)
        assert result["agents"]["a"]["base_url"] == "https://api.openai.com/v1"

    def test_resolves_in_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIST_VAR", "listval")
        data = {"items": ["${LIST_VAR}", "normal"]}
        result = resolve_env_vars(data)
        assert result["items"] == ["listval", "normal"]

    def test_non_string_values_untouched(self) -> None:
        data = {"port": 8080, "enabled": True, "ratio": 0.5}
        result = resolve_env_vars(data)
        assert result == data

    def test_partial_env_var_not_resolved(self) -> None:
        """Values that are not entirely ${...} should not be resolved."""
        data = {"text": "prefix-${SOME_VAR}"}
        result = resolve_env_vars(data)
        assert result["text"] == "prefix-${SOME_VAR}"

    def test_empty_default(self) -> None:
        """${VAR:} should resolve to empty string when env not set."""
        data = {"key": "${NONEXISTENT_VAR_EMPTY:}"}
        result = resolve_env_vars(data)
        assert result["key"] == ""

    def test_does_not_mutate_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("X_VAR", "x")
        data = {"a": "${X_VAR}"}
        original = {"a": "${X_VAR}"}
        resolve_env_vars(data)
        assert data == original
