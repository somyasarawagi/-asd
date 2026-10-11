"""Answer keys and scoring.

Key tokens (one per question):
    "A"      single correct option
    "AC"     either A or C is accepted (e.g. a disputed question)
    "*"      bonus - everybody gets full marks
    "-"      cancelled - question is removed from the paper
    ""       not set
"""
from __future__ import annotations

import re

NUMBERED = re.compile(r"(\d+)\s*[\.\):=,\-]?\s*(\([A-Za-z*\-]+\)|[A-Za-z*]+|-)")


def parse_key(text: str) -> list[str]:
    """Accepts 'ABCDA...', 'A B C D', '1.A 2.B 3.(AC) 4.*', one per line, etc."""
    text = (text or "").strip().upper()
    if not text:
        return []
    nums = NUMBERED.findall(text)
    if len(nums) >= 2 and re.search(r"\d", text):
        table = {}
        for q, tok in nums:
            table[int(q)] = tok.strip("()")
        n = max(table)
        return [table.get(i, "") for i in range(1, n + 1)]
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            j = text.find(")", i)
            j = len(text) if j < 0 else j
            out.append("".join(c for c in text[i + 1:j] if c.isalpha()))
            i = j + 1
            continue
        if ch.isalpha() or ch in "*-":
            out.append(ch)
        elif ch == "_":
            out.append("")
        i += 1
    return out


def key_to_text(key: list[str]) -> str:
    """Compact text form; '_' marks a question with no key yet."""
    return "".join("_" if t == "" else t if len(t) == 1 else f"({t})" for t in key)


def _section_for(q: int, cfg: dict):
    for s in cfg.get("sections") or []:
        if s["start"] <= q <= s["end"]:
            return s
    return None


def score_sheet(answers: list[str], key: list[str], cfg: dict) -> dict:
    """Score one sheet. per_q chars: C correct, W wrong, B blank, M multi(wrong), m multi(zero),
    X bonus, N cancelled, . no key."""
    base_c = float(cfg.get("correct", 1))
    base_w = float(cfg.get("wrong", 0))
    multi_wrong = cfg.get("multi", "wrong") == "wrong"
    per_q = []
    total = mx = 0.0
    counts = {"correct": 0, "wrong": 0, "blank": 0, "multi": 0}
    sections: dict[str, dict] = {}

    def sec_bucket(name):
        return sections.setdefault(name, {"score": 0.0, "max": 0.0, "correct": 0, "wrong": 0, "blank": 0})

    for qi, tok in enumerate(key):
        q = qi + 1
        sec = _section_for(q, cfg)
        pos = float(sec["correct"]) if sec and sec.get("correct") not in (None, "") else base_c
        neg = float(sec["wrong"]) if sec and sec.get("wrong") not in (None, "") else base_w
        bucket = sec_bucket(sec["name"]) if sec else None
        ans = answers[qi] if qi < len(answers) else ""
        if tok == "":
            per_q.append(".")
            continue
        if tok == "-":
            per_q.append("N")
            continue
        mx += pos
        if bucket:
            bucket["max"] += pos
        if tok == "*":
            per_q.append("X")
            total += pos
            counts["correct"] += 1
            if bucket:
                bucket["score"] += pos
                bucket["correct"] += 1
            continue
        if ans == "":
            per_q.append("B")
            counts["blank"] += 1
            if bucket:
                bucket["blank"] += 1
        elif len(ans) > 1:
            counts["multi"] += 1
            if multi_wrong:
                per_q.append("M")
                total += neg
                if bucket:
                    bucket["score"] += neg
                    bucket["wrong"] += 1
            else:
                per_q.append("m")
                if bucket:
                    bucket["blank"] += 1
        elif ans in tok:
            per_q.append("C")
            total += pos
            counts["correct"] += 1
            if bucket:
                bucket["score"] += pos
                bucket["correct"] += 1
        else:
            per_q.append("W")
            total += neg
            counts["wrong"] += 1
            if bucket:
                bucket["score"] += neg
                bucket["wrong"] += 1
    return {
        "score": round(total, 2), "max": round(mx, 2),
        "percent": round(100.0 * total / mx, 2) if mx else 0.0,
        "sections": {k: {**v, "score": round(v["score"], 2), "max": round(v["max"], 2)} for k, v in sections.items()},
        "per_q": "".join(per_q), **counts,
    }


def assign_ranks(rows: list[dict], field: str = "score") -> None:
    """Competition ranking (1,2,2,4). Rows without a score are ranked last/None."""
    scored = sorted((r for r in rows if r.get(field) is not None), key=lambda r: -r[field])
    prev, rank = None, 0
    for i, r in enumerate(scored, 1):
        if r[field] != prev:
            rank, prev = i, r[field]
        r["rank"] = rank
    for r in rows:
        r.setdefault("rank", None)


def question_stats(all_answers: list[list[str]], key: list[str], labels: str = "ABCD") -> list[dict]:
    """Per-question option distribution - the quickest way to spot a wrong answer key."""
    stats = []
    n = len(all_answers)
    for qi, tok in enumerate(key):
        dist = {l: 0 for l in labels}
        blank = multi = 0
        for ans in all_answers:
            a = ans[qi] if qi < len(ans) else ""
            if a == "":
                blank += 1
            elif len(a) > 1:
                multi += 1
            elif a in dist:
                dist[a] += 1
        attempted = n - blank - multi
        top = max(dist, key=dist.get) if attempted else ""
        top_share = dist[top] / n if n and top else 0.0
        right = sum(dist[l] for l in dist if l in tok) if tok not in ("", "-", "*") else 0
        suspicious = bool(
            top and tok not in ("", "-", "*") and top not in tok
            and top_share >= 0.4 and dist[top] > right
        )
        stats.append({
            "q": qi + 1, "key": tok, "dist": dist, "blank": blank, "multi": multi,
            "pct_correct": round(100.0 * right / n, 1) if n else 0.0,
            "top": top, "suspicious": suspicious,
        })
    return stats


def parse_sections(text: str) -> list[dict]:
    """'Physics 1-45, Chemistry 46-90' (optionally ' 4/-1') -> section dicts."""
    out = []
    for part in re.split(r"[;\n,]+", text or ""):
        m = re.match(r"\s*(.+?)\s+(\d+)\s*[-to]+\s*(\d+)(?:\s+\+?(-?[\d.]+)\s*/\s*(-?[\d.]+))?\s*$", part)
        if m:
            name, a, b, pos, neg = m.groups()
            out.append({"name": name, "start": int(a), "end": int(b),
                        "correct": float(pos) if pos else None,
                        "wrong": float(neg) if neg else None})
    return out
