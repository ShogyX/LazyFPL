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
for arg in "$@"; do
  case "$arg" in
    --with-scheduler) WITH_SCHEDULER=1 ;;
    --no-system-deps) NO_SYSTEM_DEPS=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: ./install.sh [--with-scheduler] [--no-system-deps]
  --with-scheduler   install & enable the auto-refresh + API services
  --no-system-deps   skip apt/PostgreSQL/Node provisioning (use what's installed)
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
    psql_su() { $SUDO -u postgres psql -tAc "$1" 2>/dev/null; }
    info "Ensuring role '$DB_USER' and databases '$DB_NAME' / '${DB_NAME}_test'"
    if [ "$(psql_su "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'")" != "1" ]; then
      $SUDO -u postgres psql -c "CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASS}';" >/dev/null 2>&1 \
        || warn "could not create role ${DB_USER}"
    fi
    for db in "$DB_NAME" "${DB_NAME}_test"; do
      if [ "$(psql_su "SELECT 1 FROM pg_database WHERE datname='${db}'")" != "1" ]; then
        # Force UTF8 via template0 — FPL data has non-ASCII names; a SQL_ASCII
        # database (the default on C/POSIX-locale boxes) would reject them.
        $SUDO -u postgres createdb -O "$DB_USER" -E UTF8 -T template0 \
              --lc-collate=C --lc-ctype=C "$db" >/dev/null 2>&1 \
          || warn "could not create db ${db}"
      fi
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
if alembic upgrade head >/dev/null 2>&1; then
  info "Applied database migrations (alembic upgrade head)"
else
  warn "Migrations failed — check PostgreSQL is running and FPL_DATABASE_URL in .env, then: alembic upgrade head"
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

if [ "$WITH_SCHEDULER" -eq 1 ]; then
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
