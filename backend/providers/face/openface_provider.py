"""OpenFace head pose and action unit provider (subprocess-based)."""
from __future__ import annotations
import asyncio, json, os, shutil, tempfile, time
from pathlib import Path
from typing import Optional, Dict, Any
from providers.base import HeadPoseProvider, ActionUnitProvider

class OpenFaceProvider(HeadPoseProvider, ActionUnitProvider):
    """OpenFace 2.2 head pose estimation and facial action unit extraction.

    Requires OpenFace to be installed and `FeatureExtraction` executable on PATH.
    Falls back gracefully if not available.
    """

    provider_id = "openface"
    display_name = "OpenFace 2.2"
    provider_type = "head_pose"

    name = "openface"
    version = "2.2"

    def __init__(self, executable: str = "FeatureExtraction", **kwargs):
        self.executable = executable
        self._available: Optional[bool] = None

    def _check_available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(self.executable) is not None
        return self._available

    async def is_available(self) -> bool:
        return self._check_available()

    async def _run_openface(self, image_path: str) -> Optional[Dict[str, Any]]:
        """Run OpenFace on a single image, return parsed CSV result."""
        if not self._check_available():
            return None
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                self.executable,
                "-f", image_path,
                "-out_dir", tmpdir,
                "-2Dfp",  # 2D facial landmarks
                "-3Dfp",  # 3D facial landmarks
                "-pose",  # head pose
                "-aus",   # action units
                "-quiet",
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=30)
            except (asyncio.TimeoutError, Exception):
                return None

            # Find output CSV
            csv_files = list(Path(tmpdir).glob("*.csv"))
            if not csv_files:
                return None
            import csv
            with open(csv_files[0]) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if not rows:
                return None
            return {k.strip(): v.strip() for k, v in rows[0].items()}

    async def estimate_head_pose(self, image_path: str,
                                  options: Optional[dict] = None) -> Dict[str, Any]:
        """Return head pose (yaw, pitch, roll) in degrees."""
        t0 = time.monotonic()
        row = await self._run_openface(image_path)
        if row is None:
            return {"available": False, "error": "OpenFace not available or failed"}
        try:
            return {
                "yaw": float(row.get("pose_Ry", 0)),
                "pitch": float(row.get("pose_Rx", 0)),
                "roll": float(row.get("pose_Rz", 0)),
                "tx": float(row.get("pose_Tx", 0)),
                "ty": float(row.get("pose_Ty", 0)),
                "tz": float(row.get("pose_Tz", 0)),
                "confidence": float(row.get("confidence", 0)),
                "success": row.get("success", "0") == "1",
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
        except Exception as e:
            return {"error": str(e)}

    async def extract_action_units(self, image_path: str,
                                    options: Optional[dict] = None) -> Dict[str, Any]:
        """Return FACS action unit intensities and presence."""
        t0 = time.monotonic()
        row = await self._run_openface(image_path)
        if row is None:
            return {"available": False, "error": "OpenFace not available or failed"}
        try:
            # AUs: AU01_r, AU02_r, ... (intensity) and AU01_c, AU02_c, ... (presence)
            intensities = {k: float(v) for k, v in row.items() if k.startswith("AU") and k.endswith("_r")}
            presence = {k: int(float(v)) for k, v in row.items() if k.startswith("AU") and k.endswith("_c")}
            return {
                "intensities": intensities,
                "presence": presence,
                "confidence": float(row.get("confidence", 0)),
                "success": row.get("success", "0") == "1",
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── ABC compliance: HeadPoseProvider ────────────────────────────────────────

    async def estimate_pose(self, image_path: str, face_bbox=None):
        """HeadPoseProvider ABC method — delegates to estimate_head_pose."""
        from providers.base import HeadPoseResult
        result = await self.estimate_head_pose(image_path)
        if result.get("error") or not result.get("success", False):
            return None
        return HeadPoseResult(
            yaw=result.get("yaw", 0.0),
            pitch=result.get("pitch", 0.0),
            roll=result.get("roll", 0.0),
            provider=self.name,
        )

    # ── ABC compliance: ActionUnitProvider ────────────────────────────────────

    async def detect_action_units(self, image_path: str, face_bbox=None) -> Dict[str, float]:
        """ActionUnitProvider ABC method — delegates to extract_action_units."""
        result = await self.extract_action_units(image_path)
        if result.get("error"):
            return {}
        return result.get("intensities", {})

    async def health_check(self) -> dict:
        available = self._check_available()
        return {
            "ok": available,
            "provider": self.name,
            "version": self.version,
            "latency_ms": 0,
            "details": {
                "executable": self.executable,
                "error": None if available else f"'{self.executable}' not found on PATH",
            },
        }
