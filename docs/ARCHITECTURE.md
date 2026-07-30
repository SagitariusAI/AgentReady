# Architecture

AgentReady is a Python command-line application. Its public core operates on local repositories and local files; it
does not require a server, hosted account, or background network service.

## Main components

1. **Coordination** — `agent_coordination` manages task claims, path-conflict checks, events, handoffs, reviews,
   worktrees, locks, and memory-use receipts.
2. **Activity capture** — `factory_capture` records repository activity, applies redaction, maintains an append-only
   JSONL event stream, and builds a local SQLite query index.
3. **Data preparation** — the data-foundry modules validate provenance, rights, dataset structure, evaluation
   records, and training exports created by the user. No dataset is included in the distribution.
4. **Quality and release** — CI, security, report-contract, publication, packaging, readiness, and scorecard modules
   produce local evidence under ignored report directories.
5. **Command routing** — the unified `agentready` entry point and individual console commands expose the public
   capabilities.

## State boundaries

Coordination state is keyed to the target repository and stored beneath `%USERPROFILE%\.agentready` by default. The
target repository receives a small ignored `.agent-state` pointer so worktrees can resolve the same coordination
ledger.

Capture state defaults to `<target-repository>\.factory_capture`. Its JSONL event stream is the durable record and
its SQLite database is a query index created on first initialization. `FACTORY_CAPTURE_DIR` can place this state
elsewhere.

Generated validation and release evidence uses ignored `.agent-reports` directories. These runtime locations are not
part of the versioned source inventory or release archive.

## Trust boundary

AgentReady can inspect repositories, install local Git hooks when explicitly requested, and execute deterministic
verification commands. Operators should review commands before using them on valuable work and should back up runtime
records according to their own retention requirements.

Remote integrations and environment-specific adapters are outside this public core. If added by a downstream user,
they should be isolated behind explicit configuration and must not place credentials in the repository.
