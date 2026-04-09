#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${GREEN}[draco]${NC} $*"; }
warning() { echo -e "${YELLOW}[draco]${NC} $*"; }
error()   { echo -e "${RED}[draco]${NC} $*" >&2; }

# ── Check deps ────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
  error "Python not found. Install Python 3.11+."
  exit 1
fi

PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python $PY_VERSION found at $PYTHON"

# Require Python 3.11+
"$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
  error "Python 3.11 or newer is required (found $PY_VERSION)."
  exit 1
fi

if ! command -v node &>/dev/null; then
  error "Node.js not found. Install Node.js 18+."
  exit 1
fi
info "Node.js $(node --version) found"

# ── Install backend deps ───────────────────────────────────────────────────────
VENV_DIR="backend/.venv"
VENV_PY="$VENV_DIR/bin/python"

if [ ! -f "$VENV_PY" ]; then
  info "Creating backend virtual environment..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

if [ ! -f "$VENV_DIR/.deps.ok" ] || [ backend/requirements.txt -nt "$VENV_DIR/.deps.ok" ]; then
  info "Installing backend dependencies..."
  "$VENV_PY" -m pip install -r backend/requirements.txt
  touch "$VENV_DIR/.deps.ok"
else
  info "Backend dependencies up to date"
fi

# ── Install frontend deps ──────────────────────────────────────────────────────
if [ ! -d frontend/node_modules ] || [ frontend/package.json -nt frontend/node_modules/.package-lock.json 2>/dev/null ]; then
  info "Installing frontend dependencies..."
  cd frontend && npm install --silent && cd ..
else
  info "Frontend dependencies up to date"
fi

# ── Enable DEBUG mode for local desktop use ────────────────────────────────────
export DEBUG="${DEBUG:-true}"

# ── Run migrations (skip if no alembic or if DEBUG auto-creates tables) ────────
if [ -f backend/alembic.ini ] && [ "$DEBUG" != "true" ]; then
  info "Running database migrations..."
  cd backend && "$PYTHON" -m alembic upgrade head 2>&1 | tail -5 && cd ..
else
  info "Database will auto-create tables in DEBUG mode"
fi

# ── Create .env if missing ────────────────────────────────────────────────────
if [ ! -f .env ]; then
  warning ".env not found — copying from .env.example"
  cp .env.example .env 2>/dev/null || true
fi

# ── Start servers ──────────────────────────────────────────────────────────────
info "Starting Draco Studio..."
info "  Backend:  http://127.0.0.1:18082"
info "  Frontend: http://127.0.0.1:5173"
info "  Press Ctrl+C to stop both servers"
echo ""

cleanup() {
  info "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

cd backend && "$SCRIPT_DIR/$VENV_DIR/bin/python" -m uvicorn main:app --host 127.0.0.1 --port 18082 --reload &
BACKEND_PID=$!
cd "$SCRIPT_DIR"

cd frontend && npm run dev -- --host 127.0.0.1 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

wait "$BACKEND_PID" "$FRONTEND_PID"
