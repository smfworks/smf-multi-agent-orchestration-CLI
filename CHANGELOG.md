# Changelog

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
