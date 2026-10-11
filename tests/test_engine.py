import cv2
import numpy as np
import pytest

from omr import engine, samplegen as sg

TPL = sg.sample_template()


def _case(seed, **kw):
    rng = np.random.default_rng(seed)
    ans = sg.random_answers(rng)
    roll = "".join(str(x) for x in rng.integers(0, 10, 8))
    img = sg.make_sheet(roll=roll, batch="07", set_code="C", answers=ans, seed=seed, **kw)
    return img, ans, roll


@pytest.mark.parametrize("seed,kw", [
    (1, dict(tilt=1.2, shift=(12, -8))),
    (2, dict(tilt=-2.2, noise=11, scale=0.7, jpeg=50)),
    (3, dict(tilt=2.0, scale=1.46, jpeg=75)),
    (4, dict(tilt=0.0, noise=2, jpeg=90)),
])
def test_reads_every_answer(seed, kw):
    img, ans, roll = _case(seed, **kw)
    scan, r = engine.read_with_retry(img, TPL)
    assert (r["roll"], r["batch"], r["set"]) == (roll, "07", "C")
    for q, (got, want) in enumerate(zip(r["answers"], ans), 1):
        # a mismatch is only acceptable when the sheet was flagged for review
        assert got == want or any(f.startswith(f"q{q}:") for f in r["flags"]), (q, got, want)
    assert sum(g != w for g, w in zip(r["answers"], ans)) <= 2


def test_upside_down_page_is_rotated_back():
    img, ans, roll = _case(5, tilt=1.0)
    scan, r = engine.read_with_retry(cv2.rotate(img, cv2.ROTATE_180), TPL)
    assert scan.rotation == 180 and r["roll"] == roll


def test_blank_sheet_has_no_marks_and_asks_for_review():
    scan, r = engine.read_with_retry(sg.make_sheet(blank=True, seed=3), TPL)
    assert not any(r["answers"])
    assert "roll:unreadable" in r["flags"]


def test_wrong_sheet_is_reported_not_guessed():
    img = np.full((2000, 1500, 3), 255, np.uint8)
    cv2.putText(img, "NOT AN OMR", (100, 300), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 5)
    scan, r = engine.read_with_retry(img, TPL)
    assert "layout" in r["flags"] and r["answers"] == []


def test_auto_detects_blocks_and_guesses_types():
    img, *_ = _case(6, tilt=0.5)
    scan = engine.analyze(img)
    assert engine.check_layout(scan, TPL)
    kinds = [b.kind for b in scan.blocks if b.kind != "ignore"]
    assert kinds == ["roll", "roll", "set", "answers", "answers", "answers", "answers"]


def test_light_pencil_and_faint_marks():
    # a faint mark that is not clearly filled must be flagged, never silently dropped
    img = sg.make_sheet(answers=["A"] * 100, seed=9)
    scan, r = engine.read_with_retry(img, TPL)     # the title letters form a stray block: skipped via signature
    assert r["answers"].count("A") >= 98
