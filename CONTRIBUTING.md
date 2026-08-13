# Contributing

## Setup

```bash
git clone https://github.com/smfworks/smf-multi-agent-orchestration-CLI.git
cd smf-multi-agent-orchestration-CLI
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

A change is ready for review when:

```bash
pytest
ruff check src tests
```

and a new engineer can still do this with no API keys:

```bash
smf-forge init --directory /tmp/forge-smoke
smf-forge run demo --config /tmp/forge-smoke/forge.yaml --prompt hi
```

## CI workflow (operator path)

`.github/workflows/ci.yml` lives in the tree (pytest + ruff on Python 3.10–3.12). Some org PATs lack the `workflow` scope, so `git push` of `.github/workflows/*` is rejected with:

`refusing to allow a Personal Access Token to create or update the .github/workflows/... without workflow scope`

To publish or update CI when that happens, do **not** force-push the workflow with the limited PAT. Use one of:

1. GitHub web editor: open `.github/workflows/ci.yml` on the target branch and commit there (or paste the file via Actions → New workflow).
2. A PAT or GitHub App token that includes the `workflow` scope.
3. A human operator with write + workflow permission.

The workflow file in this repo is the source of truth even when it is not yet on `main`.

## Conventions

- Python 3.10+.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`).
- Do not weaken shell-agent isolation to make a test pass.
- Bump `src/smf_forge/__init__.py` and `pyproject.toml` together.

## Pull requests

Open against `main` from a feature branch. Include the test command you ran and its result.
