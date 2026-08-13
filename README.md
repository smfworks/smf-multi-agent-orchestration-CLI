# SMF Forge

**Lightweight multi-agent orchestration CLI** — define, compose, and run AI agent pipelines from the terminal.

SMF Forge lets you declare agents and pipelines in a `forge.yaml` file, then execute them with dependency resolution, parallel execution, and context passing between steps.

This package is **not published to PyPI yet**. Install from source.

## Install

```bash
git clone https://github.com/smfworks/smf-multi-agent-orchestration-CLI.git
cd smf-multi-agent-orchestration-CLI
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Confirm the CLI:

```bash
smf-forge --version
pytest
```

## Quick Start

No API keys required.

```bash
smf-forge init --name my-project
smf-forge validate
smf-forge agents
smf-forge run demo --prompt "Explain quantum computing"
```

`init` writes an echo-only `demo` pipeline so the first run works offline.

## Agent Types

| Type | Description |
|------|-------------|
| `echo` | Returns the input — useful for testing pipelines |
| `http` | Calls an OpenAI-compatible chat completions endpoint |
| `shell` | Runs a **configured** command (never the prompt). Argv by default |
| `transform` | Applies a Jinja2 template to context data |
| `hermes` | Calls a local Hermes agent HTTP endpoint |

## CLI Commands

```
smf-forge init             Create a forge.yaml template
smf-forge run PIPELINE     Execute a named pipeline
smf-forge agents           List configured agents
smf-forge pipelines        List configured pipelines
smf-forge validate         Validate forge.yaml without running
```

`smf-forge run` flags:

- `--prompt TEXT` — available to templates as `{{ prompt }}`
- `--fail-fast` / `--continue-on-error`
- `--verbose` / `-v` — show step outputs
- `--json` — machine-readable result including `run_id`

## Features

- **DAG-based execution** — steps run in dependency order; independent steps run in parallel
- **Context passing** — step outputs are available as template variables in downstream steps
- **Jinja2 templating** — render prompts dynamically from pipeline context
- **Environment variable resolution** — `${ENV_VAR}` or `${ENV_VAR:default}`
- **Fail-fast or continue** — choose how the pipeline handles errors
- **Built-in agent types** — echo, HTTP, shell, transform, hermes
- **Extensible** — subclass `BaseAgent` to create custom agent types

## Configuration Reference

### Agent Config

```yaml
agents:
  agent-name:
    type: echo | http | shell | transform | hermes
    model: gpt-4o-mini              # for http type
    base_url: https://...           # for http / hermes
    api_key: ${API_KEY:}            # empty default = optional
    system_prompt: "..."
    temperature: 0.7
    max_tokens: 4096
    options:
      command: ["echo", "hello"]    # shell: argv (preferred)
      shell: false                  # set true only for trusted static strings
      timeout: 60
      template: "{{ data }}"        # transform
      agent_name: default           # hermes
      endpoint: http://localhost:8642
```

### Pipeline Config

```yaml
pipelines:
  pipeline-name:
    name: pipeline-name
    steps:
      - name: step1
        agent: agent-name
        prompt: "Your prompt here"
        depends_on: []              # list of step names this depends on
```

Echo agent output is `{echo, agent, context_keys}`. HTTP and Hermes output is `{response, ...}`. Downstream templates must use the field the upstream agent actually returns (`{{ step.echo }}` vs `{{ step.response }}`).

## HTTP / Hermes example

```yaml
agents:
  echo:
    type: echo
  reviewer:
    type: http
    model: gpt-4o-mini
    base_url: ${OPENAI_BASE_URL:https://api.openai.com/v1}
    api_key: ${OPENAI_API_KEY:}
    system_prompt: "You are a code reviewer."

pipelines:
  review:
    name: review
    steps:
      - name: echo_input
        agent: echo
        prompt: "{{ prompt }}"
      - name: review_output
        agent: reviewer
        prompt: "Review this output:\n{{ echo_input.echo }}"
        depends_on: [echo_input]
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [SECURITY.md](SECURITY.md).

## License

MIT © SMF Works
