"""Generates a realistic *sample* OMR sheet (roll no, batch, set, 100 questions).

Used by the automated tests and by the "try with a sample sheet" button, so you
can test the whole app before scanning real sheets.
"""
from __future__ import annotations

import cv2
import numpy as np

W, H = 1700, 2404
D = 30            # bubble diameter
PITCH = 44
INK = (40, 40, 200)  # red print (BGR)
LABELS = "ABCD"

ROLL_POS = (100, 330, 8)      # x, y, digits
BATCH_POS = (520, 330, 2)
SET_POS = (820, 330)
ANS_X = (150, 550, 950, 1350)
ANS_Y = 850
ROWS = 25


def sample_template() -> dict:
    return {
        "labels": LABELS, "sensitivity": "normal",
        "blocks": [
            {"type": "roll", "orient": "down", "digits": "0123456789"},
            {"type": "batch", "orient": "down", "digits": "0123456789"},
            {"type": "set", "orient": "across"},
            *[{"type": "answers", "orient": "across"} for _ in ANS_X],
        ],
        "signature": [[10, 8], [10, 2], [1, 4]] + [[ROWS, 4]] * len(ANS_X),
    }


def _bubble(img, cx, cy, letter, state):
    cv2.circle(img, (cx, cy), D // 2, INK, 2, cv2.LINE_AA)
    if letter:
        (tw, th), _ = cv2.getTextSize(letter, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(img, letter, (cx - tw // 2, cy + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1, cv2.LINE_AA)
    if state:
        kind, rng = state
        if kind == "pen":
            cv2.circle(img, (cx, cy), int(D * 0.48), (35, 30, 30), -1, cv2.LINE_AA)
        elif kind == "pencil":
            shade = int(rng.integers(80, 115))
            cv2.circle(img, (cx, cy), int(D * 0.46), (shade, shade, shade), -1, cv2.LINE_AA)
        else:  # light
            shade = int(rng.integers(125, 150))
            cv2.circle(img, (cx, cy), int(D * 0.40), (shade, shade, shade), -1, cv2.LINE_AA)


def make_sheet(roll="20240017", batch="03", set_code="B", answers=None, seed=0,
               tilt=0.0, shift=(0, 0), noise=5.0, scale=1.0, jpeg=80, blank=False):
    """Return a BGR image of a filled-in sheet."""
    rng = np.random.default_rng(seed)
    answers = answers if answers is not None else [""] * (ROWS * len(ANS_X))
    img = np.full((H, W, 3), 250, np.uint8)
    cv2.putText(img, "SAMPLE OMR ANSWER SHEET", (100, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.rectangle(img, (40, 40), (W - 40, H - 40), (0, 0, 0), 3)
    for x, y, lab in ((ROLL_POS[0], 280, "ROLL NO"), (BATCH_POS[0], 280, "BATCH"), (SET_POS[0], 280, "SET")):
        cv2.putText(img, lab, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)

    def pick_state():
        if blank:
            return None
        return (rng.choice(["pen", "pencil", "pencil", "light"]), rng)

    # roll & batch digit grids
    for (x0, y0, n), text in ((ROLL_POS, roll), (BATCH_POS, batch)):
        for c in range(n):
            for r in range(10):
                on = (not blank) and c < len(text) and text[c] == str(r)
                _bubble(img, x0 + c * PITCH, y0 + r * PITCH, str(r), pick_state() if on else None)
    # set
    for i, lab in enumerate(LABELS):
        on = (not blank) and set_code == lab
        _bubble(img, SET_POS[0] + i * PITCH, SET_POS[1], lab, pick_state() if on else None)
    # answers
    for b, x0 in enumerate(ANS_X):
        for r in range(ROWS):
            q = b * ROWS + r
            cy = ANS_Y + r * PITCH
            cv2.putText(img, f"{q + 1}", (x0 - 75, cy + 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
            for j, lab in enumerate(LABELS):
                on = (not blank) and lab in answers[q]
                _bubble(img, x0 + j * PITCH, cy, lab, pick_state() if on else None)

    # scanner effects
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), tilt, 1.0)
    m[:, 2] += shift
    img = cv2.warpAffine(img, m, (w, h), borderValue=(235, 235, 235))
    grad = np.linspace(0.88, 1.0, w, dtype=np.float32)[None, :, None]
    img = np.clip(img.astype(np.float32) * grad, 0, 255)
    if noise:
        img += rng.normal(0, noise, img.shape).astype(np.float32)
    img = cv2.GaussianBlur(np.clip(img, 0, 255).astype(np.uint8), (0, 0), 0.8)
    if jpeg:
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
        img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return img


def random_answers(rng, n=ROWS * len(ANS_X), p_blank=0.06, p_multi=0.04):
    out = []
    for _ in range(n):
        r = rng.random()
        if r < p_blank:
            out.append("")
        elif r < p_blank + p_multi:
            out.append("".join(sorted(rng.choice(list(LABELS), 2, replace=False))))
        else:
            out.append(str(rng.choice(list(LABELS))))
    return out
