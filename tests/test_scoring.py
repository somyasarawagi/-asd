from omr import scoring

CFG = {"correct": 4, "wrong": -1, "multi": "wrong", "sections": []}


def test_parse_key_formats():
    assert scoring.parse_key("ABCD") == list("ABCD")
    assert scoring.parse_key("A B, C\nD") == list("ABCD")
    assert scoring.parse_key("1.A 2.B 3.(AC) 4.*") == ["A", "B", "AC", "*"]
    assert scoring.parse_key("1-A, 2-B, 3-C") == ["A", "B", "C"]
    assert scoring.parse_key("A(BC)*-_D") == ["A", "BC", "*", "-", "", "D"]
    assert scoring.parse_key(scoring.key_to_text(["A", "", "BC"])) == ["A", "", "BC"]


def test_scoring_rules():
    key = ["A", "B", "AC", "*", "-", "D"]
    res = scoring.score_sheet(["A", "C", "C", "", "A", "AB"], key, CFG)
    assert res["per_q"] == "CWCXNM"
    assert res["score"] == 4 - 1 + 4 + 4 - 1       # correct, wrong, either-accepted, bonus, cancelled, multi-wrong
    assert res["max"] == 20                        # cancelled question not counted
    zero = scoring.score_sheet(["A", "C", "C", "", "A", "AB"], key, {**CFG, "multi": "zero"})
    assert zero["score"] == 4 - 1 + 4 + 4


def test_sections_and_custom_marks():
    cfg = {**CFG, "sections": scoring.parse_sections("Physics 1-2, Maths 3-4 2/0")}
    res = scoring.score_sheet(["A", "A", "B", "A"], list("ABAB"), cfg)
    assert res["sections"]["Physics"]["score"] == 3
    assert res["sections"]["Maths"]["score"] == 0 and res["sections"]["Maths"]["max"] == 4


def test_ranks_with_ties():
    rows = [{"score": 10}, {"score": 30}, {"score": 30}, {"score": 5}]
    scoring.assign_ranks(rows)
    assert [r["rank"] for r in rows] == [3, 1, 1, 4]


def test_wrong_key_detection():
    answers = [["B"]] * 8 + [["A"]] * 2
    st = scoring.question_stats(answers, ["A"])[0]
    assert st["suspicious"] and st["top"] == "B"
