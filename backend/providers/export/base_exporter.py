"""Base exporter utilities shared by all export format providers."""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def create_zip(source_dir: Path, output_path: Path) -> Path:
    """Zip a directory. Returns the zip path."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in source_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(source_dir.parent))
    return output_path


def sanitize_filename(name: str) -> str:
    """Remove characters unsafe for filenames."""
    unsafe = set('<>:"/\\|?*\x00')
    return "".join(c if c not in unsafe else "_" for c in name)
