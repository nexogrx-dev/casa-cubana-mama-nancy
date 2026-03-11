#!/usr/bin/env python3
"""
Casa Cubana Mamá Nancy — Instagram/WhatsApp Raw Archive Processor

Goal:
  Build a clean, editorial, production-ready web image set from the full raw archive
  with minimal manual work: dedupe, score, classify, select, resize, WebP, report.

Usage:
  python3 scripts/process-ig-archive.py run
  python3 scripts/process-ig-archive.py run --raw 04_media/raw --out public/images_web
  python3 scripts/process-ig-archive.py run --dry-run
  python3 scripts/process-ig-archive.py inspect

Requires:
  - Pillow (installed)
  - OpenCV + numpy (installed)

Notes:
  - Excludes obviously invented/AI images by filename (e.g. "Gemini_Generated_Image*").
  - Does not change website copy or layout; only produces ready-to-drop image assets + reports.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageFilter, ImageOps, ImageStat

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"Error: missing dependencies for face detection (opencv/numpy). {e}")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RAW = ROOT / "04_media" / "raw"
DEFAULT_OUT = ROOT / "public" / "images_web"
SEED_MANIFEST = ROOT / "photos-manifest.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

# Requested categories
CATEGORIES = ("hero", "nancy", "food", "cocktails", "history", "memories")

# Keep sets small and strong (production-ready)
DEFAULT_LIMITS: Dict[str, int] = {
    "hero": 1,
    "nancy": 10,
    "food": 12,
    "cocktails": 10,
    "history": 12,
    "memories": 20,
}

# Role filenames requested for integration
ROLE_TARGETS: Dict[str, str] = {
    "nancy-portrait": "nancy",
    "casa-rincon": "history",
    "nancy-habana": "nancy",
    "comida-mesa": "food",
    "cocteles-mojitos": "cocktails",
    "bar-detalle": "history",
    "casa-habana": "history",
    "memorias-fachada": "memories",
    "memorias-mojitos": "memories",
    "memorias-habana": "memories",
    "memorias-nancy": "memories",
    "memorias-barra": "memories",
    "memorias-mesa": "memories",
}


def _pct(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(xs[int(k)])
    return float(xs[f] * (c - k) + xs[c] * (k - f))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _norm_percentile(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return _clamp((x - lo) / (hi - lo), 0.0, 1.0)


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _slugify_filename(stem: str) -> str:
    s = stem.strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "image"


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def dhash(image: Image.Image, hash_size: int = 8) -> int:
    resized = image.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    # Pillow 12 deprecates getdata(); keep forward-compatible.
    if hasattr(resized, "get_flattened_data"):
        pixels = list(resized.get_flattened_data())  # type: ignore[attr-defined]
    else:
        pixels = list(resized.getdata())
    w = hash_size + 1
    bits: List[bool] = []
    for row in range(hash_size):
        for col in range(hash_size):
            bits.append(pixels[row * w + col] < pixels[row * w + col + 1])
    return sum((1 if b else 0) << i for i, b in enumerate(bits))


def hamming_distance(h1: int, h2: int) -> int:
    return int(bin(h1 ^ h2).count("1"))


@dataclass
class Metrics:
    width: int
    height: int
    megapixels: float
    aspect: float
    mean_r: float
    mean_g: float
    mean_b: float
    warm_excess: float
    green_excess: float
    blue_excess: float
    edge_mean: float
    sharpness_raw: float
    mean_luma: float
    stdev_luma: float
    clip_low: float
    clip_high: float
    sat_mean: float
    center_edge_ratio: float
    thirds_edge_score: float
    faces: int
    max_face_area_ratio: float


def _measure_sharpness(gray: Image.Image) -> Tuple[float, float]:
    edges = gray.filter(ImageFilter.FIND_EDGES)
    st = ImageStat.Stat(edges)
    return float(st.var[0]), float(st.mean[0])


def _luma_stats(gray: Image.Image) -> Tuple[float, float, float, float]:
    hist = gray.histogram()
    total = float(sum(hist)) or 1.0
    mean_val = sum(i * hist[i] for i in range(256)) / total
    # Approx stddev from histogram
    var = sum(((i - mean_val) ** 2) * hist[i] for i in range(256)) / total
    stdev = math.sqrt(var)
    clip_low = sum(hist[:5]) / total
    clip_high = sum(hist[-5:]) / total
    return float(mean_val), float(stdev), float(clip_low), float(clip_high)


def _saturation_mean(rgb: Image.Image) -> float:
    hsv = rgb.convert("HSV")
    s = hsv.split()[1]
    return float(ImageStat.Stat(s).mean[0]) / 255.0


def _composition_scores(gray: Image.Image) -> Tuple[float, float]:
    # Use edge energy in a small image; compare center vs overall,
    # and measure edge energy along rule-of-thirds lines.
    edges = gray.filter(ImageFilter.FIND_EDGES).resize((128, 128), Image.BILINEAR)
    a = np.asarray(edges, dtype=np.float32)
    overall = float(a.mean()) + 1e-6

    c0, c1 = 128 // 3, 2 * 128 // 3
    center = a[c0:c1, c0:c1].mean()
    center_ratio = float(center / overall)

    thirds_x = (128 // 3, 2 * 128 // 3)
    thirds_y = (128 // 3, 2 * 128 // 3)
    v_lines = [a[:, x].mean() for x in thirds_x]
    h_lines = [a[y, :].mean() for y in thirds_y]
    thirds = float((sum(v_lines) + sum(h_lines)) / 4.0 / overall)
    return center_ratio, thirds


def _load_face_cascade() -> cv2.CascadeClassifier:
    cascade_path = Path(getattr(cv2.data, "haarcascades", "")) / "haarcascade_frontalface_default.xml"
    if not cascade_path.is_file():
        raise RuntimeError("OpenCV haarcascade not found; cannot do face detection.")
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise RuntimeError("Failed to load OpenCV haarcascade for face detection.")
    return cascade


FACE_CASCADE = _load_face_cascade()


def _face_metrics(rgb: Image.Image) -> Tuple[int, float]:
    # Work at a max dimension for speed
    img = rgb
    w, h = img.size
    scale = 900 / max(w, h) if max(w, h) > 900 else 1.0
    if scale != 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
    gray = np.asarray(img.convert("L"))

    faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    if len(faces) == 0:
        return 0, 0.0

    img_area = float(gray.shape[0] * gray.shape[1])
    max_area_ratio = 0.0
    for (x, y, fw, fh) in faces:
        max_area_ratio = max(max_area_ratio, (fw * fh) / img_area)
    return int(len(faces)), float(max_area_ratio)


def compute_metrics(img_in: Image.Image) -> Metrics:
    img = ImageOps.exif_transpose(img_in)
    width, height = img.size
    mp = (width * height) / 1_000_000.0
    aspect = width / height if height else 1.0

    # Color signature on a small thumbnail (fast + robust)
    thumb = img.convert("RGB").resize((64, 64), Image.BILINEAR)
    r, g, b = thumb.split()
    mean_r = float(ImageStat.Stat(r).mean[0])
    mean_g = float(ImageStat.Stat(g).mean[0])
    mean_b = float(ImageStat.Stat(b).mean[0])
    warm_excess = (mean_r - mean_b) + 0.35 * (mean_r - mean_g)
    green_excess = mean_g - (mean_r + mean_b) / 2.0
    blue_excess = mean_b - (mean_r + mean_g) / 2.0

    gray = img.convert("L")
    sharpness_raw, edge_mean = _measure_sharpness(gray)
    mean_luma, stdev_luma, clip_low, clip_high = _luma_stats(gray)
    sat_mean = _saturation_mean(img.convert("RGB"))
    center_ratio, thirds = _composition_scores(gray)
    faces, max_face_area_ratio = _face_metrics(img.convert("RGB"))

    return Metrics(
        width=width,
        height=height,
        megapixels=round(mp, 3),
        aspect=aspect,
        mean_r=mean_r,
        mean_g=mean_g,
        mean_b=mean_b,
        warm_excess=warm_excess,
        green_excess=green_excess,
        blue_excess=blue_excess,
        edge_mean=edge_mean,
        sharpness_raw=sharpness_raw,
        mean_luma=mean_luma,
        stdev_luma=stdev_luma,
        clip_low=clip_low,
        clip_high=clip_high,
        sat_mean=sat_mean,
        center_edge_ratio=center_ratio,
        thirds_edge_score=thirds,
        faces=faces,
        max_face_area_ratio=max_face_area_ratio,
    )


def exposure_score(mean_luma: float, clip_low: float, clip_high: float) -> float:
    # Target a warm, documentary exposure (slightly on the bright side but not clipped).
    target = 135.0
    dist = abs(mean_luma - target)
    base = 1.0 - _clamp(dist / 75.0, 0.0, 1.0)
    clip_pen = _clamp((clip_low + clip_high) * 3.0, 0.0, 1.0)
    return _clamp(base * (1.0 - clip_pen), 0.0, 1.0)


def resolution_score(width: int, height: int) -> float:
    mp = (width * height) / 1_000_000.0
    mp_norm = _clamp(mp / 3.5, 0.0, 1.0)  # 3.5MP ~= full score
    min_dim_norm = _clamp(min(width, height) / 1200.0, 0.0, 1.0)
    return 0.6 * mp_norm + 0.4 * min_dim_norm


def face_presence_score(faces: int, max_face_area_ratio: float) -> float:
    if faces <= 0:
        return 0.0
    # Reward a clear face presence; cap quickly
    area = _clamp(max_face_area_ratio * 18.0, 0.0, 1.0)
    count = 1.0 if faces == 1 else 0.75 if faces == 2 else 0.6
    return _clamp(0.7 * area + 0.3 * count, 0.0, 1.0)


def composition_score(center_edge_ratio: float, thirds_edge_score: float) -> float:
    # Center ratio around 1.05–1.35 is good (subject present without being messy).
    center = 1.0 - _clamp(abs(center_edge_ratio - 1.2) / 0.65, 0.0, 1.0)
    thirds = _clamp((thirds_edge_score - 0.9) / 0.7, 0.0, 1.0)
    return 0.6 * center + 0.4 * thirds


def build_seed_map(path: Path) -> Dict[str, str]:
    """
    Map existing categories from previous curation to requested categories.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    mapping = {
        "hero": "hero",
        "nancy": "nancy",
        "comida": "food",
        "cocteles": "cocktails",
        "casa": "history",
        "memorias": "memories",
    }
    seed: Dict[str, str] = {}
    for e in data:
        cat = (e.get("category") or "").strip()
        if not cat:
            continue
        mapped = mapping.get(cat)
        if mapped:
            seed[str(e.get("file"))] = mapped
    return seed


def is_invented(path: Path) -> bool:
    n = path.name.lower()
    if n.startswith("gemini_generated_image"):
        return True
    if "generated" in n and "image" in n:
        return True
    return False


def classify(
    *,
    filename: str,
    metrics: Metrics,
    seed_category: Optional[str],
    sat_mean: float,
    mean_luma: float,
) -> Tuple[str, List[str]]:
    if seed_category in CATEGORIES:
        return seed_category, ["seeded-from-manifest"]

    reasons: List[str] = []

    face_score = face_presence_score(metrics.faces, metrics.max_face_area_ratio)
    if face_score >= 0.50 and metrics.max_face_area_ratio >= 0.02 and metrics.faces <= 2:
        reasons.append(f"faces={metrics.faces}")
        return "nancy", reasons

    # Heuristic: mojitos / bar drinks often skew green and have specular highlights.
    if metrics.green_excess >= 10 and sat_mean >= 0.16 and metrics.clip_high >= 0.006:
        reasons.append("green-skew")
        reasons.append("specular-highlights")
        return "cocktails", reasons

    # Heuristic: food tends to be warm/saturated, textured, close-up.
    # Use warmth + saturation rather than just texture (to avoid misclassifying interiors).
    if metrics.warm_excess >= 22 and sat_mean >= 0.16 and metrics.sharpness_raw >= 110:
        reasons.append("warmth")
        return "food", reasons

    # Heuristic: Cuban blue walls / facade shots.
    if metrics.blue_excess >= 10 and mean_luma >= 60:
        reasons.append("blue-wall")
        return "history", reasons

    # Heuristic: history tends to be wider/architectural, calmer saturation.
    if (metrics.aspect >= 1.25 or metrics.aspect <= 0.82) and sat_mean <= 0.25 and mean_luma >= 65:
        reasons.append("architectural-aspect")
        return "history", reasons

    return "memories", ["documentary-detail"]


def score_image(m: Metrics, sharp_lo: float, sharp_hi: float) -> Dict[str, float]:
    sharp = _norm_percentile(m.sharpness_raw, sharp_lo, sharp_hi)
    exp = exposure_score(m.mean_luma, m.clip_low, m.clip_high)
    res = resolution_score(m.width, m.height)
    comp = composition_score(m.center_edge_ratio, m.thirds_edge_score)
    face = face_presence_score(m.faces, m.max_face_area_ratio)

    overall = (
        sharp * 0.28
        + exp * 0.22
        + res * 0.18
        + comp * 0.18
        + face * 0.14
    )

    return {
        "sharpness": sharp,
        "exposure": exp,
        "resolution": res,
        "composition": comp,
        "face_presence": face,
        "overall": overall,
    }


def affinity_scores(m: Metrics, parts: Dict[str, float], edge_lo: float, edge_hi: float) -> Dict[str, float]:
    # Normalize edge mean to a 0..1 "busyness" measure
    edge_busyness = _norm_percentile(m.edge_mean, edge_lo, edge_hi)

    nancy_aff = parts["face_presence"]

    food_aff = _clamp((m.warm_excess - 8) / 55.0, 0.0, 1.0) * 0.45
    food_aff += _clamp((m.sat_mean - 0.12) / 0.32, 0.0, 1.0) * 0.25
    food_aff += _clamp(parts["sharpness"], 0.0, 1.0) * 0.20
    food_aff += _clamp(edge_busyness, 0.0, 1.0) * 0.10

    cocktails_aff = _clamp((m.sat_mean - 0.14) / 0.38, 0.0, 1.0) * 0.35
    cocktails_aff += _clamp((m.clip_high - 0.004) / 0.03, 0.0, 1.0) * 0.25
    cocktails_aff += _clamp(m.green_excess / 18.0, 0.0, 1.0) * 0.20
    cocktails_aff += _clamp(1.0 - edge_busyness, 0.0, 1.0) * 0.20

    aspect_aff = 1.0 if (m.aspect >= 1.25 or m.aspect <= 0.82) else 0.45
    history_aff = aspect_aff * 0.30
    history_aff += _clamp((m.blue_excess + 5) / 28.0, 0.0, 1.0) * 0.30
    history_aff += _clamp((0.28 - m.sat_mean) / 0.20, 0.0, 1.0) * 0.20
    history_aff += _clamp(parts["composition"], 0.0, 1.0) * 0.20

    memories_aff = _clamp(parts["composition"], 0.0, 1.0) * 0.55
    memories_aff += _clamp((m.sat_mean - 0.08) / 0.55, 0.0, 1.0) * 0.20
    memories_aff += _clamp(parts["sharpness"], 0.0, 1.0) * 0.15
    memories_aff += _clamp(parts["exposure"], 0.0, 1.0) * 0.10

    return {
        "nancy": _clamp(nancy_aff, 0.0, 1.0),
        "food": _clamp(food_aff, 0.0, 1.0),
        "cocktails": _clamp(cocktails_aff, 0.0, 1.0),
        "history": _clamp(history_aff, 0.0, 1.0),
        "memories": _clamp(memories_aff, 0.0, 1.0),
    }


def hero_score(parts: Dict[str, float], m: Metrics) -> float:
    # Strong emotional/editorial presence: prioritize composition + face + sharpness,
    # while still requiring reasonable exposure and resolution.
    return (
        parts["composition"] * 0.34
        + parts["face_presence"] * 0.30
        + parts["sharpness"] * 0.18
        + parts["exposure"] * 0.12
        + parts["resolution"] * 0.06
    )


def choose_role(
    role: str,
    entries: List[Dict[str, Any]],
    *,
    prefer_category: str,
) -> Optional[Dict[str, Any]]:
    # Lightweight role heuristics to keep this automatic and fast.
    candidates = [e for e in entries if e["selected"] and e["category"] == prefer_category]
    if not candidates:
        candidates = [e for e in entries if e["selected"]]
    if not candidates:
        return None

    def key(e: Dict[str, Any]) -> Tuple[float, float, float]:
        m = e["metrics"]
        parts = e["parts"]
        # Role-specific nudges
        if role in {"nancy-portrait", "memorias-nancy", "nancy-habana"}:
            return (
                parts["face_presence"],
                parts["composition"],
                parts["overall"],
            )
        if role in {"cocteles-mojitos", "memorias-mojitos"}:
            return (
                parts["exposure"],
                parts["composition"],
                parts["overall"],
            )
        if role in {"comida-mesa", "memorias-mesa"}:
            return (
                parts["composition"],
                parts["exposure"],
                parts["overall"],
            )
        if role in {"casa-rincon", "bar-detalle", "casa-habana", "memorias-fachada", "memorias-barra", "memorias-habana"}:
            return (
                parts["composition"],
                parts["sharpness"],
                parts["overall"],
            )
        return (parts["overall"], parts["composition"], parts["sharpness"])

    candidates.sort(key=key, reverse=True)
    return candidates[0]


def export_webp(
    src: Path,
    dst: Path,
    *,
    max_width: int = 1600,
    quality: int = 82,
) -> Tuple[int, int]:
    with Image.open(src) as im0:
        im = ImageOps.exif_transpose(im0).convert("RGB")
        w, h = im.size
        if w > max_width:
            new_h = int(h * (max_width / w))
            im = im.resize((max_width, new_h), Image.LANCZOS)
            w, h = im.size
        _safe_mkdir(dst.parent)
        im.save(dst, "WEBP", quality=quality, method=6, optimize=True)
        return w, h


def cmd_inspect(raw_dir: Path) -> None:
    if not raw_dir.is_dir():
        raise SystemExit(f"Raw folder not found: {raw_dir}")

    files = [p for p in raw_dir.iterdir() if p.is_file()]
    imgs = [p for p in files if p.suffix.lower() in IMAGE_EXTENSIONS]
    print(f"Raw folder: {raw_dir}")
    print(f"Total files: {len(files)}")
    print(f"Images: {len(imgs)}")
    exts: Dict[str, int] = {}
    for p in imgs:
        exts[p.suffix.lower()] = exts.get(p.suffix.lower(), 0) + 1
    print("Extensions:", ", ".join(f"{k}:{v}" for k, v in sorted(exts.items())))
    invented = sum(1 for p in imgs if is_invented(p))
    print(f"Excluded invented/AI (by filename): {invented}")


def cmd_run(raw_dir: Path, out_dir: Path, *, dry_run: bool, limits: Dict[str, int]) -> Dict[str, Any]:
    if not raw_dir.is_dir():
        raise SystemExit(f"Raw folder not found: {raw_dir}")

    seed = build_seed_map(SEED_MANIFEST)

    # Collect candidates
    paths: List[Path] = []
    skipped_non_images = 0
    for p in sorted(raw_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTENSIONS:
            skipped_non_images += 1
            continue
        paths.append(p)

    # Phase 1: exact dedupe by file hash
    by_hash: Dict[str, List[Path]] = {}
    for p in paths:
        by_hash.setdefault(_sha256(p), []).append(p)
    exact_dupe_groups = [g for g in by_hash.values() if len(g) > 1]

    def best_of(group: List[Path]) -> Path:
        # Prefer largest pixel count, then largest file size.
        best = group[0]
        best_px = -1
        best_sz = -1
        for p in group:
            try:
                with Image.open(p) as im:
                    px = im.size[0] * im.size[1]
            except Exception:
                px = 0
            sz = p.stat().st_size
            if (px, sz) > (best_px, best_sz):
                best, best_px, best_sz = p, px, sz
        return best

    exact_keep = {best_of(g) for g in exact_dupe_groups}
    exact_dupes = set()
    for g in exact_dupe_groups:
        for p in g:
            if p not in exact_keep:
                exact_dupes.add(p)

    candidates = [p for p in paths if p not in exact_dupes]

    # Phase 2: compute metrics + dhash
    entries: List[Dict[str, Any]] = []
    errors: List[Tuple[str, str]] = []
    sharpness_values: List[float] = []
    edge_mean_values: List[float] = []

    for p in candidates:
        if is_invented(p):
            entries.append(
                {
                    "file": p.name,
                    "path": str(p),
                    "skip_reason": "invented/ai (filename)",
                    "selected": False,
                    "category": "",
                }
            )
            continue
        try:
            with Image.open(p) as im:
                im.load()
                m = compute_metrics(im)
                sharpness_values.append(m.sharpness_raw)
                edge_mean_values.append(m.edge_mean)
                h = dhash(ImageOps.exif_transpose(im))
        except Exception as e:
            errors.append((p.name, str(e)))
            continue

        entries.append(
            {
                "file": p.name,
                "path": str(p),
                "dhash": h,
                "metrics": m,
                "seed_category": seed.get(p.name),
                "skip_reason": "",
                "selected": False,
                "category": "",
            }
        )

    sharp_lo = _pct(sharpness_values, 15)
    sharp_hi = _pct(sharpness_values, 90)
    edge_lo = _pct(edge_mean_values, 15)
    edge_hi = _pct(edge_mean_values, 90)

    # Phase 3: near-duplicate grouping by dhash
    # With ~100–1000 images, a simple bucket + local comparisons is fast enough.
    threshold = 8
    buckets: Dict[int, List[int]] = {}
    for idx, e in enumerate(entries):
        if "dhash" not in e:
            continue
        h = int(e["dhash"])
        buckets.setdefault(h >> 48, []).append(idx)  # coarse bucket by high 16 bits

    near_dupe_of: Dict[int, int] = {}  # idx -> idx_kept
    near_groups: List[List[int]] = []
    visited = set()

    # Precompute scores for selecting best within group
    for e in entries:
        if "metrics" not in e:
            continue
        m: Metrics = e["metrics"]
        parts = score_image(m, sharp_lo, sharp_hi)
        e["parts"] = parts
        e["affinity"] = affinity_scores(m, parts, edge_lo, edge_hi)
        e["score"] = round(parts["overall"] * 100.0, 1)

    for idx, e in enumerate(entries):
        if idx in visited or "dhash" not in e or "metrics" not in e:
            continue
        h = int(e["dhash"])
        candidates_idx: List[int] = []
        for b in (h >> 48,):
            candidates_idx.extend(buckets.get(b, []))
        group = [idx]
        visited.add(idx)
        for j in candidates_idx:
            if j == idx or j in visited:
                continue
            ej = entries[j]
            if "dhash" not in ej or "metrics" not in ej:
                continue
            if hamming_distance(h, int(ej["dhash"])) <= threshold:
                group.append(j)
                visited.add(j)
        if len(group) > 1:
            near_groups.append(group)

    near_dupe_count = 0
    for group in near_groups:
        group_sorted = sorted(group, key=lambda i: float(entries[i].get("score", 0.0)), reverse=True)
        keep = group_sorted[0]
        for j in group_sorted[1:]:
            near_dupe_of[j] = keep
            near_dupe_count += 1

    # Phase 4: classify + select
    for i, e in enumerate(entries):
        if e.get("skip_reason"):
            continue
        if i in near_dupe_of:
            e["skip_reason"] = f"near-duplicate of {entries[near_dupe_of[i]]['file']}"
            continue
        if "metrics" not in e:
            continue
        m: Metrics = e["metrics"]
        parts = e["parts"]
        sat = m.sat_mean
        cat, reasons = classify(
            filename=e["file"],
            metrics=m,
            seed_category=e.get("seed_category"),
            sat_mean=sat,
            mean_luma=m.mean_luma,
        )
        e["category_guess"] = cat
        e["class_reasons"] = reasons
        e["quality_reasons"] = []
        if parts["face_presence"] >= 0.35:
            e["quality_reasons"].append("face presence")
        if parts["sharpness"] >= 0.65:
            e["quality_reasons"].append("sharp")
        if parts["exposure"] >= 0.65:
            e["quality_reasons"].append("good exposure")
        if parts["composition"] >= 0.62:
            e["quality_reasons"].append("good composition")

    # Pick hero from strongest candidates (not invented / not dup / not tiny)
    pool = [
        e
        for e in entries
        if not e.get("skip_reason")
        and "metrics" in e
        and float(e.get("score", 0.0)) >= 40.0
        and e["metrics"].width >= 900
    ]

    hero_candidates = list(pool)
    for e in hero_candidates:
        e["hero_score"] = round(hero_score(e["parts"], e["metrics"]) * 100.0, 2)
    hero_candidates.sort(key=lambda e: float(e.get("hero_score", 0.0)), reverse=True)
    hero_pick = hero_candidates[0] if hero_candidates else None
    selected: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    chosen_files: set[str] = set()

    if hero_pick:
        hero_pick["selected"] = True
        hero_pick["category"] = "hero"
        hero_pick["class_reasons"] = (hero_pick.get("class_reasons") or []) + ["picked-as-hero"]
        selected["hero"] = [hero_pick]
        chosen_files.add(hero_pick["file"])

    def pick_for_category(cat: str, limit: int, weight_overall: float, weight_aff: float) -> None:
        if limit <= 0:
            return
        cand = [e for e in pool if e["file"] not in chosen_files]
        # Nudge: honor manifest guesses when strong
        def cat_key(e: Dict[str, Any]) -> float:
            overall = float(e["parts"]["overall"])
            aff = float(e["affinity"].get(cat, 0.0))
            seed_bonus = 0.06 if e.get("category_guess") == cat else 0.0
            return (overall * weight_overall) + (aff * weight_aff) + seed_bonus

        cand.sort(key=cat_key, reverse=True)
        picks = []
        for e in cand:
            if len(picks) >= limit:
                break
            # Basic quality gate per category (keeps weak/blurry out)
            score = float(e.get("score", 0.0))
            if cat in ("nancy", "food") and score < 46.0:
                continue
            if cat == "cocktails" and score < 44.0:
                continue
            if cat == "history" and score < 42.0:
                continue
            if cat == "memories" and score < 40.0:
                continue
            e["selected"] = True
            e["category"] = cat
            chosen_files.add(e["file"])
            picks.append(e)
        selected[cat].extend(picks)

    pick_for_category("nancy", limits.get("nancy", 0), weight_overall=0.62, weight_aff=0.38)
    pick_for_category("food", limits.get("food", 0), weight_overall=0.70, weight_aff=0.30)
    pick_for_category("cocktails", limits.get("cocktails", 0), weight_overall=0.60, weight_aff=0.40)
    pick_for_category("history", limits.get("history", 0), weight_overall=0.68, weight_aff=0.32)
    pick_for_category("memories", limits.get("memories", 0), weight_overall=0.72, weight_aff=0.28)

    # Export
    report: Dict[str, Any] = {}
    report["raw_dir"] = str(raw_dir)
    report["out_dir"] = str(out_dir)
    report["total_images_found"] = len(paths)
    report["skipped_non_image_files"] = skipped_non_images
    report["exact_duplicates_removed"] = sum(len(g) - 1 for g in exact_dupe_groups)
    report["near_duplicates_removed"] = near_dupe_count
    report["errors"] = errors
    report["selected_counts"] = {k: len(v) for k, v in selected.items()}
    report["hero_choice"] = hero_pick["file"] if hero_pick else None

    if dry_run:
        return {"entries": entries, "report": report, "selected": selected}

    _clear_dir(out_dir)
    for cat in CATEGORIES:
        _safe_mkdir(out_dir / cat)

    exported: List[Dict[str, Any]] = []
    for cat, items in selected.items():
        for e in items:
            src = Path(e["path"])
            m: Metrics = e["metrics"]
            slug = _slugify_filename(Path(e["file"]).stem)
            short = hashlib.sha1(e["file"].encode("utf-8")).hexdigest()[:8]
            out_name = f"{slug}-{short}.webp" if cat != "hero" else "hero.webp"
            dst = out_dir / cat / out_name
            w, h = export_webp(src, dst, max_width=1600, quality=82)
            exported.append(
                {
                    "selected_filename": out_name,
                    "source_filename": e["file"],
                    "category": cat,
                    "score": float(e.get("score", 0.0)),
                    "hero_score": float(e.get("hero_score", 0.0) or 0.0),
                    "reasons": ", ".join(e.get("quality_reasons") or e.get("class_reasons") or []),
                    "width": w,
                    "height": h,
                    "source_width": m.width,
                    "source_height": m.height,
                }
            )

    # Role exports (fixed filenames)
    role_map: Dict[str, str] = {}
    for role, prefer_cat in ROLE_TARGETS.items():
        chosen = choose_role(role, entries, prefer_category=prefer_cat)
        if not chosen:
            continue
        src = Path(chosen["path"])
        dst = out_dir / ROLE_TARGETS[role] / f"{role}.webp"
        export_webp(src, dst, max_width=1600, quality=82)
        role_map[role] = f"{ROLE_TARGETS[role]}/{role}.webp"

    # Reports
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "roles.json").write_text(json.dumps(role_map, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary CSV
    with open(out_dir / "summary.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "selected_filename",
                "category",
                "score",
                "hero_score",
                "width",
                "height",
                "source_filename",
                "source_width",
                "source_height",
                "reasons",
            ],
        )
        w.writeheader()
        for row in sorted(exported, key=lambda r: (r["category"], -r["score"], r["selected_filename"])):
            w.writerow(row)

    # Lightweight contact sheet (HTML)
    html_lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'/>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'/>",
        "<title>Casa Cubana Mamá Nancy — images_web contact sheet</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:24px;background:#faf7f2;color:#111}",
        "h1{font-size:20px;margin:0 0 12px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}",
        ".card{background:#fff;border:1px solid rgba(0,0,0,0.08);border-radius:10px;overflow:hidden}",
        "img{width:100%;height:160px;object-fit:cover;display:block;background:#eee}",
        ".meta{padding:10px 10px 12px;font-size:12px;line-height:1.4}",
        ".k{font-weight:700}",
        ".pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#eee;margin-right:6px}",
        "</style></head><body>",
        "<h1>Casa Cubana Mamá Nancy — images_web</h1>",
        "<p style='margin:0 0 16px;font-size:13px'>Generated by process-ig-archive.py. Sorted by category then score.</p>",
        "<div class='grid'>",
    ]
    for row in sorted(exported, key=lambda r: (r["category"], -r["score"])):
        rel = f"./{row['category']}/{row['selected_filename']}"
        html_lines.extend(
            [
                "<div class='card'>",
                f"<img src='{rel}' loading='lazy'/>",
                "<div class='meta'>",
                f"<div><span class='pill'>{row['category']}</span> <span class='k'>{row['score']:.1f}</span></div>",
                f"<div style='opacity:.75'>{row['selected_filename']}</div>",
                f"<div style='opacity:.75'>{row['reasons']}</div>",
                "</div></div>",
            ]
        )
    html_lines.extend(["</div></body></html>"])
    (out_dir / "contact-sheet.html").write_text("\n".join(html_lines), encoding="utf-8")

    report["final_selected_images"] = len(exported)
    report["selected_files_by_category"] = {
        cat: [r["selected_filename"] for r in exported if r["category"] == cat]
        for cat in CATEGORIES
    }
    report["selected_files"] = [r["selected_filename"] for r in exported]
    report["role_filenames"] = role_map
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"entries": entries, "report": report, "selected": selected, "exported": exported, "roles": role_map}


def parse_limits(s: str) -> Dict[str, int]:
    # Example: hero=1,nancy=10,food=12,cocktails=8,history=10,memories=18
    out = dict(DEFAULT_LIMITS)
    if not s.strip():
        return out
    for part in s.split(","):
        if not part.strip():
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = int(v.strip())
        if k in out:
            out[k] = v
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    insp = sub.add_parser("inspect", help="Inspect raw folder and counts")
    insp.add_argument("--raw", type=Path, default=DEFAULT_RAW)

    run = sub.add_parser("run", help="Run full pipeline and export images_web")
    run.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    run.add_argument("--out", type=Path, default=DEFAULT_OUT)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--limits", type=str, default="")

    args = ap.parse_args(argv)

    if args.cmd == "inspect":
        cmd_inspect(args.raw)
        return 0

    if args.cmd == "run":
        limits = parse_limits(args.limits)
        result = cmd_run(args.raw, args.out, dry_run=args.dry_run, limits=limits)
        report = result["report"]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if not args.dry_run:
            print(f"\nWrote: {args.out}/report.json")
            print(f"Wrote: {args.out}/summary.csv")
            print(f"Wrote: {args.out}/contact-sheet.html")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
