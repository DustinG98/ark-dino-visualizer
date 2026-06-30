from pathlib import Path
from typing import Optional
import json

import numpy as np
from PIL import Image, ImageEnhance

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DINO_IMAGE_DIR = DATA_DIR / "dino_images" / "images"

REGION_COUNT = 6
NEUTRAL_COLOR_ID = 18
OUTPUT_SCALE = 1.0

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

try:
    from scipy.ndimage import distance_transform_edt
    _HAS_SCIPY = True
except Exception:
    _HAS_SCIPY = False


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


def _upscale_for_render(
    image: Image.Image,
    mask: Image.Image,
    scale: float,
) -> tuple[Image.Image, Image.Image]:
    if scale == 1.0:
        return image, mask
    new_w = int(round(image.width * scale))
    new_h = int(round(image.height * scale))
    image_up = image.resize((new_w, new_h), Image.BICUBIC)
    mask_up = mask.resize((new_w, new_h), Image.NEAREST)
    return image_up, mask_up


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


def _chamfer_vectorized(dist: np.ndarray, lab: np.ndarray, W1: float, W2: float) -> tuple[np.ndarray, np.ndarray]:
    INF = 1e9

    def _pass(d: np.ndarray, l: np.ndarray, fwd: bool) -> tuple[np.ndarray, np.ndarray]:
        for axis_shift, off in ((0, -1), (0, 1), (1, -1), (1, 1)):
            if fwd:
                nd = np.roll(d, off, axis=axis_shift)
                nl = np.roll(l, off, axis=axis_shift)
            else:
                nd = np.roll(d, -off, axis=axis_shift)
                nl = np.roll(l, -off, axis=axis_shift)
            w = W2 if off != 0 and axis_shift != 0 else W1
            if axis_shift == 0:
                if fwd:
                    nd[:, -1] = INF
                    nl[:, -1] = -1
                else:
                    nd[:, 0] = INF
                    nl[:, 0] = -1
            else:
                if fwd:
                    nd[-1, :] = INF
                    nl[-1, :] = -1
                else:
                    nd[0, :] = INF
                    nl[0, :] = -1
            nd = nd + w
            better = (nd < d) & (d < INF)
            d = np.where(better, nd, d)
            adopt = better & (l < 0) & (nl >= 0)
            l = np.where(adopt, nl, l)
        return d, l

    d, l = _pass(dist, lab, True)
    d, l = _pass(d, l, False)
    return d, l


def _chamfer_forward(dist: np.ndarray, lab: np.ndarray, W1: float, W2: float) -> None:
    d, l = _chamfer_vectorized(dist.copy(), lab, W1, W2)
    dist[...] = d
    lab[...] = l


def _chamfer_backward(dist: np.ndarray, lab: np.ndarray, W1: float, W2: float) -> None:
    d, l = _chamfer_vectorized(dist.copy(), lab, W1, W2)
    dist[...] = d
    lab[...] = l


def _chamfer_with_labels(dist_seed: np.ndarray, lab_seed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    INF = 1e9
    if _HAS_SCIPY:
        seed_mask = (dist_seed == 0)
        if not seed_mask.any():
            return (np.full(dist_seed.shape, INF, dtype=np.float32),
                    np.full(dist_seed.shape, -1, dtype=np.int16))
        not_seed = np.where(seed_mask, 0, 1).astype(np.uint8)
        dist, idx = distance_transform_edt(not_seed, return_indices=True)
        nearest = lab_seed[idx[0], idx[1]].astype(np.int16)
        nearest = np.where(seed_mask, lab_seed, nearest)
        dist = np.where(seed_mask | (dist > 0), dist, INF).astype(np.float32)
        return dist, nearest

    W1 = 1.0
    W2 = np.sqrt(2.0)
    d = dist_seed.copy()
    l = lab_seed.copy()
    d, l = _chamfer_vectorized(d, l, W1, W2)
    d, l = _chamfer_vectorized(d, l, W1, W2)
    return d, l


def _get_mask_exactness_2d(
    slot: np.ndarray, mr: np.ndarray, mg: np.ndarray, mb: np.ndarray,
    threshold: float = 80, feather: float = 0,
) -> np.ndarray:
    t = np.clip(threshold / 150.0, 0, 1)
    fw = 0.02 + np.clip(feather, 0, 4) * 0.06
    t0 = np.maximum(0, t - fw * 0.5)
    t1 = np.minimum(1, t + fw * 0.5)

    exactness = np.zeros_like(mr, dtype=np.float32)
    valid = (slot >= 0) & (slot <= 5)
    if not np.any(valid):
        return exactness

    slot_clipped = np.clip(slot, 0, 5).astype(np.int32)
    refs = SLOT_REF_RGB[slot_clipped]
    dr = mr - refs[..., 0]
    dg = mg - refs[..., 1]
    db = mb - refs[..., 2]
    dist_n = np.sqrt(dr * dr + dg * dg + db * db) / MAX_SLOT_REF_DIST

    ts = np.clip((dist_n - t0) / (t1 - t0 + 1e-10), 0, 1)
    smooth = ts * ts * (3 - 2 * ts)
    exactness = np.where(valid, 1 - smooth, 0.0).astype(np.float32)
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
    lab = np.full((h, w), -1, dtype=np.int16)
    conf = np.zeros((h, w), dtype=np.float32)

    best_cs = np.full((h, w), -2.0, dtype=np.float32)
    for s in range(6):
        ref = REF[s]
        cs = rxd * ref[0] + gxd * ref[1] + bxd * ref[2]
        update = valid_mask & (cs > best_cs)
        best_cs = np.where(update, cs, best_cs)
        lab = np.where(update, s, lab)

    valid_pixels = lab >= 0
    exactness = np.zeros((h, w), dtype=np.float32)
    if np.any(valid_pixels):
        exactness = _get_mask_exactness_2d(lab, mr, mg, mb, threshold, feather)

    conf = np.where(valid_pixels, (chr_arr / 255) * exactness, 0.0)
    seed_chr = max(8, int(8 + (threshold / 150) * 30))
    seed_mask = valid_pixels & (chr_arr >= seed_chr)

    dist_seed = np.where(seed_mask, 0.0, INF).astype(np.float32)
    lab_seed = np.where(seed_mask, lab, -1).astype(np.int16)
    dist, lab = _chamfer_with_labels(dist_seed, lab_seed)

    sc_raw = float(np.clip(speckle_clean, 0, 2))
    if sc_raw > 0:
        sc1 = min(sc_raw, 1.0)
        sc2 = max(0.0, sc_raw - 1.0)
        conf_thr = 0.05 + 0.5 * sc1 + 0.3 * sc2
        min_major = 3 if sc_raw >= 1.0 else (4 if sc_raw >= 0.7 else 5)
        passes = 3 if sc_raw >= 1.6 else (2 if sc_raw >= 0.6 else 1)

        for _pass in range(passes):
            one_hot = np.zeros((h, w, 6), dtype=np.int8)
            valid_lab = lab >= 0
            for s in range(6):
                one_hot[..., s] = (lab == s) & valid_lab

            shifts = [(-1, -1), (-1, 0), (-1, 1),
                      (0, -1),           (0, 1),
                      (1, -1),  (1, 0),  (1, 1)]
            counts = np.zeros((h, w, 6), dtype=np.int32)
            for dy, dx in shifts:
                src_y0 = max(0, -dy)
                src_y1 = h - max(0, dy)
                src_x0 = max(0, -dx)
                src_x1 = w - max(0, dx)
                dst_y0 = max(0, dy)
                dst_y1 = h + min(0, dy)
                dst_x0 = max(0, dx)
                dst_x1 = w + min(0, dx)
                counts[dst_y0:dst_y1, dst_x0:dst_x1] += one_hot[src_y0:src_y1, src_x0:src_x1].astype(np.int32)

            best_idx = counts.argmax(axis=-1)
            best_count = counts.max(axis=-1)
            update = (best_count >= min_major) & (conf <= conf_thr) & (lab != best_idx)
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
    opacities = np.stack([
        np.maximum(0, mr - mg - mb),
        np.maximum(0, mg - mr - mb),
        np.maximum(0, mb - mr - mg),
        np.minimum(mg, mb),
        np.minimum(mr, mg),
        np.minimum(mr, mb),
    ], axis=-1)
    used = set(np.where(opacities.max(axis=(0, 1)) > 2.55)[0].tolist())
    return used


def apply_region_color(
    image: Image.Image,
    mask: Image.Image,
    region_colors: dict[int, int],
    color_lut: dict[int, tuple[int, int, int]],
    **kwargs,
) -> Image.Image:
    image, mask = _upscale_for_render(image, mask, OUTPUT_SCALE)

    has_alpha = image.mode == "RGBA"
    if has_alpha:
        alpha = np.array(image)[:, :, 3]

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

    image, mask = _upscale_for_render(image, mask, OUTPUT_SCALE)

    has_alpha = image.mode == "RGBA"
    base = np.array(image.convert("RGB"), dtype=np.float32)
    mask_arr = np.array(mask.convert("RGB"), dtype=np.float32)
    alpha = np.array(image)[:, :, 3] if has_alpha else None

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
    sorted_wv = -np.sort(-wv_all, axis=-1)
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
        one_hot = np.zeros((h, w, 6), dtype=np.int8)
        valid_lab = (lab >= 0)
        for s in range(6):
            one_hot[..., s] = (lab == s) & valid_lab

        cnt = np.zeros((h, w), dtype=np.float32)
        cnt_other = np.zeros((h, w), dtype=np.float32)
        nb = np.full((h, w), -1, dtype=np.int16)
        nb_valid = np.zeros((h, w), dtype=bool)

        shifts = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1)]
        for dy, dx in shifts:
            src_y0 = max(0, -dy); src_y1 = h - max(0, dy)
            src_x0 = max(0, -dx); src_x1 = w - max(0, dx)
            dst_y0 = max(0, dy);  dst_y1 = h + min(0, dy)
            dst_x0 = max(0, dx);  dst_x1 = w + min(0, dx)

            nlab = lab[src_y0:src_y1, src_x0:src_x1]
            valid_neighbor = nlab >= 0
            cnt[dst_y0:dst_y1, dst_x0:dst_x1] += valid_neighbor.astype(np.float32)

            diff = (nlab != new_lab[dst_y0:dst_y1, dst_x0:dst_x1]) & valid_neighbor & (new_lab[dst_y0:dst_y1, dst_x0:dst_x1] >= 0)
            cnt_other[dst_y0:dst_y1, dst_x0:dst_x1] += diff.astype(np.float32)

            for s in range(6):
                if not pal_valid[s]:
                    continue
                is_s = (nlab == s) & diff
                take = is_s & (~nb_valid[dst_y0:dst_y1, dst_x0:dst_x1])
                nb[dst_y0:dst_y1, dst_x0:dst_x1] = np.where(take, s, nb[dst_y0:dst_y1, dst_x0:dst_x1])
                nb_valid[dst_y0:dst_y1, dst_x0:dst_x1] |= is_s

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

    is_white_target = (target_c <= 0.03) & (target_l >= 0.92)

    low_chroma = (target_c <= 0.03) & (w_mask < 0.999)
    cap = 0.65 + 0.3 * np.where(conf > 0, conf, 0.0)
    cap = np.where(is_white_target, 0.97, cap)
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
    keep_l = np.where(is_white_target, np.minimum(keep_l, 0.12), keep_l)

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
    shade_preserve = np.where(is_white_target, np.minimum(shade_preserve, 0.06), shade_preserve)
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