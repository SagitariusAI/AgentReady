# Windows installation

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Git
- [uv](https://docs.astral.sh/uv/)
- PowerShell 7 recommended

No fixed drive letter, Windows username, database server, service account, API key, or network service is required.
The complete required and optional inventory is maintained in
[Prerequisites and third-party downloads](PREREQUISITES.md).

## Verify the download before execution

Obtain the archive and its checksum or signed source manifest from the same official AgentReady release. Before
extracting or running `install-agentready.py`, compare the archive's SHA-256:

```powershell
Get-FileHash .\AgentReady-<version>.zip -Algorithm SHA256
```

Reject a mismatched or missing release checksum. After extraction, inspect the packaged source manifest and confirm
that its commit and file digests match the release metadata. Do not treat an installer contained in an unverified
archive as proof of that archive's authenticity.

AgentReady needs no hosted service during normal runtime. uv may contact configured Python package indexes during the
initial tool installation if required build components are not cached. An offline installation therefore requires a
pre-populated uv cache or an operator-approved local package source.

## Preview the deployment

Clone or extract AgentReady into any writable directory, then open PowerShell in that directory:

```powershell
python .\install-agentready.py --dry-run
```

The dry run validates the source checkout and the availability of `uv`, then prints the steps it would execute. It
does not install commands or bootstrap a repository.

To inspect prerequisites without changing anything:

```powershell
python .\install-agentready.py --prerequisites-only --prerequisite-profile recommended
```

For an LLM:

```powershell
python .\install-agentready.py --mode agent --yes --json --prerequisites-only --prerequisite-profile full
```

## Human installation

Run the installer from the AgentReady source root:

```powershell
python .\install-agentready.py
```

Human mode asks for confirmation when PowerShell is interactive. In a trusted noninteractive script, confirmation
must be explicit:

```powershell
python .\install-agentready.py --yes
```

To install and bootstrap an existing repository in one operation:

```powershell
python .\install-agentready.py `
  --target-repo "C:\path\to\your-repository"
```

The target must already exist and be a directory. Bootstrapping adds or updates the portable AgentReady guidance and
initializes empty coordination state; it does not initialize capture, install Git hooks, contact a remote service, or
create populated data.

To replace an existing uv-managed AgentReady installation:

```powershell
python .\install-agentready.py --force
```

`--force` applies to the uv tool installation. It does not authorize replacement of unrelated target-repository
content.

## Deterministic LLM or frontier-model installation

Agent mode is noninteractive and requires both `--yes` and `--json`:

```powershell
python .\install-agentready.py `
  --mode agent `
  --yes `
  --json `
  --dry-run
```

After verifying exit code `0` and JSON `"overall": "PLANNED"`, remove `--dry-run`:

```powershell
python .\install-agentready.py `
  --mode agent `
  --yes `
  --json `
  --target-repo "C:\path\to\your-repository"
```

A model or automation must treat a nonzero exit code, `"overall": "FAIL"`, or any failed step as a failed
deployment. It must not infer success from partial output. Successful installation returns `"overall": "PASS"`.

PowerShell can enforce the contract:

```powershell
$resultJson = python .\install-agentready.py --mode agent --yes --json
$installExit = $LASTEXITCODE
$result = $resultJson | ConvertFrom-Json
if ($installExit -ne 0 -or $result.overall -ne "PASS") {
    throw "AgentReady installation failed."
}
```

## Runtime locations

Coordination state defaults to `%USERPROFILE%\.agentready`. Capture state defaults to an ignored
`.factory_capture` directory in the repository being observed. To use an explicit coordination location during
deployment:

```powershell
python .\install-agentready.py `
  --runtime-home "C:\AgentReadyState" `
  --target-repo "C:\path\to\your-repository"
```

This argument sets the environment for installer steps; it does not permanently modify the user's PowerShell
profile. Set `AGENTREADY_HOME` in each later process that should use the same location. Set `FACTORY_CAPTURE_DIR`
separately before capture commands when a repository should not use its default `.factory_capture` directory:

```powershell
$env:AGENTREADY_HOME = "C:\AgentReadyState"
$env:FACTORY_CAPTURE_DIR = "C:\AgentReadyCapture"
```

Use a separate capture directory for each unrelated repository. Do not point multiple repositories at one event
store unless that sharing is intentional.

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
agent-deploy --help
agent-prerequisites --profile recommended
agent-coordination --help
agent-session-reentry --help
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
installation that has active hooks or records. The [User manual](USER_MANUAL.md) covers task, memory-receipt,
capture, and release workflows.

AgentReady is owned and maintained by SagitariusAI. Project owner: Alex Burca.
