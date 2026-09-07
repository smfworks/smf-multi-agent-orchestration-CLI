# Contributing to SMF Forge

Thank you for your interest in contributing to SMF Forge! This document covers the development workflow, coding standards, and submission process.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/smfworks/smf-multi-agent-orchestration-CLI.git
cd smf-multi-agent-orchestration-CLI

# Create a virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

## Project Structure

```
src/smf_forge/
├── __init__.py          # Package metadata (__version__)
├── cli.py               # Click-based CLI commands
├── config/__init__.py   # Config loading, validation, env var resolution
├── engine/__init__.py   # Pipeline engine (DAG execution, topological sort)
├── agents/__init__.py   # Agent base class and built-in agent types
└── templates/forge.yaml # Default config template for `smf-forge init`

tests/
├── test_config.py       # Config loading and validation tests
├── test_engine.py       # Pipeline engine and agent builder tests
├── test_agents.py       # Agent type tests (echo, shell, transform, http, hermes)
└── test_cli.py          # CLI command tests (Click test runner)
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=smf_forge --cov-report=term-missing

# Run a specific test file
pytest tests/test_config.py

# Run with verbose output
pytest -v
```

The project targets >80% test coverage. Current coverage: 93%.

## Code Quality

### Linting

```bash
ruff check src/ tests/
```

Ruff is configured in `pyproject.toml` with the following rule sets:
- `E` — pycodestyle errors
- `F` — pyflakes
- `W` — pycodestyle warnings
- `I` — isort
- `UP` — pyupgrade
- `B` — flake8-bugbear
- `SIM` — flake8-simplify

### Type Checking

```bash
mypy src/
```

All new code should include proper type hints. The project uses `from __future__ import annotations` for forward reference support.

### Line Length

Maximum line length is 100 characters (configured in `pyproject.toml`).

## Coding Standards

1. **Type hints**: All public functions and methods must have type hints.
2. **Docstrings**: All public functions, classes, and modules must have docstrings (Google or Sphinx style).
3. **Error handling**: Use specific exception types. Agents should return `{"error": "..."}` dicts rather than raising exceptions, so the pipeline engine can handle failures gracefully.
4. **Logging**: Use `logging.getLogger(__name__)` for module-level loggers.
5. **Backward compatibility**: Do not break the existing public API. The `smf-forge` CLI commands, `forge.yaml` format, and `BaseAgent` interface must remain stable.

## Adding a New Agent Type

1. Create a new class inheriting from `BaseAgent` in `src/smf_forge/agents/__init__.py`.
2. Implement the `async def run(self, prompt: str, context: dict | None = None) -> Any` method.
3. Register the class in the `AGENT_TYPES` dict.
4. Add the type name to `KNOWN_AGENT_TYPES` in `src/smf_forge/config/__init__.py`.
5. Write tests in `tests/test_agents.py`.
6. Update the README agent types table.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new agent type for Slack notifications
fix: resolve crash when pipeline has no steps
docs: update README with new agent type
test: add tests for env var default value syntax
refactor: simplify topological sort implementation
ci: update GitHub Actions workflow
chore: bump version to 1.1.0
```

## Pull Request Process

1. Create a feature branch: `git checkout -b feat/my-feature`
2. Make your changes and commit with conventional commit messages.
3. Ensure all tests pass: `pytest`
4. Ensure linting passes: `ruff check src/ tests/`
5. Ensure type checking passes: `mypy src/`
6. Push your branch and open a pull request.
7. Describe what you changed and why. Link any related issues.

## CI/CD

`.github/workflows/ci.yml` runs linting and tests on every push and pull request (Python 3.10–3.13). All checks must pass before merging.

Some org PATs lack the `workflow` scope, so `git push` of `.github/workflows/*` is rejected. When that happens, do **not** force-push the workflow with the limited PAT. Publish or update CI via:

1. The GitHub web editor on the target branch (or Actions → New workflow), or
2. A PAT / GitHub App token that includes the `workflow` scope.

The workflow file in this repo is the source of truth. The current GitHub PAT
includes `workflow` scope, so CI may be pushed from git. If a future PAT lacks
that scope, publish the workflow via the GitHub web editor instead of stripping
it from the tree.

Do not weaken shell-agent isolation to make a test pass. The step prompt is never a command.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.