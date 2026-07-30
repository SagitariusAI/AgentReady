# Security and privacy

The public distribution contains no credentials, authentication tokens, private endpoints, user-profile paths,
production topology, operational logs, captured conversations, or populated databases.

AgentReady's public core does not expose a network service. It operates on local repositories and local state.

Before sharing a build:

1. run the test and lint suites;
2. run Gitleaks and TruffleHog over the complete public history;
3. run the publication guard over the source tree and archive;
4. verify the archive manifest matches the exact Git commit and SHA-256 digest.

Report vulnerabilities privately to the repository owner until a public security contact is configured.
