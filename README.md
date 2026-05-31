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

As its final step on a fresh database it runs a **one-time history backfill +
model training** (`fpl bootstrap`: acquire all seasons → features → study →
freeze the model → predict) — this is what gives the app historical data and a
trained model to serve, so the install finishes with a working app rather than an
empty one. It's heavy (10–30+ min) and runs in the foreground by default (also
logged to `bootstrap.log`); the scheduler then keeps the current season fresh.

**Memory:** the bootstrap's study/freeze stages are the peak (~1GB/season + ~2GB
base; the full 6-season default ≈ 6GB). On ≤4GB it trains alone on the last 3
seasons, ≤6GB on 4, ≥8GB on all 6 — install.sh sizes this from `/proc/meminfo`.
Override with `FPL_BOOTSTRAP_YEARS=N ./install.sh …`, or train the full history
by hand with `fpl bootstrap --all-seasons` on a larger box. Give the VM ~8GB for
the full model; a 4GB box works but trains a slightly smaller one.

Re-running it is safe and idempotent: on a git checkout it first **fast-forwards
to the latest commit** (only when the tree is clean — never clobbering local
changes) and re-execs the updated installer, then updates deps/migrations in
place. When an install already exists it also **runs the freshly-pulled test
suite** (against the `_test` database) to confirm the build isn't hitting a
known, already-fixed bug — flagging `--reinstall` if anything fails.

Flags: `--with-scheduler` (install & start services), `--no-system-deps` (skip
apt/PostgreSQL/Node provisioning), `--bootstrap-bg` (run the backfill detached
instead of inline), `--no-bootstrap` (skip it), `--no-update` (don't auto-pull
the latest commit), `--verify` / `--no-verify` (force/skip the test-suite check),
`--reinstall` (wipe `.venv`/`node_modules`/`dist` and rebuild; keeps the data).

Requirements it installs for you (Debian/Ubuntu): **Python 3.11+**, **Node 18+**,
**PostgreSQL**. On other systems install those yourself, then run
`./install.sh --no-system-deps`.

## Running

```bash
# Production: whole app (UI + API) on all interfaces, one process.
# `served_app` serves the built frontend at / and the API under /api.
uvicorn fpl_engine.api.app:served_app --host 0.0.0.0 --port 8000
#   -> http://<host>:8000

# Development (frontend hot-reload): API + Vite dev server separately.
uvicorn fpl_engine.api.app:app --host 0.0.0.0 --port 8000   # API at root, /api proxied
cd frontend && npm run dev -- --host                         # UI on 0.0.0.0:5173
```

`served_app` requires the frontend to be built (`cd frontend && npm run build`,
which `install.sh` does). Bind to `0.0.0.0` (default in the systemd unit) to reach
it from other machines; use `127.0.0.1` to keep it local.

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
