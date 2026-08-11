# AgentReady contributor rules

These rules apply to people and automated development agents working in this repository.

## Work safely

- Work from the repository root and read the relevant documentation before changing behavior.
- Keep changes focused. Do not overwrite unrelated work or mutate another checkout.
- Do not add a network dependency, hosted service, telemetry path, or authentication requirement without documenting
  the design and obtaining maintainer approval.
- Keep user-created state outside the installed source inventory. Respect `AGENTREADY_HOME`,
  `FACTORY_CAPTURE_DIR`, and repository-specific runtime paths.

## Protect user data

- Never commit databases, event streams, datasets, logs, credentials, tokens, private endpoints, user-profile paths,
  or machine-specific configuration.
- Treat a missing database as the normal first-run state. Initialization must create an empty schema, not bundled
  sample or operational records.
- Use synthetic, obviously non-secret fixtures in tests. Do not copy real user activity into an issue, fixture, or
  documentation example.
- Preserve redaction and publication checks when modifying capture, reporting, packaging, or export behavior.

## Verify changes

- Add or update tests and documentation in the same change as the behavior they describe.
- Run focused tests while editing, followed by the complete test, lint, type, security, and publication checks
  appropriate to the change.
- Build releases only from a clean Git commit. The archive manifest, source inventory, and digest must identify that
  exact commit.
- Do not describe a build as release-ready while a required check is failing or its evidence belongs to another
  commit.

AgentReady is owned and maintained by SagitariusAI and is licensed under the Apache License 2.0.
