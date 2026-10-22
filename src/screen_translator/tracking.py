"""Follow text that moves on screen (scrolling) without reading it again.

A translation is made once. When the page scrolls, the whole picture shifts as one piece: that shift is measured
between two screenshots (a coarse phase correlation, then an exact pixel search on some of the text blocks) and each
translated block is moved with the content it sits on, after checking that its own pixels really moved that way.
Blocks that did not move (a fixed header) stay where they are."""
import numpy as np

COARSE = 4  # the first estimate is made on screenshots shrunk this much (cheap)
MIN_PEAK = 0.08  # phase-correlation peak below this: the picture did not just shift
MAX_ERROR = 14.0  # mean pixel difference (0-255) under which a patch counts as "the same pixels"
PROBES = 4  # text blocks used to find the exact shift
PROBE_SIZE = (400, 60)  # largest patch (w, h) compared per probe


def shrink(gray, k=COARSE):
    """Average k x k pixels into one: shifts that are not a multiple of k still look like shifts."""
    h, w = gray.shape
    return gray[:h // k * k, :w // k * k].astype(np.float32).reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def estimate_shift(prev, cur):
    """(dx, dy, peak): how far the content of `prev` moved to become `cur`, in pixels of these 2-D arrays."""
    h, w = prev.shape
    window = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    a = np.fft.rfft2((prev - prev.mean()) * window)
    b = np.fft.rfft2((cur - cur.mean()) * window)
    cross = a.conj() * b
    cross /= np.abs(cross) + 1e-6
    corr = np.fft.irfft2(cross, s=prev.shape)
    iy, ix = np.unravel_index(int(np.argmax(corr)), corr.shape)
    dy = iy if iy <= h // 2 else iy - h
    dx = ix if ix <= w // 2 else ix - w
    return int(dx), int(dy), float(corr[iy, ix])


def _error(prev, cur, box, dx, dy):
    """Mean pixel difference between the block in `prev` and the same block moved by (dx, dy) in `cur`;
    None when too little of it is still on screen to tell."""
    h, w = prev.shape
    x0, y0, x1, y1 = box
    cx0, cy0, cx1, cy1 = max(x0 + dx, 0), max(y0 + dy, 0), min(x1 + dx, w), min(y1 + dy, h)
    if cx1 - cx0 < 0.5 * (x1 - x0) or cy1 - cy0 < 0.5 * (y1 - y0):
        return None
    a = prev[cy0 - dy:cy1 - dy, cx0 - dx:cx1 - dx].astype(np.int16)
    b = cur[cy0:cy1, cx0:cx1].astype(np.int16)
    return float(np.abs(a - b).mean())


def _box(t):
    return int(t["x"]), int(t["y"]), int(t["x"] + t["w"]), int(t["y"] + t["h"])


def _refine(tracks, prev, cur, dx, dy):
    """The exact shift near the coarse one: try each pixel offset on a few big text blocks, up to the nearest pixel."""
    h, w = prev.shape
    probes = []
    for t in sorted(tracks, key=lambda t: -t["w"] * t["h"]):
        x0, y0, x1, y1 = _box(t)
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 - x0 < 20 or y1 - y0 < 8:
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        hw, hh = min(x1 - x0, PROBE_SIZE[0]) // 2, min(y1 - y0, PROBE_SIZE[1]) // 2
        probes.append((cx - hw, cy - hh, cx + hw, cy + hh))
        if len(probes) == PROBES:
            break
    if not probes:
        return dx, dy

    def cost(ax, ay):
        errors = [_error(prev, cur, p, ax, ay) for p in probes]
        errors = [e for e in errors if e is not None]
        return min(errors) if errors else float("inf")  # the best-matching block: some blocks do not scroll
    span = range(-COARSE - 1, COARSE + 2)
    best_dy = min((dy + j for j in span), key=lambda ay: cost(dx, ay))
    best_dx = min((dx + i for i in span), key=lambda ax: cost(ax, best_dy))
    return best_dx, best_dy


def follow(tracks, prev, cur):
    """Move each track (dicts with x, y, w, h in screen pixels) with the content it sits on. `prev` and `cur` are
    consecutive full-size grayscale screenshots (2-D uint8). Returns the (dx, dy) the picture shifted by, (0, 0) if
    it moved too little to measure yet, or None when it did not simply shift (a page change, a video)."""
    if not tracks or prev.shape != cur.shape:
        return None
    dx, dy, peak = estimate_shift(shrink(prev), shrink(cur))
    if peak < MIN_PEAK:
        return None
    if dx == 0 and dy == 0:
        return 0, 0
    dx, dy = _refine(tracks, prev, cur, dx * COARSE, dy * COARSE)
    moved = 0
    for t in tracks:
        box = _box(t)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        go, stay = _error(prev, cur, box, dx, dy), _error(prev, cur, box, 0, 0)
        if go is not None and go < MAX_ERROR and (stay is None or go < 0.7 * stay):
            t["x"] += dx
            t["y"] += dy
            moved += 1
    return (dx, dy) if moved else None
