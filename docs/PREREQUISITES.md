# Prerequisites and third-party download list

This is the authoritative installation inventory for AgentReady. It separates the small required core from optional
AI-assistant integrations so a human or an LLM does not install unrelated software or mistake a companion service for
a core requirement.

AgentReady does not silently download these companion tools, accept their licenses, start their services, open
listeners, create API keys, or configure an AI client. Review each upstream license and security boundary before
installing it.

## Machine-readable preflight

Before installing AgentReady, run the source-checkout preflight:

```powershell
python .\install-agentready.py --prerequisites-only --prerequisite-profile recommended
```

An LLM or noninteractive automation must use JSON:

```powershell
python .\install-agentready.py `
  --mode agent `
  --yes `
  --json `
  --prerequisites-only `
  --prerequisite-profile full
```

After AgentReady is installed, the equivalent commands are:

```powershell
agent-prerequisites --profile recommended
agent-prerequisites --profile full --json
agentready prerequisites --profile development --json
```

The normal exit status is based only on missing required core tools. Add `--strict` to `agent-prerequisites`, or
`--strict-prerequisites` to the source installer, when every selected optional tool must be present. The JSON schema is
`agentready.prerequisites.v1`; inspect `overall`, `blocking`, and every entry's `installed` field.

## Required core

Only these components are required for normal AgentReady installation and operation:

| Component | Requirement | Official download | Verify |
| --- | --- | --- | --- |
| Windows | Windows 10 or Windows 11 | [Microsoft Windows](https://www.microsoft.com/windows/) | `winver` |
| Python | 3.11 or newer | [Python for Windows](https://www.python.org/downloads/windows/) | `python --version` |
| Git | Current supported release | [Git for Windows](https://git-scm.com/downloads/win) | `git --version` |
| uv | Current supported release | [Official uv installation](https://docs.astral.sh/uv/getting-started/installation/) | `uv --version` |

Official uv installation command for Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Inspect remote installation scripts before executing them. Direct release downloads are available from the upstream
uv documentation when organizational policy does not permit executing a downloaded script.

PowerShell 7 is recommended for the documented command examples but is not a core AgentReady runtime dependency:

```powershell
winget install --id Microsoft.PowerShell --source winget
pwsh --version
```

Official instructions: [Install PowerShell on Windows](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows).

## Recommended AI-assistant companions

These tools make the governed workflow more capable, but AgentReady remains functional when either is absent.

### Serena

[Serena](https://github.com/oraios/serena) provides MCP semantic code retrieval, symbol-aware editing, and durable
agent memory. Serena's current official quick start uses Python 3.13 through uv:

```powershell
uv tool install -p 3.13 serena-agent
serena init
serena --help
```

Then configure the `serena` MCP server in the selected AI client using Serena's upstream instructions. Language-server
support for some programming languages can add language-specific prerequisites. Do not copy another user's Serena
memory directory into a new installation.

### Graphify

[Graphify](https://github.com/Graphify-Labs/graphify) creates queryable knowledge graphs from repositories and
documents. The official PyPI package is `graphifyy` with two `y` characters; its CLI command is `graphify`.

```powershell
uv tool install "graphifyy[mcp]"
graphify agents install
graphify --help
```

Use the plain `graphifyy` package when MCP support is unnecessary. Additional Graphify extras for PDFs, Office files,
video, databases, or model providers are optional and are documented upstream. Some document extraction backends can
send content to a configured model provider; review that data boundary before enabling them.

## Optional memory and local-model services

### Qdrant MCP memory

The official [Qdrant MCP server](https://github.com/qdrant/mcp-server-qdrant) can use either an explicit Qdrant server
URL or a local storage path:

```powershell
uv tool install mcp-server-qdrant
mcp-server-qdrant --help
```

For a fully local file-backed setup, configure `QDRANT_LOCAL_PATH` and a unique `COLLECTION_NAME` in the AI client's
MCP environment. If using a Qdrant server, follow the [Qdrant local quickstart](https://qdrant.tech/documentation/quickstart/).
Keep any container port bound to loopback unless network exposure is explicitly intended, and never commit API keys.

### Ollama

[Ollama for Windows](https://ollama.com/download/windows) is optional. AgentReady uses it only when an operator
explicitly requests local-model enrichment, such as `factory-capture summarize --ollama`.

```powershell
ollama --version
ollama list
```

Models are separate downloads and may consume tens to hundreds of gigabytes. Select and pull a model deliberately;
AgentReady does not choose or download one automatically.

### Docker Desktop

[Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) is optional and is needed only when
the user chooses container-backed services such as Qdrant. Review Docker's system requirements, licensing, daemon
privileges, storage use, and listener configuration before installation.

```powershell
docker version
```

### AgentGraph

AgentGraph is an AgentReady-compatible repository-intelligence provider, but no public AgentGraph distribution is
currently available. It is not a prerequisite for public AgentReady. Do not use a private URL, copied installation, or
unverified binary. Use Graphify or another trusted MCP-compatible graph provider unless an official public AgentGraph
release becomes available.

## AgentReady-managed Python packages

The base AgentReady installation has no third-party runtime Python dependencies. uv creates the isolated environment
and installs AgentReady itself.

The optional `toolbox` extra is pinned in `pyproject.toml` and `uv.lock`:

| Package | Pinned version | Purpose |
| --- | ---: | --- |
| DuckDB | 1.5.3 | Optional local analytical database |
| NetworkX | 3.6.1 | Graph algorithms |
| pandas | 3.0.3 | Data-frame operations |
| SymPy | 1.14.0 | Symbolic mathematics |
| Z3 Solver | 4.16.0.0 | Constraint solving |

Install it only when those capabilities are needed:

```powershell
uv sync --frozen --extra toolbox
```

Contributors and maintainers install the locked development group:

```powershell
uv sync --frozen --group dev
```

That group provides Bandit, build, coverage, Pyright, pytest, and Ruff. Release environments may also use external
scanners such as Gitleaks, Trivy, Syft, Grype, OSV-Scanner, Semgrep, pip-audit, Vulture, and Radon. Those scanners are
maintainer tools, not end-user prerequisites, and AgentReady reports a missing scanner instead of silently installing
it.

## Recommended installation order

1. Verify the AgentReady release archive and SHA-256.
2. Install and verify Python, Git, and uv.
3. Run the `core` prerequisite preflight.
4. Install AgentReady and bootstrap the selected Git repository.
5. Run the `recommended` preflight.
6. Install Serena and/or Graphify only if the selected AI client will use them.
7. Configure each MCP server in that client and verify it independently.
8. Add Qdrant, Ollama, Docker, toolbox packages, or development tools only for an identified capability.
9. Re-run `agent-prerequisites --profile full --json`; preserve the result as installation evidence.

Never treat the presence of an executable as proof that its server is configured safely. Verify storage locations,
network listeners, authentication, licenses, and model/data boundaries separately.
