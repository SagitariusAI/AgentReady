# AgentReady

AgentReady is a local-first toolkit for governing software work performed by AI agents and people. It provides:

- collision-resistant task claims and handoffs;
- repository activity capture with automatic redaction;
- memory-use and workflow-lane receipts;
- local CI, security, boundary, and release checks;
- deterministic tooling for common engineering calculations.

This public repository is an intentionally clean distribution. It contains no operational databases, captured
activity, datasets, credentials, private network configuration, model state, or production history.

## Install

Install Python 3.11 or newer and [uv](https://docs.astral.sh/uv/), then run:

```powershell
uv sync --frozen --group dev
uv run agentready --help
```

The optional deterministic toolbox adds data, graph, symbolic-math, and solver dependencies:

```powershell
uv sync --frozen --group dev --extra toolbox
```

## Quick start

Initialize AgentReady metadata in another repository:

```powershell
uv run agent-bootstrap-repo C:\path\to\your-repository
```

Start and inspect governed coordination:

```powershell
uv run agent-coordination coordination-init --repo C:\path\to\your-repository
uv run agent-coordination task-status --repo C:\path\to\your-repository
```

Capture repository activity:

```powershell
uv run factory-capture --help
```

Run the public verification suite:

```powershell
uv run pytest
uv run ruff check src tests
uv build
```

See [installation](docs/INSTALL_WINDOWS.md), [configuration](docs/CONFIGURATION.md),
[database handling](docs/DATABASES.md), and [security and privacy](docs/SECURITY_PRIVACY.md).

## Data boundary

AgentReady creates runtime state only when its commands are used. Runtime directories and databases are ignored by
Git and excluded from release archives. A clone starts with schemas and initialization code only.

## License

Apache License 2.0. See [LICENSE](LICENSE).
