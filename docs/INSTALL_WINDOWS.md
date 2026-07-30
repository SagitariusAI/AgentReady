# Windows installation

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Git
- PowerShell 7 recommended
- uv

Clone the repository into any writable directory. No fixed drive letter or username is required.

```powershell
uv sync --frozen --group dev
uv run agentready --help
```

AgentReady does not require a pre-existing database, service account, API key, or network service.

To remove the development environment, delete `.venv`. Runtime state lives under the configured AgentReady state
directory and can be removed separately after exporting anything you want to retain.
