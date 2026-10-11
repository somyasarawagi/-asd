"""OMR engine: finds the bubble grid on a scanned sheet and reads the marks.

No fixed coordinates are needed. The sheet is deskewed, every bubble is located,
bubbles are grouped into rectangular *blocks* (answer columns, roll-number grid,
set-code row ...) and a saved *template* tells us what each block means.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

TARGET_W = 1700          # every scan is resized to this width before analysis
DEFAULT_LABELS = "ABCD"
DIGITS = "0123456789"


# --------------------------------------------------------------------------- #
# image loading
# --------------------------------------------------------------------------- #
def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def iter_pages(name: str, data: bytes):
    """Yield (label, bgr_image) for an uploaded file (image or multi-page PDF)."""
    if name.lower().endswith(".pdf"):
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover
            import fitz  # type: ignore
        doc = fitz.open(stream=data, filetype="pdf")
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200, colorspace=fitz.csRGB)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            yield f"{name}#p{i + 1}", cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return
    img = decode_image(data)
    if img is not None:
        yield name, img


# --------------------------------------------------------------------------- #
# data classes
# --------------------------------------------------------------------------- #
@dataclass
class Bubble:
    x: float
    y: float
    dark: float = 0.0


@dataclass
class Block:
    index: int
    x0: float
    y0: float
    x1: float
    y1: float
    grid: list  # rows x cols of Bubble | None
    kind: str = "answers"
    orient: str = "across"

    @property
    def rows(self) -> int:
        return len(self.grid)

    @property
    def cols(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    def bubbles(self):
        for row in self.grid:
            for b in row:
                if b is not None:
                    yield b


@dataclass
class Scan:
    image: np.ndarray                 # processed (rotated/resized/deskewed) colour image
    bw: float                         # bubble width
    bh: float                         # bubble height
    blocks: list = field(default_factory=list)
    angle: float = 0.0
    rotation: int = 0
    error: str = ""

    @property
    def signature(self):
        return [[b.rows, b.cols] for b in self.blocks]


# --------------------------------------------------------------------------- #
# step 1 - preprocessing & bubble detection
# --------------------------------------------------------------------------- #
def _rotate90(img: np.ndarray, rotation: int) -> np.ndarray:
    return {
        0: img,
        90: cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
        180: cv2.rotate(img, cv2.ROTATE_180),
        270: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE),
    }[rotation % 360]


def _normalised_ink(bgr: np.ndarray) -> np.ndarray:
    """Darkness image with the paper brightness divided out (uint8, paper ~255)."""
    ink = bgr.min(axis=2)  # coloured print (red/blue) counts as ink too
    small = cv2.resize(ink, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, k)
    bg = cv2.GaussianBlur(bg, (0, 0), 8)
    bg = cv2.resize(bg, (ink.shape[1], ink.shape[0]), interpolation=cv2.INTER_LINEAR)
    norm = ink.astype(np.float32) / np.maximum(bg.astype(np.float32), 1.0) * 255.0
    return np.clip(norm, 0, 255).astype(np.uint8)


def _find_candidates(norm: np.ndarray):
    bw = (norm < 205).astype(np.uint8) * 255
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # CCOMP: outer boundaries of anything, even inside a page border (hole level)
    contours, hier = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    if hier is None:
        return np.zeros((0, 4), np.float32)
    for c, hh in zip(contours, hier[0]):
        if hh[3] != -1:      # a hole inside a ring / letter
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not (10 <= w <= 70 and 10 <= h <= 70):
            continue
        r = w / h
        if not (0.45 <= r <= 2.2):
            continue
        if cv2.contourArea(c) / (w * h) < 0.6:
            continue
        out.append((x + w / 2.0, y + h / 2.0, w, h))
    return np.array(out, dtype=np.float32).reshape(-1, 4)


def _filter_by_modal_size(c: np.ndarray):
    """Keep candidates whose size matches the most common size (= the bubbles)."""
    if len(c) == 0:
        return c, 0.0, 0.0
    hist = np.zeros((40, 40), np.float32)
    iw = np.clip((c[:, 2] // 2).astype(int), 0, 39)
    ih = np.clip((c[:, 3] // 2).astype(int), 0, 39)
    np.add.at(hist, (iw, ih), 1)
    smooth = cv2.blur(hist, (3, 3))
    bi, bj = np.unravel_index(np.argmax(smooth), smooth.shape)
    near = (np.abs(iw - bi) <= 1) & (np.abs(ih - bj) <= 1)
    rw, rh = float(np.median(c[near, 2])), float(np.median(c[near, 3]))
    keep = (np.abs(c[:, 2] - rw) <= 0.22 * rw + 1.5) & (np.abs(c[:, 3] - rh) <= 0.22 * rh + 1.5)
    return c[keep], rw, rh


def _estimate_rotation(pts: np.ndarray, centre):
    """Return the rotation matrix (deg) that makes bubble rows horizontal."""
    def score(angle):
        m = cv2.getRotationMatrix2D(centre, angle, 1.0)
        y = pts[:, 0] * m[1, 0] + pts[:, 1] * m[1, 1] + m[1, 2]
        counts = np.bincount(np.clip((y // 3).astype(int), 0, None))
        return float((counts.astype(np.float64) ** 2).sum())

    best = max(np.arange(-5, 5.01, 0.25), key=score)
    best = max(np.arange(best - 0.25, best + 0.251, 0.05), key=score)
    return float(best)


# --------------------------------------------------------------------------- #
# step 2 - group bubbles into blocks / grids
# --------------------------------------------------------------------------- #
def _cluster_1d(values: np.ndarray, gap: float) -> np.ndarray:
    """Cluster ids for 1-D values; a new cluster starts when the gap is exceeded."""
    order = np.argsort(values)
    ids = np.zeros(len(values), dtype=int)
    cid, last = 0, None
    for i in order:
        if last is not None and values[i] - last > gap:
            cid += 1
        ids[i] = cid
        last = values[i]
    return ids


def _local_pitch(pts: np.ndarray, bw: float, bh: float):
    """Per-bubble distance to nearest neighbour on the same row / same column."""
    n = len(pts)
    dx = pts[None, :, 0] - pts[:, None, 0]
    dy = pts[None, :, 1] - pts[:, None, 1]
    same_row = np.abs(dy) < 0.5 * bh
    same_col = np.abs(dx) < 0.5 * bw
    px = np.where(same_row & (np.abs(dx) > 0.3 * bw), np.abs(dx), np.inf).min(axis=1)
    py = np.where(same_col & (np.abs(dy) > 0.3 * bh), np.abs(dy), np.inf).min(axis=1)
    gx = np.median(px[np.isfinite(px)]) if np.isfinite(px).any() else bw * 1.5
    gy = np.median(py[np.isfinite(py)]) if np.isfinite(py).any() else bh * 1.5
    # lone bubbles (no close neighbour) must not "reach" across the page
    px = np.minimum(np.where(np.isfinite(px), px, gx), 2.2 * gx)
    py = np.minimum(np.where(np.isfinite(py), py, gy), 2.2 * gy)
    return px, py, same_row, same_col, np.abs(dx), np.abs(dy)


def _group_blocks(pts: np.ndarray, bw: float, bh: float):
    n = len(pts)
    px, py, same_row, same_col, adx, ady = _local_pitch(pts, bw, bh)
    reach_x = 1.7 * np.maximum(px[:, None], px[None, :])
    reach_y = 1.7 * np.maximum(py[:, None], py[None, :])
    link = (same_row & (adx < reach_x)) | (same_col & (ady < reach_y))

    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    ii, jj = np.nonzero(np.triu(link, 1))
    for a, b in zip(ii, jj):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) >= 2]


def _build_grid(idx: list[int], pts: np.ndarray, bw: float, bh: float):
    p = pts[idx]
    rid = _cluster_1d(p[:, 1], 0.6 * bh)
    cid = _cluster_1d(p[:, 0], 0.6 * bw)
    nr, nc = rid.max() + 1, cid.max() + 1
    grid = [[None] * nc for _ in range(nr)]
    for k, i in enumerate(idx):
        if grid[rid[k]][cid[k]] is None:
            grid[rid[k]][cid[k]] = Bubble(float(p[k, 0]), float(p[k, 1]))
    # drop empty rows/cols (can happen when two bubbles collided in one cell)
    grid = [r for r in grid if any(b is not None for b in r)]
    return grid


def _order_blocks(blocks: list[Block], bh: float) -> list[Block]:
    """Reading order: top-to-bottom bands, left-to-right inside a band."""
    blocks = sorted(blocks, key=lambda b: b.y0)
    bands: list[list[Block]] = []
    for b in blocks:
        if bands and b.y0 - bands[-1][0].y0 <= 1.5 * bh:
            bands[-1].append(b)
        else:
            bands.append([b])
    out = []
    for band in bands:
        out.extend(sorted(band, key=lambda b: b.x0))
    for i, b in enumerate(out):
        b.index = i
    return out


def _guess_kind(block: Block, k: int):
    r, c = block.rows, block.cols
    n = sum(1 for _ in block.bubbles())
    if n < 3:                       # a stray pair of letters / logo, not a real bubble block
        return "ignore", "across"
    if (r == 1 or c == 1) and n <= 8:
        return "set", "across" if r == 1 else "down"
    if r == 10 and c != k:
        return "roll", "down"
    if c == 10 and r != k:
        return "roll", "across"
    if c % k == 0 or c >= r:
        return "answers", "across"
    if r % k == 0:
        return "answers", "down"
    return "answers", "across"


# --------------------------------------------------------------------------- #
# step 3 - analyse a scan
# --------------------------------------------------------------------------- #
def analyze(bgr: np.ndarray, rotation: int = 0, option_count: int = 4) -> Scan:
    img = _rotate90(bgr, rotation)
    h, w = img.shape[:2]
    scale = TARGET_W / w
    img = cv2.resize(img, (TARGET_W, int(round(h * scale))),
                     interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    norm = _normalised_ink(img)
    cand = _find_candidates(norm)
    cand, bw, bh = _filter_by_modal_size(cand)
    scan = Scan(image=img, bw=bw, bh=bh, rotation=rotation)
    if len(cand) < 8:
        scan.error = "Bubbles not found - is this the right sheet / scan quality?"
        return scan

    # deskew
    pts = cand[:, :2].astype(np.float64)
    centre = (img.shape[1] / 2.0, img.shape[0] / 2.0)
    angle = _estimate_rotation(pts, centre)
    if abs(angle) >= 0.1:
        m = cv2.getRotationMatrix2D(centre, angle, 1.0)
        img = cv2.warpAffine(img, m, (img.shape[1], img.shape[0]),
                             flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
        norm = cv2.warpAffine(norm, m, (img.shape[1], img.shape[0]),
                              flags=cv2.INTER_LINEAR, borderValue=255)
        pts = np.hstack([pts, np.ones((len(pts), 1))]) @ m.T
        scan.image = img
        scan.angle = angle

    # group & build grids
    groups = _group_blocks(pts, bw, bh)
    blocks: list[Block] = []
    for g in groups:
        grid = _build_grid(g, pts, bw, bh)
        if not grid:
            continue
        xs = [b.x for r in grid for b in r if b]
        ys = [b.y for r in grid for b in r if b]
        blocks.append(Block(0, min(xs) - bw / 2, min(ys) - bh / 2,
                            max(xs) + bw / 2, max(ys) + bh / 2, grid))
    scan.blocks = _order_blocks(blocks, bh)
    for b in scan.blocks:
        b.kind, b.orient = _guess_kind(b, option_count)

    # darkness of every bubble
    _measure(norm, scan)
    return scan


def _measure(norm: np.ndarray, scan: Scan):
    rw, rh = int(round(scan.bw)), int(round(scan.bh))
    pad = max(rw, rh)
    padded = cv2.copyMakeBorder(norm, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    mask = np.zeros((rh | 1, rw | 1), np.uint8)
    cv2.ellipse(mask, (mask.shape[1] // 2, mask.shape[0] // 2),
                (max(1, int(0.38 * rw)), max(1, int(0.38 * rh))), 0, 0, 360, 1, -1)
    msum = float(mask.sum())
    hh, hw = mask.shape[0] // 2, mask.shape[1] // 2
    for blk in scan.blocks:
        for b in blk.bubbles():
            cx, cy = int(round(b.x)) + pad, int(round(b.y)) + pad
            patch = padded[cy - hh: cy + hh + 1, cx - hw: cx + hw + 1]
            if patch.shape != mask.shape:
                continue
            b.dark = float(((255 - patch.astype(np.float32)) * mask).sum() / msum / 255.0)


# --------------------------------------------------------------------------- #
# step 4 - read marks using a template
# --------------------------------------------------------------------------- #
SENSITIVITY = {"low": 0.28, "normal": 0.18, "high": 0.12}


def _otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=64, range=(0, 1))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 0.5
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * centres)
    mt = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (w0 * w1) * ((m0 / w0) - ((mt - m0) / w1)) ** 2
    between = np.nan_to_num(between)
    return float(centres[int(np.argmax(between))])


def thresholds(scan: Scan, sensitivity: str = "normal"):
    vals = np.array([b.dark for blk in scan.blocks if blk.kind != "ignore" for b in blk.bubbles()])
    if len(vals) == 0:
        return 0.3, 0.2, 0.1
    base = float(np.median(vals))
    min_delta = SENSITIVITY.get(sensitivity, 0.18)
    thr = float(np.clip(_otsu(vals), base + min_delta, base + 0.30))
    faint = base + 0.55 * min_delta
    return thr, faint, base


def _marked(darks: list, thr: float, base: float):
    """(marked indices, ghost indices).

    A second mark much lighter than the darkest one is most likely an erased
    pencil mark: it is not counted, but reported so the sheet can be reviewed.
    """
    cand = [i for i, d in enumerate(darks) if d >= thr]
    ghosts = []
    if len(cand) > 1:
        top = max(darks[i] for i in cand) - base
        ghosts = [i for i in cand if darks[i] - base < 0.4 * top]
        cand = [i for i in cand if i not in ghosts]
    return cand, ghosts


def _box(bubbles, bw, bh):
    xs = [b.x for b in bubbles if b]
    ys = [b.y for b in bubbles if b]
    if not xs:
        return None
    return [min(xs) - bw / 2, min(ys) - bh / 2, max(xs) + bw / 2, max(ys) + bh / 2]


def _transpose(grid):
    return [list(col) for col in zip(*grid)] if grid else grid


def align_blocks(blocks: list, template: dict):
    """Blocks of the scan that correspond to the template's blocks (or None).

    Logos / big printed letters can look like a tiny extra bubble block; with a
    saved layout signature we simply skip blocks that don't fit.
    """
    n = len(template.get("blocks", []))
    sig = template.get("signature")
    if not sig:
        return list(blocks) if len(blocks) == n else None
    if [[b.rows, b.cols] for b in blocks] == sig:
        return list(blocks)
    out, j = [], 0
    for b in blocks:
        if j < len(sig) and [b.rows, b.cols] == sig[j]:
            out.append(b)
            j += 1
    return out if j == len(sig) else None


def check_layout(scan: Scan, template: dict) -> bool:
    return align_blocks(scan.blocks, template) is not None


def read_sheet(scan: Scan, template: dict, sensitivity: str | None = None) -> dict:
    """Read a scan with a template. Returns roll/set/batch/answers + flags + overlay."""
    sensitivity = sensitivity or template.get("sensitivity", "normal")
    labels_default = template.get("labels", DEFAULT_LABELS)
    thr, faint, base = thresholds(scan, sensitivity)
    out = {"roll": "", "batch": "", "set": "", "answers": [], "flags": [],
           "notes": [], "overlay": [], "qboxes": {}}
    if scan.error:
        out["notes"].append(scan.error)
        out["flags"].append("layout")
        return out
    tblocks = template.get("blocks", [])
    blocks = align_blocks(scan.blocks, template)
    if blocks is None:
        out["notes"].append(f"Sheet has {len(scan.blocks)} bubble blocks, template expects {len(tblocks)} "
                            "(wrong sheet, cut page or poor scan?)")
        out["flags"].append("layout")
        return out

    qno = 0
    roll_done = batch_done = set_done = False
    for blk, tb in zip(blocks, tblocks):
        kind = tb.get("type", "ignore")
        orient = tb.get("orient", "across")
        grid = blk.grid
        if kind == "answers":
            labels = tb.get("labels") or labels_default
            k = len(labels)
            g = grid if orient == "across" else _transpose(grid)
            ncols = len(g[0]) if g else 0
            if ncols % k:
                out["notes"].append(f"Block {blk.index + 1}: {ncols} columns is not a multiple of {k} options")
                out["flags"].append("layout")
            groups = max(1, ncols // k)
            for gi in range(groups):
                for row in g:
                    cells = row[gi * k:(gi + 1) * k]
                    qno += 1
                    darks = [c.dark if c else 0.0 for c in cells]
                    darks += [0.0] * (k - len(darks))
                    sel, ghosts = _marked(darks, thr, base)
                    letters = "".join(labels[i] for i in sel)
                    out["answers"].append(letters)
                    flag = None
                    if len(sel) > 1:
                        flag = "multiple"
                    elif ghosts:
                        flag = "ghost"
                    elif not sel and max(darks) >= faint:
                        flag = "faint"
                    elif any(c is None for c in cells) or len(cells) < k:
                        flag = "missing"
                    if flag:
                        out["flags"].append(f"q{qno}:{flag}")
                        box = _box(cells, scan.bw, scan.bh)
                        if box:
                            out["qboxes"][str(qno)] = box
                    for i in sel:
                        c = cells[i]
                        out["overlay"].append([c.x, c.y, 1])
        elif kind in ("roll", "batch"):
            digits = tb.get("digits") or DIGITS
            g = grid if orient == "down" else _transpose(grid)   # g: rows=digits, cols=positions
            chars = []
            for ci in range(len(g[0]) if g else 0):
                col = [g[ri][ci] for ri in range(len(g))]
                darks = [c.dark if c else 0.0 for c in col]
                sel, _ = _marked(darks, thr, base)
                if len(sel) == 1 and sel[0] < len(digits):
                    chars.append(digits[sel[0]])
                    out["overlay"].append([col[sel[0]].x, col[sel[0]].y, 1])
                elif len(sel) == 0:
                    chars.append("_")
                else:
                    chars.append("*")
            text = "".join(chars)
            text = text.strip("_")
            if "_" in text or "*" in text:
                out["flags"].append(f"{kind}:unreadable")
            if kind == "roll" and not roll_done:
                out["roll"], roll_done = text, True
                if not text:
                    out["flags"].append("roll:unreadable")
            elif kind == "batch" and not batch_done:
                out["batch"], batch_done = text, True
        elif kind == "set":
            labels = tb.get("labels") or labels_default
            cells = [c for row in grid for c in row if c is not None]
            if orient == "down":
                cells = [c for row in _transpose(grid) for c in row if c is not None]
            darks = [c.dark for c in cells]
            sel, _ = _marked(darks, thr, base)
            if len(sel) == 1 and sel[0] < len(labels):
                out["set"] = labels[sel[0]]
                out["overlay"].append([cells[sel[0]].x, cells[sel[0]].y, 1])
            else:
                out["set"] = ""
                out["flags"].append("set:unreadable")
            set_done = True
    return out


def read_with_retry(bgr: np.ndarray, template: dict, rotations=(0, 180, 90, 270)):
    """Analyse + read; if the layout doesn't match, try the other page rotations."""
    k = len(template.get("labels", DEFAULT_LABELS))
    first = None
    for rot in rotations:
        scan = analyze(bgr, rot, k)
        if scan.error and first is not None:
            continue
        if check_layout(scan, template):
            return scan, read_sheet(scan, template)
        if first is None:
            first = scan
    return first, read_sheet(first, template)


def template_from_scan(scan: Scan, labels: str = DEFAULT_LABELS, sensitivity="normal") -> dict:
    """Auto-guessed template that the setup screen lets the user correct."""
    blocks = []
    for b in scan.blocks:
        t = {"type": b.kind, "orient": b.orient}
        if b.kind == "roll":
            t["digits"] = DIGITS
        blocks.append(t)
    return {"labels": labels, "sensitivity": sensitivity, "blocks": blocks,
            "signature": scan.signature}
