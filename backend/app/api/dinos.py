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

REF = np.array([
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.0, 1.0, 1.0],
    [1.0, 1.0, 0.0],
    [1.0, 0.0, 1.0],
], dtype=np.float32)

for i in range(6):
    v = REF[i]
    l = np.linalg.norm(v)
    REF[i] = v / l

SLOT_REF_RGB = np.array([
    [255, 0, 0],
    [0, 255, 0],
    [0, 0, 255],
    [0, 255, 255],
    [255, 255, 0],
    [255, 0, 255],
], dtype=np.float32)

MAX_SLOT_REF_DIST = np.sqrt(255 * 255 * 3)


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


def _srgb_to_linear(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(np.maximum(v, 0), 1 / 2.4) - 0.055)


def _srgb_to_linear_gamma(v: np.ndarray, g: float = 2.2) -> np.ndarray:
    return np.clip(v, 0, 1) ** g


def _linear_to_srgb_gamma(v: np.ndarray, g: float = 2.2) -> np.ndarray:
    return np.clip(v, 0, 1) ** (1 / g)


def _smoothstep(a: float, b: float, x: np.ndarray) -> np.ndarray:
    if b <= a:
        return np.where(x < a, 0, 1)
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _rgb2oklab(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rl = _srgb_to_linear(r)
    gl = _srgb_to_linear(g)
    bl = _srgb_to_linear(b)

    l = 0.4122214708 * rl + 0.5363325363 * gl + 0.0514459929 * bl
    m = 0.2119034982 * rl + 0.6806995451 * gl + 0.1073969566 * bl
    s = 0.0883024619 * rl + 0.2817188376 * gl + 0.6299787005 * bl

    l = np.cbrt(l)
    m = np.cbrt(m)
    s = np.cbrt(s)

    L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
    b_val = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
    return L, a, b_val


def _oklab2rgb(L: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.291485548 * b

    l = l_ ** 3
    m = m_ ** 3
    s = s_ ** 3

    rl = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    gl = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = 0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s

    return (
        np.clip(_linear_to_srgb(rl), 0, 1),
        np.clip(_linear_to_srgb(gl), 0, 1),
        np.clip(_linear_to_srgb(bl), 0, 1),
    )


def _oklab_to_lch(L: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    C = np.hypot(a, b)
    h = np.arctan2(b, a)
    return L, C, h


def _lch_to_oklab(L: np.ndarray, C: np.ndarray, h: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    a = C * np.cos(h)
    b_val = C * np.sin(h)
    return L, a, b_val


def _chamfer_forward(dist: np.ndarray, lab: np.ndarray, W1: float, W2: float) -> None:
    """Forward chamfer distance pass (in-place)."""
    h, w = dist.shape
    for y in range(h):
        for x in range(w):
            d = dist[y, x]
            l = lab[y, x]
            if d >= 1e9:
                continue
            if x > 0:
                nd = dist[y, x - 1] + W1
                if nd < d:
                    d = nd
                    l = lab[y, x - 1]
            if y > 0:
                nd = dist[y - 1, x] + W1
                if nd < d:
                    d = nd
                    l = lab[y - 1, x]
            if x > 0 and y > 0:
                nd = dist[y - 1, x - 1] + W2
                if nd < d:
                    d = nd
                    l = lab[y - 1, x - 1]
            if x < w - 1 and y > 0:
                nd = dist[y - 1, x + 1] + W2
                if nd < d:
                    d = nd
                    l = lab[y - 1, x + 1]
            dist[y, x] = d
            if lab[y, x] < 0 and l >= 0:
                lab[y, x] = l


def _chamfer_backward(dist: np.ndarray, lab: np.ndarray, W1: float, W2: float) -> None:
    """Backward chamfer distance pass (in-place)."""
    h, w = dist.shape
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            d = dist[y, x]
            l = lab[y, x]
            if x < w - 1:
                nd = dist[y, x + 1] + W1
                if nd < d:
                    d = nd
                    l = lab[y, x + 1]
            if y < h - 1:
                nd = dist[y + 1, x] + W1
                if nd < d:
                    d = nd
                    l = lab[y + 1, x]
            if x < w - 1 and y < h - 1:
                nd = dist[y + 1, x + 1] + W2
                if nd < d:
                    d = nd
                    l = lab[y + 1, x + 1]
            if x > 0 and y < h - 1:
                nd = dist[y + 1, x - 1] + W2
                if nd < d:
                    d = nd
                    l = lab[y + 1, x - 1]
            dist[y, x] = d
            if lab[y, x] < 0 and l >= 0:
                lab[y, x] = l


def _get_mask_exactness_2d(
    slot: np.ndarray, mr: np.ndarray, mg: np.ndarray, mb: np.ndarray,
    threshold: float = 80, feather: float = 0,
) -> np.ndarray:
    """Vectorized mask exactness computation across all pixels."""
    t = np.clip(threshold / 150.0, 0, 1)
    fw = 0.02 + np.clip(feather, 0, 4) * 0.06
    t0 = np.maximum(0, t - fw * 0.5)
    t1 = np.minimum(1, t + fw * 0.5)

    exactness = np.zeros_like(mr, dtype=np.float32)
    valid_slot = (slot >= 0) & (slot <= 5)
    if not np.any(valid_slot):
        return exactness

    slots = np.unique(slot[valid_slot]).astype(int)
    for s in slots:
        mask = slot == s
        ref = SLOT_REF_RGB[s]
        dr = mr[mask] - ref[0]
        dg = mg[mask] - ref[1]
        db = mb[mask] - ref[2]
        dist_n = np.sqrt(dr * dr + dg * dg + db * db) / MAX_SLOT_REF_DIST

        ts = np.clip((dist_n - t0) / (t1 - t0 + 1e-10), 0, 1)
        smooth = ts * ts * (3 - 2 * ts)
        exactness[mask] = 1 - smooth

    return exactness


def _get_advanced_mask_analysis(
    mask_arr: np.ndarray, w: int, h: int, params: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    threshold = params.get("threshold", 80)
    feather = params.get("feather", 0)
    speckle_clean = params.get("speckleClean", 0.35)

    mr = mask_arr[..., 0].astype(np.float32)
    mg = mask_arr[..., 1].astype(np.float32)
    mb = mask_arr[..., 2].astype(np.float32)

    max_c = np.maximum(np.maximum(mr, mg), mb)
    min_c = np.minimum(np.minimum(mr, mg), mb)
    chr_arr = max_c - min_c

    rxd = mr - min_c
    gxd = mg - min_c
    bxd = mb - min_c
    ln = np.sqrt(rxd * rxd + gxd * gxd + bxd * bxd)

    valid_mask = ln > 1e-6
    safe_ln = np.where(valid_mask, ln, 1.0)
    rxd = np.where(valid_mask, rxd / safe_ln, 0.0)
    gxd = np.where(valid_mask, gxd / safe_ln, 0.0)
    bxd = np.where(valid_mask, bxd / safe_ln, 0.0)

    INF = 1e9
    dist = np.full((h, w), INF, dtype=np.float32)
    lab = np.full((h, w), -1, dtype=np.int16)
    conf = np.zeros((h, w), dtype=np.float32)

    import logging
    _logger2 = logging.getLogger("app")

    best_cs = np.full((h, w), -2.0, dtype=np.float32)
    for s in range(6):
        ref = REF[s]
        cs = rxd * ref[0] + gxd * ref[1] + bxd * ref[2]
        update = valid_mask & (cs > best_cs)
        best_cs = np.where(update, cs, best_cs)
        lab = np.where(update, s, lab)

    test_y, test_x = 100, 100
    if h > test_y and w > test_x:
        _rxd_v = float(rxd[test_y, test_x])
        _gxd_v = float(gxd[test_y, test_x])
        _bxd_v = float(bxd[test_y, test_x])
        _valid_v = bool(valid_mask[test_y, test_x])
        _cs_vals = []
        for s in range(6):
            _ref = REF[s]
            _cs = _rxd_v * float(_ref[0]) + _gxd_v * float(_ref[1]) + _bxd_v * float(_ref[2])
            _cs_vals.append(round(_cs, 4))
        _logger2.info("DEBUG slot test [%d,%d]: rxd=%.4f gxd=%.4f bxd=%.4f valid=%s cs_per_slot=%s best_cs=%.4f lab=%d",
                      test_y, test_x, _rxd_v, _gxd_v, _bxd_v, _valid_v, _cs_vals, float(best_cs[test_y, test_x]), int(lab[test_y, test_x]))

    _logger2.info("DEBUG AFTER slot finding: %s", {int(v): int((lab == v).sum()) for v in np.unique(lab)})

    test_y, test_x = 100, 100
    if h > test_y and w > test_x:
        _mr = float(mr[test_y, test_x])
        _mg = float(mg[test_y, test_x])
        _mb = float(mb[test_y, test_x])
        _minc = float(min_c[test_y, test_x])
        _rxd_raw = _mr - _minc
        _gxd_raw = _mg - _minc
        _bxd_raw = _mb - _minc
        _ln_calc = (_rxd_raw**2 + _gxd_raw**2 + _bxd_raw**2) ** 0.5
        _rxd_norm = _rxd_raw / _ln_calc if _ln_calc > 1e-6 else 0.0
        _gxd_norm = _gxd_raw / _ln_calc if _ln_calc > 1e-6 else 0.0
        _bxd_norm = _bxd_raw / _ln_calc if _ln_calc > 1e-6 else 0.0
        _logger2.info("DEBUG pixel [%d,%d] mask=(%.1f,%.1f,%.1f) min_c=%.1f raw=(%.1f,%.1f,%.1f) ln=%.3f norm=(%.3f,%.3f,%.3f) lab=%d",
                      test_y, test_x, _mr, _mg, _mb, _minc, _rxd_raw, _gxd_raw, _bxd_raw, _ln_calc, _rxd_norm, _gxd_norm, _bxd_norm, int(lab[test_y, test_x]))

    valid_pixels = lab >= 0
    exactness = np.zeros((h, w), dtype=np.float32)
    if np.any(valid_pixels):
        exactness = _get_mask_exactness_2d(lab, mr, mg, mb, threshold, feather)

    conf = np.where(valid_pixels, (chr_arr / 255) * exactness, 0.0)
    seed_chr = max(8, int(8 + (threshold / 150) * 30))
    seed_mask = valid_pixels & (chr_arr >= seed_chr)
    dist = np.where(seed_mask, 0.0, dist)
    _logger2.info("DEBUG AFTER seed: %s", {int(v): int((lab == v).sum()) for v in np.unique(lab)})

    W1 = 1.0
    W2 = np.sqrt(2.0)

    _chamfer_forward(dist, lab, W1, W2)
    _chamfer_backward(dist, lab, W1, W2)
    _logger2.info("DEBUG AFTER chamfer: %s", {int(v): int((lab == v).sum()) for v in np.unique(lab)})

    sc_raw = float(np.clip(speckle_clean, 0, 2))
    if sc_raw > 0:
        sc1 = min(sc_raw, 1.0)
        sc2 = max(0.0, sc_raw - 1.0)
        conf_thr = 0.05 + 0.5 * sc1 + 0.3 * sc2
        min_major = 3 if sc_raw >= 1.0 else (4 if sc_raw >= 0.7 else 5)
        passes = 3 if sc_raw >= 1.6 else (2 if sc_raw >= 0.6 else 1)

        for _pass in range(passes):
            votes = np.zeros((h, w, 6), dtype=np.int32)
            for s in range(6):
                mask_s = (lab == s)
                count = np.zeros((h, w), dtype=np.int32)
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        src = mask_s[
                            max(0, -dy):h - max(0, dy),
                            max(0, -dx):w - max(0, dx),
                        ]
                        dst_slice = (
                            slice(max(0, dy), h + min(0, dy)),
                            slice(max(0, dx), w + min(0, dx)),
                        )
                        count[dst_slice] += src.astype(np.int32)
                votes[..., s] = count

            best_idx = votes.argmax(axis=-1)
            best_count = votes.max(axis=-1)
            update = (best_count >= min_major) & (conf <= conf_thr) & (best_idx < 6) & (lab != best_idx)
            lab = np.where(update, best_idx.astype(np.int16), lab)

    return dist, lab, conf


def _opacity_from_mask(region: int, mr: np.ndarray, mg: np.ndarray, mb: np.ndarray) -> np.ndarray:
    if region == 0:
        return np.maximum(0, mr.astype(np.float32) - mg - mb) / 255.0
    if region == 1:
        return np.maximum(0, mg.astype(np.float32) - mr - mb) / 255.0
    if region == 2:
        return np.maximum(0, mb.astype(np.float32) - mr - mg) / 255.0
    if region == 3:
        return np.minimum(mg, mb).astype(np.float32) / 255.0
    if region == 4:
        return np.minimum(mr, mg).astype(np.float32) / 255.0
    if region == 5:
        return np.minimum(mr, mb).astype(np.float32) / 255.0
    return np.zeros_like(mr, dtype=np.float32)


def detect_used_regions(mask_path: Path) -> set[int]:
    mask_arr = np.array(Image.open(mask_path).convert("RGB"), dtype=np.float32)
    mr = mask_arr[..., 0]
    mg = mask_arr[..., 1]
    mb = mask_arr[..., 2]
    used = set()
    for region in range(REGION_COUNT):
        opacity = _opacity_from_mask(region, mr, mg, mb)
        if opacity.max() > 0.01:
            used.add(region)
    return used


def apply_region_color(
    image: Image.Image,
    mask: Image.Image,
    region_colors: dict[int, int],
    color_lut: dict[int, tuple[int, int, int]],
    **kwargs,
) -> Image.Image:
    has_alpha = image.mode == "RGBA"
    image_arr = np.array(image)
    if has_alpha:
        alpha = image_arr[:, :, 3]

    base = np.array(image.convert("RGB"), dtype=np.float32)
    mask_arr = np.array(mask.convert("RGB"), dtype=np.float32)

    mr = mask_arr[..., 0]
    mg = mask_arr[..., 1]
    mb = mask_arr[..., 2]

    result = base.copy()

    for region in range(REGION_COUNT):
        color_id = region_colors.get(region, NEUTRAL_COLOR_ID)
        color = color_lut.get(color_id, (128, 128, 128))
        opacity = _opacity_from_mask(region, mr, mg, mb)

        if opacity.max() < 0.001:
            continue

        c = np.array(color, dtype=np.float32)
        opacity3 = opacity[..., np.newaxis]

        mixed = np.clip(result + (c - 128.0), 0, 255)
        result = result * (1 - opacity3) + mixed * opacity3

    result = np.clip(result, 0, 255).astype(np.uint8)

    if has_alpha:
        return Image.fromarray(np.dstack([result, alpha]), "RGBA")
    return Image.fromarray(result, "RGB")


def render_advanced(
    image: Image.Image,
    mask: Image.Image,
    region_colors: dict[int, int],
    color_lut: dict[int, tuple[int, int, int]],
    params: dict | None = None,
) -> Image.Image:
    params = params or {}

    threshold = float(params.get("threshold", 80))
    strength = float(params.get("strength", 0.88))
    neutral_strength = float(params.get("neutralStrength", 1))
    feather = float(params.get("feather", 0))
    gamma = float(params.get("gamma", 0.93))
    keep_light = float(params.get("keepLight", 0.88))
    chroma_boost = float(params.get("chromaBoost", 1))
    chroma_curve = float(params.get("chromaCurve", 0.9))
    speckle_clean = float(params.get("speckleClean", 0.35))
    boundary_blend = float(params.get("boundaryBlend", 0.28))
    color_mix_boost = float(params.get("colorMixBoost", 0))
    min_chroma = float(params.get("minChroma", 0))
    shade_base = float(params.get("shadeBase", 0.14))
    shade_scale = float(params.get("shadeScale", 0.12))

    has_alpha = image.mode == "RGBA"
    base = np.array(image.convert("RGB"), dtype=np.float32)
    mask_arr = np.array(mask.convert("RGB"), dtype=np.float32)
    alpha = np.array(image)[:, :, 3] if has_alpha else None

    import logging
    _logger = logging.getLogger("app")
    _logger.info("DEBUG mask mode: %s shape: %s", mask.mode, mask_arr.shape)
    _logger.info("DEBUG mask file: %s", mask.filename if hasattr(mask, 'filename') else 'unknown')
    _logger.info("DEBUG mask full value range: min=%s max=%s mean=%s", mask_arr.min(), mask_arr.max(), mask_arr.mean())
    _logger.info("DEBUG mask unique R values: %s", np.unique(mask_arr[..., 0])[:20])
    _logger.info("DEBUG mask unique G values: %s", np.unique(mask_arr[..., 1])[:20])
    _logger.info("DEBUG mask unique B values: %s", np.unique(mask_arr[..., 2])[:20])
    if mask.mode == "RGBA":
        mask_rgba = np.array(mask)
        _logger.info("DEBUG mask alpha unique: %s", np.unique(mask_rgba[..., 3])[:10])
        _logger.info("DEBUG mask RGB unique (first 10): %s", [list(c) for c in np.unique(mask_rgba[..., :3].reshape(-1, 3), axis=0)[:10]])

    high_pixels = (mask_arr.max(axis=-1) > 100)
    total_pixels = mask_arr.shape[0] * mask_arr.shape[1]
    _logger.info("DEBUG high-value pixels (>100): %d out of %d", int(high_pixels.sum()), total_pixels)
    if high_pixels.sum() > 0:
        high_colors = mask_arr[high_pixels]
        unique_high = np.unique(high_colors.reshape(-1, 3), axis=0)
        _logger.info("DEBUG high-value unique colors (first 20): %s", [list(c) for c in unique_high[:20]])

    mask_flat = mask_arr.reshape(-1, 3)
    bright_pixels = mask_flat[(mask_flat.max(axis=-1) > 30) & (mask_flat.max(axis=-1) - mask_flat.min(axis=-1) > 15)]
    if len(bright_pixels) > 0:
        unique_bright = np.unique(bright_pixels, axis=0)
        _logger.info("DEBUG bright mask pixels count: %d", len(unique_bright))
        _logger.info("DEBUG bright mask pixels (first 40): %s", [list(c) for c in unique_bright[:40]])

        for pixel in unique_bright[:30]:
            r, g, b = float(pixel[0]), float(pixel[1]), float(pixel[2])
            min_c = min(r, g, b)
            max_c = max(r, g, b)
            chr_val = max_c - min_c
            if chr_val < 1:
                continue
            ln = (r*r + g*g + b*b - 2*min_c*(r+g+b) + 3*min_c*min_c) ** 0.5
            if ln < 1e-6:
                continue
            rxd = (r - min_c) / ln
            gxd = (g - min_c) / ln
            bxd = (b - min_c) / ln
            dots = []
            for s in range(6):
                ref = REF[s]
                dot = max(0, rxd*ref[0] + gxd*ref[1] + bxd*ref[2])
                dots.append(round(dot, 3))
            _logger.info("DEBUG pixel (%s) dir=(%.3f,%.3f,%.3f) dots=%s best_slot=%d", [r,g,b], rxd, gxd, bxd, dots, dots.index(max(dots)))
    else:
        _logger.info("DEBUG no bright colored pixels found in mask")

    h, w = base.shape[:2]

    pal = np.zeros((6, 3), dtype=np.float32)
    pal_valid = np.zeros(6, dtype=bool)
    for region in range(REGION_COUNT):
        color_id = region_colors.get(region)
        if color_id is not None:
            color = color_lut.get(color_id)
            if color is not None:
                pal[region] = (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)
                pal_valid[region] = True

    mix_boost_clamped = float(np.clip(color_mix_boost, 0, 1.5) if np.isfinite(color_mix_boost) else 0)
    spread_px = 2 + feather * 6
    tol_pix = (2 + feather * 6) * 1.25
    sharp = max(1.5, 12 - 2.5 * max(0.0, min(4.0, feather)))
    bstr = float(np.clip(boundary_blend or 0, 0, 2))
    neutral_amt = float(np.clip(neutral_strength, 0, 5) if np.isfinite(neutral_strength) else 1)
    neutral_amt_eq1 = (neutral_amt == 1.0)

    dist, lab, conf = _get_advanced_mask_analysis(mask_arr, w, h, {
        "threshold": threshold,
        "feather": feather,
        "speckleClean": speckle_clean,
    })

    import logging
    _logger = logging.getLogger("app")
    _logger.info("DEBUG lab counts: %s", {int(v): int((lab == v).sum()) for v in np.unique(lab)})
    _logger.info("DEBUG pal_valid: %s", pal_valid.tolist())
    _logger.info("DEBUG region_colors: %s", region_colors)

    mr = mask_arr[..., 0]
    mg = mask_arr[..., 1]
    mb = mask_arr[..., 2]

    base_norm = base / 255.0
    br = base_norm[:, :, 0]
    bg = base_norm[:, :, 1]
    bb = base_norm[:, :, 2]

    max_c = np.maximum(np.maximum(mr, mg), mb)
    val = max_c / 255.0

    has_lab = lab >= 0
    has_pal = np.zeros_like(has_lab)
    for s in range(6):
        if pal_valid[s]:
            has_pal |= (lab == s)
    process = has_lab & has_pal

    ws = np.exp(-(dist / (spread_px + 0.0001)) ** 2)
    ws = np.where(dist < 1e9, ws, 0.0)

    exactness = _get_mask_exactness_2d(lab, mr, mg, mb, threshold, feather)

    w_mask = (dist <= tol_pix) * ws * (0.6 * conf + 0.25 * val + 0.15 * exactness)
    w_mask = w_mask * (0.45 + 0.55 * exactness)

    whiteness = val * (1 - conf)
    white_clip = _smoothstep(0.2, 0.55, whiteness)
    blackness = 1 - val
    black_clip = _smoothstep(0.8, 0.98, blackness)
    chroma_soft = _smoothstep(0.05, 0.25, 1 - conf)
    w_mask = w_mask * (1 - white_clip) * (1 - black_clip) * (1 - 0.4 * chroma_soft)
    w_mask = np.clip(w_mask, 0, 1)

    w_mask = np.where(process, w_mask, 0.0)
    w_mask = np.where(w_mask > 1e-5, w_mask, 0.0)

    min_c2 = np.minimum(np.minimum(mr, mg), mb)
    rxd = mr - min_c2
    gxd = mg - min_c2
    bxd = mb - min_c2
    ln = np.sqrt(rxd * rxd + gxd * gxd + bxd * bxd)
    safe_ln = np.where(ln > 1e-6, ln, 1.0)
    rxdn = np.where(ln > 1e-6, rxd / safe_ln, 0.0)
    gxdn = np.where(ln > 1e-6, gxd / safe_ln, 0.0)
    bxdn = np.where(ln > 1e-6, bxd / safe_ln, 0.0)

    cs_all = (
        rxdn[..., None] * REF[:, 0] +
        gxdn[..., None] * REF[:, 1] +
        bxdn[..., None] * REF[:, 2]
    )
    cs_all = np.maximum(0, cs_all)
    cs_all = np.where(pal_valid[None, :], cs_all, 0.0)

    wv_all = np.where(cs_all > 0, cs_all ** sharp, 0.0)
    wv_all = np.where(pal_valid[None, :], wv_all, 0.0)
    sum_w = wv_all.sum(axis=-1)
    wmax = wv_all.max(axis=-1)
    wmax_idx = wv_all.argmax(axis=-1)
    sorted_wv = np.sort(wv_all, axis=-1)[:, :, ::-1] if False else -np.sort(-wv_all, axis=-1)
    w2 = sorted_wv[:, :, 1] if wv_all.shape[-1] > 1 else np.zeros_like(wmax)

    ratio = np.where(w2 > 0, wmax / np.maximum(w2, 1e-10), np.inf)
    use_blend = (sum_w > 1e-6) & ~((ratio >= 1.8) & (wmax >= 0.75) & (conf >= 0.25))

    new_lab = np.where(use_blend, lab, np.where(wmax_idx >= 0, wmax_idx, lab))
    new_lab = np.where(has_pal, new_lab, -1)
    new_pal_valid = np.zeros_like(has_lab)
    for s in range(6):
        if pal_valid[s]:
            new_pal_valid |= (new_lab == s)
    new_process = (new_lab >= 0) & new_pal_valid

    t_r = np.zeros((h, w), dtype=np.float32)
    t_g = np.zeros((h, w), dtype=np.float32)
    t_b = np.zeros((h, w), dtype=np.float32)

    if use_blend.any():
        sw = sum_w
        inv = np.where(sw > 1e-6, 1.0 / np.maximum(sw, 1e-10), 0.0)
        for s in range(6):
            if not pal_valid[s]:
                continue
            contrib = wv_all[..., s] * inv
            t_r += contrib * pal[s, 0]
            t_g += contrib * pal[s, 1]
            t_b += contrib * pal[s, 2]

    for s in range(6):
        if not pal_valid[s]:
            continue
        mask_s = (new_lab == s) & ~use_blend
        t_r = np.where(mask_s, pal[s, 0], t_r)
        t_g = np.where(mask_s, pal[s, 1], t_g)
        t_b = np.where(mask_s, pal[s, 2], t_b)

    t_r = np.where(new_process, t_r, 0.0)
    t_g = np.where(new_process, t_g, 0.0)
    t_b = np.where(new_process, t_b, 0.0)

    if bstr > 0.0001:
        lab_padded = np.pad(lab, 1, mode="constant", constant_values=-1)
        pal_valid_neighbors = np.zeros((h, w), dtype=bool)
        cnt_other = np.zeros((h, w), dtype=np.float32)
        cnt = np.zeros((h, w), dtype=np.float32)
        nb = np.full((h, w), -1, dtype=np.int16)
        nb_valid = np.zeros((h, w), dtype=bool)

        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                nlab = lab_padded[1 + dy:h + 1 + dy, 1 + dx:w + 1 + dx]
                valid_neighbor = nlab >= 0
                cnt += valid_neighbor
                diff = (nlab != new_lab) & valid_neighbor & (new_lab >= 0)
                cnt_other += diff.astype(np.float32)

                for s in range(6):
                    if not pal_valid[s]:
                        continue
                    is_s = (nlab == s) & diff
                    take = is_s & (~nb_valid | ((nlab == s) & (cnt_other > 0)))
                    nb = np.where(take, s, nb)
                    nb_valid = nb_valid | is_s

        ratio_nb = np.where(cnt > 0, cnt_other / np.maximum(cnt, 1e-10), 0.0)
        a = np.clip(bstr * ratio_nb, 0, 1)

        nb_r = np.zeros((h, w), dtype=np.float32)
        nb_g = np.zeros((h, w), dtype=np.float32)
        nb_b = np.zeros((h, w), dtype=np.float32)
        for s in range(6):
            if not pal_valid[s]:
                continue
            sel = nb == s
            nb_r = np.where(sel, pal[s, 0], nb_r)
            nb_g = np.where(sel, pal[s, 1], nb_g)
            nb_b = np.where(sel, pal[s, 2], nb_b)

        blend_mask = nb_valid & (a > 0)
        t_r = np.where(blend_mask, t_r * (1 - a) + nb_r * a, t_r)
        t_g = np.where(blend_mask, t_g * (1 - a) + nb_g * a, t_g)
        t_b = np.where(blend_mask, t_b * (1 - a) + nb_b * a, t_b)

    target_ok_l, target_ok_a, target_ok_b = _rgb2oklab(t_r, t_g, t_b)
    target_l, target_c, target_h = _oklab_to_lch(target_ok_l, target_ok_a, target_ok_b)

    low_chroma = (target_c <= 0.03) & (w_mask < 0.999)
    cap = 0.65 + 0.3 * np.where(conf > 0, conf, 0.0)
    w_mask = np.where(low_chroma & (w_mask > cap), cap, w_mask)
    w_mask = np.where(new_process, w_mask, 0.0)

    rl = _srgb_to_linear_gamma(br)
    gl = _srgb_to_linear_gamma(bg)
    bl = _srgb_to_linear_gamma(bb)

    base_mix = np.clip(strength, 0, 1) * w_mask
    if not neutral_amt_eq1:
        neutral_weight = np.clip(1 - np.minimum(1, target_c / 0.12), 0, 1)
    else:
        neutral_weight = np.zeros_like(target_c)

    base_lum = np.clip(0.2126 * br + 0.7152 * bg + 0.0722 * bb, 0, 1)
    highlight = np.where(base_lum <= 0.5, 0.0, np.power(np.maximum(0, (base_lum - 0.5) / 0.5), 1.25))
    shadow = np.where(base_lum >= 0.45, 0.0, np.power(np.maximum(0, (0.45 - base_lum) / 0.45), 1.15))

    highlight_guard = np.maximum(0.45, 1 - 0.4 * neutral_weight * np.minimum(1, highlight * neutral_amt))
    shadow_boost = 1 + 0.25 * neutral_weight * np.minimum(1.2, shadow * np.maximum(0, neutral_amt - 1))
    if neutral_amt_eq1:
        neutral_scale = np.ones_like(target_c)
    else:
        neutral_scale = 1 + (neutral_amt - 1) * neutral_weight
    mix_scale = np.clip(neutral_scale * highlight_guard * shadow_boost, 0, 1.2)
    k_base = np.clip(base_mix * mix_scale, 0, 1)

    vivid = np.clip((target_c - 0.06) / 0.24, 0, 1)
    vivid_weight = np.where(vivid > 0, vivid ** 0.65, 0.0)

    if mix_boost_clamped > 0:
        coverage_boost = np.where(
            vivid_weight > 0,
            np.minimum(1, (0.35 + 0.65 * vivid_weight) * mix_boost_clamped * vivid_weight),
            0.0,
        )
        vivid_lift = mix_boost_clamped * vivid_weight
    else:
        coverage_boost = np.zeros_like(vivid)
        vivid_lift = np.zeros_like(vivid)

    k_adj = np.where(coverage_boost > 0, k_base + (1 - k_base) * coverage_boost, k_base)
    k_adj = np.clip(k_adj, 0, 1)

    base_ok_l, base_ok_a, base_ok_b = _rgb2oklab(br, bg, bb)
    target_c_max = np.maximum(target_c, min_chroma)
    cx = (target_c_max ** chroma_curve) * chroma_boost
    cx = np.where(vivid_lift > 0, cx * (1 + 0.3 * vivid_lift), cx)
    cn = np.clip(cx / 0.3, 0, 1)
    neutral_pull = neutral_weight * max(0.0, neutral_amt - 1)
    keep_light_drop = np.minimum(0.75, 0.15 + 0.3 * neutral_pull)
    keep_l = np.clip(keep_light - (1 - cn) * keep_light_drop, 0, 1)
    keep_l = np.minimum(1, keep_l + 0.2 * neutral_weight * highlight)
    keep_l = np.where(vivid_lift > 0, np.clip(keep_l - 0.25 * vivid_lift, 0, 1), keep_l)

    l_mix = base_ok_l * keep_l + target_l * (1 - keep_l)
    tint_l, tint_a, tint_b = _lch_to_oklab(l_mix, cx, target_h)
    rt, gt, bt = _oklab2rgb(tint_l, tint_a, tint_b)

    rt = np.clip(rt, 0, 1)
    gt = np.clip(gt, 0, 1)
    bt = np.clip(bt, 0, 1)

    target_rl = _srgb_to_linear_gamma(t_r)
    target_gl = _srgb_to_linear_gamma(t_g)
    target_bl = _srgb_to_linear_gamma(t_b)

    rt_lin = _srgb_to_linear_gamma(np.clip(rt, 0, 1))
    gt_lin = _srgb_to_linear_gamma(np.clip(gt, 0, 1))
    bt_lin = _srgb_to_linear_gamma(np.clip(bt, 0, 1))

    o0 = rl * (1 - k_adj) + rt_lin * k_adj
    o1 = gl * (1 - k_adj) + gt_lin * k_adj
    o2 = bl * (1 - k_adj) + bt_lin * k_adj

    mul_r = rl * (0.5 + 0.5 * target_rl)
    mul_g = gl * (0.5 + 0.5 * target_gl)
    mul_b = bl * (0.5 + 0.5 * target_bl)

    shade_preserve = np.clip(shade_base + shade_scale * w_mask + 0.05 * vivid_weight, 0, 0.3)
    o0 = o0 * (1 - shade_preserve) + mul_r * shade_preserve
    o1 = o1 * (1 - shade_preserve) + mul_g * shade_preserve
    o2 = o2 * (1 - shade_preserve) + mul_b * shade_preserve

    gp = 1.0 / gamma if gamma and gamma != 1 else 1.0
    o0 = np.power(np.maximum(o0, 0), gp)
    o1 = np.power(np.maximum(o1, 0), gp)
    o2 = np.power(np.maximum(o2, 0), gp)

    out_r = _linear_to_srgb_gamma(o0)
    out_g = _linear_to_srgb_gamma(o1)
    out_b = _linear_to_srgb_gamma(o2)

    out_r = np.clip(out_r, 0, 1)
    out_g = np.clip(out_g, 0, 1)
    out_b = np.clip(out_b, 0, 1)

    out_r = np.where(new_process, out_r, br)
    out_g = np.where(new_process, out_g, bg)
    out_b = np.where(new_process, out_b, bb)

    if has_alpha:
        out = np.stack([
            (out_r * 255).astype(np.uint8),
            (out_g * 255).astype(np.uint8),
            (out_b * 255).astype(np.uint8),
            alpha.astype(np.uint8),
        ], axis=-1)
        return Image.fromarray(out, "RGBA")

    out = np.stack([
        (out_r * 255).astype(np.uint8),
        (out_g * 255).astype(np.uint8),
        (out_b * 255).astype(np.uint8),
    ], axis=-1)
    return Image.fromarray(out, "RGB")


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
