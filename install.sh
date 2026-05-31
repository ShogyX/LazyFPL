#!/usr/bin/env bash
# LazyFPL installer — fire-and-forget.
#
#   git clone https://github.com/ShogyX/LazyFPL.git && cd LazyFPL && ./install.sh
#
# Detects and installs everything needed (system packages, Node 20, PostgreSQL +
# database, Python venv + deps), applies migrations, builds the frontend, and
# (with --with-scheduler) installs the auto-refresh service. Idempotent — safe to
# re-run. On Debian/Ubuntu it provisions system packages automatically (using
# sudo if not root); elsewhere it uses whatever is already installed.
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd)"

WITH_SCHEDULER=0
NO_SYSTEM_DEPS=0
BOOTSTRAP=auto      # auto = run only if no v1 model yet; on = force; off = skip
for arg in "$@"; do
  case "$arg" in
    --with-scheduler) WITH_SCHEDULER=1 ;;
    --no-system-deps) NO_SYSTEM_DEPS=1 ;;
    --bootstrap)      BOOTSTRAP=on ;;
    --bootstrap-bg)   BOOTSTRAP=bg ;;
    --no-bootstrap)   BOOTSTRAP=off ;;
    -h|--help)
      cat <<'USAGE'
Usage: ./install.sh [--with-scheduler] [--no-system-deps] [--bootstrap|--bootstrap-bg|--no-bootstrap]
  --with-scheduler   install & enable the auto-refresh + API services
  --no-system-deps   skip apt/PostgreSQL/Node provisioning (use what's installed)
  --bootstrap        force the one-time history backfill + model training (foreground)
  --bootstrap-bg     run that backfill detached (logs to bootstrap.log)
  --no-bootstrap     skip it (default: runs in the foreground when no model exists yet)
USAGE
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# --- privilege + package manager detection ---------------------------------
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi
fi
HAVE_APT=0; command -v apt-get >/dev/null 2>&1 && HAVE_APT=1
CAN_ELEVATE=1
if [ "$(id -u)" -ne 0 ] && [ -z "$SUDO" ]; then CAN_ELEVATE=0; fi

apt_get() { DEBIAN_FRONTEND=noninteractive $SUDO apt-get "$@"; }
APT_UPDATED=0
apt_install() {
  if [ "$APT_UPDATED" -eq 0 ]; then apt_get update -y >/dev/null 2>&1 || true; APT_UPDATED=1; fi
  apt_get install -y --no-install-recommends "$@"
}

PROVISION=1
if [ "$NO_SYSTEM_DEPS" -eq 1 ] || [ "$HAVE_APT" -eq 0 ] || [ "$CAN_ELEVATE" -eq 0 ]; then
  PROVISION=0
  [ "$HAVE_APT" -eq 0 ] && warn "Non-apt system: skipping auto system-dep install (using what's installed)."
  [ "$CAN_ELEVATE" -eq 0 ] && warn "Not root and no sudo: skipping system-dep install."
fi

# --- system packages --------------------------------------------------------
if [ "$PROVISION" -eq 1 ]; then
  info "Installing system packages (apt)"
  apt_install ca-certificates curl gnupg git build-essential pkg-config \
              python3 python3-venv python3-pip || warn "some base packages failed to install"
fi

command -v python3 >/dev/null 2>&1 || die "python3 not found (need >= 3.11)"
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PY_VER" in
  3.1[1-9]|3.[2-9]*|[4-9]*) : ;;
  *) die "Python $PY_VER found; this project needs >= 3.11" ;;
esac
info "Python $PY_VER OK"

# venv module (ensurepip) — Debian ships it separately, sometimes versioned.
if ! python3 -m ensurepip --version >/dev/null 2>&1; then
  if [ "$PROVISION" -eq 1 ]; then
    apt_install "python${PY_VER}-venv" || apt_install python3-venv || true
  fi
  python3 -m ensurepip --version >/dev/null 2>&1 || \
    die "Python venv support missing. Install it: sudo apt install -y python${PY_VER}-venv python3-pip"
fi

# --- Node 20 (frontend build) ----------------------------------------------
node_major() { command -v node >/dev/null 2>&1 && node -v | sed 's/v\([0-9]*\).*/\1/' || echo 0; }
if [ "$(node_major)" -lt 18 ]; then
  if [ "$PROVISION" -eq 1 ]; then
    info "Installing Node.js 20 (NodeSource)"
    if curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO -E bash - >/dev/null 2>&1; then
      apt_install nodejs || warn "nodejs install failed"
    else
      apt_install nodejs npm || warn "nodejs install failed"
    fi
  fi
  [ "$(node_major)" -lt 18 ] && warn "Node 18+ not available — the frontend build will be skipped."
fi

# --- PostgreSQL + database --------------------------------------------------
# Read the target DB from .env (or fall back to the default); auto-provision only
# when it points at localhost.
DB_URL_DEFAULT="postgresql+psycopg2://fpl:fpl@localhost:5432/fpl"
DB_URL="$DB_URL_DEFAULT"
if [ -f .env ]; then
  v="$(grep -E '^FPL_DATABASE_URL=' .env | tail -1 | cut -d= -f2-)"
  [ -n "${v:-}" ] && DB_URL="$v"
fi
read DB_USER DB_PASS DB_NAME DB_HOST <<EOF
$(python3 - "$DB_URL" <<'PY'
import sys, urllib.parse as u
x = u.urlparse(sys.argv[1].replace("+psycopg2", "").replace("+psycopg", ""))
print(x.username or "fpl", x.password or "fpl",
      (x.path or "/fpl").lstrip("/") or "fpl", x.hostname or "localhost")
PY
)
EOF

# Run a command AS the postgres OS user. As root there is no sudo, so use su;
# otherwise use sudo -u. ($SUDO -u postgres is wrong as root — "-u" is not a
# command — which previously left the role/db uncreated and the app unable to
# authenticate.)
#
# Always cd to /tmp first: the installer's CWD is often the clone under /root
# (mode 700), which the postgres user can't enter — that makes the shell print
# "could not change directory" and createdb/psql fail spuriously, so the role/db
# checks wrongly report "could not create".
if [ "$(id -u)" -eq 0 ]; then
  pg_run() { (cd /tmp && su -s /bin/sh postgres -c "$*"); }
elif [ -n "$SUDO" ]; then
  pg_run() { (cd /tmp && $SUDO -u postgres sh -c "$*"); }
else
  pg_run() { (cd /tmp && sh -c "$*"); }   # last resort: current user is the db superuser
fi

if [ "$PROVISION" -eq 1 ] && { [ "$DB_HOST" = "localhost" ] || [ "$DB_HOST" = "127.0.0.1" ]; }; then
  info "Ensuring PostgreSQL is installed and running"
  command -v psql >/dev/null 2>&1 || apt_install postgresql postgresql-contrib || warn "postgresql install failed"
  # Start the server (systemd, SysV, or pg_ctlcluster — whichever the box uses).
  $SUDO service postgresql start >/dev/null 2>&1 \
    || $SUDO systemctl start postgresql >/dev/null 2>&1 \
    || { ver="$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1)"; \
         [ -n "$ver" ] && $SUDO pg_ctlcluster "$ver" main start >/dev/null 2>&1; } \
    || warn "could not start postgresql automatically"

  if command -v psql >/dev/null 2>&1; then
    has() { [ "$(pg_run "psql -tAc \"$1\" 2>/dev/null")" = "1" ]; }
    info "Ensuring role '$DB_USER' and databases '$DB_NAME' / '${DB_NAME}_test'"
    has "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" \
      || pg_run "psql -c \"CREATE ROLE \\\"${DB_USER}\\\" LOGIN PASSWORD '${DB_PASS}';\"" >/dev/null 2>&1 \
      || warn "could not create role ${DB_USER}"
    # Always (re)set the password + LOGIN so it matches FPL_DATABASE_URL even if
    # the role already existed from a prior run (the apt cluster persists).
    pg_run "psql -c \"ALTER ROLE \\\"${DB_USER}\\\" WITH LOGIN PASSWORD '${DB_PASS}';\"" >/dev/null 2>&1 \
      || warn "could not set password for role ${DB_USER}"
    for db in "$DB_NAME" "${DB_NAME}_test"; do
      has "SELECT 1 FROM pg_database WHERE datname='${db}'" \
        || pg_run "createdb -O '${DB_USER}' -E UTF8 -T template0 --lc-collate=C --lc-ctype=C '${db}'" >/dev/null 2>&1 \
        || warn "could not create db ${db}"
    done
  fi
fi

# --- backend: virtualenv + deps --------------------------------------------
if [ ! -x .venv/bin/python3 ] || ! .venv/bin/python3 -m pip --version >/dev/null 2>&1; then
  info "Creating virtualenv (.venv)"
  rm -rf .venv
  python3 -m venv .venv || die "venv creation failed — sudo apt install -y python${PY_VER}-venv python3-pip"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
info "Installing Python dependencies (editable, with dev extras)"
python -m pip install --upgrade pip >/dev/null
pip install -e ".[dev]"

# --- env file ---------------------------------------------------------------
if [ ! -f .env ]; then
  info "Creating .env from .env.example"
  cp .env.example .env
else
  info ".env already present — leaving it untouched"
fi

# --- migrations -------------------------------------------------------------
MIGRATED=0
if alembic upgrade head >/dev/null 2>&1; then
  info "Applied database migrations (alembic upgrade head)"
  MIGRATED=1
else
  warn "Migrations failed — check PostgreSQL is running and FPL_DATABASE_URL in .env, then: alembic upgrade head"
fi

# Decide whether the one-time backfill is needed (the actual run happens at the
# end, once the UI + services are set up). A fresh DB has no historical data and
# no trained model, so without this the app comes up empty.
DO_BOOTSTRAP=0
if [ "$MIGRATED" -eq 1 ] && [ "$BOOTSTRAP" != "off" ]; then
  HAVE_MODEL="$(python - <<'PY' 2>/dev/null || echo 0
from sqlalchemy import create_engine, text
from fpl_engine.config import get_settings
try:
    e = create_engine(get_settings().database_url)
    with e.connect() as c:
        print(c.execute(text("select count(*) from study.model_registry where version='v1'")).scalar())
except Exception:
    print(0)
PY
)"
  if [ "$BOOTSTRAP" = "on" ] || [ "$BOOTSTRAP" = "bg" ] || [ "${HAVE_MODEL:-0}" = "0" ]; then
    DO_BOOTSTRAP=1
  else
    info "Model already trained (study.model_registry has v1) — skipping bootstrap."
  fi
fi

# --- frontend ---------------------------------------------------------------
if [ "$(node_major)" -ge 18 ] && command -v npm >/dev/null 2>&1; then
  info "Installing frontend dependencies + building"
  ( cd frontend && npm install --no-audit --no-fund && npm run build )
else
  warn "Node 18+ / npm not available — skipping frontend build. Install Node 18+, then: cd frontend && npm install && npm run build"
fi

# --- systemd services -------------------------------------------------------
info "Writing systemd unit templates to deploy/"
mkdir -p deploy
FPL_BIN="$REPO_DIR/.venv/bin/fpl"
UVICORN_BIN="$REPO_DIR/.venv/bin/uvicorn"
SVC_USER="${SUDO_USER:-$(id -un)}"

write_unit() {  # $1=path  $2=description  $3=ExecStart  [system]
  local user_line=""
  [ "${4:-}" = "system" ] && [ "$SVC_USER" != "root" ] && user_line="User=$SVC_USER"
  cat > "$1" <<EOF
[Unit]
Description=$2
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
$user_line
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStart=$3
Restart=on-failure
RestartSec=10

[Install]
WantedBy=${5:-default.target}
EOF
}
write_unit deploy/lazyfpl-scheduler.service "LazyFPL scheduler (auto data + prediction refresh)" "$FPL_BIN schedule" system multi-user.target
write_unit deploy/lazyfpl-api.service "LazyFPL app (UI + API)" "$UVICORN_BIN fpl_engine.api.app:served_app --host 0.0.0.0 --port 8000" system multi-user.target

# Install + enable the systemd services. Defined here but invoked AFTER the
# one-time bootstrap so training isn't starved of RAM/CPU/DB by the always-on
# API and the scheduler's hourly ingest (a real stall risk on 8GB boxes).
enable_services() {
  [ "$WITH_SCHEDULER" -eq 1 ] || return 0
  if command -v systemctl >/dev/null 2>&1 && [ "$CAN_ELEVATE" -eq 1 ] && systemctl >/dev/null 2>&1; then
    info "Installing & enabling system services: lazyfpl-scheduler, lazyfpl-api"
    $SUDO cp deploy/lazyfpl-scheduler.service deploy/lazyfpl-api.service /etc/systemd/system/
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now lazyfpl-scheduler.service lazyfpl-api.service \
      && info "Services up. Status: systemctl status lazyfpl-scheduler lazyfpl-api" \
      || warn "could not enable services (no systemd? run 'fpl schedule' manually)"
  else
    warn "systemd not available — run manually: source .venv/bin/activate && fpl schedule"
    warn "(System units are in deploy/ for later: sudo cp deploy/*.service /etc/systemd/system/)"
  fi
}

# --- one-time history backfill + model training ----------------------------
# The app needs historical data and a trained model to be useful. It's heavy
# (10-30+ min) so we run it BEFORE starting the services: on small (8GB) hosts
# the always-on API plus the scheduler's hourly ingest otherwise contend for
# RAM/CPU/DB and make training crawl — which looks like a hang. Foreground
# bootstrap → then services (so the API serves a trained model immediately).
# --bootstrap-bg explicitly opts into a detached run alongside the services.
if [ "$DO_BOOTSTRAP" -eq 1 ] && [ "$BOOTSTRAP" != "bg" ]; then
  info "Backfilling all seasons + training the model (one-time, 10-30+ min; runs alone before services start)…"
  fpl bootstrap | tee -a "$REPO_DIR/bootstrap.log" || warn "bootstrap reported errors — see bootstrap.log; you can re-run: fpl bootstrap"
fi

enable_services

if [ "$DO_BOOTSTRAP" -eq 1 ] && [ "$BOOTSTRAP" = "bg" ]; then
  info "Backfilling history + training the model in the background -> bootstrap.log"
  nohup "$REPO_DIR/.venv/bin/fpl" bootstrap >>"$REPO_DIR/bootstrap.log" 2>&1 &
  info "Running detached (10-30+ min). Watch it: tail -f $REPO_DIR/bootstrap.log"
  [ "$WITH_SCHEDULER" -eq 1 ] && command -v systemctl >/dev/null 2>&1 \
    && warn "When bootstrap.log shows completion, load the model: sudo systemctl restart lazyfpl-api"
fi

cat <<EOF

Done. To run manually (if you didn't use --with-scheduler):

  source .venv/bin/activate
  # Whole app (UI + API) on all interfaces, port 8000:
  uvicorn fpl_engine.api.app:served_app --host 0.0.0.0 --port 8000
  fpl schedule                                      # auto data + prediction refresh

  # Or, for frontend hot-reload during development (UI on :5173, API on :8000):
  uvicorn fpl_engine.api.app:app --host 0.0.0.0 --port 8000
  cd frontend && npm run dev -- --host

First data load: the scheduler fills predictions within a gameweek cycle, or run
'fpl refresh' once now. Edit .env for optional API keys / notifications.
EOF
