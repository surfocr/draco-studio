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

if ! command -v node &>/dev/null; then
  error "Node.js not found. Install Node.js 18+."
  exit 1
fi
info "Node.js $(node --version) found"

# ── Install backend deps ───────────────────────────────────────────────────────
if [ ! -f backend/.deps_installed ] || [ backend/requirements.txt -nt backend/.deps_installed ]; then
  info "Installing backend dependencies..."
  "$PYTHON" -m pip install -r backend/requirements.txt --quiet
  touch backend/.deps_installed
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

# ── Run migrations ─────────────────────────────────────────────────────────────
info "Running database migrations..."
cd backend && "$PYTHON" -m alembic upgrade head 2>&1 | tail -5 && cd ..

# ── Create .env if missing ────────────────────────────────────────────────────
if [ ! -f .env ]; then
  warning ".env not found — copying from .env.example"
  cp .env.example .env 2>/dev/null || true
fi

# ── Start servers ──────────────────────────────────────────────────────────────
info "Starting Draco Studio..."
info "  Backend:  http://localhost:8000"
info "  Frontend: http://localhost:5173"
info "  Press Ctrl+C to stop both servers"
echo ""

cleanup() {
  info "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

cd backend && "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd "$SCRIPT_DIR"

cd frontend && npm run dev &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

wait "$BACKEND_PID" "$FRONTEND_PID"
