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

## Conventions

- Python 3.10+.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`).
- Do not weaken shell-agent isolation to make a test pass.
- Bump `src/smf_forge/__init__.py` and `pyproject.toml` together.

## Pull requests

Open against `main` from a feature branch. Include the test command you ran and its result.
