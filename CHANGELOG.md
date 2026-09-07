# Changelog

## 1.0.2 — 2026-08-29

Production follow-up on the 1.0.1 / oppositional-analysis tree.

- Shell agent uses `create_subprocess_exec` only. `shell: true` is rejected.
- Command strings that contain `$`, backticks, or `$(` are rejected.
- The step prompt is never executed and is not exported as `FORGE_PROMPT`.
- Nonzero process exit fails the step unless `options.allow_nonzero`.
- Timeouts kill the child process group (`start_new_session` + `killpg`).
- Prompt and transform templates use sandboxed Jinja. Syntax/security errors fail the step instead of falling back to raw text.
- HTTP clients disable env proxy trust and redirects. URLs with embedded credentials are rejected. Literal private-IP SSRF errors are no longer swallowed.
- `smf-forge agents` / `pipelines` do not require unused secrets (`strict=False`).
- CI is tracked again (lint + mypy, tests on 3.10–3.13 with 80% coverage, wheel/sdist build).
- README, SECURITY, and ARCHITECTURE match runtime behavior.

## 1.0.1 — 2026-08-13

Security and onboarding follow-up on the 1.0.0 tree.

- README no longer claims a PyPI package that does not exist.
- Default `init` template is echo-only. First run needs no API keys.
- Shell agent executes `options.command` only; the prompt is never the command.
- Nonzero process exit fails the step unless `allow_nonzero`.
- Timeout kills the process group.
- Prompt template errors fail the step instead of running raw text.
- Listing agents does not require unused secrets (`strict=False` env resolve).
- Validate message is wrap-safe for CI.
- Documented CI operator path for PATs without `workflow` scope.

## 1.0.0 — 2026-08-13

Type hints, logging, expanded validation, tests, docs, and CI on Python 3.10–3.13.
