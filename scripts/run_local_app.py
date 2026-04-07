from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def ensure_env_file(example_path: Path, target_path: Path) -> None:
    if target_path.exists() or not example_path.exists():
        return
    target_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[launcher] Created {target_path.relative_to(target_path.parent.parent if target_path.parent.parent.exists() else target_path.parent)} from example")


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(host: str, preferred_port: int, limit: int = 20) -> int:
    for offset in range(limit):
        port = preferred_port + offset
        if is_port_available(host, port):
            return port
    raise RuntimeError(f"Could not find a free port near {preferred_port}")


def http_ready(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def draco_backend_ready(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return payload.get("status") == "ok" and payload.get("database") is True
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def npm_command() -> str:
    candidates = ["npm.cmd", "npm"] if os.name == "nt" else ["npm"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("npm is not available on PATH. Install Node.js and npm first.")


def start_logged_process(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> subprocess.Popen[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def _pump() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                text = line.rstrip()
                print(f"[{name}] {text}")
                log_file.write(line)
                log_file.flush()
        finally:
            log_file.close()

    threading.Thread(target=_pump, daemon=True).start()
    return process


def read_log_tail(log_path: Path, lines: int = 20) -> str:
    if not log_path.exists():
        return ""
    try:
        contents = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(contents[-lines:])


def run_startup_diagnostics(repo_root: Path) -> None:
    diagnostics_script = repo_root / "scripts" / "model_health.py"
    if not diagnostics_script.exists():
        return
    print("[launcher] Checking local model/provider readiness...")
    try:
        completed = subprocess.run(
            [sys.executable, str(diagnostics_script)],
            cwd=str(repo_root),
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[launcher] Could not run model readiness checks: {exc}")
        return

    output = (completed.stdout or "").strip()
    error_output = (completed.stderr or "").strip()
    if output:
        print(output)
    if error_output:
        print(error_output, file=sys.stderr)
    if completed.returncode != 0:
        print(
            "[launcher] Local model diagnostics were incomplete. Draco can still run, "
            "but optional providers may need extra setup.",
            file=sys.stderr,
        )


def startup_hint_from_log(log_tail: str, process_name: str) -> str | None:
    lowered = log_tail.lower()
    if "modulenotfounderror" in lowered or "no module named" in lowered:
        if process_name == "backend":
            return "Backend dependencies look incomplete. Try: pip install -r backend/requirements-dev.txt"
        return "Frontend dependencies look incomplete. Try: npm install and npm install --prefix frontend"
    if "alembic" in lowered and "can't locate revision" in lowered:
        return "Database migrations are out of date. Try: cd backend && alembic upgrade head"
    if "address already in use" in lowered:
        return "A required port is already busy. Restart with --backend-port/--frontend-port or stop the conflicting process."
    if "'vite' is not recognized" in lowered or "vite: not found" in lowered:
        return "Frontend dependencies are missing. Try: npm install --prefix frontend"
    return None


def format_failure_details(name: str, log_path: Path) -> str:
    log_tail = read_log_tail(log_path)
    details = [f"Check {log_path} for startup logs."]
    hint = startup_hint_from_log(log_tail, name)
    if hint:
        details.append(hint)
    if log_tail:
        details.append("Recent log output:")
        details.append(log_tail)
    return " ".join(details[:2]) + (f"\n{details[2]}\n{details[3]}" if len(details) > 2 else "")


def wait_for_url(
    url: str,
    *,
    timeout_seconds: float,
    ready_check,
    process: subprocess.Popen[str] | None = None,
    name: str,
    log_path: Path | None = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready_check(url):
            return
        if process is not None and process.poll() is not None:
            message = f"{name} exited early with code {process.returncode}."
            if log_path is not None:
                message += f" {format_failure_details(name, log_path)}"
            raise RuntimeError(message)
        time.sleep(0.5)
    message = f"Timed out waiting for {name} to become ready at {url}."
    if log_path is not None:
        message += f" {format_failure_details(name, log_path)}"
    raise RuntimeError(message)


def terminate_process(process: subprocess.Popen[str] | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"[launcher] Stopping {name}...")
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Draco locally and open it in a browser.")
    parser.add_argument("--backend-port", type=int, default=18082)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true", help="Enable backend autoreload.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "frontend"
    logs_dir = repo_root / ".logs" / "launch"
    logs_dir.mkdir(parents=True, exist_ok=True)

    ensure_env_file(repo_root / ".env.example", repo_root / ".env")
    ensure_env_file(frontend_dir / ".env.example", frontend_dir / ".env")

    npm = npm_command()

    backend_health_url = f"http://{args.host}:{args.backend_port}/api/health"
    frontend_url = f"http://{args.host}:{args.frontend_port}"

    backend_process: subprocess.Popen[str] | None = None
    frontend_process: subprocess.Popen[str] | None = None

    backend_port = args.backend_port
    if draco_backend_ready(backend_health_url):
        print(f"[launcher] Reusing existing Draco backend at {backend_health_url}")
    else:
        if not is_port_available(args.host, backend_port):
            replacement = find_free_port(args.host, backend_port + 1)
            print(
                f"[launcher] Backend port {backend_port} is busy with another process; using {replacement} instead."
            )
            backend_port = replacement
            backend_health_url = f"http://{args.host}:{backend_port}/api/health"

        backend_log = logs_dir / "backend.log"
        backend_command = [
            sys.executable,
            str(repo_root / "scripts" / "run_backend.py"),
            "--host",
            args.host,
            "--port",
            str(backend_port),
        ]
        if args.reload:
            backend_command.append("--reload")

        print(f"[launcher] Starting backend on http://{args.host}:{backend_port}")
        backend_process = start_logged_process(
            "backend",
            backend_command,
            cwd=repo_root,
            env=os.environ.copy(),
            log_path=backend_log,
        )
        wait_for_url(
            backend_health_url,
            timeout_seconds=60,
            ready_check=draco_backend_ready,
            process=backend_process,
            name="backend",
            log_path=backend_log,
        )
        print(f"[launcher] Backend is healthy at {backend_health_url}")

    run_startup_diagnostics(repo_root)

    frontend_port = args.frontend_port
    if not is_port_available(args.host, frontend_port):
        replacement = find_free_port(args.host, frontend_port + 1)
        print(
            f"[launcher] Frontend port {frontend_port} is busy; using {replacement} instead."
        )
        frontend_port = replacement
    frontend_url = f"http://{args.host}:{frontend_port}"

    frontend_log = logs_dir / "frontend.log"
    frontend_env = os.environ.copy()
    frontend_env["VITE_API_URL"] = f"http://{args.host}:{backend_port}"
    frontend_env["BROWSER"] = "none"

    print(f"[launcher] Starting frontend on {frontend_url}")
    frontend_process = start_logged_process(
        "frontend",
        [
            npm,
            "--prefix",
            str(frontend_dir),
            "run",
            "dev",
            "--",
            "--host",
            args.host,
            "--port",
            str(frontend_port),
            "--strictPort",
        ],
        cwd=repo_root,
        env=frontend_env,
        log_path=frontend_log,
    )
    wait_for_url(
        frontend_url,
        timeout_seconds=60,
        ready_check=http_ready,
        process=frontend_process,
        name="frontend",
        log_path=frontend_log,
    )
    print(f"[launcher] Frontend is ready at {frontend_url}")

    if not args.no_open:
        print(f"[launcher] Opening {frontend_url}")
        try:
            opened = webbrowser.open(frontend_url)
        except webbrowser.Error as exc:
            print(
                f"[launcher] Could not open a browser automatically: {exc}. Open {frontend_url} manually.",
                file=sys.stderr,
            )
        else:
            if not opened:
                print(
                    f"[launcher] Browser auto-open was not supported in this environment. Open {frontend_url} manually.",
                    file=sys.stderr,
                )

    print("[launcher] Draco is running. Press Ctrl+C to stop both processes.")

    stop_event = threading.Event()

    def _handle_signal(signum, frame) -> None:  # type: ignore[override]
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not stop_event.is_set():
            if backend_process is not None and backend_process.poll() is not None:
                raise RuntimeError(
                    f"Backend exited unexpectedly with code {backend_process.returncode}. "
                    f"{format_failure_details('backend', logs_dir / 'backend.log')}"
                )
            if frontend_process is not None and frontend_process.poll() is not None:
                raise RuntimeError(
                    f"Frontend exited unexpectedly with code {frontend_process.returncode}. "
                    f"{format_failure_details('frontend', logs_dir / 'frontend.log')}"
                )
            time.sleep(0.5)
    except RuntimeError as exc:
        print(f"[launcher] {exc}", file=sys.stderr)
        return_code = 1
    else:
        return_code = 0
    finally:
        terminate_process(frontend_process, "frontend")
        terminate_process(backend_process, "backend")
        if return_code == 0:
            print("[launcher] Shutdown complete.")

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
