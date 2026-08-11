# Privacy Notice

Effective date: July 30, 2026

This notice describes the privacy boundary of the official AgentReady software distributed by SagitariusAI. It
does not govern GitHub, package indexes, model providers, third-party prerequisites, repositories you operate, or
other services that have their own privacy terms.

## Local operation

The AgentReady public core is designed to operate on repositories and state under the user's control. It does not
include a SagitariusAI account service, hosted control plane, advertising system, or SagitariusAI telemetry
endpoint. AgentReady does not intentionally transmit repository activity, captured conversations, local reports, or
runtime databases to SagitariusAI.

AgentReady can create local task records, reports, logs, capture records, configuration, and databases after the user
enables or runs relevant features. The user controls the machine, storage location, access, retention, backup,
export, and deletion of that information.

## Network and third-party activity

Network activity can occur when the user or an installer obtains dependencies, follows download links, accesses a
Git remote, or configures an optional third-party tool, model, MCP server, package index, container service, or other
integration. Optional Ollama summarization communicates with the user-configured local Ollama service. A third-party
component may collect or transmit data under its own configuration and privacy terms.

SagitariusAI does not control and is not responsible for third-party data practices. Before enabling an
integration, review its destination, configuration, permissions, privacy terms, retention, and security.

## User responsibility

The user is responsible for:

- determining whether repository activity, prompts, model output, source code, or identifiers contain personal,
  confidential, third-party-owned, regulated, or security-sensitive information;
- obtaining required authorization and consent before monitoring people or capturing their activity;
- applying appropriate redaction, minimization, access controls, retention limits, deletion, and breach procedures;
- avoiding secrets in prompts, command lines, notes, fixtures, logs, issues, and shared reports; and
- complying with privacy, employment, communications, intellectual-property, and data-protection law.

Capture redaction and publication checks reduce specific risks but do not promise complete detection or removal.
Users must independently inspect data before sharing, exporting, publishing, or using it for training.

## GitHub

Downloading AgentReady or interacting with its repository through GitHub is governed by GitHub's own terms and
privacy statement. Security-sensitive reports should follow [SECURITY.md](SECURITY.md), not a public issue.

This notice makes no promise that software or third-party systems will be private, secure, available, or error-free.
See [DISCLAIMER.md](DISCLAIMER.md) and [USER_AGREEMENT.md](USER_AGREEMENT.md).
