# Architecture

SMF Forge is a local CLI. It is not a hosted orchestrator.

```
forge.yaml  →  config.load / validate / resolve_env
                    ↓
              agents.build_registry
                    ↓
              engine.PipelineEngine
                    ↓
         layer 1 (parallel) → layer 2 → …
                    ↓
              PipelineResult (steps, timings)
```

## Modules

| Module | Responsibility |
|--------|----------------|
| `smf_forge.config` | Find `forge.yaml`, parse YAML, validate graph, resolve `${VAR}` |
| `smf_forge.agents` | Agent types, SSRF URL checks, registry |
| `smf_forge.engine` | Topological layers, sandboxed Jinja prompts, fail-fast / continue |
| `smf_forge.cli` | Click commands |

## Execution model

1. Validate names, types, agent refs, `depends_on`, and cycles before run.
2. Kahn layers: a layer is the set of steps with no remaining deps.
3. Steps in a layer run concurrently via `asyncio.gather`.
4. Each step output is stored on the context under the step name.
5. Agent `{error: ...}` dicts without a `response` key are failures. Shell nonzero exit is an error unless `allow_nonzero`.
6. Prompt template syntax/security errors fail the step. They do not fall back to raw text.

## Trust boundary

- Config and templates are local operator input.
- `shell` agents execute only `options.command` via `create_subprocess_exec`. The step prompt is never the command and is not exported as an env var.
- Nonzero exit fails the step unless `options.allow_nonzero` is true. Timeouts kill the process group.
- `shell: true` is rejected.
- HTTP calls use `trust_env=False` and `follow_redirects=False`, and reject private/internal destinations. Hermes may target localhost.
- Secrets belong in env vars, not in the repo.
