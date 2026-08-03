# Contributing to AgentReady

AgentReady accepts focused, evidence-backed improvements. Please open an issue before proposing a broad architectural,
networked, telemetry, authentication, or compatibility change.

## Change discipline

- Keep each pull request to one coherent concern.
- Use an imperative Conventional Commit subject such as `fix(router): handle an empty profile`.
- Add tests and update the controlling documentation in the same change.
- Do not rewrite shared history or combine unrelated cleanup with behavior changes.
- Preserve local-first operation and keep user-created state outside the source tree.

## Required verification

Run these checks from the repository root:

```powershell
python -m pip install -e . pytest ruff build
ruff check src tests
pytest -q
python -m build
```

The GitHub Actions matrix repeats these checks on every push and pull request for supported Python versions.

## Security, privacy, and disclosure

Do not open a public issue containing credentials, private endpoints, personal data, or an unpatched vulnerability.
Follow [SECURITY.md](SECURITY.md) for private reporting. Contributions remain subject to the repository's
[license](LICENSE), [user agreement](USER_AGREEMENT.md), [privacy notice](PRIVACY.md), and
[disclaimer](DISCLAIMER.md).

No contribution, review, merge, or release creates a promise of support, maintenance, compatibility, security, or
continued distribution.
