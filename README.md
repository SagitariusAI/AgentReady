# AgentReady

AgentReady is a local-first toolkit for coordinating and verifying software work performed by people and AI-assisted
development tools. It helps a team maintain an auditable workflow without requiring a hosted service.

AgentReady provides:

- task claims, path-conflict checks, reviews, handoffs, and worktree support;
- repository activity capture with local redaction and summaries;
- workflow-lane and memory-use receipts;
- local CI, security, publication, packaging, and release-readiness checks;
- deterministic utilities for common engineering calculations.

The public distribution is intentionally clean. It contains source code, schemas, tests, and documentation only. It
does not include captured activity, populated databases, datasets, credentials, network configuration, model files,
or another user's runtime history.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Git
- [uv](https://docs.astral.sh/uv/)

## Install for regular use

Clone or extract the repository, open PowerShell in its root directory, and install the command-line tools:

```powershell
uv tool install .
agentready --help
```

To replace an older local installation with the current checkout:

```powershell
uv tool install --force .
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

Initialize AgentReady guidance in a repository:

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
uv run agent-publication-guard --repo .
uv run agent-security-scan --repo .
uv run agent-release-readiness --repo .
uv run agent-release-scorecard --repo .
```

## Data boundary

AgentReady creates state only after an initialization or operational command is run. Coordination records are stored
under the current user's AgentReady home, while capture records default to an ignored `.factory_capture` directory in
the repository being observed. A fresh installation starts with no runtime records and no database files.

See the guides for [Windows installation](docs/INSTALL_WINDOWS.md),
[configuration](docs/CONFIGURATION.md), [database handling](docs/DATABASES.md),
[security and privacy](docs/SECURITY_PRIVACY.md), [retention and backup](docs/DATA_RETENTION_AND_EXPORT.md),
and [uninstallation](docs/UNINSTALL.md).

## Ownership and license

AgentReady is owned and maintained by Sagittarius AI.

Copyright 2026 Sagittarius AI. Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
