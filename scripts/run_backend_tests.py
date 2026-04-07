from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"
    os.chdir(backend_dir)
    sys.path.insert(0, str(backend_dir))

    try:
        import pytest
    except ImportError as exc:
        print(
            "pytest is not installed. Install backend dev dependencies first with:\n"
            "  pip install -r backend/requirements-dev.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    return pytest.main(["tests"])


if __name__ == "__main__":
    raise SystemExit(main())
