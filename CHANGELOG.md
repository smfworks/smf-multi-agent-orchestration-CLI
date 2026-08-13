# Changelog

## 0.2.0 — 2026-08-13

Production-hardening pass.

- Default `init` template is echo-only. First run needs no API keys.
- README no longer claims a PyPI package that does not exist.
- Validator rejects unknown agent types, unknown agent refs, and unknown `depends_on`.
- Env resolution can be non-strict so listing agents does not require unused secrets.
- Shell agent executes `options.command` only; prompt is never the command. Timeout kills the child.
- Prompt template errors fail the step instead of running raw text.
- `smf-forge run --json` emits `run_id` and per-step results.
- Tests cover CLI smoke, HTTP, shell, transform, Hermes connect-error, and validator cases.
- Added ARCHITECTURE, SECURITY, CONTRIBUTING.

## 0.1.0 — 2026-06-12

Initial CLI: echo, http, shell, transform, hermes agents and DAG engine.
