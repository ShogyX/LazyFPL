# Security Policy

## Reporting a vulnerability

This is a private, single-operator project. If you discover a security issue, please
open a **private** security advisory on GitHub (Security → Advisories → Report a
vulnerability) rather than a public issue. Do not include live credentials in the
report.

## Handling of secrets

- All secrets (FPL session cookie, odds/API-Football keys, SMTP & Pushover
  credentials) are typed as `pydantic.SecretStr` and are **never logged** — a logging
  redaction filter scrubs their plaintext from every log line as defence-in-depth.
- Secrets load from environment variables (`FPL_*`) or a local `.env` file, or are
  stored server-side in `core.app_settings` via the Settings page. Stored secrets are
  **write-only over the API**: the read endpoints return only a masked presence flag,
  never the plaintext.
- `.env` and other credential files are git-ignored. **Never commit real secrets.**
- The FPL session cookie enables authed reads (selling prices / bank). Auth failures
  degrade gracefully and flag re-auth rather than retrying blindly.

## Data & network boundaries

- The read API is **read-only** over the serving/normalised tables, except the
  Settings writes and an explicit team-tracking ingest.
- Outbound calls to third-party providers are rate-limited and budgeted per provider.
- Treat the database as sensitive: it can contain your tracked team and any stored
  credentials.

## Dependencies

- Python and npm dependencies are monitored by Dependabot
  (`.github/dependabot.yml`).
- CI runs CodeQL static analysis and a dependency audit (`pip-audit`, `npm audit`)
  on every push and pull request (`.github/workflows/security.yml`).

## If a secret is exposed

Rotate it immediately at the provider (e.g. revoke and reissue the token/key), then
update `.env` or the Settings page. Assume any secret committed to git or pasted into
a chat/transcript is compromised.
