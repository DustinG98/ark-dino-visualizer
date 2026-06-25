from pathlib import Path
from typing import Optional
import json

import numpy as np
from PIL import Image, ImageEnhance

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DINO_IMAGE_DIR = DATA_DIR / "dino_images" / "images"

REGION_COUNT = 6
NEUTRAL_COLOR_ID = 18

_REGION_CACHE_PATH = DINO_IMAGE_DIR / "_region_cache.json"


def _file_hash(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}-{stat.st_mtime}"


def _load_region_cache() -> dict[str, list[int]]:
    if _REGION_CACHE_PATH.exists():
        with open(_REGION_CACHE_PATH) as f:
            return json.load(f)
    return {}


def _save_region_cache(cache: dict[str, list[int]]) -> None:
    with open(_REGION_CACHE_PATH, "w") as f:
        json.dump(cache, f)


def _overlay_blend_arr(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    return np.where(
        base < 128,
        (2 * base * overlay) / 255.0,
        255.0 - (2 * (255.0 - base) * (255.0 - overlay)) / 255.0,
    )


def _get_region_weights_arr(mask_rgb: np.ndarray) -> np.ndarray:
    max_val = mask_rgb.max(axis=2, keepdims=True)
    valid = (max_val[..., 0] >= 10)
    safe_max = np.where(max_val > 0, max_val, 1.0)
    rn = mask_rgb[..., 0] / safe_max[..., 0]
    gn = mask_rgb[..., 1] / safe_max[..., 0]
    bn = mask_rgb[..., 2] / safe_max[..., 0]

    weights = np.stack([
        rn * (1 - gn) * (1 - bn),   # 0: Red
        gn * (1 - rn) * (1 - bn),   # 1: Green
        bn * (1 - rn) * (1 - gn),   # 2: Blue
        gn * bn * (1 - rn),          # 3: Cyan
        rn * gn * (1 - bn),          # 4: Yellow
        rn * bn * (1 - gn),          # 5: Magenta
    ], axis=2)

    total = weights.sum(axis=2, keepdims=True)
    weights = weights / np.where(total > 0.0001, total, 1.0)
    weights[~valid] = 0.0
    return weights


# Option 2: push target color away from gray along its own hue vector
def _saturate_color(color: np.ndarray, factor: float = 1.6) -> np.ndarray:
    gray = color.mean()
    return np.clip(gray + (color - gray) * factor, 0, 255)


def detect_used_regions(mask_path: Path) -> set[int]:
    mask_arr = np.array(Image.open(mask_path).convert("RGB"), dtype=np.float32)
    weights = _get_region_weights_arr(mask_arr)
    return {region_id for region_id in range(REGION_COUNT) if weights[..., region_id].max() > 0.1}


def apply_region_color(
    image: Image.Image,
    mask: Image.Image,
    region_colors: dict[int, int],
    color_lut: dict[int, tuple[int, int, int]],
    color_saturate_factor: float = 1.6,   # Option 2 strength (1.0 = off)
    post_saturate_factor: float = 1.35,    # Option 4 strength (1.0 = off)
) -> Image.Image:
    has_alpha = image.mode == "RGBA"
    if has_alpha:
        alpha = np.array(image)[:, :, 3]

    image_rgb = np.array(image.convert("RGB"), dtype=np.float32)
    mask_rgb  = np.array(mask.convert("RGB"),  dtype=np.float32)

    weights = _get_region_weights_arr(mask_rgb)

    H, W = image_rgb.shape[:2]
    blended = np.zeros((H, W, 3), dtype=np.float32)

    for region_id in range(REGION_COUNT):
        w = weights[..., region_id]
        if w.max() < 0.001:
            continue

        color_id   = region_colors.get(region_id, NEUTRAL_COLOR_ID)
        target     = color_lut.get(color_id, (128, 128, 128))

        # Option 2: saturate the target color before blending
        target_arr = _saturate_color(
            np.array(target, dtype=np.float32),
            factor=color_saturate_factor,
        )

        for c in range(3):
            blended[..., c] += _overlay_blend_arr(image_rgb[..., c], target_arr[c]) * w

    max_val    = mask_rgb.max(axis=2)
    mask_alpha = np.clip(max_val / 255.0, 0.0, 1.0)
    intensity  = (0.72 * mask_alpha)[..., np.newaxis]

    result_rgb = np.clip(image_rgb * (1 - intensity) + blended * intensity, 0, 255).astype(np.uint8)

    # Option 4: mask-weighted post-blend saturation boost
    if post_saturate_factor != 1.0:
        boosted_arr = np.array(
            ImageEnhance.Color(Image.fromarray(result_rgb, "RGB")).enhance(post_saturate_factor),
            dtype=np.float32,
        )
        mask_weight = mask_alpha[..., np.newaxis]
        result_rgb = np.clip(
            result_rgb.astype(np.float32) * (1 - mask_weight) + boosted_arr * mask_weight,
            0, 255,
        ).astype(np.uint8)

    if has_alpha:
        return Image.fromarray(np.dstack([result_rgb, alpha]), "RGBA")
    return Image.fromarray(result_rgb, "RGB")


def load_color_lut() -> dict[int, tuple[int, int, int]]:
    color_path = DATA_DIR / "asa_colors.json"
    with open(color_path) as f:
        color_json = json.load(f)

    lut = {}
    for entry in color_json:
        hex_str = entry["Hex"].lstrip("#")
        lut[entry["ID"]] = (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
        )
    return lut


def load_color_entries() -> list[dict]:
    with open(DATA_DIR / "asa_colors.json") as f:
        return json.load(f)


def load_region_mappings() -> list[dict]:
    with open(DATA_DIR / "asa_region_mappings.json") as f:
        data = json.load(f)
    return data.get("Region Mapping", [])


def _is_asa_image(filename: str) -> bool:
    return filename.endswith("_ASA.png") and "_ASA_v" not in filename


def _parse_dino_name(filename: str) -> str:
    return filename.replace("_ASA.png", "")


def get_dino_list(search: Optional[str] = None) -> list[dict]:
    with open(DINO_IMAGE_DIR / "_manifest.json") as f:
        manifest = json.load(f)

    cache = _load_region_cache()
    cache_dirty = False

    dinos = []
    for filename in manifest["files"]:
        if not _is_asa_image(filename):
            continue

        name = _parse_dino_name(filename)
        mask_filename = filename.replace(".png", "_m.png")
        mask_path = DINO_IMAGE_DIR / mask_filename

        used_regions: list[int] = []
        if mask_path.exists():
            file_key = f"{mask_filename}:{_file_hash(mask_path)}"
            if file_key in cache:
                used_regions = cache[file_key]
            else:
                used_regions = sorted(detect_used_regions(mask_path))
                cache[file_key] = used_regions
                cache_dirty = True

        dinos.append({
            "name": name,
            "imageFile": filename,
            "maskFile": mask_filename,
            "searchTerms": [t.lower() for t in name.replace("_", " ").split()],
            "usedRegions": used_regions,
        })

    if cache_dirty:
        _save_region_cache(cache)

    dinos.sort(key=lambda d: d["name"])

    if search:
        term = search.lower()
        dinos = [d for d in dinos if any(term in t for t in d["searchTerms"])]

    return dinos