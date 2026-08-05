# AgentReady

AgentReady is a local-first toolkit for coordinating and verifying software work performed by people and AI-assisted
development tools. It helps a team maintain an auditable workflow without requiring a hosted service.

AgentReady provides:

- task claims, path-conflict checks, reviews, handoffs, and worktree support;
- repository activity capture with local redaction and summaries;
- workflow-lane and memory-use receipts;
- local CI, security, publication, packaging, and release-readiness checks;
- deterministic utilities for common engineering calculations.
- an autonomous, configuration-driven memory-to-graph pipeline with a durable local queue and watchdog.
- a fail-closed Claude/Codex session re-entry gate for harness updates and context resets.

The re-entry gate can hold a frontier agent read-only until it reconciles
urgent instructions, one active task, dirty state, source authority, and a
short-lived session receipt. See [Frontier-agent session re-entry](docs/SESSION_REENTRY.md).

Repository bootstrap also installs a vendor-neutral
[factory operating prompt](docs/AGENT_FACTORY_PROMPT.md), so agents receive a
coherent lifecycle contract rather than an unconnected list of commands.

The installed runtime does not require a hosted service. Initial installation may contact Python package indexes
through uv when required build components are not already cached. Optional local-model summarization is networked
only when the operator explicitly enables `factory-capture summarize --ollama`.

## Legal and safety notice

AgentReady is provided without promises or guarantees. Before downloading, installing, or using it, review the
[User Agreement](USER_AGREEMENT.md), [Disclaimer](DISCLAIMER.md), [Privacy Notice](PRIVACY.md),
[Security Policy](SECURITY.md), and [Apache License 2.0](LICENSE). You are responsible for deciding whether the
software is appropriate for your environment, protecting your systems and data, reviewing automated output, and
complying with applicable law and third-party terms.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Git
- [uv](https://docs.astral.sh/uv/)

See the [complete prerequisite and third-party download list](docs/PREREQUISITES.md) before installing companion
memory, graph, local-model, or container tools.

## Install for regular use

Obtain AgentReady from its official release source. Before running any included script, compare the downloaded
archive's SHA-256 with the checksum published alongside that release and inspect its source manifest:

```powershell
Get-FileHash .\AgentReady-<version>.zip -Algorithm SHA256
```

Clone or extract the verified repository, open PowerShell in its root directory, and preview the installation:

```powershell
python .\install-agentready.py --dry-run
```

Install interactively:

```powershell
python .\install-agentready.py
agentready --help
```

The installer uses `uv tool install`, verifies the installed `agentready`, `agent-deploy`, `agent-prerequisites`,
`agent-bootstrap-repo`, `agent-coordination`, and `factory-capture` commands, and can optionally bootstrap an existing
target repository:

```powershell
python .\install-agentready.py --target-repo "C:\path\to\your-repository"
```

See [Windows installation](docs/INSTALL_WINDOWS.md) for path configuration and
[the user manual](docs/USER_MANUAL.md) for human and autonomous-agent workflows.

For local memory corpora, see the [autonomous memory pipeline](docs/autonomous-memory-pipeline.md). The public
distribution supplies the generic queue, watcher, scheduler, and health contract; it does not include private data,
model endpoints, or operating configuration.

### Deterministic agent installation

An LLM or other noninteractive automation must request machine-readable output and explicit confirmation:

```powershell
python .\install-agentready.py --mode agent --yes --json --dry-run
python .\install-agentready.py --mode agent --yes --json
```

The caller must check both the process exit code and the JSON `overall` value. A dry run succeeds with `PLANNED`; an
actual installation succeeds with `PASS`. Agent mode refuses to run unless both `--yes` and `--json` are present.
An LLM can obtain the complete machine-readable prerequisite catalog first:

```powershell
python .\install-agentready.py --mode agent --yes --json --prerequisites-only --prerequisite-profile full
```

## Install for development

```powershell
uv sync --frozen --group dev
uv run agentready --help
```

The optional toolbox adds data-frame, graph, symbolic-math, and constraint-solver dependencies:

```powershell
uv sync --frozen --group dev --extra toolbox
```

## Quick start

If the installer did not bootstrap a repository, initialize its AgentReady guidance:

```powershell
agent-bootstrap-repo --repo "C:\path\to\your-repository"
```

Initialize its coordination state and inspect current tasks:

```powershell
agent-coordination coordination-init --repo "C:\path\to\your-repository"
agent-coordination task-status --repo "C:\path\to\your-repository"
```

To capture activity, open PowerShell in the repository being worked on:

```powershell
factory-capture init
factory-capture status
factory-capture hooks install
```

Installing hooks changes only that repository's local Git hooks. Use `factory-capture hooks uninstall` before removing
AgentReady.

## Verify a source checkout

```powershell
uv run pytest
uv run ruff check src tests
uv run pyright src
uv build
```

The publication and release commands are intended for maintainers:

```powershell
agent-tool-router --profile release --mode run --include-heavy --repo .
agent-tool-router --profile release --mode audit --repo .
agent-release-scorecard --repo .
```

## Data boundary

AgentReady creates state only after an initialization or operational command is run. Coordination records are stored
under the current user's AgentReady home, while capture records default to an ignored `.factory_capture` directory in
the repository being observed. A fresh installation starts with no runtime records and no database files.

See the guides for [Windows installation](docs/INSTALL_WINDOWS.md),
[complete operation](docs/USER_MANUAL.md),
[prerequisites and third-party downloads](docs/PREREQUISITES.md),
[configuration](docs/CONFIGURATION.md), [database handling](docs/DATABASES.md),
[security and privacy](docs/SECURITY_PRIVACY.md), [retention and backup](docs/DATA_RETENTION_AND_EXPORT.md),
and [uninstallation](docs/UNINSTALL.md).

## Ownership and license

AgentReady is owned and maintained by SagitariusAI. Project owner: Alex Burca.

Copyright 2026 SagitariusAI. Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
