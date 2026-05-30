#!/usr/bin/env bash
# LazyFPL installer: sets up the Python backend and the React frontend.
# Idempotent — safe to re-run. Does not start any servers or touch your DB data
# beyond (optionally) applying migrations when a database is reachable.
set -euo pipefail

cd "$(dirname "$0")"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# --- prerequisites ----------------------------------------------------------
command -v python3 >/dev/null 2>&1 || die "python3 not found (need >= 3.11)"
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PY_VER" in
  3.1[1-9]|3.[2-9]*|[4-9]*) : ;;
  *) die "Python $PY_VER found; this project needs >= 3.11" ;;
esac
info "Python $PY_VER OK"

# --- backend: virtualenv + deps --------------------------------------------
if [ ! -d .venv ]; then
  info "Creating virtualenv (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
info "Installing Python dependencies (editable, with dev extras)"
python -m pip install --upgrade pip >/dev/null
pip install -e ".[dev]"

# --- env file ---------------------------------------------------------------
if [ ! -f .env ]; then
  info "Creating .env from .env.example (fill in your values)"
  cp .env.example .env
else
  info ".env already present — leaving it untouched"
fi

# --- migrations (best-effort; needs a reachable Postgres) -------------------
if alembic upgrade head >/dev/null 2>&1; then
  info "Applied database migrations (alembic upgrade head)"
else
  warn "Skipped migrations — database not reachable. Start Postgres, set FPL_DATABASE_URL in .env, then run: alembic upgrade head"
fi

# --- frontend ---------------------------------------------------------------
if command -v npm >/dev/null 2>&1; then
  info "Installing frontend dependencies"
  ( cd frontend && npm install --no-audit --no-fund )
  info "Building frontend"
  ( cd frontend && npm run build )
else
  warn "npm not found — skipping frontend. Install Node 18+ then: cd frontend && npm install && npm run build"
fi

cat <<'EOF'

Done. To run:

  # backend  (http://localhost:8000)
  source .venv/bin/activate
  uvicorn fpl_engine.api.app:app --reload --port 8000

  # frontend (http://localhost:5173)
  cd frontend && npm run dev

Edit .env to configure the database and optional API keys.
EOF
