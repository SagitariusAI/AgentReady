# Generic factory operating prompt

AgentReady bootstraps a portable operating contract into each target
repository's `AGENTS.md`. The contract is intentionally vendor-neutral: it can
guide Claude, Codex, or another capable development agent without depending on
a Sagittarius AI network, repository, account, or private policy map.

The generated prompt tells an agent to:

- act as an engineering operator pursuing a bounded, testable outcome;
- inspect repository and source-control truth before changing anything;
- use deterministic routing, semantic memory, and repository-graph context when
  those capabilities are available;
- read coordination state and claim one exact lane before mutation;
- remain read-only after a harness/context change until session re-entry passes;
- distinguish durable evidence from chat claims and preserve negative results;
- keep identity, lineage, user data, and intellectual property intact;
- update controlling documentation with behavior;
- treat the operator-configured source authority as canonical and hosted
  publication as a separate decision;
- call work done only when the exact commit is gate-green, committed, present at
  the configured authority, clean, and durably handed off.

## Install the prompt into a repository

```powershell
agent-bootstrap-repo --repo "C:\path\to\repository"
```

Bootstrap writes or appends only the marked AgentReady block in `AGENTS.md`,
creates portable `.agentready.yaml` defaults, adds generated-state exclusions,
and initializes empty coordination state. Existing instructions outside the
marked block are preserved. Use `--force` only when you intend to refresh an
existing AgentReady block to the currently installed prompt.

## Customization boundary

Repository-specific instructions may add language, build, safety, review, or
deployment requirements. They should not weaken these invariants:

1. one owner per working lane;
2. evidence before completion claims;
3. fail-closed unavailable/red gates;
4. explicit source authority and publication separation;
5. session re-entry after harness or context discontinuity;
6. no private data or runtime state in source distributions.

The installed prompt is an operating baseline, not a guarantee that every
third-party model or host supports tool hooks. Where a direct mutation hook is
unavailable, enforce the same boundary through the commit guard and operator
review.
