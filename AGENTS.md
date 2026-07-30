# AgentReady contributor rules

Work from the repository root and inspect existing project guidance before changing code.

- Keep runtime state outside the installed source tree. Respect `AGENTREADY_HOME` and feature-specific runtime paths.
- Never commit databases, event stores, datasets, logs, credentials, private endpoints, or machine-specific paths.
- Treat a missing database as the normal first-run state. Initialization must create a new schema with zero captured rows.
- Run focused tests while editing, then the complete test, lint, type, security, publication, and package gates.
- Keep documentation and tests in the same change as the behavior they describe.
- Do not claim a release is ready unless its manifest and archive are bound to the exact clean Git commit.
