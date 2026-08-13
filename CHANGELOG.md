# Changelog

## 0.2.0 — 2026-08-13

Production-hardening pass.

- Default `init` template is echo-only. First run needs no API keys.
- README no longer claims a PyPI package that does not exist.
- Validator rejects unknown agent types, unknown agent refs, unknown `depends_on`, and cycles.
- Env resolution can be non-strict so listing agents does not require unused secrets.
- Missing or invalid YAML is a `ConfigError`, not a traceback.
- Shell agent executes `options.command` only; prompt is never the command. Nonzero exit fails the step. Timeout kills the process group.
- Prompt template errors fail the step instead of running raw text.
- `smf-forge run --json` emits `run_id` and per-step results.
- Tests cover CLI smoke, HTTP, shell, transform, Hermes connect-error, validator, and wrap-safe validate output.
- Added ARCHITECTURE, SECURITY, CONTRIBUTING.
- CI workflow restored in-tree; operator path for workflow-scope PATs documented in CONTRIBUTING.

## 0.1.0 — 2026-06-12

Initial CLI: echo, http, shell, transform, hermes agents and DAG engine.
