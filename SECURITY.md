# Security Policy

## Supported versions

The `main` branch and the latest tagged release.

## What this tool is

A local developer CLI. It reads `forge.yaml` from disk and can call HTTP APIs or run configured subprocesses. Treat the config file as code.

## Rules of use

1. **Do not commit API keys.** Use `${VAR}` or `${VAR:}` in `forge.yaml`.
2. **Shell agents never execute the prompt.** Set `options.command` to an argv list (preferred) or a string without `$`, backticks, or `$(`. The prompt is not exported to the child environment.
3. **`shell: true` is not supported.** There is no shell escape hatch.
4. **Nonzero process exit fails the step** unless `options.allow_nonzero: true`.
5. **Timeouts kill the child process group** (`start_new_session` + `killpg`). This is not a sandbox.
6. **HTTP agents block private/internal destinations** (SSRF). Hermes agents may target localhost. URLs must be `http`/`https` without embedded credentials.
7. **Hermes and HTTP agents send prompts off-box.** Assume the remote can see the rendered prompt and prior step outputs you template in.

## Reporting

Email `dev@smfworks.com` or open a private security advisory on the GitHub repository. Do not file public issues for exploitable command-injection or secret-leak bugs.
