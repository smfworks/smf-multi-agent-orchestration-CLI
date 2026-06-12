# SMF Forge

**Lightweight multi-agent orchestration CLI** — define, compose, and run AI agent pipelines from the terminal.

SMF Forge lets you declare agents and pipelines in a simple `forge.yaml` file, then execute them with dependency resolution, parallel execution, and context passing between steps.

## Install

```bash
pip install smf-forge
```

Or from source:

```bash
git clone https://github.com/smfworks/smf-multi-agent-orchestration-CLI.git
cd smf-multi-agent-orchestration-CLI
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize a project

```bash
smf-forge init --name my-project
```

This creates a `forge.yaml` template in the current directory.

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

| Type | Description |
|------|-------------|
| `echo` | Returns the input — useful for testing pipelines |
| `http` | Calls an OpenAI-compatible chat completions endpoint |
| `shell` | Runs a shell command and returns stdout |
| `transform` | Applies a Jinja2 template to context data |

## CLI Commands

```
smf-forge init             Create a forge.yaml template
smf-forge run PIPELINE     Execute a named pipeline
smf-forge agents           List configured agents
smf-forge pipelines        List configured pipelines
smf-forge validate         Validate forge.yaml without running
```

## Features

- **DAG-based execution** — steps run in dependency order; independent steps run in parallel
- **Context passing** — step outputs are available as template variables in downstream steps
- **Jinja2 templating** — render prompts dynamically from pipeline context
- **Environment variable resolution** — use `${ENV_VAR}` in config for secrets
- **Fail-fast or continue** — choose how the pipeline handles errors
- **Built-in agent types** — echo, HTTP (OpenAI-compatible), shell, transform
- **Extensible** — subclass `BaseAgent` to create custom agent types

## Configuration Reference

### Agent Config

```yaml
agents:
  agent-name:
    type: echo | http | shell | transform
    model: gpt-4                    # for http type
    base_url: https://...           # for http type
    api_key: ${API_KEY}             # resolved from env
    system_prompt: "..."
    temperature: 0.7
    max_tokens: 4096
    options:                        # type-specific options
      command: "echo hello"         # for shell type
      template: "{{ data }}"        # for transform type
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

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT © SMF Works