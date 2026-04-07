from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"
    sys.path.insert(0, str(backend_dir))
    os.chdir(backend_dir)

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Draco FastAPI backend.")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload for local development.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "18082")))
    args = parser.parse_args()

    if not port_available(args.host, args.port):
        print(
            f"[draco-backend] Port {args.port} on {args.host} is already in use.\n"
            f"Choose another port with --port or stop the process using that port first.",
            file=sys.stderr,
        )
        return 1

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
