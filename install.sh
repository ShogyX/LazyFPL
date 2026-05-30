#!/usr/bin/env bash
# LazyFPL installer: sets up the Python backend and the React frontend.
# Idempotent — safe to re-run. Does not start any servers or touch your DB data
# beyond (optionally) applying migrations when a database is reachable.
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd)"

WITH_SCHEDULER=0
for arg in "$@"; do
  case "$arg" in
    --with-scheduler) WITH_SCHEDULER=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--with-scheduler]"
      echo "  --with-scheduler   also install & enable a systemd --user service that"
      echo "                     runs 'fpl schedule' (auto data + prediction refresh)."
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

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

# --- systemd unit templates -------------------------------------------------
# The scheduler ('fpl schedule') is what makes data + prediction refresh
# hands-off: it runs the hourly ingest, the 6-hourly prediction rebuild, and the
# change-driven triggers. We generate user-level unit files pinned to this repo.
info "Writing systemd unit templates to deploy/"
mkdir -p deploy
FPL_BIN="$REPO_DIR/.venv/bin/fpl"
UVICORN_BIN="$REPO_DIR/.venv/bin/uvicorn"

cat > deploy/lazyfpl-scheduler.service <<EOF
[Unit]
Description=LazyFPL scheduler (auto data + prediction refresh)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStart=$FPL_BIN schedule
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

cat > deploy/lazyfpl-api.service <<EOF
[Unit]
Description=LazyFPL read API
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStart=$UVICORN_BIN fpl_engine.api.app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

if [ "$WITH_SCHEDULER" -eq 1 ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    info "Installing & enabling systemd --user service: lazyfpl-scheduler"
    mkdir -p "$HOME/.config/systemd/user"
    cp deploy/lazyfpl-scheduler.service "$HOME/.config/systemd/user/"
    cp deploy/lazyfpl-api.service "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    systemctl --user enable --now lazyfpl-scheduler.service
    warn "Enable lingering so it runs without an active login: sudo loginctl enable-linger \"$USER\""
    info "Scheduler status: systemctl --user status lazyfpl-scheduler"
  else
    warn "systemd --user not available here. Run the scheduler manually: source .venv/bin/activate && fpl schedule"
    warn "(Templates are in deploy/ for system-wide install: sudo cp deploy/*.service /etc/systemd/system/ && sudo systemctl enable --now lazyfpl-scheduler)"
  fi
fi

cat <<EOF

Done. To run:

  # backend  (http://localhost:8000)
  source .venv/bin/activate
  uvicorn fpl_engine.api.app:app --reload --port 8000

  # frontend (http://localhost:5173)
  cd frontend && npm run dev

  # automatic data + prediction refresh (blocking; or use the service below)
  source .venv/bin/activate && fpl schedule

Hands-off scheduling:
  Re-run with --with-scheduler to install a systemd --user service, or use the
  generated unit files in deploy/. Manual one-off refresh: 'fpl refresh'.

Edit .env to configure the database and optional API keys.
EOF
