# Autonomous memory pipeline

AgentReady includes a local, writer-agnostic pipeline runner for memory-to-graph workflows. It detects declared source
changes by content hash, persists work in SQLite WAL state, serializes stage execution with a process lock, retries
failed work indefinitely with bounded exponential backoff, and retains machine-readable convergence health.

The distribution includes no memory corpus, graph, model, endpoint, credential, or private operating configuration.
You provide the stage commands and keep configuration containing sensitive paths outside a public repository.

## Configure

Copy `examples/memory-pipeline.config.json` to an operator-controlled location. `root` may be absolute or relative to
the configuration file. Source globs must remain inside that root. Each stage is an argv array executed directly with
`shell=False`; the supported exact-token substitutions are `{python}`, `{root}`, `{state_dir}`, and `{config}`.

Put extraction, graph generation, and completeness validation in separate ordered stages. A stage is successful only
when it exits zero. The final validator should fail closed when any source is stale, absent, or only partially indexed.

Validate and run one reconciliation:

```powershell
agent-memory-pipeline --config .\memory-pipeline.json validate
agent-memory-pipeline --config .\memory-pipeline.json once --reconcile
agent-memory-pipeline --config .\memory-pipeline.json status
```

State defaults to the current user's local application-data directory, outside the source checkout. The health file
reports `CONVERGED`, `CATCHING_UP`, `DEGRADED`, `IDLE`, or `STARTING` and never treats a failed stage as completion.

## Run independently

On Windows, preview and then register a persistent watcher plus a 15-minute reconciliation watchdog:

```powershell
.\scripts\register-memory-pipeline.ps1 -Config .\memory-pipeline.json -WhatIf
.\scripts\register-memory-pipeline.ps1 -Config .\memory-pipeline.json
```

The watcher is the correctness path. Editor or agent hooks are optional accelerators. The included Claude hook only
enqueues a scan when `AGENTREADY_MEMORY_PIPELINE_CONFIG` is set; it never runs graph stages itself. Codex, Claude,
other agents, editors, and direct filesystem writers therefore share the same durable convergence mechanism.

## Source-control boundary

Runtime convergence is automatic; source-control publication is deliberately not. The pipeline does not stage,
commit, push, upload, or mirror source data or generated artifacts. Apply your repository's gates and privacy policy
before explicitly promoting any derived output.
