# LazyFPL — FPL Intelligence Engine

A self-hosted Fantasy Premier League prediction & optimisation service. It ingests
historical and live FPL data, predicts expected points per player per gameweek with
an ensemble of models, optimises squads/transfers/captaincy under the real FPL rules
via MILP, and serves it all through a FastAPI read API and a React dashboard.

> Single-operator, runs entirely on your own machine. Secrets stay server-side and
> are never logged.

## Features

- **Component-wise expected points (xP)** — minutes, goals, assists, clean sheets
  (Dixon–Coles), bonus, defensive contribution, all combined per position.
- **Ensemble models** — IC-weighted / per-position / rank z-blends, a Ridge stacking
  meta-learner, an **online Hedge** blend that re-weights members from realised
  results, and decorrelation-aware member selection. Recency-weighted so fresher
  data counts more.
- **Optimisation (MILP / CBC)** — squad + XI selection, multi-GW transfer planning
  with free-transfer value and future-GW decay, **value-aware budgeting** (tracks
  bank + sell value as prices drift), captaincy and chips (Triple Captain, Bench
  Boost, Free Hit).
- **Availability-aware** — injured/suspended/doubtful players are gated out of
  selections and transfers.
- **Leakage-disciplined backtester** — train season ≠ eval season, strictly causal
  features, autosubs + vice-captain + chip realism, multi-season validation.
- **React dashboard** — three pages: Settings, Team Planner (FPL-style pitch), and
  Model Performance (season/GW comparison, predicted-vs-actual accuracy, calibration,
  optimal-XI realised, online-hedge weight adaptation, player search).

## Architecture

```
src/fpl_engine/
  ingest/       data sources (FPL, Understat, FBref, API-Football, odds, elite, entry)
  store/ resolve/ features/   normalisation, identity crosswalk, feature panels
  model/        predictors, ensembles, stacking, components, minutes, analysis
  optimise/     squad / transfer / value-step / chips MILP
  backtest/     leakage-safe walk-forward engine
  api/          FastAPI read API (app.py), settings store, analytics
  cli.py        `fpl` command-line entry
migrations/     Alembic (Postgres: raw / normalised / feature / study / serving / core)
frontend/       React + Vite + TypeScript + Tailwind + Recharts dashboard
tests/          pytest suite
```

Data lives in Postgres across layered schemas: `raw` (immutable snapshots),
`normalised` (typed facts), `feature` (model inputs), `study` (validity artefacts +
model registry), `serving` (predictions, recommendations, backtests), and `core`
(operational + app settings).

## Quick start

```bash
git clone https://github.com/ShogyX/LazyFPL.git
cd LazyFPL
./install.sh --with-scheduler   # fire-and-forget: provisions everything + starts services
```

`install.sh` is self-provisioning on Debian/Ubuntu: it installs the system
packages it needs (Python venv, **Node 20**, **PostgreSQL**), creates the database
and role, sets up the virtualenv and Python deps, writes `.env`, applies
migrations, builds the frontend, and (with `--with-scheduler`) installs and starts
the auto-refresh + API systemd services. Run it as **root or with sudo** so it can
install system packages. It's idempotent — safe to re-run.

Flags: `--with-scheduler` (install & start services), `--no-system-deps` (skip
apt/PostgreSQL/Node provisioning and use what's already installed).

Requirements it installs for you (Debian/Ubuntu): **Python 3.11+**, **Node 18+**,
**PostgreSQL**. On other systems install those yourself, then run
`./install.sh --no-system-deps`.

## Running

```bash
# Backend read API (http://localhost:8000)
uvicorn fpl_engine.api.app:app --reload --port 8000

# Frontend dev server (http://localhost:5173, proxies /api -> :8000)
cd frontend && npm run dev
```

### Automatic refresh (hands-off)

`fpl schedule` starts a blocking scheduler (APScheduler) that keeps everything
fresh without manual steps:

| Job | Cadence | What it does |
|---|---|---|
| `fpl_bootstrap` / `fpl_fixtures` | hourly | pull FPL prices/status/news + fixtures |
| `refresh_predictions` | every 6h | rebuild xP for the **next 6 GWs** (ingest → crosswalk → facts → targets → panel → predict) |
| `price_watch` | daily 01:30 | on price moves → full recompute + recommendation |
| `news_lineup_watch` | every 30 min | on injury/lineup flips → recompute |
| `post_match_recompute` | every 15 min | once bonus is confirmed → recompute |
| `elite_refresh` | weekly | elite-cohort ownership |

The refresh **auto-detects the current season and next gameweek from the live FPL
calendar** (so a brand-new season — and GW1 — is picked up the moment the API
publishes it, no manual config). It builds *forward* feature rows for upcoming,
not-yet-played gameweeks, so the model forecasts the whole planning horizon (GW1 of
a new season is forecast from prior-season carryover) — and it correctly drops teams
in blank gameweeks. These forward rows are leakage-safe (history strictly precedes
each gameweek's deadline).

Run it as a service via `./install.sh --with-scheduler` (systemd `--user`), or
manually: `source .venv/bin/activate && fpl schedule`. One-off rebuild of the next N
gameweeks: `fpl refresh --horizon 6`.

CLI examples:

```bash
fpl --help
fpl schedule                                            # start auto-refresh (blocking)
fpl refresh                                             # rebuild current-GW predictions once
fpl backtest --season 2024-25 --strategy ict           # backtest a strategy
fpl recommend --entry <id> --season 2024-25 --from-gw 30
fpl track --entry <id>                                  # pull & save your team
```

## Configuration

All settings load from environment variables (prefix `FPL_`) or `.env`; see
[`.env.example`](.env.example). The Settings page can also manage config and secrets
at runtime — stored server-side in `core.app_settings`, write-only, and never
returned in plaintext. Stored secrets override env values.

Secrets are typed `SecretStr` and scrubbed from logs. **Never commit `.env`.** See
[`SECURITY.md`](SECURITY.md).

## Data sources

Only the **official FPL API is required**, and it needs no key. Everything else is
optional enrichment.

| Source | Key? | Used for | Coverage |
|---|---|---|---|
| [Official FPL API](https://fantasy.premierleague.com/api) | none | live prices, status/news, fixtures, current-season per-match stats, your team | **current season only** |
| [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League) | none | historical per-GW match data for training & backtests | **10 seasons (2016‑17 →)** |
| [Understat](https://understat.com) | none | advanced xG / npxG / shot data (optional) | 2014‑15 → |
| [FBref](https://fbref.com) | none | creation / progression / defensive actions (optional) | recent seasons |
| [ClubElo](http://clubelo.com) | none | team Elo ratings (optional) | long history |
| [API-Football](https://www.api-football.com) | free key | lineups / injuries / referees (optional) | current |

> **Why both the FPL API and vaastav?** vaastav's data is itself scraped from the
> FPL API, so for the *current* season the depth and accuracy are identical. The
> official API, however, only exposes the **current** season — it has no historical
> endpoint — whereas vaastav archives 10 seasons of merged per-gameweek data. The
> engine therefore reads live state from the FPL API and historical/per-match data
> from vaastav; dropping vaastav would lose all multi-season training and backtest
> coverage. The bookmaker/odds providers are intentionally **iced**.

### Software dependencies

Backend (see [`pyproject.toml`](pyproject.toml)): SQLAlchemy, Alembic, psycopg2,
Pydantic / pydantic-settings, httpx, APScheduler, NumPy, SciPy, scikit-learn,
pandas, PuLP (CBC solver), FastAPI, Uvicorn.

Frontend (see [`frontend/package.json`](frontend/package.json)): React, Vite,
TypeScript, Tailwind CSS, Recharts, lucide-react, React Router, TanStack Query.

## Testing

```bash
pytest -q                       # backend (needs a Postgres test DB: fpl_test)
cd frontend && npm run build    # frontend type-check + build
```

CI runs the backend suite against a Postgres service container and type-checks /
builds the frontend on every push and PR (`.github/workflows/ci.yml`). Security
scanning (CodeQL + dependency audit) runs in `.github/workflows/security.yml`.

## Acknowledgements

This project stands on data generously maintained by others:

- **[vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)**
  — the historical per-gameweek FPL dataset that makes multi-season training and
  backtesting possible. The engine's history layer is built directly on it; huge
  thanks to [@vaastav](https://github.com/vaastav) and its contributors.
- **[Understat](https://understat.com)** and **[FBref](https://fbref.com)** — advanced
  expected-goals and player-action data.
- **[ClubElo](http://clubelo.com)** — team strength ratings.
- The **official Fantasy Premier League API** — live game state.

Please respect each source's terms of use and rate limits (the ingest layer
self-rate-limits accordingly).

## License

Private project. Not affiliated with the Premier League or the official FPL game.
