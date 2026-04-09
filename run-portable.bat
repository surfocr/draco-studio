@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Draco Dataset Studio

echo [draco] Preparing Draco Dataset Studio...

call :resolve_python || goto :failed
call :ensure_node || goto :failed
call :ensure_backend || goto :failed
call :ensure_frontend || goto :failed

echo [draco] Checking optional local model support...
"%VENV_PYTHON%" scripts\model_health.py
if errorlevel 1 (
  echo [draco] Optional model checks were incomplete. Draco can still run.
)

echo [draco] Launching Draco...

rem ── Ensure DEBUG mode is on for local desktop use (skips Alembic check, uses create_all) ──
if not defined DEBUG set "DEBUG=true"

"%VENV_PYTHON%" scripts\run_local_app.py %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [draco] Draco exited with code %EXIT_CODE%.
  goto :failed_exit
)
goto :done

:resolve_python
set "HOST_PYTHON="
where py >nul 2>&1
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    if not defined HOST_PYTHON (
      py -%%V -c "import sys" >nul 2>&1
      if not errorlevel 1 set "HOST_PYTHON=py -%%V"
    )
  )
)
if not defined HOST_PYTHON (
  where python >nul 2>&1
  if not errorlevel 1 (
    set "HOST_PYTHON=python"
  )
)
if not defined HOST_PYTHON (
  echo [draco] Python 3.11+ was not found on PATH.
  echo [draco] Install Python 3.11 or newer, then rerun this launcher.
  exit /b 1
)

%HOST_PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [draco] Draco requires Python 3.11 or newer.
  exit /b 1
)

set "VENV_DIR=backend\.venv"
set "VENV_PYTHON=%CD%\%VENV_DIR%\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
  echo [draco] Creating backend virtual environment...
  %HOST_PYTHON% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [draco] Failed to create the backend virtual environment.
    exit /b 1
  )
)
exit /b 0

:ensure_node
where npm >nul 2>&1
if errorlevel 1 (
  echo [draco] npm was not found on PATH.
  echo [draco] Install Node.js 20+ and npm, then rerun this launcher.
  exit /b 1
)
exit /b 0

:ensure_backend
if exist "backend\.venv\.bootstrap.ok" exit /b 0

echo [draco] Installing backend dependencies...
echo [draco]   This may take several minutes on first run (downloading AI/ML packages).
echo [draco]   Please wait - do not close this window.
echo.
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 (
  echo [draco] Backend dependency installation failed.
  exit /b 1
)
>"backend\.venv\.bootstrap.ok" echo ok
echo [draco]   Backend dependencies installed successfully.
exit /b 0

:ensure_frontend
if exist "frontend\node_modules" exit /b 0

echo [draco] Installing frontend dependencies...
call npm --prefix frontend install
if errorlevel 1 (
  echo [draco] Frontend dependency installation failed.
  exit /b 1
)
exit /b 0

:failed
echo.
echo [draco] Startup could not continue.
pause
exit /b 1

:failed_exit
pause
exit /b %EXIT_CODE%

:done
exit /b 0
