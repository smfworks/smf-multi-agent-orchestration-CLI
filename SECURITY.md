# Security Policy

`smf-forge` runs **local pipelines**. Treat `forge.yaml` as code.

## Shell agent

`type: shell` executes `options.command` as an argv list
(`asyncio.create_subprocess_exec`). A string command is `shlex.split`;
a YAML list is used as-is.

- The step **prompt is never used as a command**.
- If `options.command` is missing, the agent fails closed.
- Do not interpolate untrusted step output into `options.command`.

## HTTP agent

`api_key` is sent as a Bearer token to `base_url`. Use `${ENV_VAR}` in
config. Never commit live keys.

## Templates

Transform and pipeline prompts use a **sandboxed** Jinja2 environment.

## Reporting

Email security@smfworks.com or open a private GitHub advisory on
https://github.com/smfworks/smf-multi-agent-orchestration-CLI
