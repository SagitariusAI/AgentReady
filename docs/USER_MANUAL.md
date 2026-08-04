# AgentReady user manual

AgentReady is a local-first command-line toolkit for coordinating, capturing, and verifying software work. It can be
operated by a person, a deterministic local model, a frontier model, or ordinary automation. The same public commands
and evidence contracts apply to every operator.

AgentReady is owned and maintained by Sagittarius AI. Project owner: Alex Burca.

## 1. Operating model

AgentReady separates four kinds of information:

- **source** — versioned AgentReady code and documentation;
- **coordination state** — task claims, events, memory-use receipts, reviews, and handoffs;
- **capture state** — repository activity stored as JSONL with a local SQLite query index;
- **evidence** — local CI, security, packaging, and release reports.

A public installation contains none of the last three. They are created only when commands are run. AgentReady does
not require a hosted account, API key, database server, or network service.

Python, Git, and uv are the only hard installation prerequisites. Serena and Graphify are recommended companion
tools; Qdrant, Ollama, Docker, AgentGraph, toolbox packages, and development scanners are optional. See the
[authoritative prerequisite and third-party download list](PREREQUISITES.md).

## 2. Installation

### Verify the release first

Download AgentReady and its checksum or signed source manifest from the same official release location. Verify the
archive before extracting or executing any included code:

```powershell
Get-FileHash .\AgentReady-<version>.zip -Algorithm SHA256
```

The digest must match the value published with that exact release. After extraction, inspect the source manifest and
confirm its commit and file digests. An installer inside an unverified archive cannot establish the archive's
authenticity.

Normal AgentReady runtime is local and does not require a hosted service. uv may contact configured Python package
indexes during installation when build components are not cached. `factory-capture summarize --ollama` contacts a
local model service only when explicitly enabled.

### Human operator

From the extracted or cloned AgentReady source directory:

```powershell
python .\install-agentready.py --dry-run
python .\install-agentready.py
```

The first command produces a plan. The second asks for confirmation, installs AgentReady with `uv tool install`,
resolves uv's tool directory, and verifies the public command surface.

Inspect the companion-tool catalog before installation:

```powershell
python .\install-agentready.py --prerequisites-only --prerequisite-profile recommended
```

To bootstrap an existing repository during installation:

```powershell
python .\install-agentready.py `
  --target-repo "C:\path\to\your-repository"
```

### Deterministic model or automation

Agent mode requires explicit confirmation and one machine-readable JSON result:

```powershell
python .\install-agentready.py `
  --mode agent `
  --yes `
  --json `
  --dry-run `
  --source "C:\path\to\AgentReady" `
  --target-repo "C:\path\to\your-repository"
```

Accept the preview only when the process exits with code `0`, `overall` is `PLANNED`, and every step is `PLANNED`.
Then run the same command without `--dry-run`. Accept the deployment only when the process exits with code `0`,
`overall` is `PASS`, and every executed step is `PASS`.

Agent mode refuses to run without both `--yes` and `--json`. Automation must not retry with `--force`, change the
target path, or delete state to make a failure disappear unless the operator explicitly authorizes that action.

Before deployment, obtain the complete download and availability list:

```powershell
python .\install-agentready.py `
  --mode agent `
  --yes `
  --json `
  --prerequisites-only `
  --prerequisite-profile full
```

The caller must inspect `blocking`, each entry's `installed` value, official `download_url`, and
`publicly_available`. It must never invent a download source for an unavailable companion.

### Installer options

| Option | Meaning |
| --- | --- |
| `--mode human` | Human-readable mode; this is the default. |
| `--mode agent` | Noninteractive mode requiring `--yes --json`. |
| `--source PATH` | AgentReady source containing `pyproject.toml` and `uv.lock`. |
| `--target-repo PATH` | Existing repository to bootstrap after installation. |
| `--runtime-home PATH` | `AGENTREADY_HOME` for deployment steps. |
| `--prerequisites-only` | Check/list prerequisites without installing AgentReady. |
| `--prerequisite-profile PROFILE` | Select `core`, `recommended`, `full`, or `development`. |
| `--strict-prerequisites` | Treat every missing selected companion as blocking. |
| `--dry-run` | Validate and emit a plan without installing or bootstrapping. |
| `--force` | Replace the uv-managed tool installation; it does not erase runtime data. |
| `--yes` | Confirm without a prompt. |
| `--json` | Emit one JSON deployment result. |

`--runtime-home` does not permanently change the user's environment. Set `AGENTREADY_HOME` in later processes that
must use the same path. Set `FACTORY_CAPTURE_DIR` separately before capture commands when overriding the
repository-local default.

## 3. Public command surface

The installed console commands are:

- `agentready` — unified public command dispatcher;
- `agent-deploy` and `agent-bootstrap-repo` — deployment and repository onboarding;
- `agent-prerequisites` — required and optional third-party availability/download catalog;
- `agent-coordination`, `agent-commit-guard`, `agent-history-search`, `agent-workstate`, and
  `agent-version-record` — governed work and evidence;
- `factory-capture` — local repository activity capture;
- `agent-tool-router` and `agent-tool-context` — deterministic tool selection and model-facing context;
- `agent-ci-local`, `agent-governance-detectors`, `agent-security-scan`, and `agent-report-contract` — quality and
  governance checks;
- `agent-publication-guard`, `agent-package-public`, `agent-release-readiness`, and `agent-release-scorecard` —
  publication and release checks;
- `agent-data-foundry` and `agent-data-foundry-event-runner` — user-controlled dataset curation and validation.
- `agent-memory-pipeline` — durable, configuration-driven local memory-to-graph convergence.

Run `<command> --help` before using an unfamiliar command. The unified form is also available; for example,
`agentready coordination --help` dispatches to the public coordination command.

## 4. Onboard a repository

The installer can bootstrap a target through `--target-repo`. To bootstrap later:

```powershell
agent-bootstrap-repo --repo "C:\path\to\your-repository"
agent-coordination coordination-init --repo "C:\path\to\your-repository"
agent-coordination task-status --repo "C:\path\to\your-repository"
```

Bootstrap creates portable guidance, local exclusions, `.agentready.yaml`, and empty coordination state. It does not
install capture hooks or connect to a remote service.

Before changing a valuable repository, inspect `git status`, confirm the resolved path, and preserve unrelated work.

## 5. Governed work workflow

### Plan

Run the router from the target repository:

```powershell
agent-tool-router `
  --task "Describe the requested work precisely" `
  --mode plan `
  --repo .
```

Use the selected profile. Do not silently skip a relevant check; record why a command was not applicable.

### Claim work

```powershell
agent-coordination task-start `
  --repo . `
  --title "Clear task title" `
  --agent "operator-id" `
  --summary "Intent, scope, and expected outcome" `
  --paths "src/example.py,tests/test_example.py" `
  --workflow-lane personal `
  --create-worktree
```

Workflow lanes are `personal`, `business`, and `research`. Use the lane that describes the work's purpose, not the
model performing it.

Read the returned task ID, then check for path conflicts:

```powershell
agent-coordination conflict-check --repo . --task-id "task-id"
```

One operator should own a working tree at a time. Concurrent operators should use separate worktrees and nonoverlapping
path claims.

### Record memory and graph use

AgentReady records memory-use receipts; it does not replace a model's own memory or repository-intelligence system.
After a relevant memory read or graph query:

```powershell
agent-coordination task-memory `
  --repo . `
  --task-id "task-id" `
  --agent "operator-id" `
  --kind memory_read `
  --store "operator-memory" `
  --memory-name "relevant-memory-name" `
  --evidence "What was read and how it affected the work"
```

Allowed receipt kinds are `graph_query`, `memory_read`, `durable_write`, `graph_refresh`, and
`no_relevant_memory`. When no memory applies, record the reason rather than fabricating a read:

```powershell
agent-coordination task-memory `
  --repo . `
  --task-id "task-id" `
  --kind no_relevant_memory `
  --evidence "Memory inventory checked; no task-relevant item found" `
  --reason "The task is isolated and repository-local"
```

Audit memory-receipt coverage with:

```powershell
agent-coordination memory-compliance --repo . --fail-on-missing
```

Receipts should contain interpreted evidence, not credentials, private prompts, or copied memory-bank contents.

### Verify and hand off

Run the checks selected by the router, inspect their reports, and then record a truthful handoff:

```powershell
agent-coordination task-handoff `
  --repo . `
  --task-id "task-id" `
  --operator "operator-id" `
  --summary "What changed and the current repository state" `
  --evidence "Tests and checks run, with interpreted results" `
  --next "Next safe action, or state that none remains" `
  --status complete
```

Use `--status wip` or `--status blocked` when work is not complete. Do not use weak or dirty-tree overrides merely to
obtain a successful command result.

## 6. Activity capture

Open PowerShell in the repository to be observed:

```powershell
Set-Location "C:\path\to\your-repository"
factory-capture init
factory-capture status
```

Capture state defaults to `.factory_capture` in that repository. A new store begins with an empty event table. No
existing database or event stream is included with AgentReady.

Optional local Git hooks:

```powershell
factory-capture hooks status
factory-capture hooks install
```

Record a deliberate note, inspect recent events, and create a deterministic summary:

```powershell
factory-capture note "Public-safe description of the work"
factory-capture tail -n 20 --json
factory-capture summarize
```

`factory-capture summarize --ollama` enables optional local-model enrichment. It is off by default and should be used
only after the operator has reviewed the local model and data boundary.

Redaction reduces accidental retention but cannot make an unsafe command or secret safe. Do not place credentials,
private keys, personal data, or confidential repository content in notes or command arguments.

Before uninstalling AgentReady or retiring the repository:

```powershell
factory-capture hooks uninstall
```

## 7. Quality and release workflow

The router defines the applicable order. Preview it first:

```powershell
agent-tool-router --profile release --mode plan --repo .
```

For a complete public-source candidate:

```powershell
agent-tool-router --profile release --mode run --include-heavy --repo .
agent-tool-router --profile release --mode audit --repo .
agent-release-scorecard --repo .
```

The release profile runs the public CI, security, publication, packaging, readiness, and scorecard commands. Heavy mode
includes the commit-bound public package.

A release claim is valid only when:

- the required checks pass;
- the working tree is clean;
- evidence belongs to the current Git commit;
- the publication guard finds no credentials, private topology, runtime state, databases, datasets, or logs;
- the package manifest identifies the exact commit and archive digest;
- the release scorecard is `PASS`.

`agent-package-public` refuses a dirty tree. Do not bypass a failing publication or release check. Correct the source,
rerun the evidence chain, and review the new reports.

The public packager reads the release version from `[project].version` in `pyproject.toml`, writes it to
`package-manifest.json`, and names the archive `AgentReady-<version>-source.zip`. Keep `pyproject.toml` and `uv.lock`
on the same version. Do not rename a generated archive by hand, because the manifest and digest must remain bound to
the exact file produced from the committed source.

## 8. Data and memory safety

- Never copy an existing operational database into the source checkout.
- Keep each repository's capture store separate unless shared storage is an explicit design choice.
- Back up the complete capture directory before deletion; JSONL is the durable stream and SQLite is the query index.
- Keep model memory contents in their designated memory system. Store only evidence receipts in AgentReady.
- Treat generated datasets as user data. Verify provenance, rights, redaction, and split integrity before training or
  sharing.
- Do not publish `.agent-state`, `.agent-reports`, `.factory_capture`, caches, credentials, or generated datasets.

See [Database lifecycle](DATABASES.md), [Data retention](DATA_RETENTION_AND_EXPORT.md), and
[Security and privacy](SECURITY_PRIVACY.md).

## 9. Troubleshooting

### `uv` was not found

Install uv, confirm `uv --version` works in a new PowerShell session, and rerun the dry run.

### The installed command is not found

Run:

```powershell
uv tool dir --bin
```

Add the reported directory to the user PATH using uv's guidance, then open a new terminal. Rerun
`agentready --help`.

### Agent mode exits with code 2

Use both required flags:

```powershell
python .\install-agentready.py --mode agent --yes --json
```

### The target repository is rejected

Resolve the path and confirm it is the root of an existing Git working tree. Both dry-run and real deployment validate
the target before any installation or bootstrap mutation. The AgentReady source checkout, a drive root, and the user
profile root are refused as targets.

### State appears in the wrong location

Check the current process:

```powershell
Get-Item Env:AGENTREADY_HOME -ErrorAction SilentlyContinue
Get-Item Env:FACTORY_CAPTURE_DIR -ErrorAction SilentlyContinue
```

Installer path options are process-scoped. Set the same variables in every later process that should use those
locations.

### Capture already contains events

Stop. Do not assume `factory-capture init --force` erases a store. Resolve `FACTORY_CAPTURE_DIR`, inspect
`factory-capture status`, and preserve any required records before selecting a new empty directory.

### A release command fails

Read the named report under `.agent-reports`, verify it belongs to the current commit, correct the underlying problem,
and rerun the release profile. Do not delete evidence or use an override to turn a real failure into a release claim.

## 10. Uninstall

Remove optional hooks from every managed repository, back up records, and uninstall the uv tool:

```powershell
factory-capture hooks uninstall
uv tool uninstall agentready
```

Remove runtime directories only after resolving each exact path and verifying the backup. Uninstalling the command
does not silently delete capture databases, coordination ledgers, reports, or repositories. See
[Uninstall](UNINSTALL.md) for the complete sequence.

Copyright 2026 Sagittarius AI. Licensed under the Apache License 2.0.
