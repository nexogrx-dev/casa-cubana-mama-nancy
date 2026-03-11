#!/usr/bin/env python3
"""
Casa Cubana Mamá Nancy — Image Curation Pipeline

Usage:
  python3 scripts/curate-photos.py scan    # Scan /04_media/raw, deduplicate, rank, generate manifest
  python3 scripts/curate-photos.py build   # Read manifest, copy categorized images to /photos/

Requires: pip3 install Pillow
"""

import json
import os
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image, ImageFilter, ImageStat
except ImportError:
    print("Error: Pillow not installed. Run: pip3 install Pillow")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "04_media" / "raw"
PHOTOS_DIR = ROOT / "photos"
MANIFEST = ROOT / "photos-manifest.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

CATEGORY_LIMITS = {
    "hero": 1,
    "casa": 3,
    "nancy": 2,
    "comida": 6,
    "cocteles": 3,
    "memorias": 6,
}

VALID_CATEGORIES = set(CATEGORY_LIMITS.keys()) | {"skip", ""}

# ── dHash (perceptual hash) ─────────────────────────────────────────────────

def dhash(image, hash_size=8):
    """Compute difference hash. Returns an integer."""
    resized = image.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(resized.getdata())
    w = hash_size + 1
    bits = []
    for row in range(hash_size):
        for col in range(hash_size):
            bits.append(pixels[row * w + col] < pixels[row * w + col + 1])
    return sum(b << i for i, b in enumerate(bits))


def hamming_distance(h1, h2):
    """Count differing bits between two hashes."""
    return bin(h1 ^ h2).count("1")


# ── Quality metrics ─────────────────────────────────────────────────────────

def measure_sharpness(image):
    """Estimate sharpness via edge detection variance (higher = sharper)."""
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(edges)
    # Variance of edge intensities
    return stat.var[0]


def measure_brightness(image):
    """Mean brightness 0–255. Returns score 0–100 penalizing extremes."""
    gray = image.convert("L")
    mean_val = ImageStat.Stat(gray).mean[0]
    # Ideal range: 80–180. Penalize outside.
    if 80 <= mean_val <= 180:
        return 100.0
    elif mean_val < 80:
        return max(0, 100 - (80 - mean_val) * 1.5)
    else:
        return max(0, 100 - (mean_val - 180) * 1.5)


def measure_resolution(image):
    """Score based on megapixels. Cap at 4MP for max score."""
    mp = (image.width * image.height) / 1_000_000
    return min(100.0, mp * 25)  # 4MP = 100


def composite_score(sharpness_raw, brightness_score, resolution_score):
    """Weighted composite. Sharpness is normalized to 0–100 range."""
    # Sharpness raw can vary wildly; normalize with a soft cap
    sharpness_norm = min(100.0, sharpness_raw / 20.0)
    return round(
        sharpness_norm * 0.50 + brightness_score * 0.25 + resolution_score * 0.25,
        1,
    )


# ── Scan command ────────────────────────────────────────────────────────────

def cmd_scan():
    if not RAW_DIR.is_dir():
        print(f"Error: {RAW_DIR} not found.")
        sys.exit(1)

    # Collect image paths
    files = sorted(
        f
        for f in RAW_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not files:
        print(f"No images found in {RAW_DIR}")
        sys.exit(1)

    print(f"Scanning {len(files)} images in {RAW_DIR}...\n")

    # Phase 1: compute hashes and metrics
    entries = []
    errors = []

    for i, fpath in enumerate(files, 1):
        try:
            img = Image.open(fpath)
            img.load()  # Force load to catch corrupt files
        except Exception as e:
            errors.append((fpath.name, str(e)))
            continue

        h = dhash(img)
        sharpness = measure_sharpness(img)
        brightness = measure_brightness(img)
        resolution = measure_resolution(img)
        score = composite_score(sharpness, brightness, resolution)

        entries.append(
            {
                "file": fpath.name,
                "hash": h,
                "score": score,
                "sharpness": round(sharpness, 1),
                "brightness": round(brightness, 1),
                "resolution": f"{img.width}x{img.height}",
                "megapixels": round((img.width * img.height) / 1_000_000, 2),
                "duplicate_of": None,
                "category": "",
            }
        )

        if i % 20 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] processed")

    # Phase 2: find near-duplicates
    THRESHOLD = 8
    duplicate_count = 0

    for i, a in enumerate(entries):
        if a["duplicate_of"] is not None:
            continue
        for b in entries[i + 1 :]:
            if b["duplicate_of"] is not None:
                continue
            if hamming_distance(a["hash"], b["hash"]) <= THRESHOLD:
                # Keep the higher-scored one
                if b["score"] >= a["score"]:
                    a["duplicate_of"] = b["file"]
                else:
                    b["duplicate_of"] = a["file"]
                duplicate_count += 1

    # Phase 3: sort by score (best first), duplicates at bottom
    unique = [e for e in entries if e["duplicate_of"] is None]
    dupes = [e for e in entries if e["duplicate_of"] is not None]
    unique.sort(key=lambda x: x["score"], reverse=True)
    dupes.sort(key=lambda x: x["score"], reverse=True)

    manifest = unique + dupes

    # Remove internal hash (not useful for the user)
    for entry in manifest:
        del entry["hash"]

    # Write manifest
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*50}")
    print(f"  SCAN COMPLETE")
    print(f"{'='*50}")
    print(f"  Total images:    {len(entries)}")
    print(f"  Unique:          {len(unique)}")
    print(f"  Duplicates:      {duplicate_count}")
    if errors:
        print(f"  Errors:          {len(errors)}")
        for name, err in errors:
            print(f"    - {name}: {err}")
    print(f"\n  Top 10 by quality:")
    for i, e in enumerate(unique[:10], 1):
        print(f"    {i:2d}. [{e['score']:5.1f}] {e['resolution']:>10s}  {e['file']}")
    print(f"\n  Manifest saved to: {MANIFEST}")
    print(f"\n  NEXT STEP:")
    print(f"  Open photos-manifest.json and set 'category' for each image:")
    print(f"  hero, casa, nancy, comida, cocteles, memorias, or skip")
    print(f"  Then run: npm run curate:build")


# ── Build command ───────────────────────────────────────────────────────────

def cmd_build():
    if not MANIFEST.is_file():
        print(f"Error: {MANIFEST} not found. Run 'scan' first.")
        sys.exit(1)

    with open(MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Validate categories
    categorized = {}
    for entry in manifest:
        cat = entry.get("category", "").strip().lower()
        if not cat or cat == "skip":
            continue
        if cat not in CATEGORY_LIMITS:
            print(f"Warning: unknown category '{cat}' for {entry['file']}, skipping.")
            continue
        categorized.setdefault(cat, []).append(entry)

    if not categorized:
        print("No images have been categorized yet.")
        print("Open photos-manifest.json and set 'category' for each image.")
        sys.exit(1)

    # Enforce limits (take best-scored within each category)
    for cat, items in categorized.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        limit = CATEGORY_LIMITS[cat]
        if len(items) > limit:
            print(f"  {cat}: {len(items)} assigned, limit is {limit}. Taking top {limit}.")
            categorized[cat] = items[:limit]

    # Create folder structure
    for cat in CATEGORY_LIMITS:
        (PHOTOS_DIR / cat).mkdir(parents=True, exist_ok=True)

    # Copy files
    total_copied = 0
    print(f"\nBuilding /photos/ ...\n")

    for cat, items in sorted(categorized.items()):
        print(f"  {cat}/ ({len(items)} images)")
        for i, entry in enumerate(items, 1):
            src = RAW_DIR / entry["file"]
            if not src.exists():
                print(f"    ✗ {entry['file']} — not found in raw/")
                continue
            ext = src.suffix.lower()
            dst = PHOTOS_DIR / cat / f"{cat}-{i:02d}{ext}"
            shutil.copy2(src, dst)
            print(f"    ✓ {entry['file']} → {cat}/{dst.name}")
            total_copied += 1

    print(f"\n{'='*50}")
    print(f"  BUILD COMPLETE")
    print(f"{'='*50}")
    print(f"  Copied {total_copied} images to {PHOTOS_DIR}/")
    for cat in CATEGORY_LIMITS:
        count = len(list((PHOTOS_DIR / cat).glob("*"))) if (PHOTOS_DIR / cat).exists() else 0
        limit = CATEGORY_LIMITS[cat]
        status = "✓" if count > 0 else "·"
        print(f"    {status} {cat}: {count}/{limit}")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scan", "build"):
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "scan":
        cmd_scan()
    elif sys.argv[1] == "build":
        cmd_build()


if __name__ == "__main__":
    main()
