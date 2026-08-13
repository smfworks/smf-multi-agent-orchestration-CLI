"""Tests for smf-forge config module."""

from pathlib import Path

import pytest
import yaml

from smf_forge.config import (
    ConfigError,
    find_config,
    load_config,
    resolve_env_vars,
    validate_config,
)


def write_config(directory: Path, data: dict) -> Path:
    path = directory / "forge.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


class TestFindConfig:
    def test_finds_in_cwd(self, tmp_path):
        write_config(tmp_path, {"agents": {}})
        assert find_config(tmp_path) == tmp_path / "forge.yaml"

    def test_finds_in_parent(self, tmp_path):
        write_config(tmp_path, {"agents": {}})
        child = tmp_path / "subdir"
        child.mkdir()
        assert find_config(child) == tmp_path / "forge.yaml"

    def test_raises_when_missing(self, tmp_path):
        with pytest.raises(ConfigError, match="No forge.yaml found"):
            find_config(tmp_path / "nonexistent")


class TestLoadConfig:
    def test_loads_valid_yaml(self, tmp_path):
        path = write_config(tmp_path, {"project": "test", "agents": {}})
        data = load_config(path)
        assert data["project"] == "test"

    def test_rejects_non_mapping(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ConfigError, match="YAML mapping"):
            load_config(path)

    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "missing.yaml")

    def test_rejects_invalid_yaml(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text("agents: [\n")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(path)


class TestValidateConfig:
    def test_valid_config(self):
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

    def test_missing_agent_type(self):
        data = {"agents": {"bad": {"model": "gpt-4"}}}
        errors = validate_config(data)
        assert any("missing required 'type'" in e for e in errors)

    def test_unknown_agent_type(self):
        data = {"agents": {"bad": {"type": "telepathy"}}}
        errors = validate_config(data)
        assert any("unknown type" in e for e in errors)

    def test_unknown_agent_reference(self):
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "bad": {
                    "steps": [{"name": "s1", "agent": "ghost"}],
                }
            },
        }
        errors = validate_config(data)
        assert any("unknown agent 'ghost'" in e for e in errors)

    def test_unknown_dependency(self):
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "bad": {
                    "steps": [
                        {"name": "s1", "agent": "echo", "depends_on": ["ghost"]},
                    ]
                }
            },
        }
        errors = validate_config(data)
        assert any("unknown step 'ghost'" in e for e in errors)

    def test_circular_dependency(self):
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "loop": {
                    "steps": [
                        {"name": "a", "agent": "echo", "depends_on": ["b"]},
                        {"name": "b", "agent": "echo", "depends_on": ["a"]},
                    ]
                }
            },
        }
        errors = validate_config(data)
        assert any("circular" in e for e in errors)

    def test_self_dependency(self):
        data = {
            "agents": {"echo": {"type": "echo"}},
            "pipelines": {
                "loop": {
                    "steps": [
                        {"name": "a", "agent": "echo", "depends_on": ["a"]},
                    ]
                }
            },
        }
        errors = validate_config(data)
        assert any("circular" in e for e in errors)

    def test_duplicate_step_names(self):
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

    def test_step_missing_agent(self):
        data = {
            "pipelines": {
                "bad": {
                    "steps": [{"name": "step1"}]
                }
            }
        }
        errors = validate_config(data)
        assert any("missing 'agent'" in e for e in errors)

    def test_empty_pipeline(self):
        data = {"pipelines": {"empty": {"steps": []}}}
        errors = validate_config(data)
        assert any("no steps" in e for e in errors)

    def test_depends_on_not_list(self):
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


class TestResolveEnvVars:
    def test_resolves_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "secret123")
        data = {"agents": {"bot": {"api_key": "${TEST_KEY}"}}}
        result = resolve_env_vars(data)
        assert result["agents"]["bot"]["api_key"] == "secret123"

    def test_raises_on_missing_env_when_strict(self):
        data = {"key": "${NONEXISTENT_VAR_XYZ}"}
        with pytest.raises(ConfigError, match="not set"):
            resolve_env_vars(data, strict=True)

    def test_empty_on_missing_env_when_not_strict(self):
        data = {"key": "${NONEXISTENT_VAR_XYZ}"}
        result = resolve_env_vars(data, strict=False)
        assert result["key"] == ""

    def test_passes_through_normal_strings(self):
        data = {"name": "hello"}
        assert resolve_env_vars(data) == data

    def test_nested_resolution(self, monkeypatch):
        monkeypatch.setenv("MY_URL", "http://localhost:8080")
        data = {"agents": {"a": {"base_url": "${MY_URL}"}}}
        result = resolve_env_vars(data)
        assert result["agents"]["a"]["base_url"] == "http://localhost:8080"

    def test_default_value_when_env_not_set(self):
        data = {"project": "${NONEXISTENT_PROJECT:my-default}"}
        result = resolve_env_vars(data)
        assert result["project"] == "my-default"

    def test_default_value_overridden_by_env(self, monkeypatch):
        monkeypatch.setenv("MY_PROJECT", "from-env")
        data = {"project": "${MY_PROJECT:fallback}"}
        result = resolve_env_vars(data)
        assert result["project"] == "from-env"

    def test_default_value_with_url(self):
        data = {"agents": {"a": {"base_url": "${MISSING_URL:https://api.openai.com/v1}"}}}
        result = resolve_env_vars(data)
        assert result["agents"]["a"]["base_url"] == "https://api.openai.com/v1"
