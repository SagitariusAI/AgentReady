# Architecture

The public core has four layers:

1. `agent_coordination` stores task claims, events, handoffs, reviews, locks, and memory-use receipts.
2. `factory_capture` records governed repository activity with redaction and local storage boundaries.
3. Quality and release modules run CI, security, boundary, report-contract, readiness, and scorecard checks.
4. The router and unified CLI expose deterministic command selection.

All durable runtime state is created outside the versioned source inventory. Remote-service and machine-specific
adapters are deliberately excluded from the public core.
