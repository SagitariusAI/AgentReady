# Security and privacy

## Default posture

AgentReady's public core operates on local repositories and local state. It does not expose a network service, require
authentication, or include telemetry.

The distribution must not contain credentials, tokens, private endpoints, user-profile paths, environment-specific
topology, operational logs, captured conversations, populated databases, or datasets. A release archive is built from
tracked files in a clean Git commit, not from an operational working directory.

## Local access

AgentReady runs with the permissions of the current Windows user. It can read the target repository, create ignored
runtime directories, and install repository-local Git hooks when explicitly requested. Review the target path before
initialization and use normal operating-system access controls to protect sensitive repositories and capture stores.

Capture redaction reduces accidental secret retention but is not a replacement for credential hygiene. Do not enter
secrets in manual notes, command arguments, fixtures, or documentation.

## Maintainer release checks

Before sharing a build:

1. run the complete test, lint, and type-check suites;
2. run the built-in security scan;
3. scan the complete candidate Git history with reputable secret-scanning tools;
4. run the publication guard over the source tree;
5. build from a clean commit and run the publication guard over the archive;
6. verify that the manifest records the exact Git commit and expected SHA-256 digest;
7. install the archive in a clean environment and confirm that it contains no runtime databases or records.

The public commands include:

```powershell
uv run agent-security-scan --repo .
uv run agent-publication-guard --repo .
uv run agent-package-public --repo .
uv run agent-release-readiness --repo .
uv run agent-release-scorecard --repo .
```

## Reporting a vulnerability

Do not include secrets, private repository content, or personal data in a public issue. Report security concerns
privately to the repository owner until a dedicated security contact is published.
