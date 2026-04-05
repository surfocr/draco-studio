"""MMPose whole-body keypoint provider."""
from __future__ import annotations
import time
from typing import Optional, List, Dict, Any
from providers.base import PoseProvider

class MMPoseProvider(PoseProvider):
    """MMPose RTMPose whole-body 133-keypoint provider."""

    name = "mmpose"
    version = "rtmpose-l"

    def __init__(self, model_config: str = "rtmpose-l_8xb32-270e_coco-wholebody-384x288",
                 device: str = "auto"):
        self.model_config = model_config
        self._device = device
        self._pose_estimator = None
        self._load_error: Optional[str] = None

    def _load(self):
        if self._pose_estimator is not None or self._load_error:
            return
        try:
            import torch
            from mmpose.apis import init_model, inference_topdown
            from mmpose.utils import adapt_mmdet_pipeline

            device = self._device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            # RTMPose whole-body config
            cfg_file = "td-hm_hrnet-w48_8xb32-210e_coco-wholebody-384x288"
            ckpt = "https://download.openmmlab.com/mmpose/top_down/hrnet/hrnet_w48_coco_wholebody_384x288_dark-f5726563_20200918.pth"
            self._pose_estimator = init_model(cfg_file, ckpt, device=device)
            self._loaded_device = device
        except Exception as e:
            self._load_error = str(e)

    async def detect(self, image_path: str, options: Optional[dict] = None) -> Dict[str, Any]:
        """Return keypoints for all people detected in image."""
        self._load()
        if self._load_error:
            return {"error": self._load_error, "people": []}
        try:
            from mmpose.apis import inference_topdown
            import mmcv

            t0 = time.monotonic()
            img = mmcv.imread(image_path)
            # Use full image as bounding box if no detection provided
            h, w = img.shape[:2]
            bboxes = options.get("bboxes", [[0, 0, w, h, 1.0]]) if options else [[0, 0, w, h, 1.0]]

            result = inference_topdown(self._pose_estimator, image_path,
                                       bboxes=bboxes, bbox_format="xyxy")
            people = []
            for person in result:
                kpts = person.pred_instances.keypoints[0].tolist()
                scores = person.pred_instances.keypoint_scores[0].tolist()
                people.append({
                    "keypoints": kpts,        # [[x,y], ...] 133 points
                    "scores": scores,         # [float, ...] confidence per keypoint
                    "bbox": person.pred_instances.bboxes[0].tolist() if hasattr(person.pred_instances, 'bboxes') else None,
                })
            latency = int((time.monotonic() - t0) * 1000)
            return {"people": people, "keypoint_count": 133, "latency_ms": latency}
        except Exception as e:
            return {"error": str(e), "people": []}

    async def health_check(self) -> dict:
        self._load()
        return {
            "provider": self.name,
            "version": self.version,
            "available": self._load_error is None,
            "error": self._load_error,
        }
