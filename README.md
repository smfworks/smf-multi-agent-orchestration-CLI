# SMF Forge

**Lightweight multi-agent orchestration CLI** — define, compose, and run AI agent pipelines from the terminal.

SMF Forge lets you declare agents and pipelines in a simple `forge.yaml` file, then execute them with dependency resolution, parallel execution, and context passing between steps. It's designed for developers who want to orchestrate multiple AI agents (or shell commands, transforms, and HTTP endpoints) without writing glue code.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          smf-forge CLI                              │
│                                                                     │
│  ┌──────────┐   ┌───────────┐   ┌───────────┐   ┌──────────────┐  │
│  │  init    │   │   run     │   │  agents   │   │  pipelines   │  │
│  │ command  │   │  command  │   │  command  │   │   command    │  │
│  └────┬─────┘   └─────┬─────┘   └─────┬─────┘   └──────┬───────┘  │
│       │               │               │                │           │
│       ▼               ▼               ▼                ▼           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Config Module                          │   │
│  │  find_config → load_config → resolve_env_vars → validate   │   │
│  └─────────────────────────────┬───────────────────────────────┘   │
│                                │                                    │
│                                ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Pipeline Engine                          │   │
│  │                                                             │   │
│  │  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐    │   │
│  │  │ Topological │───▶│  Layer-based  │───▶│  Context    │    │   │
│  │  │    Sort     │    │  Execution   │    │  Passing    │    │   │
│  │  └─────────────┘    └──────────────┘    └──────────────┘    │   │
│  └─────────────────────────────┬───────────────────────────────┘   │
│                                │                                    │
│                                ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Agent Registry                          │   │
│  │                                                             │   │
│  │  ┌──────┐ ┌────────┐ ┌───────┐ ┌──────────┐ ┌────────┐    │   │
│  │  │ Echo │ │  HTTP  │ │ Shell │ │ Transform│ │ Hermes │    │   │
│  │  └──────┘ └────────┘ └───────┘ └──────────┘ └────────┘    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Install

This package is **not published to PyPI yet**. Install from source.

```bash
git clone https://github.com/smfworks/smf-multi-agent-orchestration-CLI.git
cd smf-multi-agent-orchestration-CLI
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
smf-forge --version
```

Requires Python 3.10+.

## Quick Start

No API keys required.

```bash
smf-forge init --name my-project
smf-forge validate
smf-forge agents
smf-forge run demo --prompt "Explain quantum computing"
```

`init` writes an echo-only `demo` pipeline so the first run works offline.

### 2. Define agents and pipelines

Edit `forge.yaml`:

```yaml
agents:
  researcher:
    type: http
    model: gpt-4
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    system_prompt: "You are a research assistant."

  summarizer:
    type: http
    model: gpt-4
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    system_prompt: "Summarize the following text concisely."

pipelines:
  research-summarize:
    name: research-summarize
    steps:
      - name: research
        agent: researcher
        prompt: "{{ prompt }}"

      - name: summarize
        agent: summarizer
        prompt: "Summarize this research:\n{{ research.response }}"
        depends_on:
          - research
```

### 3. Run a pipeline

```bash
smf-forge run research-summarize --prompt "Explain quantum computing"
```

## Agent Types

| Type | Description | Key Config |
|------|-------------|------------|
| `echo` | Returns the input — useful for testing pipelines | — |
| `http` | Calls an OpenAI-compatible chat completions endpoint | `model`, `base_url`, `api_key` |
| `shell` | Runs a **configured** argv command (never the prompt, never in env) | `options.command` |
| `transform` | Applies a Jinja2 template to context data | `options.template` |
| `hermes` | Calls a Hermes/OpenClaw-compatible agent endpoint | `options.endpoint`, `options.agent_name` |

## CLI Commands

```
smf-forge init              Create a forge.yaml template
smf-forge run PIPELINE      Execute a named pipeline
smf-forge agents            List configured agents
smf-forge pipelines         List configured pipelines
smf-forge validate          Validate forge.yaml without running
smf-forge --version         Show version
smf-forge --help            Show help
```

### `smf-forge run` options

| Option | Description | Default |
|--------|-------------|---------|
| `--config PATH` | Path to forge.yaml | Auto-discovered |
| `--prompt TEXT` | Input prompt for the pipeline | Empty |
| `--fail-fast` / `--continue-on-error` | Stop on first failure or continue | `--fail-fast` |
| `--verbose` / `-v` | Show step outputs | Off |
| `--timeout SECONDS` | Overall pipeline timeout | None |

## YAML Config Reference

### Agent Config

```yaml
agents:
  agent-name:
    type: echo | http | shell | transform | hermes  # required
    model: gpt-4                    # for http/hermes types
    provider: openai                 # informational label
    base_url: https://...            # for http/hermes types
    api_key: ${API_KEY}             # resolved from env
    system_prompt: "..."
    temperature: 0.7
    max_tokens: 4096
    options:                        # type-specific options
      command: ["ls", "-la", "/tmp"]  # for shell type (argv preferred)
      template: "{{ data }}"        # for transform type
      endpoint: http://localhost:8642  # for hermes type
      agent_name: default           # for hermes type
      timeout: 120                  # for hermes/shell types
      allow_nonzero: false          # for shell type
```

### Pipeline Config

```yaml
pipelines:
  pipeline-name:
    name: pipeline-name             # optional (defaults to key)
    steps:
      - name: step1                 # required, must be unique within pipeline
        agent: agent-name           # required, must reference a defined agent
        prompt: "Your prompt here"  # Jinja2 template — can reference context vars
        depends_on: []              # list of step names this depends on
```

### Environment Variable Resolution

SMF Forge resolves `${...}` expressions in string values throughout the config:

| Syntax | Behavior |
|--------|----------|
| `${VAR}` | Resolves from environment; error if not set |
| `${VAR:default}` | Resolves from environment; uses `default` if not set |

Only values that are **entirely** a `${...}` expression are resolved. Embedded references like `"prefix-${VAR}"` are left as-is.

## Features

- **DAG-based execution** — steps run in dependency order; independent steps run in parallel
- **Context passing** — step outputs are available as template variables in downstream steps
- **Jinja2 templating** — render prompts dynamically from pipeline context
- **Environment variable resolution** — use `${ENV_VAR}` or `${ENV_VAR:default}` in config for secrets
- **Fail-fast or continue** — choose how the pipeline handles errors
- **Built-in agent types** — echo, HTTP (OpenAI-compatible), shell, transform, Hermes
- **Extensible** — subclass `BaseAgent` to create custom agent types
- **Config validation** — `smf-forge validate` checks structural integrity before running

## Examples

### Shell command pipeline

```yaml
agents:
  lister:
    type: shell
    options:
      command: ["ls", "-la", "/tmp"]

  formatter:
    type: transform
    options:
      template: "Files found:\n{{ lister.stdout }}"

pipelines:
  list-and-format:
    steps:
      - name: lister
        agent: lister
        prompt: ""

      - name: formatter
        agent: formatter
        prompt: ""
        depends_on: [lister]
```

```bash
smf-forge run list-and-format
```

### Parallel research

```yaml
agents:
  researcher-a:
    type: http
    model: gpt-4
    api_key: ${OPENAI_API_KEY}
    system_prompt: "Research topic A"

  researcher-b:
    type: http
    model: gpt-4
    api_key: ${OPENAI_API_KEY}
    system_prompt: "Research topic B"

  combiner:
    type: transform
    options:
      template: "A: {{ researcher_a.response }}\nB: {{ researcher_b.response }}"

pipelines:
  parallel-research:
    steps:
      - name: researcher_a
        agent: researcher-a
        prompt: "{{ prompt }}"

      - name: researcher_b
        agent: researcher-b
        prompt: "{{ prompt }}"

      - name: combiner
        agent: combiner
        prompt: ""
        depends_on: [researcher_a, researcher_b]
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=smf_forge --cov-report=term-missing

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## License

MIT © SMF Works