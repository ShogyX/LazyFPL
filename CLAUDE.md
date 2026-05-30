# Repository guide for Claude Code

LazyFPL — a self-hosted FPL prediction & optimisation service (Python backend +
React frontend). Read this before making changes.

## Layout

- `src/fpl_engine/` — backend package (`ingest`, `store`, `resolve`, `features`,
  `model`, `optimise`, `backtest`, `api`, `cli.py`).
- `migrations/` — Alembic; the migration DDL is the source of truth, `db/models.py`
  mirrors it. Keep them consistent (tests assert this).
- `frontend/` — React + Vite + TypeScript + Tailwind + Recharts.
- `tests/` — pytest; needs a Postgres `fpl_test` database (see `tests/conftest.py`).

## Commands

```bash
source .venv/bin/activate
pytest -q                              # backend tests (Postgres fpl_test required)
pytest tests/test_api.py -q            # API tests only
uvicorn fpl_engine.api.app:app --reload --port 8000
cd frontend && npm run build           # frontend type-check + build
cd frontend && npm run dev             # dev server, proxies /api -> :8000
```

## Conventions

- **Leakage discipline is critical.** Models train on a different season than they
  evaluate. Online/adaptive updates may use only *earlier* gameweeks. When touching
  `model/` or `backtest/`, preserve and verify this (there are explicit leakage tests).
- **Secrets never logged.** Use `SecretStr`; never print, log, or return plaintext
  secrets. The Settings API is write-only for secrets — return masked presence only.
- **Don't commit `.env`** or any credentials.
- Add a migration for any schema change and mirror it in `db/models.py`.
- Backend: 4-space indent, type hints, concise docstrings explaining *why*.
- Frontend: keep design-system tokens (Tailwind CSS vars); don't hardcode colours.
- Run the relevant tests and the frontend build before declaring work done.

## Iced / out of scope

Odds/bookmaker integration, elite-pick emulation, and risk-taking captaincy
strategies are intentionally iced — don't reactivate them without explicit ask.
