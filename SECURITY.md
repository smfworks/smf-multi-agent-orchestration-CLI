# Security Policy

## Supported versions

The `main` branch and the latest tagged release.

## What this tool is

A local developer CLI. It reads `forge.yaml` from disk and can call HTTP APIs or run configured subprocesses. Treat the config file as code.

## Rules of use

1. **Do not commit API keys.** Use `${VAR}` or `${VAR:}` in `forge.yaml`.
2. **Shell agents never execute the prompt.** Set `options.command` to an argv list. `shell: true` is opt-in and must be a static trusted string.
3. **Do not interpolate untrusted context into `shell: true` commands.**
4. **Hermes and HTTP agents send prompts off-box.** Assume the remote can see the rendered prompt and prior step outputs you template in.
5. **Timeouts kill the child process.** Do not rely on this as a sandbox. There is no seccomp, no container, no network policy.

## Reporting

Email `dev@smfworks.com` or open a private security advisory on the GitHub repository. Do not file public issues for exploitable command-injection or secret-leak bugs.
