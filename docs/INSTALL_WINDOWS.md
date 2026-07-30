# Windows installation

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Git
- [uv](https://docs.astral.sh/uv/)
- PowerShell 7 recommended

No fixed drive letter, Windows username, database server, service account, API key, or network service is required.

## Install the command-line tools

Clone or extract AgentReady into any writable directory, then open PowerShell in that directory:

```powershell
uv tool install .
agentready --help
```

`uv tool install` places AgentReady in an isolated environment managed by uv and exposes its console commands on the
user's executable path. If PowerShell cannot find `agentready`, follow uv's displayed PATH guidance and open a new
terminal.

To replace an earlier local installation:

```powershell
uv tool install --force .
```

## Development checkout

Contributors can instead create a repository-local environment:

```powershell
uv sync --frozen --group dev
uv run agentready --help
uv run pytest
```

Install the optional deterministic toolbox dependencies with:

```powershell
uv sync --frozen --group dev --extra toolbox
```

## Verify the installation

```powershell
agentready --help
agent-coordination --help
factory-capture --help
```

Help commands do not require or initialize a populated database. Runtime state is created only when an initialization
or operational command is used.

## First repository

```powershell
agent-bootstrap-repo --repo "C:\path\to\your-repository"
agent-coordination coordination-init --repo "C:\path\to\your-repository"
```

To enable local activity capture, change to that repository:

```powershell
Set-Location "C:\path\to\your-repository"
factory-capture init
factory-capture status
```

Git hooks are optional and are installed only when requested:

```powershell
factory-capture hooks install
```

See [Configuration](CONFIGURATION.md) before relocating runtime state and [Uninstall](UNINSTALL.md) before removing an
installation that has active hooks or records.
