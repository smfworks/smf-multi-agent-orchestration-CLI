# Changelog

## 0.2.0 — 2026-08-13

Production-hardening.

- Shell agent no longer executes the prompt; `options.command` is required
- Transform agent uses Jinja2 `SandboxedEnvironment`
- Pytest `pythonpath = ["src"]` so tests collect without a prior install
- GitHub Actions CI (pytest + ruff, Python 3.10–3.12)
- SECURITY.md; classifier moved to Beta

## 0.1.0

Initial public CLI: DAG engine, echo/http/shell/transform/hermes agents.
