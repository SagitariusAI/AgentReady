# Configuration

AgentReady is local-first and works without authentication or remote services.

`AGENTREADY_HOME` optionally selects the AgentReady source/runtime root. When unset, commands resolve the installed
repository root. Repository-specific state is derived from the target repository identity.

Do not place credentials in this repository. Optional third-party integrations are outside the public core and must
load their own configuration from user-controlled files or environment variables.
