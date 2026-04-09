#!/usr/bin/env python3
"""
DRACO Dataset Studio v5 — Python Sidecar Server
FastAPI server providing InsightFace ArcFace 512-d, CLIP ViT-L/14, Florence-2,
aesthetic scoring, and advanced dataset analysis.

Implements knowledge from:
- The Definitive LoRA Training Guide V2
- AI Training Master Reference (Resolution/Bucketing/Captioning mechanics)
- High-Fidelity Character LoRA Training guide
- Community best practices (150+ training runs)

Key analysis features:
- Shot type classification (close-up/mid/full-body) with ideal ratio checking
- Training bucket calculation (Mod-64 bucketing algorithm)
- Pose/expression diversity analysis
- Background consistency detection
- Skin tone consistency checking
- Compression artifact detection
- Dataset composition report with per-model recommendations
"""
import os, sys, io, base64, argparse, logging, math, hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from collections import Counter

import numpy as np
import cv2
from PIL import Image

# ── FastAPI ──────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn[standard]"])
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn

# ── Config ───────────────────────────────────────────────
MODELS_DIR = Path(os.environ.get("DRACO_MODELS_DIR", Path.home() / ".draco-studio" / "models"))
MODELS_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("DRACO_PORT", 18082))

logging.basicConfig(level=logging.INFO, format="[DRACO] %(message)s")
log = logging.getLogger("draco")

app = FastAPI(title="DRACO Sidecar", version="5.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ═══════════════════════════════════════════════════════════
# TRAINING BUCKET DEFINITIONS (from AI Training Master Reference)
# Resolution is a PIXEL BUDGET, not fixed dimensions.
# Mod-64 bucketing: snap to nearest multiple of 64.
# ═══════════════════════════════════════════════════════════
TRAINING_BUCKETS = {
    512: [
        (512, 512), (640, 384), (384, 640), (576, 448), (448, 576),
        (704, 384), (384, 704), (640, 448), (448, 640),
    ],
    768: [
        (768, 768), (896, 576), (576, 896), (960, 640), (640, 960),
        (1024, 576), (576, 1024), (832, 704), (704, 832),
    ],
    1024: [
        (1024, 1024), (1152, 896), (896, 1152), (1216, 832), (832, 1216),
        (1344, 768), (768, 1344), (1280, 768), (768, 1280),
        (1152, 832), (832, 1152), (1088, 960), (960, 1088),
    ],
    1536: [
        (1536, 1536), (1792, 1280), (1280, 1792), (1664, 1408), (1408, 1664),
        (2048, 1152), (1152, 2048), (1920, 1216), (1216, 1920),
        (1856, 1280), (1280, 1856), (1728, 1344), (1344, 1728),
    ],
}

# Dataset size recommendations per model (from Definitive LoRA Guide V2)
MODEL_DATASET_RECS = {
    "z_image_turbo": {"character": (15, 25), "style": (30, 120), "min": 10, "caption_style": "minimal"},
    "z_image_base":  {"character": (15, 50), "style": (30, 200), "min": 15, "caption_style": "rich"},
    "flux_klein_9b": {"character": (20, 60), "style": (30, 100), "min": 20, "caption_style": "moderate"},
    "flux_dev":      {"character": (15, 27), "style": (20, 100), "min": 9,  "caption_style": "moderate"},
    "qwen_2512":     {"character": (20, 30), "style": (30, 80),  "min": 10, "caption_style": "moderate"},
}

# Ideal shot distribution (from High-Fidelity Character LoRA guide)
# Close-ups: 20-30%, Mid shots: 40-50%, Full body: 20-30%
IDEAL_SHOT_DISTRIBUTION = {
    "close_up": (0.20, 0.30),
    "mid_shot": (0.40, 0.50),
    "full_body": (0.20, 0.30),
}

# ── Lazy-loaded Models ───────────────────────────────────
_models = {}

def get_insightface():
    if "insightface" not in _models:
        log.info("Loading InsightFace buffalo_l (ArcFace 512-d)...")
        from insightface.app import FaceAnalysis
        analyzer = FaceAnalysis(
            name="buffalo_l",
            root=str(MODELS_DIR / "insightface"),
            providers=_get_onnx_providers()
        )
        analyzer.prepare(ctx_id=0, det_size=(640, 640))
        _models["insightface"] = analyzer
        log.info("InsightFace ready.")
    return _models["insightface"]

def get_clip():
    if "clip" not in _models:
        log.info("Loading CLIP ViT-L/14...")
        import torch
        from transformers import CLIPModel, CLIPProcessor
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = CLIPModel.from_pretrained(
            "openai/clip-vit-large-patch14",
            cache_dir=str(MODELS_DIR / "clip")
        ).to(device)
        processor = CLIPProcessor.from_pretrained(
            "openai/clip-vit-large-patch14",
            cache_dir=str(MODELS_DIR / "clip")
        )
        _models["clip"] = {"model": model, "processor": processor, "device": device}
        log.info(f"CLIP ready on {device}.")
    return _models["clip"]

def get_florence2():
    if "florence2" not in _models:
        log.info("Loading Florence-2-base for captioning...")
        import torch
        from transformers import AutoProcessor, AutoModelForCausalLM
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = AutoModelForCausalLM.from_pretrained(
            "microsoft/Florence-2-base",
            cache_dir=str(MODELS_DIR / "florence2"),
            trust_remote_code=True,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device)
        processor = AutoProcessor.from_pretrained(
            "microsoft/Florence-2-base",
            cache_dir=str(MODELS_DIR / "florence2"),
            trust_remote_code=True,
        )
        _models["florence2"] = {"model": model, "processor": processor, "device": device}
        log.info(f"Florence-2 ready on {device}.")
    return _models["florence2"]

def get_clip_fastembed():
    """CLIP ViT-L/14 via fastembed (ONNX, GPU-accelerated, no heavy torch dep)."""
    if "clip_fastembed" not in _models:
        log.info("Loading CLIP ViT-L/14 via fastembed...")
        from fastembed import ImageEmbeddingModel, TextEmbeddingModel
        providers = _get_onnx_providers()
        _models["clip_image"] = ImageEmbeddingModel.from_pretrained(
            "Qdrant/clip-ViT-L-14-vision",
            providers=providers
        )
        _models["clip_text"] = TextEmbeddingModel.from_pretrained(
            "Qdrant/clip-ViT-L-14",
            providers=providers
        )
        _models["clip_fastembed"] = True
        log.info("CLIP fastembed ViT-L/14 ready.")
    return _models["clip_image"], _models["clip_text"]

def get_trueskill_env():
    if "trueskill_env" not in _models:
        import trueskill
        _models["trueskill_env"] = trueskill.TrueSkill(
            mu=25.0, sigma=8.333, beta=4.167, tau=0.0833, draw_probability=0.05
        )
        log.info("TrueSkill environment ready.")
    return _models["trueskill_env"]

def get_aesthetic_model():
    """LAION Aesthetic Predictor v2 (ONNX). Requires models/aesthetic_v2.onnx."""
    if "aesthetic" not in _models:
        aesthetic_path = Path(__file__).parent / "models" / "aesthetic_v2.onnx"
        if not aesthetic_path.exists():
            return None
        import onnxruntime as ort
        session = ort.InferenceSession(
            str(aesthetic_path),
            providers=_get_onnx_providers()
        )
        _models["aesthetic"] = session
        log.info("LAION Aesthetic v2 ONNX ready.")
    return _models["aesthetic"]

def get_deepface():
    if "deepface" not in _models:
        from deepface import DeepFace
        _models["deepface"] = DeepFace
        log.info("DeepFace ready (CPU attribute analysis).")
    return _models["deepface"]

def _get_onnx_providers():
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" in providers:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]
    except Exception:
        return ["CPUExecutionProvider"]

# ── Helpers ──────────────────────────────────────────────
def decode_image(b64: str) -> np.ndarray:
    """Decode base64 image to BGR numpy array."""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    buf = base64.b64decode(b64)
    arr = np.frombuffer(buf, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")
    return img

def decode_pil(b64: str) -> Image.Image:
    """Decode base64 to PIL Image."""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    buf = base64.b64decode(b64)
    return Image.open(io.BytesIO(buf)).convert("RGB")

def _compute_phash(img: np.ndarray, hash_size: int = 16) -> str:
    """Compute perceptual hash for near-duplicate detection."""
    resized = cv2.resize(img, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # DCT-based pHash
    dct = cv2.dct(gray)
    dct_low = dct[:8, :8]
    med = np.median(dct_low)
    bits = (dct_low > med).flatten()
    return ''.join('1' if b else '0' for b in bits)

def _hamming_distance(h1: str, h2: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(h1, h2))

# ── Request Models ───────────────────────────────────────
class ImageRequest(BaseModel):
    image: str

class BatchImageRequest(BaseModel):
    images: List[str]
    batch_size: int = 8

class ClusterRequest(BaseModel):
    embeddings: List[List[float]]
    threshold: float = 0.4

class CaptionRequest(BaseModel):
    image: str
    prompt: Optional[str] = None
    mode: Optional[str] = "detailed"  # "minimal" (ZIT), "detailed" (ZIB/Flux), "structured"
    trigger_word: Optional[str] = None

class ModelEnsureRequest(BaseModel):
    model: str

class ModelDownloadRequest(BaseModel):
    model: str
    repo: str
    target_dir: str

class DatasetAnalysisRequest(BaseModel):
    images: List[str]
    target_model: Optional[str] = "z_image_turbo"
    target_resolution: Optional[int] = 1024
    lora_type: Optional[str] = "character"  # "character" or "style"
    reference_index: Optional[int] = None  # index of the reference face image

class BucketRequest(BaseModel):
    widths: List[int]
    heights: List[int]
    target_resolution: int = 1024

class DuplicateRequest(BaseModel):
    images: List[str]
    threshold: int = 9  # Hamming distance <= this = duplicate

# ── v5 Request Models ─────────────────────────────────────

class EmbedRequest(BaseModel):
    images: List[str]
    filenames: List[str] = []

class EmbedTextRequest(BaseModel):
    query: str

class ClusterEmbedRequest(BaseModel):
    embeddings: List[List[float]]
    filenames: List[str] = []
    min_cluster_size: int = 5
    min_samples: int = 3

class UmapRequest(BaseModel):
    embeddings: List[List[float]]
    filenames: List[str] = []

class TrueSkillUpdateRequest(BaseModel):
    winner: Dict[str, float]  # {mu, sigma}
    loser: Dict[str, float]   # {mu, sigma}
    draw: bool = False

class AestheticRequest(BaseModel):
    embeddings: List[List[float]]
    filenames: List[str] = []

class FaceEnhancedRequest(BaseModel):
    image: str
    deep_attrs: bool = False

class FaceAttrsRequest(BaseModel):
    images: List[str]  # pre-cropped face images

class FaceClusterRequest(BaseModel):
    embeddings: List[List[float]]
    filenames: List[str]
    eps: float = 0.4
    min_samples: int = 2

class ExportSplitRequest(BaseModel):
    source_dir: str
    output_dir: str
    mode: str = "flat"  # flat | clustered | ranked | arena
    assignments: Dict[str, str] = {}   # {filename: cluster_label}
    order: List[str] = []              # sorted filenames for ranked/arena

class ReorderRequest(BaseModel):
    source_dir: str
    order: List[str]          # filenames in desired order
    prefix_digits: int = 4    # 0001_, 0002_, ...

# ── Endpoints ────────────────────────────────────────────

@app.get("/status")
def server_status():
    """Full model health check with GPU memory and VRAM usage."""
    import torch
    cuda = False
    device_name = "CPU"
    vram_total = 0
    vram_used = 0
    vram_free = 0
    try:
        cuda = torch.cuda.is_available()
        if cuda:
            device_name = torch.cuda.get_device_name(0)
            vram_total = round(torch.cuda.get_device_properties(0).total_mem / 1024**3, 2)
            vram_used = round(torch.cuda.memory_allocated(0) / 1024**3, 2)
            vram_free = round(vram_total - vram_used, 2)
    except Exception:
        pass

    return {
        "status": "ok",
        "version": "draco-server-v5",
        "cuda": cuda,
        "device": device_name,
        "vram_gb": {"total": vram_total, "used": vram_used, "free": vram_free},
        "loaded_models": list(_models.keys()),
        "available_endpoints": [
            "/embed", "/embed_text", "/cluster", "/umap",
            "/trueskill_update", "/aesthetic",
            "/face", "/face_attrs", "/face_cluster",
            "/caption", "/reorder", "/export_split", "/status",
        ],
    }

@app.get("/health")
def health():
    cuda = False
    device = "CPU"
    try:
        import torch
        cuda = torch.cuda.is_available()
        device = torch.cuda.get_device_name(0) if cuda else "CPU"
    except Exception:
        pass
    return {
        "status": "ok",
        "version": "draco-sidecar-v5",
        "cuda": cuda,
        "device": device,
        "loaded_models": list(_models.keys()),
    }

# ═══════════════════════════════════════════════════════════
# FACE DETECTION + EMBEDDING (InsightFace ArcFace 512-d)
# 99.83% LFW accuracy — best-in-class face similarity
# ═══════════════════════════════════════════════════════════

@app.post("/detect-faces")
def detect_faces(req: ImageRequest):
    analyzer = get_insightface()
    img = decode_image(req.image)
    h, w = img.shape[:2]
    faces = analyzer.get(img)
    results = []
    for face in faces:
        fw = face.bbox[2] - face.bbox[0]
        fh = face.bbox[3] - face.bbox[1]
        face_ratio = fh / h if h > 0 else 0

        # Pose estimation from landmarks
        pose_info = _estimate_pose(face, w, h)

        results.append({
            "bbox": {
                "x": int(face.bbox[0]), "y": int(face.bbox[1]),
                "w": int(fw), "h": int(fh),
            },
            "det_score": float(face.det_score),
            "age": int(getattr(face, "age", 0)),
            "gender": "Male" if getattr(face, "gender", 1) == 1 else "Female",
            "face_ratio": round(face_ratio, 4),
            "shot_type": _classify_shot_type(face_ratio),
            "pose": pose_info,
            "has_embedding": face.normed_embedding is not None,
        })
    return {"faces": results, "count": len(results), "image_size": {"w": w, "h": h}}


@app.post("/batch-faces")
def batch_faces(req: BatchImageRequest):
    analyzer = get_insightface()
    results = []
    for b64 in req.images:
        try:
            img = decode_image(b64)
            h, w = img.shape[:2]
            faces = analyzer.get(img)
            if faces:
                face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                fw = face.bbox[2] - face.bbox[0]
                fh = face.bbox[3] - face.bbox[1]
                face_ratio = fh / h if h > 0 else 0
                pose_info = _estimate_pose(face, w, h)

                results.append({
                    "embedding": face.normed_embedding.tolist(),
                    "bbox": {
                        "x": int(face.bbox[0]), "y": int(face.bbox[1]),
                        "w": int(fw), "h": int(fh),
                    },
                    "det_score": float(face.det_score),
                    "age": int(getattr(face, "age", 0)),
                    "gender": "Male" if getattr(face, "gender", 1) == 1 else "Female",
                    "face_count": len(faces),
                    "face_ratio": round(face_ratio, 4),
                    "shot_type": _classify_shot_type(face_ratio),
                    "pose": pose_info,
                })
            else:
                results.append({"embedding": None, "face_count": 0})
        except Exception as e:
            results.append({"embedding": None, "error": str(e)})
    return {"results": results}


@app.post("/compare-faces")
def compare_faces(req: BatchImageRequest):
    if len(req.images) != 2:
        raise HTTPException(400, "Exactly 2 images required")
    analyzer = get_insightface()
    embeddings = []
    for b64 in req.images:
        img = decode_image(b64)
        faces = analyzer.get(img)
        if not faces:
            raise HTTPException(400, "No face detected in one of the images")
        face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        embeddings.append(face.normed_embedding)
    sim = float(np.dot(embeddings[0], embeddings[1]))
    return {"similarity": sim, "similarity_pct": max(0, min(100, int((sim + 1) / 2 * 100))), "model": "ArcFace-512d"}


@app.post("/cluster-faces")
def cluster_faces(req: ClusterRequest):
    """Agglomerative hierarchical clustering (average-linkage) for face identity grouping.
    Upgraded from naive greedy to proper hierarchical clustering per facial recognition
    pipeline research. Handles transitive relationships and multi-identity datasets."""
    embs = np.array(req.embeddings, dtype=np.float32)
    n = len(embs)
    if n == 0:
        return {"clusters": [], "outliers": [], "centroids": []}
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embs = embs / norms
    sim_matrix = embs @ embs.T

    # Agglomerative hierarchical clustering (average-linkage)
    # Each item starts as its own cluster
    active_clusters = {i: [i] for i in range(n)}
    cluster_embs = {i: embs[i:i+1] for i in range(n)}

    while len(active_clusters) > 1:
        # Find most similar pair of clusters
        best_sim = -1.0
        best_pair = None
        cluster_ids = list(active_clusters.keys())
        for idx_a in range(len(cluster_ids)):
            for idx_b in range(idx_a + 1, len(cluster_ids)):
                ca, cb = cluster_ids[idx_a], cluster_ids[idx_b]
                # Average-linkage: mean similarity between all pairs
                sims = []
                for i in active_clusters[ca]:
                    for j in active_clusters[cb]:
                        sims.append(float(sim_matrix[i, j]))
                avg_sim = sum(sims) / len(sims)
                if avg_sim > best_sim:
                    best_sim = avg_sim
                    best_pair = (ca, cb)

        if best_sim < req.threshold or best_pair is None:
            break

        # Merge the two most similar clusters
        ca, cb = best_pair
        active_clusters[ca] = active_clusters[ca] + active_clusters[cb]
        merged = np.concatenate([cluster_embs[ca], cluster_embs[cb]], axis=0)
        cluster_embs[ca] = merged
        del active_clusters[cb]
        del cluster_embs[cb]

    # Build result
    clusters = []
    outliers = []
    centroids = []
    for cid, members in active_clusters.items():
        if len(members) > 1:
            clusters.append(members)
            # Compute centroid (mean embedding, re-normalized)
            centroid = cluster_embs[cid].mean(axis=0)
            centroid = centroid / max(np.linalg.norm(centroid), 1e-8)
            centroids.append(centroid.tolist())
        else:
            outliers.append(members[0])

    return {"clusters": clusters, "outliers": outliers, "centroids": centroids}


# ═══════════════════════════════════════════════════════════
# SHOT TYPE CLASSIFICATION
# From guides: Close-ups 20-30%, Mid shots 40-50%, Full body 20-30%
# Determined by face-to-image height ratio
# ═══════════════════════════════════════════════════════════

def _classify_shot_type(face_ratio: float) -> str:
    """Classify image shot type based on face height / image height ratio.
    - close_up: face fills >35% of frame height (headshots, tight portraits)
    - mid_shot: face fills 12-35% (waist-up, chest-up)
    - full_body: face fills <12% (full standing, environmental)
    """
    if face_ratio >= 0.35:
        return "close_up"
    elif face_ratio >= 0.12:
        return "mid_shot"
    else:
        return "full_body"

def _estimate_pose(face, img_w: int, img_h: int) -> dict:
    """Estimate face pose angles from InsightFace landmarks."""
    pose = {"yaw": "frontal", "pitch": "level", "angle_score": 85}

    # Use 5-point landmarks (available on all InsightFace models)
    kps = getattr(face, "kps", None)
    if kps is not None and len(kps) >= 5:
        # kps: [left_eye, right_eye, nose, left_mouth, right_mouth]
        left_eye = kps[0]
        right_eye = kps[1]
        nose = kps[2]

        # Yaw estimation from nose position relative to eye midpoint
        eye_mid_x = (left_eye[0] + right_eye[0]) / 2
        eye_dist = abs(right_eye[0] - left_eye[0])
        if eye_dist > 0:
            nose_offset = (nose[0] - eye_mid_x) / eye_dist
            if abs(nose_offset) < 0.12:
                pose["yaw"] = "frontal"
                pose["angle_score"] = int(95 - abs(nose_offset) * 100)
            elif abs(nose_offset) < 0.30:
                pose["yaw"] = "three_quarter"
                pose["angle_score"] = int(80 - abs(nose_offset) * 80)
            else:
                pose["yaw"] = "profile"
                pose["angle_score"] = int(60 - abs(nose_offset) * 40)

            # Pitch from nose-to-eye vertical distance
            eye_mid_y = (left_eye[1] + right_eye[1]) / 2
            vert_ratio = (nose[1] - eye_mid_y) / eye_dist
            if vert_ratio < 0.3:
                pose["pitch"] = "looking_up"
            elif vert_ratio > 0.7:
                pose["pitch"] = "looking_down"
            else:
                pose["pitch"] = "level"

    return pose


# ═══════════════════════════════════════════════════════════
# CLIP EMBEDDINGS (ViT-L/14)
# Used for semantic clustering and aesthetic scoring
# ═══════════════════════════════════════════════════════════

@app.post("/clip-embed")
def clip_embed(req: ImageRequest):
    import torch
    clip = get_clip()
    pil_img = decode_pil(req.image)
    inputs = clip["processor"](images=pil_img, return_tensors="pt").to(clip["device"])
    with torch.no_grad():
        features = clip["model"].get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
    return {"embedding": features[0].cpu().tolist(), "dim": features.shape[-1]}

@app.post("/clip-batch")
def clip_batch(req: BatchImageRequest):
    import torch
    clip = get_clip()
    results = []
    for b64 in req.images:
        try:
            pil_img = decode_pil(b64)
            inputs = clip["processor"](images=pil_img, return_tensors="pt").to(clip["device"])
            with torch.no_grad():
                features = clip["model"].get_image_features(**inputs)
                features = features / features.norm(dim=-1, keepdim=True)
            results.append({"embedding": features[0].cpu().tolist()})
        except Exception as e:
            results.append({"embedding": None, "error": str(e)})
    return {"results": results}


# ═══════════════════════════════════════════════════════════
# AESTHETIC SCORING (CLIP zero-shot)
# ═══════════════════════════════════════════════════════════

@app.post("/aesthetic-score")
def aesthetic_score(req: ImageRequest):
    import torch
    clip = get_clip()
    pil_img = decode_pil(req.image)
    inputs = clip["processor"](images=pil_img, return_tensors="pt").to(clip["device"])

    pos_prompts = [
        "a beautiful professional photograph", "sharp detailed high-resolution image",
        "well-lit studio photography", "high quality portrait photo",
        "clear focused image with good composition"
    ]
    neg_prompts = [
        "a blurry out of focus photo", "low quality compressed image with artifacts",
        "poorly lit dark photo", "amateur badly composed snapshot",
        "distorted overexposed image"
    ]

    pos_inputs = clip["processor"](text=pos_prompts, return_tensors="pt", padding=True).to(clip["device"])
    neg_inputs = clip["processor"](text=neg_prompts, return_tensors="pt", padding=True).to(clip["device"])

    with torch.no_grad():
        img_features = clip["model"].get_image_features(**inputs)
        pos_features = clip["model"].get_text_features(**pos_inputs)
        neg_features = clip["model"].get_text_features(**neg_inputs)
        img_features = img_features / img_features.norm(dim=-1, keepdim=True)
        pos_features = pos_features / pos_features.norm(dim=-1, keepdim=True)
        neg_features = neg_features / neg_features.norm(dim=-1, keepdim=True)
        pos_sim = (img_features @ pos_features.T).mean().item()
        neg_sim = (img_features @ neg_features.T).mean().item()

    score = max(0, min(100, int((pos_sim - neg_sim + 0.3) / 0.6 * 100)))
    return {"aesthetic_score": score, "positive_sim": round(pos_sim, 4), "negative_sim": round(neg_sim, 4)}


# ═══════════════════════════════════════════════════════════
# CAPTIONING (Florence-2)
# Supports captioning modes from the guides:
# - "minimal": Clean label style for ZIT (pose + clothing + background only)
# - "detailed": Full description for ZIB/Flux
# - "structured": Trigger word prefix + structured description
# ═══════════════════════════════════════════════════════════

@app.post("/caption")
def caption(req: CaptionRequest):
    import torch
    f2 = get_florence2()
    pil_img = decode_pil(req.image)
    task = "<MORE_DETAILED_CAPTION>"
    inputs = f2["processor"](text=task, images=pil_img, return_tensors="pt")
    inputs = {k: v.to(f2["device"]) for k, v in inputs.items()}
    with torch.no_grad():
        generated = f2["model"].generate(
            **inputs,
            max_new_tokens=256,
            num_beams=3,
            early_stopping=True,
        )
    text = f2["processor"].batch_decode(generated, skip_special_tokens=True)[0]
    if task in text:
        text = text.split(task)[-1].strip()

    # Apply captioning mode
    mode = req.mode or "detailed"
    if mode == "minimal":
        # Clean label: strip facial descriptions, keep pose/clothing/background
        # This implements the "silence forces concept learning" principle
        text = _strip_facial_descriptions(text)
    elif mode == "structured" and req.trigger_word:
        text = f"{req.trigger_word}, {text}"

    return {"caption": text, "model": "Florence-2-base", "mode": mode}


@app.post("/caption-batch")
def caption_batch(req: BatchImageRequest):
    results = []
    for b64 in req.images:
        try:
            result = caption(CaptionRequest(image=b64))
            results.append(result)
        except Exception as e:
            results.append({"caption": "", "error": str(e)})
    return {"results": results}


def _strip_facial_descriptions(text: str) -> str:
    """Remove facial feature descriptions from caption.
    Implements 'silence forces concept learning' from the Captioning Mechanics guide:
    - What you caption → model IGNORES (gradient zeroes out)
    - What you leave silent → model ENCODES (high loss → LoRA absorbs it)
    """
    import re
    # Remove common facial description patterns
    facial_patterns = [
        r'\b(with\s+)?(brown|blue|green|hazel|dark|light|bright)\s+eyes\b',
        r'\b(with\s+)?(long|short|curly|straight|wavy|blonde|brunette|dark|red|black|brown)\s+(hair|locks|curls)\b',
        r'\b(with\s+)?(a\s+)?(small|large|button|straight|pointed|wide|narrow)\s+nose\b',
        r'\b(with\s+)?(full|thin|pouty|pink|red)\s+lips\b',
        r'\b(with\s+)?(high|prominent|defined)\s+cheekbones\b',
        r'\b(with\s+)?(a\s+)?(strong|square|round|oval|defined)\s+(jaw|jawline|chin)\b',
        r'\b(with\s+)?(smooth|clear|fair|tan|olive|pale|dark)\s+skin\b',
        r'\b(with\s+)?(a\s+)?(beautiful|attractive|handsome|pretty|young|old)\s+face\b',
        r'\bfacial\s+features?\b',
        r'\b(his|her|their)\s+face\s+(is|looks|appears)\b[^.]*\.',
    ]
    result = text
    for pattern in facial_patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    # Clean up double spaces and orphaned commas
    result = re.sub(r'\s*,\s*,', ',', result)
    result = re.sub(r'\s+', ' ', result).strip()
    result = re.sub(r'^[,.\s]+', '', result)
    return result


# ═══════════════════════════════════════════════════════════
# QUALITY ASSESSMENT — DracoFlow v3
# Enhanced scoring integrating all guide knowledge
# ═══════════════════════════════════════════════════════════

@app.post("/quality-assess")
def quality_assess(req: ImageRequest):
    img = decode_image(req.image)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # ── Sharpness (Laplacian variance) ──
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)
    raw_sharpness = float(laplacian.var())
    sharpness = min(100, int(raw_sharpness / 950 * 100))

    # ── Brightness ──
    mean_brightness = float(gray.mean())
    brightness = min(100, int(mean_brightness / 2.55))
    # Penalize extreme brightness (from guides: avoid blown highlights, underexposure)
    brightness_penalty = 0
    if mean_brightness > 230:
        brightness_penalty = int((mean_brightness - 230) / 25 * 30)
    elif mean_brightness < 40:
        brightness_penalty = int((40 - mean_brightness) / 40 * 30)

    # ── Contrast ──
    contrast = min(100, int(gray.std() / 55 * 100))

    # ── Saturation ──
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    saturation = min(100, int(hsv[:, :, 1].mean() / 2.55))

    # ── Compression artifact detection ──
    # (from guides: use PNG whenever possible, JPEG at max quality)
    artifact_score = _detect_compression_artifacts(img, gray)

    # ── Over/under exposure (from guides: avoid harsh shadows, blown highlights) ──
    overexposed_pct = float((gray > 238).sum() / gray.size)
    underexposed_pct = float((gray < 16).sum() / gray.size)
    exposure_ok = overexposed_pct < 0.14 and underexposed_pct < 0.14

    # ── Background analysis ──
    bg_info = _analyze_background(img)

    # ── Face analysis ──
    analyzer = get_insightface()
    faces = analyzer.get(img)
    center_score = 65
    pose_score = 65
    face_ratio = 0.0
    shot_type = "unknown"
    pose_info = {"yaw": "unknown", "pitch": "unknown", "angle_score": 50}
    face_data = None

    if faces:
        face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        fx = (face.bbox[0] + face.bbox[2]) / 2
        fy = (face.bbox[1] + face.bbox[3]) / 2
        fw = face.bbox[2] - face.bbox[0]
        fh = face.bbox[3] - face.bbox[1]
        face_ratio = fh / h if h > 0 else 0
        shot_type = _classify_shot_type(face_ratio)

        # Centering (from guides: ensure main subject is centered)
        cx, cy = fx / w, fy / h
        center_score = max(0, min(100, int((1 - abs(cx - 0.5) * 1.8 - abs(cy - 0.38) * 1.2) * 100)))

        # Pose estimation
        pose_info = _estimate_pose(face, w, h)
        pose_score = pose_info["angle_score"]

        # Skin tone sample for consistency checking across dataset
        skin_color = _sample_skin_tone(img, face)

        face_data = {
            "embedding": face.normed_embedding.tolist() if face.normed_embedding is not None else None,
            "det_score": float(face.det_score),
            "age": int(getattr(face, "age", 0)),
            "gender": "Male" if getattr(face, "gender", 1) == 1 else "Female",
            "skin_tone_lab": skin_color,
        }

    # ── Posterization / Banding Detection (from Diffusion Course research) ──
    # Non-Gaussian noise patterns (posterization, banding) conflict with the
    # Gaussian noise assumption in diffusion training, degrading LoRA quality.
    posterization_score = _detect_posterization(gray)

    # ── Pixel Clipping Check (from Diffusion research) ──
    # Pixels at exact 0 or 255 map to extremes of [-1,1] normalization
    # and provide zero gradient information to the diffusion model.
    clipped_pct = float(((gray == 0) | (gray == 255)).sum() / gray.size)
    clipping_penalty = min(20, int(clipped_pct * 200))

    # ── Watermark Detection ──
    watermark_info = _detect_watermark(img)
    watermark_penalty = 15 if watermark_info["likely_watermark"] else 0

    # ── DracoFlow v4 Composite ──
    # Diffusion-informed weights: sharpness increased to 0.30 because low-noise
    # timesteps (which dominate gradient) disproportionately learn fine detail.
    # Added watermark penalty, posterization penalty, pixel clipping penalty.
    # Weights: sharpness×0.30, pose×0.18, contrast×0.12, brightness×0.10,
    #          centering×0.08, artifact×0.07, posterization×0.05, exposure×0.05,
    #          saturation×0.05
    composite = int(
        sharpness * 0.30 +
        pose_score * 0.18 +
        contrast * 0.12 +
        max(0, brightness - brightness_penalty) * 0.10 +
        center_score * 0.08 +
        artifact_score * 0.07 +
        posterization_score * 0.05 +
        (85 if exposure_ok else 30) * 0.05 +
        saturation * 0.05
    )
    # Apply penalties
    composite = max(0, composite - watermark_penalty - clipping_penalty)

    grade = "Excellent" if composite >= 72 else "Good" if composite >= 55 else "OK" if composite >= 35 else "Low"

    # ── Training bucket assignment ──
    bucket = _assign_bucket(w, h, 1024)

    return {
        "sharpness": sharpness,
        "sharpness_raw": round(raw_sharpness, 2),
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "artifact_score": artifact_score,
        "posterization_score": posterization_score,
        "pose_score": pose_score,
        "center_score": center_score,
        "composite": composite,
        "grade": grade,
        "scoring_model": "DracoFlow-v4",
        "face_ratio": round(face_ratio, 4),
        "shot_type": shot_type,
        "pose": pose_info,
        "overexposed": overexposed_pct > 0.14,
        "underexposed": underexposed_pct > 0.14,
        "overexposed_pct": round(overexposed_pct * 100, 1),
        "underexposed_pct": round(underexposed_pct * 100, 1),
        "clipped_pixel_pct": round(clipped_pct * 100, 2),
        "face_count": len(faces) if faces else 0,
        "face_data": face_data,
        "background": bg_info,
        "watermark": watermark_info,
        "bucket_1024": bucket,
        "image_size": {"w": w, "h": h},
        "megapixels": round(w * h / 1_000_000, 2),
    }


def _detect_posterization(gray: np.ndarray) -> int:
    """Detect posterization/banding artifacts (from Diffusion Course research).
    Posterization creates non-Gaussian noise patterns that conflict with the
    Gaussian noise assumption in DDPM training, degrading LoRA quality.
    Returns 0-100 (100 = no posterization, clean gradients)."""
    h, w = gray.shape
    sample = gray[h//4:3*h//4, w//4:3*w//4]  # Center region
    if sample.size == 0:
        return 80
    unique_levels = len(np.unique(sample.astype(np.uint8)))

    # Also check for banding: histogram gaps indicate posterization
    hist = cv2.calcHist([sample.astype(np.uint8)], [0], None, [256], [0, 256]).flatten()
    zero_bins = int((hist == 0).sum())

    # Heavy banding override
    if zero_bins > 180:  # More than 70% of bins empty
        return min(30, unique_levels)

    # A well-photographed image has 150+ unique levels in center region
    if unique_levels > 150:
        return 95
    elif unique_levels > 100:
        return 80
    elif unique_levels > 60:
        return 55  # Moderate posterization
    elif unique_levels > 30:
        return 30  # Significant posterization
    else:
        return 10  # Heavy posterization


def _detect_compression_artifacts(img: np.ndarray, gray: np.ndarray) -> int:
    """Detect JPEG compression artifacts using block boundary analysis.
    Returns 0-100 score (100 = no artifacts / PNG quality).
    From guides: 'Use high-resolution images in PNG format whenever possible'
    """
    h, w = gray.shape
    if h < 16 or w < 16:
        return 80

    # Check for 8x8 block boundary artifacts (JPEG hallmark)
    block_diffs = []
    for y in range(8, min(h - 8, 200), 8):
        row_above = gray[y - 1, :min(w, 200)].astype(float)
        row_at = gray[y, :min(w, 200)].astype(float)
        diff = np.mean(np.abs(row_above - row_at))
        block_diffs.append(diff)

    if not block_diffs:
        return 85

    mean_block_diff = np.mean(block_diffs)
    # Higher block boundary differences = more compression artifacts
    if mean_block_diff < 3.0:
        return 95  # Likely PNG or very high quality JPEG
    elif mean_block_diff < 6.0:
        return 80
    elif mean_block_diff < 12.0:
        return 55
    else:
        return 25  # Heavy compression


def _analyze_background(img: np.ndarray) -> dict:
    """Analyze background for consistency and distraction level.
    From guides: 'Backgrounds should either vary, be neutral, or be removed entirely.
    Distracting elements introduce noise, reduce model focus, and can accelerate overtraining.'
    """
    h, w = img.shape[:2]
    # Sample border regions (top/bottom/left/right edges)
    border_size = max(10, min(h, w) // 8)
    regions = [
        img[:border_size, :, :],                  # top
        img[h - border_size:, :, :],               # bottom
        img[:, :border_size, :],                    # left
        img[:, w - border_size:, :],                # right
    ]

    # Measure color variance in border regions
    all_border = np.concatenate([r.reshape(-1, 3) for r in regions], axis=0)
    border_std = float(np.std(all_border))
    border_mean = all_border.mean(axis=0).tolist()

    # Convert to HSV for better analysis
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    border_hsv = []
    for r in regions:
        if r.size > 0:
            r_hsv = cv2.cvtColor(r, cv2.COLOR_BGR2HSV)
            border_hsv.append(r_hsv.reshape(-1, 3))
    if border_hsv:
        all_border_hsv = np.concatenate(border_hsv, axis=0)
        sat_mean = float(all_border_hsv[:, 1].mean())
    else:
        sat_mean = 50.0

    # Classify background
    if border_std < 15 and sat_mean < 30:
        bg_type = "neutral"  # Clean solid/gradient background (ideal)
    elif border_std < 30:
        bg_type = "simple"  # Relatively clean
    elif border_std < 60:
        bg_type = "moderate"  # Some detail
    else:
        bg_type = "busy"  # Distracting (warn user)

    return {
        "type": bg_type,
        "complexity": round(border_std, 1),
        "border_color_bgr": [int(c) for c in border_mean],
        "saturation": round(sat_mean, 1),
    }


def _sample_skin_tone(img: np.ndarray, face) -> list:
    """Sample skin tone from the detected face region in LAB color space.
    From guides: 'Skin tone must be consistent across the dataset.'
    LAB color space is perceptually uniform — ideal for consistency checking.
    """
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    h, w = img.shape[:2]
    # Sample from center of face (avoid edges/hair)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    fw = x2 - x1
    fh = y2 - y1
    # Inner 40% of face
    sx = max(0, cx - fw // 5)
    sy = max(0, cy - fh // 5)
    ex = min(w, cx + fw // 5)
    ey = min(h, cy + fh // 5)
    if ex <= sx or ey <= sy:
        return [50.0, 0.0, 0.0]

    face_patch = img[sy:ey, sx:ex]
    if face_patch.size == 0:
        return [50.0, 0.0, 0.0]

    lab = cv2.cvtColor(face_patch, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
    return [round(float(lab[:, i].mean()), 1) for i in range(3)]


# ═══════════════════════════════════════════════════════════
# TRAINING BUCKET CALCULATOR
# Implements Mod-64 bucketing algorithm from AI Training Master Reference
# ═══════════════════════════════════════════════════════════

def _assign_bucket(w: int, h: int, target_res: int = 1024) -> dict:
    """Calculate which training bucket an image maps to.
    From the guide: 'Resolution = pixel budget, not fixed dimensions.'
    Algorithm: AR-preserving resize → snap to Mod-64 → minimal center-crop.
    """
    target_area = target_res * target_res
    ar = w / h if h > 0 else 1.0

    new_w = math.sqrt(target_area * ar)
    new_h = math.sqrt(target_area / ar)

    # Snap to nearest multiple of 64
    bucket_w = max(64, round(new_w / 64) * 64)
    bucket_h = max(64, round(new_h / 64) * 64)

    # Calculate actual pixel count and crop needed
    actual_area = bucket_w * bucket_h
    scale_x = bucket_w / w if w > 0 else 1
    scale_y = bucket_h / h if h > 0 else 1
    scale = max(scale_x, scale_y)

    # Crop after scaling
    scaled_w = int(w * scale)
    scaled_h = int(h * scale)
    crop_x = max(0, scaled_w - bucket_w)
    crop_y = max(0, scaled_h - bucket_h)

    return {
        "width": bucket_w,
        "height": bucket_h,
        "ar": round(bucket_w / bucket_h, 3),
        "megapixels": round(actual_area / 1_000_000, 2),
        "crop_px": {"x": crop_x, "y": crop_y},
        "scale_factor": round(scale, 3),
    }


@app.post("/calculate-buckets")
def calculate_buckets(req: BucketRequest):
    """Calculate training buckets for a list of images."""
    results = []
    for w, h in zip(req.widths, req.heights):
        results.append(_assign_bucket(w, h, req.target_resolution))
    # Summarize bucket distribution
    bucket_counts = Counter()
    for r in results:
        bucket_counts[f"{r['width']}x{r['height']}"] += 1

    return {
        "buckets": results,
        "distribution": dict(bucket_counts.most_common()),
        "unique_buckets": len(bucket_counts),
    }


# ═══════════════════════════════════════════════════════════
# NEAR-DUPLICATE DETECTION (pHash)
# From guides: 'Redundancy should be avoided, as repeated visuals introduce
# bias and reduce the model's ability to generalize.'
# ═══════════════════════════════════════════════════════════

@app.post("/find-duplicates")
def find_duplicates(req: DuplicateRequest):
    """Find near-duplicate image pairs using perceptual hashing."""
    hashes = []
    for b64 in req.images:
        try:
            img = decode_image(b64)
            hashes.append(_compute_phash(img))
        except Exception:
            hashes.append(None)

    duplicates = []
    n = len(hashes)
    for i in range(n):
        if hashes[i] is None:
            continue
        for j in range(i + 1, n):
            if hashes[j] is None:
                continue
            dist = _hamming_distance(hashes[i], hashes[j])
            if dist <= req.threshold:
                duplicates.append({
                    "i": i, "j": j,
                    "hamming_distance": dist,
                    "similarity_pct": round((1 - dist / 64) * 100, 1),
                })

    return {
        "duplicates": duplicates,
        "total_checked": n,
        "duplicate_pairs": len(duplicates),
    }


# ═══════════════════════════════════════════════════════════
# COMPREHENSIVE DATASET ANALYSIS
# Combines ALL knowledge from the training guides into a
# single analysis endpoint that evaluates an entire dataset.
# ═══════════════════════════════════════════════════════════

@app.post("/analyze-dataset")
def analyze_dataset(req: DatasetAnalysisRequest):
    """Full dataset analysis with recommendations based on training guides.
    Returns composition analysis, quality distribution, diversity metrics,
    and actionable recommendations."""

    n = len(req.images)
    if n == 0:
        raise HTTPException(400, "No images provided")

    target = req.target_model or "z_image_turbo"
    recs = MODEL_DATASET_RECS.get(target, MODEL_DATASET_RECS["z_image_turbo"])
    target_res = req.target_resolution or 1024

    # ── Per-image analysis ──
    shot_types = []
    poses = []
    face_embeddings = []
    skin_tones = []
    quality_scores = []
    bg_types = []
    image_sizes = []
    artifact_scores = []
    issues = []

    analyzer = get_insightface()

    for idx, b64 in enumerate(req.images):
        try:
            img = decode_image(b64)
            h, w = img.shape[:2]
            image_sizes.append((w, h))
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)

            # Quality metrics
            laplacian = cv2.Laplacian(gray, cv2.CV_32F)
            sharpness = min(100, int(laplacian.var() / 950 * 100))
            brightness = float(gray.mean())
            contrast = min(100, int(gray.std() / 55 * 100))
            artifact = _detect_compression_artifacts(img, gray)
            artifact_scores.append(artifact)

            if sharpness < 25:
                issues.append({"index": idx, "issue": "very_blurry", "severity": "high"})
            if artifact < 40:
                issues.append({"index": idx, "issue": "compression_artifacts", "severity": "high"})
            if brightness > 230:
                issues.append({"index": idx, "issue": "overexposed", "severity": "medium"})
            elif brightness < 40:
                issues.append({"index": idx, "issue": "underexposed", "severity": "medium"})

            # Face analysis
            faces = analyzer.get(img)
            if faces:
                face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                fh = face.bbox[3] - face.bbox[1]
                face_ratio = fh / h
                st = _classify_shot_type(face_ratio)
                shot_types.append(st)
                pose_info = _estimate_pose(face, w, h)
                poses.append(pose_info["yaw"])

                if face.normed_embedding is not None:
                    face_embeddings.append(face.normed_embedding)

                skin = _sample_skin_tone(img, face)
                skin_tones.append(skin)

                if len(faces) > 1:
                    issues.append({"index": idx, "issue": "multiple_faces", "severity": "medium",
                                   "detail": f"{len(faces)} faces detected"})

                # Check centering
                fx = (face.bbox[0] + face.bbox[2]) / 2
                if abs(fx / w - 0.5) > 0.35:
                    issues.append({"index": idx, "issue": "face_off_center", "severity": "low"})
            else:
                shot_types.append("no_face")
                poses.append("no_face")
                issues.append({"index": idx, "issue": "no_face_detected", "severity": "high"})

            # Background
            bg = _analyze_background(img)
            bg_types.append(bg["type"])

            quality_scores.append(sharpness * 0.4 + contrast * 0.3 + (100 - abs(brightness - 128) / 1.28) * 0.3)

        except Exception as e:
            issues.append({"index": idx, "issue": "processing_error", "severity": "high", "detail": str(e)})
            shot_types.append("error")
            poses.append("error")

    # ── Shot type distribution ──
    valid_shots = [s for s in shot_types if s in ("close_up", "mid_shot", "full_body")]
    shot_counts = Counter(valid_shots)
    total_valid = len(valid_shots)
    shot_distribution = {}
    shot_warnings = []
    if total_valid > 0:
        for st in ["close_up", "mid_shot", "full_body"]:
            actual = shot_counts.get(st, 0) / total_valid
            ideal_min, ideal_max = IDEAL_SHOT_DISTRIBUTION[st]
            shot_distribution[st] = {
                "count": shot_counts.get(st, 0),
                "percent": round(actual * 100, 1),
                "ideal_range": f"{int(ideal_min*100)}-{int(ideal_max*100)}%",
                "in_range": ideal_min <= actual <= ideal_max,
            }
            if actual < ideal_min:
                shot_warnings.append(f"Need more {st.replace('_', ' ')} images ({shot_distribution[st]['percent']}% vs {int(ideal_min*100)}-{int(ideal_max*100)}% ideal)")
            elif actual > ideal_max:
                shot_warnings.append(f"Too many {st.replace('_', ' ')} images ({shot_distribution[st]['percent']}% vs {int(ideal_min*100)}-{int(ideal_max*100)}% ideal)")

    # ── Pose diversity ──
    valid_poses = [p for p in poses if p not in ("no_face", "error", "unknown")]
    pose_counts = Counter(valid_poses)
    pose_diversity = {
        "counts": dict(pose_counts),
        "has_frontal": pose_counts.get("frontal", 0) > 0,
        "has_three_quarter": pose_counts.get("three_quarter", 0) > 0,
        "has_profile": pose_counts.get("profile", 0) > 0,
    }
    if len(pose_counts) < 2:
        shot_warnings.append("Low pose diversity — include frontal, three-quarter, and profile angles")

    # ── Face similarity (identity consistency) ──
    identity_score = None
    if len(face_embeddings) >= 2 and req.reference_index is not None:
        ref_idx = req.reference_index
        if ref_idx < len(face_embeddings):
            ref_emb = face_embeddings[ref_idx]
            sims = []
            for i, emb in enumerate(face_embeddings):
                if i != ref_idx:
                    sims.append(float(np.dot(ref_emb, emb)))
            identity_score = {
                "mean_similarity": round(float(np.mean(sims)), 4),
                "min_similarity": round(float(np.min(sims)), 4),
                "max_similarity": round(float(np.max(sims)), 4),
                "outlier_count": sum(1 for s in sims if s < 0.3),
            }
    elif len(face_embeddings) >= 2:
        # Use first image as reference by default
        ref_emb = face_embeddings[0]
        sims = [float(np.dot(ref_emb, emb)) for emb in face_embeddings[1:]]
        identity_score = {
            "mean_similarity": round(float(np.mean(sims)), 4) if sims else 0,
            "min_similarity": round(float(np.min(sims)), 4) if sims else 0,
            "max_similarity": round(float(np.max(sims)), 4) if sims else 0,
            "outlier_count": sum(1 for s in sims if s < 0.3),
        }

    # ── Skin tone consistency ──
    skin_consistency = None
    if len(skin_tones) >= 2:
        skin_arr = np.array(skin_tones)
        skin_std = skin_arr.std(axis=0).tolist()
        # In LAB, L-channel std > 8 or a/b channels std > 5 = inconsistent
        consistent = skin_std[0] < 8 and skin_std[1] < 5 and skin_std[2] < 5
        skin_consistency = {
            "std_lab": [round(s, 2) for s in skin_std],
            "consistent": consistent,
        }
        if not consistent:
            issues.append({"index": -1, "issue": "inconsistent_skin_tones",
                           "severity": "medium", "detail": f"LAB std: L={skin_std[0]:.1f}, a={skin_std[1]:.1f}, b={skin_std[2]:.1f}"})

    # ── Bucket distribution ──
    bucket_info = []
    bucket_counts = Counter()
    for w_img, h_img in image_sizes:
        b = _assign_bucket(w_img, h_img, target_res)
        bucket_info.append(b)
        bucket_counts[f"{b['width']}x{b['height']}"] += 1

    # ── Dataset size recommendation ──
    size_rec = recs.get(req.lora_type, recs.get("character", (15, 25)))
    size_min, size_max = size_rec
    size_ok = size_min <= n <= size_max

    # ── Build recommendations ──
    recommendations = []
    if not size_ok:
        if n < size_min:
            recommendations.append({
                "type": "dataset_size", "severity": "high",
                "message": f"Dataset too small for {target} {req.lora_type} LoRA. Have {n} images, need {size_min}-{size_max}."
            })
        elif n > size_max * 1.5:
            recommendations.append({
                "type": "dataset_size", "severity": "medium",
                "message": f"Dataset may be too large ({n} images). For {target}, {size_min}-{size_max} curated images work best. Quality > quantity."
            })

    for w in shot_warnings:
        recommendations.append({"type": "shot_distribution", "severity": "medium", "message": w})

    no_face_count = shot_types.count("no_face")
    if no_face_count > n * 0.15:
        recommendations.append({
            "type": "missing_faces", "severity": "high",
            "message": f"{no_face_count}/{n} images have no detectable face. Remove or replace these."
        })

    blurry_count = sum(1 for i in issues if i.get("issue") == "very_blurry")
    if blurry_count > 0:
        recommendations.append({
            "type": "quality", "severity": "high",
            "message": f"{blurry_count} images are very blurry. Replace with sharp, well-focused images."
        })

    artifact_bad = sum(1 for s in artifact_scores if s < 40)
    if artifact_bad > 0:
        recommendations.append({
            "type": "quality", "severity": "medium",
            "message": f"{artifact_bad} images have heavy compression artifacts. Use PNG format or high-quality JPEG."
        })

    busy_bg = bg_types.count("busy")
    if busy_bg > n * 0.4:
        recommendations.append({
            "type": "background", "severity": "medium",
            "message": f"{busy_bg}/{n} images have busy backgrounds. Use background removal or neutral backgrounds to reduce noise."
        })

    if recs.get("caption_style") == "minimal":
        recommendations.append({
            "type": "captioning", "severity": "info",
            "message": f"For {target}: use MINIMAL captions (pose + clothing + background only). Silence forces the LoRA to learn facial features."
        })

    # ── Overall dataset grade ──
    score = 100
    for r in recommendations:
        if r["severity"] == "high": score -= 15
        elif r["severity"] == "medium": score -= 7
    for i in issues:
        if i["severity"] == "high": score -= 3
        elif i["severity"] == "medium": score -= 1
    score = max(0, min(100, score))

    overall_grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D" if score >= 30 else "F"

    return {
        "dataset_grade": overall_grade,
        "dataset_score": score,
        "image_count": n,
        "target_model": target,
        "lora_type": req.lora_type,
        "size_recommendation": {"min": size_min, "max": size_max, "ok": size_ok},
        "caption_style": recs.get("caption_style", "moderate"),
        "shot_distribution": shot_distribution,
        "pose_diversity": pose_diversity,
        "identity_consistency": identity_score,
        "skin_consistency": skin_consistency,
        "background_distribution": dict(Counter(bg_types)),
        "quality_stats": {
            "mean_score": round(float(np.mean(quality_scores)), 1) if quality_scores else 0,
            "min_score": round(float(np.min(quality_scores)), 1) if quality_scores else 0,
            "artifact_mean": round(float(np.mean(artifact_scores)), 1) if artifact_scores else 0,
        },
        "bucket_distribution": dict(bucket_counts.most_common()),
        "unique_buckets": len(bucket_counts),
        "issues": issues,
        "recommendations": recommendations,
    }


# ═══════════════════════════════════════════════════════════
# MODEL MANAGEMENT
# ═══════════════════════════════════════════════════════════

@app.post("/models/ensure")
def model_ensure(req: ModelEnsureRequest):
    if req.model == "insightface":
        get_insightface()
        return {"status": "ready", "model": "insightface"}
    elif req.model == "clip":
        get_clip()
        return {"status": "ready", "model": "clip"}
    elif req.model == "florence2":
        get_florence2()
        return {"status": "ready", "model": "florence2"}
    else:
        raise HTTPException(404, f"Unknown model: {req.model}")

@app.post("/models/download")
def model_download(req: ModelDownloadRequest):
    from huggingface_hub import snapshot_download
    target = Path(req.target_dir)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=req.repo, local_dir=str(target))
    return {"status": "downloaded", "model": req.model, "path": str(target)}

@app.get("/models/status")
def models_status():
    return {"loaded": list(_models.keys()), "models_dir": str(MODELS_DIR)}


# ═══════════════════════════════════════════════════════════
# TOPIQ — State-of-the-Art Image Quality Assessment
# NeurIPS 2024, via pyiqa library
# Better than CLIP zero-shot for actual quality measurement
# ═══════════════════════════════════════════════════════════

def get_topiq():
    if "topiq" not in _models:
        log.info("Loading TOPIQ quality assessment model...")
        try:
            import pyiqa
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            metric = pyiqa.create_metric("topiq_nr", device=device)
            _models["topiq"] = {"metric": metric, "device": device}
            log.info(f"TOPIQ ready on {device}.")
        except ImportError:
            log.warning("pyiqa not installed, TOPIQ unavailable. Using CLIP fallback.")
            _models["topiq"] = None
    return _models.get("topiq")


@app.post("/topiq-score")
def topiq_score(req: ImageRequest):
    """Score image quality using TOPIQ (state-of-the-art NR-IQA)."""
    import torch
    from torchvision import transforms
    topiq = get_topiq()
    if topiq is None:
        # Fallback to CLIP aesthetic
        return aesthetic_score(req)

    pil_img = decode_pil(req.image)
    transform = transforms.Compose([
        transforms.Resize((512, 512)),
        transforms.ToTensor(),
    ])
    tensor = transform(pil_img).unsqueeze(0).to(topiq["device"])
    with torch.no_grad():
        score = topiq["metric"](tensor).item()
    # TOPIQ returns 0-1, scale to 0-100
    score_100 = max(0, min(100, int(score * 100)))
    return {"topiq_score": score_100, "raw_score": round(score, 4), "model": "TOPIQ-NR"}


# ═══════════════════════════════════════════════════════════
# BACKGROUND REMOVAL (BRIA RMBG-2.0 via rembg)
# From guides: 'Remove or vary backgrounds to reduce noise and
# prevent overtraining. Fill transparent regions with random
# soft color (random hue, 50% sat, 50% value).'
# ═══════════════════════════════════════════════════════════

@app.post("/remove-background")
def remove_background(req: ImageRequest):
    """Remove image background using BRIA RMBG-2.0.
    Returns base64 image with background replaced by random soft color."""
    try:
        from rembg import remove
        import random

        pil_img = decode_pil(req.image)

        # Remove background (returns RGBA)
        result = remove(pil_img)

        # Generate random soft background color (from guides: random hue, 50% sat, 50% value)
        import colorsys
        hue = random.random()
        r, g, b = colorsys.hsv_to_rgb(hue, 0.15, 0.85)
        bg_color = (int(r * 255), int(g * 255), int(b * 255))

        # Composite onto colored background
        background = Image.new("RGB", result.size, bg_color)
        if result.mode == "RGBA":
            background.paste(result, mask=result.split()[3])
        else:
            background = result.convert("RGB")

        # Encode to base64
        buf = io.BytesIO()
        background.save(buf, format="PNG")
        b64_out = base64.b64encode(buf.getvalue()).decode()

        return {
            "image": f"data:image/png;base64,{b64_out}",
            "bg_color": bg_color,
            "model": "BRIA-RMBG-2.0"
        }
    except ImportError:
        raise HTTPException(500, "rembg not installed. Run: pip install rembg")
    except Exception as e:
        raise HTTPException(500, f"Background removal failed: {str(e)}")


# ═══════════════════════════════════════════════════════════
# ENHANCED DUPLICATE DETECTION (SSCD + pHash)
# SSCD by Meta — learned copy detection embeddings
# Far better than pHash for detecting crops, color edits,
# compression changes, and other transformations
# ═══════════════════════════════════════════════════════════

def get_sscd():
    if "sscd" not in _models:
        log.info("Loading SSCD copy detection model...")
        try:
            import torch
            model = torch.hub.load("facebookresearch/sscd-copy-detection:main", "sscd_disc_mixup",
                                   force_reload=False)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = model.to(device).eval()
            _models["sscd"] = {"model": model, "device": device}
            log.info(f"SSCD ready on {device}.")
        except Exception as e:
            log.warning(f"SSCD unavailable ({e}), falling back to pHash.")
            _models["sscd"] = None
    return _models.get("sscd")


@app.post("/find-duplicates-advanced")
def find_duplicates_advanced(req: DuplicateRequest):
    """Find duplicates using SSCD (learned) + pHash (fast) two-tier approach.
    SSCD catches crops, edits, and compression artifacts that pHash misses."""
    import torch
    from torchvision import transforms

    sscd = get_sscd()
    n = len(req.images)

    # Tier 1: Fast pHash check
    phashes = []
    for b64 in req.images:
        try:
            img = decode_image(b64)
            phashes.append(_compute_phash(img))
        except Exception:
            phashes.append(None)

    phash_dups = []
    for i in range(n):
        if phashes[i] is None: continue
        for j in range(i + 1, n):
            if phashes[j] is None: continue
            dist = _hamming_distance(phashes[i], phashes[j])
            if dist <= req.threshold:
                phash_dups.append({"i": i, "j": j, "method": "phash",
                                   "distance": dist, "similarity_pct": round((1 - dist/64)*100, 1)})

    # Tier 2: SSCD learned similarity (if available)
    sscd_dups = []
    if sscd is not None and n <= 200:  # Limit for memory
        transform = transforms.Compose([
            transforms.Resize(288),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        embeddings = []
        for b64 in req.images:
            try:
                pil_img = decode_pil(b64)
                tensor = transform(pil_img).unsqueeze(0).to(sscd["device"])
                with torch.no_grad():
                    emb = sscd["model"](tensor)
                    emb = emb / emb.norm(dim=-1, keepdim=True)
                embeddings.append(emb.cpu().squeeze())
            except Exception:
                embeddings.append(None)

        # Find SSCD near-duplicates (threshold: 0.75 similarity)
        sscd_threshold = 0.75
        for i in range(n):
            if embeddings[i] is None: continue
            for j in range(i + 1, n):
                if embeddings[j] is None: continue
                sim = float(torch.dot(embeddings[i], embeddings[j]))
                if sim >= sscd_threshold:
                    # Don't duplicate pairs already found by pHash
                    already = any(d["i"] == i and d["j"] == j for d in phash_dups)
                    if not already:
                        sscd_dups.append({"i": i, "j": j, "method": "sscd",
                                          "similarity": round(sim, 4), "similarity_pct": round(sim*100, 1)})

    all_dups = phash_dups + sscd_dups
    return {
        "duplicates": all_dups,
        "phash_count": len(phash_dups),
        "sscd_count": len(sscd_dups),
        "total_pairs": len(all_dups),
        "total_checked": n,
        "sscd_available": sscd is not None,
    }


# ═══════════════════════════════════════════════════════════
# FACE ALIGNMENT (from Facial Recognition Pipeline research)
# Aligning faces to a canonical pose before embedding comparison
# dramatically improves identity verification accuracy.
# Uses affine transform based on eye positions → 112x112 aligned crop.
# ═══════════════════════════════════════════════════════════

def _align_face(img: np.ndarray, face, output_size: int = 112) -> np.ndarray:
    """Align face to canonical frontal pose using eye landmarks.
    From facial recognition pipeline best practices:
    - Rotate to align eyes horizontally
    - Scale to fixed size (112x112 for ArcFace)
    - This removes pose variance and improves embedding quality
    """
    kps = getattr(face, "kps", None)
    if kps is None or len(kps) < 2:
        # Fallback: just crop the face bbox
        x1, y1, x2, y2 = [max(0, int(v)) for v in face.bbox]
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return cv2.resize(img, (output_size, output_size))
        return cv2.resize(crop, (output_size, output_size))

    left_eye = kps[0]
    right_eye = kps[1]

    # Calculate rotation angle
    dy = right_eye[1] - left_eye[1]
    dx = right_eye[0] - left_eye[0]
    angle = math.degrees(math.atan2(dy, dx))

    # Center point between eyes
    eye_center = ((left_eye[0] + right_eye[0]) / 2, (left_eye[1] + right_eye[1]) / 2)

    # Desired eye positions in output (standard alignment)
    desired_left = (0.35 * output_size, 0.35 * output_size)
    desired_right = (0.65 * output_size, 0.35 * output_size)

    # Scale based on inter-eye distance
    eye_dist = math.sqrt(dx**2 + dy**2)
    desired_dist = desired_right[0] - desired_left[0]
    scale = desired_dist / max(eye_dist, 1)

    # Affine transform: rotate + scale
    M = cv2.getRotationMatrix2D(eye_center, angle, scale)
    # Adjust translation to center aligned face
    M[0, 2] += (output_size / 2 - eye_center[0])
    M[1, 2] += (output_size * 0.38 - eye_center[1])

    aligned = cv2.warpAffine(img, M, (output_size, output_size),
                             flags=cv2.INTER_LANCZOS4,
                             borderMode=cv2.BORDER_REFLECT_101)
    return aligned


@app.post("/align-face")
def align_face(req: ImageRequest):
    """Return an aligned face crop (112x112) for better embedding comparison."""
    analyzer = get_insightface()
    img = decode_image(req.image)
    faces = analyzer.get(img)
    if not faces:
        raise HTTPException(400, "No face detected")
    face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
    aligned = _align_face(img, face)

    # Encode as base64
    _, buf = cv2.imencode(".png", aligned)
    b64 = base64.b64encode(buf).decode()
    return {
        "aligned_face": f"data:image/png;base64,{b64}",
        "alignment_score": float(face.det_score),
        "size": 112,
    }


# ═══════════════════════════════════════════════════════════
# WATERMARK / OVERLAY TEXT DETECTION
# From License Plate Recognition & ML preprocessing research:
# - Adaptive thresholding isolates text/watermark overlays
# - Morphological operations enhance detection of thin text
# - High-frequency edge analysis in border regions
# Watermarks corrupt training data — model may learn watermark patterns
# ═══════════════════════════════════════════════════════════

def _detect_watermark(img: np.ndarray) -> dict:
    """Detect potential watermark/overlay text in image.
    Uses adaptive thresholding + morphological analysis to find
    unnatural text-like patterns overlaid on the image.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # CLAHE for enhanced local contrast (reveals subtle watermarks)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Adaptive thresholding — text/watermarks have sharp local contrast
    thresh = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 15, 8)

    # Morphological close to connect text characters
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    # Find contours that look like text regions (wide, thin)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    text_regions = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        aspect = cw / max(ch, 1)
        fill = cv2.contourArea(cnt) / max(area, 1)

        # Text-like: wide aspect ratio, moderate fill, not too small
        if (aspect > 2.5 and area > (w * h * 0.001) and
            fill > 0.15 and ch < h * 0.15):
            text_regions.append({
                "bbox": {"x": int(x), "y": int(y), "w": int(cw), "h": int(ch)},
                "area_pct": round(area / (w * h) * 100, 2),
                "position": "bottom" if y > h * 0.7 else "top" if y < h * 0.3 else "middle",
            })

    # Check corners specifically (common watermark locations)
    corner_regions = [
        gray[0:h//6, 0:w//3],              # top-left
        gray[0:h//6, 2*w//3:w],            # top-right
        gray[5*h//6:h, 0:w//3],            # bottom-left
        gray[5*h//6:h, 2*w//3:w],          # bottom-right
        gray[4*h//5:h, w//4:3*w//4],       # bottom-center (most common)
    ]
    corner_names = ["top-left", "top-right", "bottom-left", "bottom-right", "bottom-center"]
    corner_activity = []
    for region, name in zip(corner_regions, corner_names):
        if region.size == 0:
            continue
        # High-frequency content suggests text/logo
        laplacian = cv2.Laplacian(region, cv2.CV_32F)
        hf_score = float(laplacian.var())
        # Compare to image average
        full_hf = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        if hf_score > full_hf * 1.8 and hf_score > 200:
            corner_activity.append({"corner": name, "hf_score": round(hf_score, 1)})

    has_watermark = len(text_regions) > 0 or len(corner_activity) > 1
    confidence = min(100, len(text_regions) * 30 + len(corner_activity) * 20)

    return {
        "likely_watermark": has_watermark,
        "confidence": confidence,
        "text_regions": text_regions[:5],  # Limit output
        "suspicious_corners": corner_activity,
    }


@app.post("/detect-watermark")
def detect_watermark(req: ImageRequest):
    """Detect watermarks/overlay text that would corrupt training data."""
    img = decode_image(req.image)
    result = _detect_watermark(img)
    return result


# ═══════════════════════════════════════════════════════════
# CLAHE ENHANCED QUALITY ANALYSIS
# From ML preprocessing research: Contrast-Limited Adaptive
# Histogram Equalization reveals detail that global analysis misses.
# Used for more accurate sharpness measurement and detail assessment.
# ═══════════════════════════════════════════════════════════

@app.post("/enhanced-quality")
def enhanced_quality(req: ImageRequest):
    """Enhanced quality assessment using CLAHE preprocessing.
    Provides more accurate sharpness, detail, and noise metrics."""
    img = decode_image(req.image)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Standard metrics
    raw_sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())

    # CLAHE-enhanced metrics (reveals true detail level)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    enhanced_sharpness = float(cv2.Laplacian(enhanced.astype(np.float32), cv2.CV_32F).var())

    # Noise estimation (Median Absolute Deviation of Laplacian)
    # From image processing research: robust noise estimator
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    sigma_noise = float(np.median(np.abs(laplacian)) / 0.6745)

    # Detail density: ratio of edges to total area
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(edges.sum() / 255 / (h * w))

    # Color richness: number of distinct hues
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue_hist = cv2.calcHist([hsv], [0], None, [36], [0, 180]).flatten()
    active_hues = int((hue_hist > (h * w * 0.005)).sum())

    # Dynamic range (from exposure research)
    p_low = float(np.percentile(gray, 1))
    p_high = float(np.percentile(gray, 99))
    dynamic_range = p_high - p_low

    # Watermark check
    wm = _detect_watermark(img)

    # Training readiness score
    # Combines: sharpness (weighted high), noise (penalize), detail, dynamic range
    readiness = int(
        min(100, raw_sharpness / 950 * 100) * 0.30 +
        max(0, 100 - sigma_noise * 2) * 0.20 +
        min(100, edge_density * 1000) * 0.15 +
        min(100, dynamic_range / 2.2) * 0.15 +
        min(100, active_hues / 20 * 100) * 0.10 +
        (0 if wm["likely_watermark"] else 100) * 0.10
    )

    return {
        "sharpness": min(100, int(raw_sharpness / 950 * 100)),
        "enhanced_sharpness": min(100, int(enhanced_sharpness / 1200 * 100)),
        "noise_sigma": round(sigma_noise, 2),
        "noise_level": "low" if sigma_noise < 8 else "moderate" if sigma_noise < 20 else "high",
        "edge_density": round(edge_density, 4),
        "dynamic_range": round(dynamic_range, 1),
        "active_hue_count": active_hues,
        "color_richness": "rich" if active_hues > 15 else "moderate" if active_hues > 8 else "limited",
        "watermark": wm,
        "training_readiness": readiness,
        "image_size": {"w": w, "h": h},
    }


# ═══════════════════════════════════════════════════════════
# LATENT SPACE QUALITY ESTIMATION
# From HuggingFace Diffusion Course research:
# Diffusion models operate in VAE latent space. Images that
# encode poorly in VAE (high reconstruction error) will be
# harder for the model to learn from during LoRA fine-tuning.
# We estimate this using frequency-domain analysis:
# - Images with extreme high-frequency content compress poorly
# - Images with very low detail lack learning signal
# - Optimal: rich mid-frequency detail (textures, edges, structure)
# ═══════════════════════════════════════════════════════════

@app.post("/latent-quality")
def latent_quality_estimate(req: ImageRequest):
    """Estimate how well an image will encode in diffusion model latent space.
    Uses frequency-domain analysis as a proxy for VAE reconstruction quality.
    From diffusion course: images with balanced frequency content train best."""
    img = decode_image(req.image)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # 2D FFT for frequency analysis
    f_transform = np.fft.fft2(gray)
    f_shift = np.fft.fftshift(f_transform)
    magnitude = np.log1p(np.abs(f_shift))

    # Divide spectrum into low/mid/high frequency bands
    cy, cx = h // 2, w // 2
    r_low = min(h, w) // 8      # Low frequency radius
    r_mid = min(h, w) // 3      # Mid frequency radius
    # Rest is high frequency

    y_grid, x_grid = np.ogrid[:h, :w]
    dist = np.sqrt((x_grid - cx)**2 + (y_grid - cy)**2)

    low_mask = dist <= r_low
    mid_mask = (dist > r_low) & (dist <= r_mid)
    high_mask = dist > r_mid

    low_energy = float(magnitude[low_mask].mean()) if low_mask.any() else 0
    mid_energy = float(magnitude[mid_mask].mean()) if mid_mask.any() else 0
    high_energy = float(magnitude[high_mask].mean()) if high_mask.any() else 0
    total_energy = low_energy + mid_energy + high_energy

    # Frequency balance ratios
    if total_energy > 0:
        low_ratio = low_energy / total_energy
        mid_ratio = mid_energy / total_energy
        high_ratio = high_energy / total_energy
    else:
        low_ratio = mid_ratio = high_ratio = 0.33

    # Latent quality score
    # Best: balanced mid-frequency (textures, structure)
    # Penalize: too much high frequency (noise, fine grain) or too little (flat/blurry)
    # From diffusion course: VAE compresses 8x → mid-frequency detail is preserved best
    mid_bonus = min(40, int(mid_ratio * 100))
    high_penalty = max(0, int((high_ratio - 0.35) * 80)) if high_ratio > 0.35 else 0
    low_penalty = max(0, int((low_ratio - 0.5) * 60)) if low_ratio > 0.5 else 0

    latent_score = max(0, min(100, 60 + mid_bonus - high_penalty - low_penalty))

    # Check for problematic patterns
    issues = []
    if high_ratio > 0.45:
        issues.append("excessive_high_frequency")  # Noise, fine texture may not encode well
    if low_ratio > 0.6:
        issues.append("too_flat")  # Very smooth image, limited learning signal
    if mid_ratio < 0.2:
        issues.append("poor_structure")  # Lacks the detail that trains best

    # Resolution adequacy for target training
    megapixels = w * h / 1_000_000
    if megapixels < 0.25:
        issues.append("too_small")
        latent_score = max(0, latent_score - 20)
    elif megapixels > 25:
        issues.append("excessively_large")  # Will be heavily downscaled

    return {
        "latent_quality_score": latent_score,
        "frequency_balance": {
            "low": round(low_ratio, 3),
            "mid": round(mid_ratio, 3),
            "high": round(high_ratio, 3),
        },
        "frequency_assessment": (
            "excellent" if latent_score >= 75 else
            "good" if latent_score >= 55 else
            "fair" if latent_score >= 35 else "poor"
        ),
        "issues": issues,
        "megapixels": round(megapixels, 2),
    }


# ═══════════════════════════════════════════════════════════
# CAPTION QUALITY SCORING
# From LLMs-from-scratch research: good captions for LoRA
# training need information density, correct structure, and
# appropriate detail level per model. This endpoint evaluates
# existing captions against best practices.
# ═══════════════════════════════════════════════════════════

class CaptionScoreRequest(BaseModel):
    caption: str
    target_model: Optional[str] = "z_image_turbo"
    trigger_word: Optional[str] = None
    has_face: bool = True

@app.post("/score-caption")
def score_caption(req: CaptionScoreRequest):
    """Score a caption's quality for LoRA training.
    Evaluates: length, information density, facial description handling,
    trigger word usage, and structural quality."""
    caption = req.caption.strip()
    recs = MODEL_DATASET_RECS.get(req.target_model, MODEL_DATASET_RECS["z_image_turbo"])
    caption_style = recs.get("caption_style", "moderate")

    issues = []
    score = 100

    # Length analysis
    words = caption.split()
    word_count = len(words)

    if caption_style == "minimal":
        # ZIT wants 10-30 words, just pose + clothing + background
        if word_count > 40:
            issues.append({"type": "too_long", "severity": "medium",
                          "message": f"Caption too long for {req.target_model} ({word_count} words). Use 10-30 words."})
            score -= 10
        elif word_count < 5:
            issues.append({"type": "too_short", "severity": "high",
                          "message": "Caption too short — needs at minimum pose + clothing + background."})
            score -= 20
    elif caption_style == "rich":
        if word_count < 15:
            issues.append({"type": "too_short", "severity": "medium",
                          "message": f"Caption may be too short for {req.target_model}. Use 20-60 words with detail."})
            score -= 10
    else:  # moderate
        if word_count < 8:
            issues.append({"type": "too_short", "severity": "medium",
                          "message": "Caption too short. Include key visual elements."})
            score -= 10
        elif word_count > 80:
            issues.append({"type": "too_long", "severity": "low",
                          "message": "Caption very long — consider trimming to essential visual elements."})
            score -= 5

    # Facial description check (silence forces concept learning)
    facial_keywords = [
        "eyes", "hair", "nose", "lips", "mouth", "chin", "jaw",
        "cheekbones", "eyebrows", "eyelashes", "forehead", "freckles",
        "complexion", "skin tone", "facial features", "face shape",
    ]
    has_facial_desc = any(kw in caption.lower() for kw in facial_keywords)

    if req.has_face and caption_style == "minimal" and has_facial_desc:
        issues.append({"type": "facial_description", "severity": "high",
                      "message": "Remove facial descriptions! For character LoRA, silence forces the model to learn facial features."})
        score -= 20
    elif req.has_face and not has_facial_desc and caption_style == "rich":
        # Rich captions should still mostly avoid facial descriptions
        pass  # Not a penalty

    # Trigger word check
    if req.trigger_word:
        if not caption.lower().startswith(req.trigger_word.lower()):
            issues.append({"type": "missing_trigger", "severity": "high",
                          "message": f"Caption should start with trigger word '{req.trigger_word}'."})
            score -= 15

    # Information density: unique content words (not common filler)
    stop_words = {"a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "to", "of",
                  "and", "or", "with", "that", "this", "for", "by", "from", "as", "it", "be"}
    content_words = [w.lower().strip(".,!?;:") for w in words if w.lower().strip(".,!?;:") not in stop_words]
    unique_content = len(set(content_words))
    density = unique_content / max(word_count, 1)

    if density < 0.3:
        issues.append({"type": "low_density", "severity": "low",
                      "message": "Caption has low information density — too many filler words."})
        score -= 5

    # Repetition check
    if word_count > 5:
        from collections import Counter
        word_freq = Counter(content_words)
        max_repeat = max(word_freq.values()) if word_freq else 0
        if max_repeat > 3 and max_repeat / word_count > 0.15:
            issues.append({"type": "repetitive", "severity": "low",
                          "message": "Caption has repetitive words."})
            score -= 5

    # Key elements check: good captions describe pose, clothing, background
    essential_categories = {
        "pose": any(w in caption.lower() for w in ["standing", "sitting", "walking", "posing", "leaning",
                                                     "looking", "facing", "turned", "portrait", "headshot"]),
        "clothing": any(w in caption.lower() for w in ["wearing", "dressed", "shirt", "dress", "suit",
                                                         "jacket", "coat", "top", "pants", "jeans", "outfit"]),
        "setting": any(w in caption.lower() for w in ["background", "studio", "outdoors", "indoor", "room",
                                                        "street", "garden", "office", "beach", "urban", "nature"]),
    }
    missing_elements = [k for k, v in essential_categories.items() if not v]
    if missing_elements and caption_style != "minimal":
        issues.append({"type": "missing_elements", "severity": "low",
                      "message": f"Caption may be missing: {', '.join(missing_elements)}."})
        score -= len(missing_elements) * 3

    score = max(0, min(100, score))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D" if score >= 30 else "F"

    return {
        "caption_score": score,
        "caption_grade": grade,
        "word_count": word_count,
        "unique_content_words": unique_content,
        "information_density": round(density, 2),
        "has_facial_description": has_facial_desc,
        "recommended_style": caption_style,
        "essential_elements": essential_categories,
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════
# CLIP DATASET DIVERSITY METRIC
# From LLMs-from-scratch & Diffusion Course research:
# A well-curated dataset should have CLIP embeddings that cover
# a meaningful spread in embedding space, not cluster too tightly.
# ═══════════════════════════════════════════════════════════

class DiversityRequest(BaseModel):
    images: List[str]

@app.post("/clip-diversity")
def clip_diversity(req: DiversityRequest):
    """Measure CLIP embedding space coverage of a dataset.
    Low diversity = redundant images. High diversity = good training variety."""
    import torch
    clip = get_clip()
    embeddings = []

    for b64 in req.images:
        try:
            pil_img = decode_pil(b64)
            inputs = clip["processor"](images=pil_img, return_tensors="pt").to(clip["device"])
            with torch.no_grad():
                features = clip["model"].get_image_features(**inputs)
                features = features / features.norm(dim=-1, keepdim=True)
            embeddings.append(features[0].cpu().numpy())
        except Exception:
            continue

    if len(embeddings) < 2:
        return {"diversity_score": 0, "error": "Need at least 2 valid images"}

    emb_array = np.array(embeddings)

    # Mean pairwise cosine distance (diversity = 1 - mean_similarity)
    sim_matrix = emb_array @ emb_array.T
    n = len(emb_array)
    pair_sims = []
    for i in range(n):
        for j in range(i + 1, n):
            pair_sims.append(float(sim_matrix[i, j]))

    mean_sim = float(np.mean(pair_sims))
    std_sim = float(np.std(pair_sims))
    min_sim = float(np.min(pair_sims))

    # Diversity score: 0-100, higher = more diverse
    diversity = max(0, min(100, int((1 - mean_sim) * 200)))

    # Embedding spread (std of embeddings along each dimension)
    spread = float(emb_array.std(axis=0).mean())

    # Coverage: how many distinct "regions" the embeddings cover
    # Simple k-means proxy: count clusters at cosine threshold 0.85
    from collections import defaultdict
    visited = set()
    region_count = 0
    for i in range(n):
        if i in visited:
            continue
        region_count += 1
        visited.add(i)
        for j in range(i + 1, n):
            if j not in visited and sim_matrix[i, j] > 0.85:
                visited.add(j)

    return {
        "diversity_score": diversity,
        "mean_pairwise_similarity": round(mean_sim, 4),
        "similarity_std": round(std_sim, 4),
        "min_pairwise_similarity": round(min_sim, 4),
        "embedding_spread": round(spread, 6),
        "distinct_regions": region_count,
        "image_count": n,
        "assessment": (
            "excellent" if diversity >= 60 else
            "good" if diversity >= 40 else
            "moderate" if diversity >= 25 else
            "low — too many similar images"
        ),
    }


# ═══════════════════════════════════════════════════════════
# IMAGE AUGMENTATION (from Facial Recognition Pipeline research)
# Horizontal flip is the safest augmentation for character LoRAs —
# effectively doubles dataset while preserving identity.
# ═══════════════════════════════════════════════════════════

class AugmentRequest(BaseModel):
    image: str
    horizontal_flip: bool = True
    color_jitter: bool = False
    jitter_brightness: float = 0.1
    jitter_contrast: float = 0.1

@app.post("/augment")
def augment_image(req: AugmentRequest):
    """Generate augmented versions of a training image.
    Safe augmentations only: horizontal flip and mild color jitter."""
    img = decode_image(req.image)
    results = []

    if req.horizontal_flip:
        flipped = cv2.flip(img, 1)
        _, buf = cv2.imencode(".png", flipped)
        results.append({
            "image": f"data:image/png;base64,{base64.b64encode(buf).decode()}",
            "augmentation": "horizontal_flip",
        })

    if req.color_jitter:
        import random
        # Brightness jitter
        b_factor = 1.0 + random.uniform(-req.jitter_brightness, req.jitter_brightness)
        jittered = np.clip(img.astype(np.float32) * b_factor, 0, 255).astype(np.uint8)

        # Contrast jitter
        c_factor = 1.0 + random.uniform(-req.jitter_contrast, req.jitter_contrast)
        mean = jittered.mean(axis=(0, 1), keepdims=True)
        jittered = np.clip((jittered - mean) * c_factor + mean, 0, 255).astype(np.uint8)

        _, buf = cv2.imencode(".png", jittered)
        results.append({
            "image": f"data:image/png;base64,{base64.b64encode(buf).decode()}",
            "augmentation": "color_jitter",
            "brightness_factor": round(b_factor, 3),
            "contrast_factor": round(c_factor, 3),
        })

    return {"augmentations": results, "count": len(results)}


# ═══════════════════════════════════════════════════════════
# BORDER / LETTERBOX DETECTION
# From ML preprocessing research: detect black bars, white borders,
# or colored frames that indicate scraped/screenshot images.
# ═══════════════════════════════════════════════════════════

@app.post("/detect-borders")
def detect_borders(req: ImageRequest):
    """Detect letterbox bars, borders, or frames around images."""
    img = decode_image(req.image)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    borders = {}
    threshold = 8  # Max std deviation for "uniform" region

    # Check each edge
    for name, region in [
        ("top", gray[:max(1, h//15), :]),
        ("bottom", gray[h - max(1, h//15):, :]),
        ("left", gray[:, :max(1, w//15)]),
        ("right", gray[:, w - max(1, w//15):]),
    ]:
        if region.size == 0:
            continue
        std = float(region.std())
        mean_val = float(region.mean())
        if std < threshold:
            # Uniform region — likely a border
            color = "black" if mean_val < 30 else "white" if mean_val > 225 else "colored"
            borders[name] = {
                "detected": True, "color": color,
                "mean_intensity": round(mean_val, 1), "std": round(std, 2),
            }

    has_letterbox = len(borders) >= 2
    has_frame = len(borders) == 4

    return {
        "borders": borders,
        "has_letterbox": has_letterbox,
        "has_frame": has_frame,
        "border_count": len(borders),
        "recommendation": (
            "Remove frame — borders add noise to training" if has_frame else
            "Crop letterbox bars — they waste pixel budget" if has_letterbox else
            "Clean — no borders detected"
        ),
    }


# ═══════════════════════════════════════════════════════════
# v5 ENDPOINTS — CLIP EMBEDDINGS + CLUSTERING + UMAP
# fastembed Qdrant/clip-ViT-L-14-vision: ONNX, GPU via onnxruntime-gpu
# ViT-L beats ViT-B by ~15% on retrieval benchmarks
# One embedding per image — feeds clustering, aesthetic, search, dedup
# ═══════════════════════════════════════════════════════════

@app.post("/embed")
def embed_images(req: EmbedRequest):
    """Batch CLIP image embeddings. Returns 768D vectors per image."""
    clip_image, _ = get_clip_fastembed()
    pil_images = [decode_pil(b64) for b64 in req.images]
    embeddings = list(clip_image.embed(pil_images))
    filenames = req.filenames if req.filenames else [str(i) for i in range(len(embeddings))]
    return {
        "embeddings": [e.tolist() for e in embeddings],
        "dim": len(embeddings[0]) if embeddings else 0,
        "filenames": filenames,
    }


@app.post("/embed_text")
def embed_text(req: EmbedTextRequest):
    """Single text query embedding for semantic image search."""
    _, clip_text = get_clip_fastembed()
    embedding = list(clip_text.embed([req.query]))[0]
    return {"embedding": embedding.tolist()}


@app.post("/cluster")
def cluster_embeddings(req: ClusterEmbedRequest):
    """
    HDBSCAN clustering on provided embeddings.
    Superior to K-means: no k required, finds noise class, variable density clusters.
    Use for image content clusters — not face identity (use /face_cluster for that).
    """
    try:
        import hdbscan as hdbscan_lib
    except ImportError:
        raise HTTPException(status_code=503, detail="hdbscan not installed. Run: pip install hdbscan")

    embeddings = np.array(req.embeddings, dtype=np.float32)
    # L2-normalize before clustering (embeddings are cosine space)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, 1e-8)

    clusterer = hdbscan_lib.HDBSCAN(
        min_cluster_size=req.min_cluster_size,
        min_samples=req.min_samples,
        metric="euclidean",           # equivalent to cosine on normalized vectors
        cluster_selection_method="eom",
        prediction_data=True,
    )
    labels = clusterer.fit_predict(embeddings)
    probabilities = clusterer.probabilities_.tolist()

    return {
        "labels": labels.tolist(),
        "probabilities": probabilities,
        "n_clusters": int(labels.max()) + 1 if labels.max() >= 0 else 0,
        "n_noise": int((labels == -1).sum()),
        "filenames": req.filenames,
    }


@app.post("/umap")
def umap_reduce(req: UmapRequest):
    """UMAP 2D reduction for cluster map visualization. Normalizes output to [0,1]."""
    try:
        import umap
    except ImportError:
        raise HTTPException(status_code=503, detail="umap-learn not installed. Run: pip install umap-learn")

    embeddings = np.array(req.embeddings, dtype=np.float32)
    filenames = req.filenames if req.filenames else [str(i) for i in range(len(embeddings))]

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=15,
        min_dist=0.1,
        metric="cosine",
        random_state=42,
        low_memory=False,
    )
    coords = reducer.fit_transform(embeddings)

    # Normalize to [0, 1] for canvas rendering
    x_min, x_max = coords[:, 0].min(), coords[:, 0].max()
    y_min, y_max = coords[:, 1].min(), coords[:, 1].max()
    coords[:, 0] = (coords[:, 0] - x_min) / (x_max - x_min + 1e-8)
    coords[:, 1] = (coords[:, 1] - y_min) / (y_max - y_min + 1e-8)

    return {
        "points": [
            {"filename": filenames[i], "x": float(coords[i, 0]), "y": float(coords[i, 1])}
            for i in range(len(coords))
        ]
    }


# ═══════════════════════════════════════════════════════════
# v5 TRUESKILL RANKING
# Stateless: client owns the full ratings map.
# Server computes Gaussian updates only.
# Fewer comparisons to converge vs ELO; models uncertainty (µ, σ).
# ═══════════════════════════════════════════════════════════

@app.post("/trueskill_update")
def trueskill_update(req: TrueSkillUpdateRequest):
    """
    Update TrueSkill ratings after a match.
    Client maintains the ratings dict; server just computes the update.
    Conservative rating = µ - 3σ (image must consistently win to rank highly).
    """
    import trueskill
    env = get_trueskill_env()
    w_rating = trueskill.Rating(mu=req.winner["mu"], sigma=req.winner["sigma"])
    l_rating = trueskill.Rating(mu=req.loser["mu"], sigma=req.loser["sigma"])

    if req.draw:
        new_w, new_l = env.rate_1vs1(w_rating, l_rating, drawn=True)
    else:
        new_w, new_l = env.rate_1vs1(w_rating, l_rating)

    return {
        "winner": {
            "mu": new_w.mu, "sigma": new_w.sigma,
            "conservative": new_w.mu - 3 * new_w.sigma,
        },
        "loser": {
            "mu": new_l.mu, "sigma": new_l.sigma,
            "conservative": new_l.mu - 3 * new_l.sigma,
        },
    }


# ═══════════════════════════════════════════════════════════
# v5 AESTHETIC SCORING — LAION Aesthetic Predictor v2
# Takes CLIP ViT-L/14 embeddings as input (reuse from /embed).
# No duplicate vision inference.
# Requires: python/models/aesthetic_v2.onnx (run download_models.py)
# ═══════════════════════════════════════════════════════════

@app.post("/aesthetic")
def aesthetic_score(req: AestheticRequest):
    """
    LAION aesthetic predictor v2. Input: CLIP ViT-L/14 embeddings.
    Returns scores normalized to [0,1] (raw output is ~1-10).
    """
    session = get_aesthetic_model()
    if session is None:
        raise HTTPException(
            status_code=503,
            detail="Aesthetic model not found. Run: python download_models.py"
        )
    embeddings = np.array(req.embeddings, dtype=np.float32)
    # L2-normalize (same as CLIP output normalization)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, 1e-8)

    input_name = session.get_inputs()[0].name
    scores_raw = session.run(None, {input_name: embeddings})[0].flatten()
    scores_norm = np.clip((scores_raw - 1) / 9, 0, 1)
    filenames = req.filenames if req.filenames else [str(i) for i in range(len(scores_raw))]

    return {
        "scores": scores_norm.tolist(),
        "scores_raw": scores_raw.tolist(),
        "filenames": filenames,
    }


# ═══════════════════════════════════════════════════════════
# v5 ENHANCED FACE ENDPOINT
# Adds: pose (yaw/pitch/roll), 512D ArcFace embedding, face_quality score.
# Optional deep_attrs: DeepFace emotion on crop (CPU only).
# ═══════════════════════════════════════════════════════════

@app.post("/face")
def analyze_face_enhanced(req: FaceEnhancedRequest):
    """
    Enhanced InsightFace endpoint with ArcFace embeddings and quality scoring.
    Optionally appends DeepFace emotion analysis using InsightFace's face crop.
    """
    analyzer = get_insightface()
    img_pil = decode_pil(req.image)
    img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    faces = analyzer.get(img_bgr)
    results = []

    for face in faces:
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        result = {
            "bbox": [x1, y1, x2, y2],
            "score": float(face.det_score),
            "landmark_5p": face.kps.tolist() if face.kps is not None else [],
            "pose": {
                "yaw":   float(face.pose[1]) if hasattr(face, "pose") and face.pose is not None else 0.0,
                "pitch": float(face.pose[0]) if hasattr(face, "pose") and face.pose is not None else 0.0,
                "roll":  float(face.pose[2]) if hasattr(face, "pose") and face.pose is not None else 0.0,
            },
            "age": int(face.age) if hasattr(face, "age") and face.age is not None else None,
            "gender": "female" if getattr(face, "gender", 1) == 0 else "male",
            "embedding": face.normed_embedding.tolist() if face.normed_embedding is not None else [],
            "face_quality": _compute_face_quality_v2(face),
        }

        if req.deep_attrs:
            crop_bgr = img_bgr[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
            if crop_bgr.size > 0:
                try:
                    DeepFace = get_deepface()
                    attrs = DeepFace.analyze(
                        img_path=crop_bgr,
                        actions=["emotion"],
                        detector_backend="skip",
                        enforce_detection=False,
                        silent=True,
                    )
                    result["emotion"] = attrs[0]["dominant_emotion"]
                    result["emotion_scores"] = attrs[0]["emotion"]
                except Exception:
                    pass

        results.append(result)

    return {"faces": results, "count": len(results)}


def _compute_face_quality_v2(face) -> float:
    """
    Composite face quality score (0-1):
    - RetinaFace detection confidence (60%)
    - Pose frontal penalty — yaw/pitch deviation (40%)
    """
    det_score = float(face.det_score)
    if hasattr(face, "pose") and face.pose is not None:
        yaw_penalty = max(0.0, 1.0 - abs(float(face.pose[1])) / 90.0)
        pitch_penalty = max(0.0, 1.0 - abs(float(face.pose[0])) / 60.0)
        pose_score = (yaw_penalty + pitch_penalty) / 2.0
    else:
        pose_score = 0.5
    return round(det_score * 0.6 + pose_score * 0.4, 3)


@app.post("/face_attrs")
def face_attributes(req: FaceAttrsRequest):
    """
    DeepFace attribute analysis on pre-cropped face images.
    Returns emotion, estimated age, and race for each crop.
    CPU-only — detector_backend='skip' avoids double detection.
    """
    DeepFace = get_deepface()
    results = []
    for b64 in req.images:
        img_bgr = decode_image(b64)
        try:
            attrs = DeepFace.analyze(
                img_path=img_bgr,
                actions=["emotion", "age", "race"],
                detector_backend="skip",
                enforce_detection=False,
                silent=True,
            )
            results.append({
                "emotion": attrs[0]["dominant_emotion"],
                "emotion_scores": attrs[0]["emotion"],
                "age": attrs[0]["age"],
                "race": attrs[0]["dominant_race"],
            })
        except Exception as e:
            results.append({"error": str(e)})
    return {"results": results}


@app.post("/face_cluster")
def cluster_face_identities(req: FaceClusterRequest):
    """
    DBSCAN on ArcFace 512D embeddings → identity groups.
    Uses cosine metric (embeddings live on a hypersphere).
    DBSCAN (not HDBSCAN) — cosine metric + hypersphere structure is ideal here.
    """
    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import normalize

    embeddings = np.array(req.embeddings, dtype=np.float32)
    embeddings = normalize(embeddings)  # L2 normalize

    clustering = DBSCAN(
        eps=req.eps,
        min_samples=req.min_samples,
        metric="cosine",
        n_jobs=-1,
    ).fit(embeddings)

    labels = clustering.labels_
    identities: Dict[str, List[str]] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        key = f"identity_{label:03d}"
        identities.setdefault(key, []).append(req.filenames[i])

    return {
        "assignments": {
            req.filenames[i]: (f"identity_{labels[i]:03d}" if labels[i] != -1 else None)
            for i in range(len(labels))
        },
        "identities": identities,
        "n_identities": len(identities),
        "n_unmatched": int((labels == -1).sum()),
    }


# ═══════════════════════════════════════════════════════════
# v5 EXPORT SYSTEM
# Copies files (+ caption .txt sidecars) to output_dir.
# Modes: flat (as-is), clustered (subfolders), ranked/arena (prefixed 0001_)
# ═══════════════════════════════════════════════════════════

@app.post("/export_split")
def export_split(req: ExportSplitRequest):
    """Export dataset into output directory with configurable layout."""
    import shutil
    from pathlib import Path as P

    source = P(req.source_dir)
    output = P(req.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    copied = 0
    errors = []

    if req.mode == "clustered":
        for filename, cluster_label in req.assignments.items():
            src = source / filename
            if not src.exists():
                errors.append(f"Missing: {filename}")
                continue
            dest_dir = output / (cluster_label or "unclustered")
            dest_dir.mkdir(exist_ok=True)
            shutil.copy2(src, dest_dir / filename)
            cap = source / (P(filename).stem + ".txt")
            if cap.exists():
                shutil.copy2(cap, dest_dir / cap.name)
            copied += 1

    elif req.mode in ("ranked", "arena"):
        for i, filename in enumerate(req.order):
            src = source / filename
            if not src.exists():
                errors.append(f"Missing: {filename}")
                continue
            stem = P(filename).stem
            ext = P(filename).suffix
            shutil.copy2(src, output / f"{i + 1:04d}_{stem}{ext}")
            cap = source / (stem + ".txt")
            if cap.exists():
                shutil.copy2(cap, output / f"{i + 1:04d}_{stem}.txt")
            copied += 1

    else:  # flat
        filenames = req.order or list(req.assignments.keys())
        for filename in filenames:
            src = source / filename
            if not src.exists():
                errors.append(f"Missing: {filename}")
                continue
            shutil.copy2(src, output / filename)
            cap = source / (P(filename).stem + ".txt")
            if cap.exists():
                shutil.copy2(cap, output / cap.name)
            copied += 1

    return {
        "status": "ok",
        "output_dir": str(output),
        "copied": copied,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════
# v5 REORDER — Rename files on disk by sort order
# Prefixes filenames with rank: 0001_original.jpg, 0002_...
# ═══════════════════════════════════════════════════════════

@app.post("/reorder")
def reorder_files(req: ReorderRequest):
    """Rename files on disk by sort order (e.g. dracoScore or arena rank)."""
    from pathlib import Path as P
    import shutil

    source = P(req.source_dir)
    renamed = 0
    errors = []

    for i, filename in enumerate(req.order):
        src = source / filename
        if not src.exists():
            errors.append(f"Missing: {filename}")
            continue
        stem = P(filename).stem
        ext = P(filename).suffix
        prefix = str(i + 1).zfill(req.prefix_digits)
        new_name = f"{prefix}_{stem}{ext}"
        dest = source / new_name
        if src != dest:
            try:
                src.rename(dest)
                # Also rename caption sidecar
                cap = source / (stem + ".txt")
                if cap.exists():
                    cap.rename(source / f"{prefix}_{stem}.txt")
                renamed += 1
            except Exception as e:
                errors.append(f"{filename}: {e}")

    return {
        "status": "ok",
        "renamed": renamed,
        "errors": errors,
    }


# ── Main ─────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    log.info(f"Starting DRACO sidecar on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
