@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Draco Dataset Studio v6

echo ============================================================
echo   Draco Dataset Studio - Local Launcher (Windows)
echo ============================================================
echo.

:: ── Check Python ────────────────────────────────────────────
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
  for /f "tokens=*" %%i in ('py -3 -c "import sys; print(sys.executable)"  2^>nul') do set "PY=%%i"
)
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 (
    for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%i"
  )
)
if not defined PY (
  echo [ERROR] Python 3.11+ is required but not found on PATH.
  echo         Install from https://www.python.org/downloads/
  pause
  exit /b 1
)

"%PY%" -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.11 or newer is required.
  pause
  exit /b 1
)
echo [OK] Python: %PY%

:: ── Check Node/npm ──────────────────────────────────────────
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm is required but not found on PATH.
  echo         Install Node.js 18+ from https://nodejs.org/
  pause
  exit /b 1
)
echo [OK] npm found

:: ── Backend venv ────────────────────────────────────────────
set "VENV=backend\.venv"
set "VENV_PY=%CD%\%VENV%\Scripts\python.exe"
set "VENV_PIP=%CD%\%VENV%\Scripts\pip.exe"

if not exist "%VENV_PY%" (
  echo [SETUP] Creating backend virtual environment...
  "%PY%" -m venv "%VENV%"
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
)

:: ── Install backend deps ────────────────────────────────────
if not exist "%VENV%\.deps.ok" (
  echo [SETUP] Installing backend dependencies (first run, may take a few minutes)...
  echo [SETUP]   Please wait - do not close this window.
  "%VENV_PY%" -m pip install --disable-pip-version-check -r backend\requirements.txt
  if errorlevel 1 (
    echo [ERROR] Backend dependency install failed.
    pause
    exit /b 1
  )
  echo ok > "%VENV%\.deps.ok"
)
echo [OK] Backend dependencies installed

:: ── Install frontend deps ───────────────────────────────────
if not exist "frontend\node_modules" (
  echo [SETUP] Installing frontend dependencies...
  pushd frontend
  call npm install
  if errorlevel 1 (
    popd
    echo [ERROR] Frontend dependency install failed.
    pause
    exit /b 1
  )
  popd
)
echo [OK] Frontend dependencies installed

:: ── Create data directories ─────────────────────────────────
if not exist "backend\data\storage" mkdir "backend\data\storage"
if not exist "backend\data\qdrant" mkdir "backend\data\qdrant"

:: ── Launch ──────────────────────────────────────────────────
echo.
echo ============================================================
echo   Starting Draco Dataset Studio
echo   Backend:  http://127.0.0.1:18082
echo   Frontend: http://localhost:5173  (dev mode)
echo   Press Ctrl+C to stop
echo ============================================================
echo.

:: ── Ensure DEBUG mode for local desktop use ─────────────────
if not defined DEBUG set "DEBUG=true"

:: Start backend in background — write a temp launcher to avoid nested-quote issues
set "BACKEND_DIR=%CD%\backend"
set "BACKEND_PY=%CD%\%VENV%\Scripts\python.exe"
set "_LAUNCHER=%TEMP%\draco_backend_launch.bat"
(
  echo @echo off
  echo cd /d "%BACKEND_DIR%"
  echo set "DEBUG=%DEBUG%"
  echo "%BACKEND_PY%" -m uvicorn main:app --host 127.0.0.1 --port 18082
) > "%_LAUNCHER%"
start "Draco Backend" /min cmd /c ""%_LAUNCHER%""

:: Wait a moment for backend to start
timeout /t 2 /nobreak >nul

:: Start frontend dev server (foreground, bound to localhost only)
pushd frontend
call npx vite --host 127.0.0.1
popd

:: When frontend is closed, also kill backend
taskkill /fi "WINDOWTITLE eq Draco Backend" >nul 2>&1

echo.
echo Draco Dataset Studio stopped.
pause
