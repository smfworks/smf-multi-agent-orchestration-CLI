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
              PipelineResult (run_id, steps, timings)
```

## Modules

| Module | Responsibility |
|--------|----------------|
| `smf_forge.config` | Find `forge.yaml`, parse YAML, validate graph, resolve `${VAR}` |
| `smf_forge.agents` | Agent types and registry |
| `smf_forge.engine` | Topological layers, Jinja prompts, fail-fast / continue |
| `smf_forge.cli` | Click commands |

## Execution model

1. Validate names, types, agent refs, and `depends_on` before run.
2. Kahn layers: a layer is the set of steps with no remaining deps.
3. Steps in a layer run concurrently via `asyncio.gather`.
4. Each step output is stored on the context under the step name.
5. Agent `{error: ...}` dicts without a `response` key are failures.
6. Prompt template errors fail the step. They do not fall back to raw text.

## Trust boundary

- Config and templates are local operator input.
- `shell` agents execute only `options.command`. The step prompt is never the command. It is exported as `FORGE_PROMPT` for commands that opt in to reading it.
- `shell: true` is an explicit escape hatch for a trusted static string.
- HTTP and Hermes calls send the rendered prompt to the configured endpoint. Secrets belong in env vars, not in the repo.
