import io
import json

import cv2
import numpy as np
import pytest

from omr import samplegen as sg
from omr.server import create_app

KEY = "".join(np.random.default_rng(1).choice(list("ABCD"), 100))


@pytest.fixture()
def client(tmp_path):
    return create_app(tmp_path).test_client()


def _jpg(**kw):
    ok, enc = cv2.imencode(".jpg", sg.make_sheet(**kw))
    return io.BytesIO(enc.tobytes())


@pytest.fixture()
def exam(client):
    tid = client.post("/api/templates", json={**sg.sample_template(), "name": "Sample"}).json["id"]
    eid = client.post("/api/exams", json={"name": "T1", "template_id": tid, "correct": 4, "wrong": -1,
                                          "sections_text": "Physics 1-50, Chem 51-100"}).json["id"]
    assert client.put(f"/api/exams/{eid}/keys", json={"set": "A", "text": KEY}).json["count"] == 100
    return eid


def scan(client, eid, rolls, batch="", answers=None):
    data = {"batch": batch, "files": []}
    for i, roll in enumerate(rolls):
        data["files"].append((_jpg(roll=roll, batch="01", set_code="A", answers=answers or list(KEY), seed=i, tilt=0.6),
                              f"{roll}.jpg"))
    r = client.post(f"/api/exams/{eid}/scan", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.json
    return r.json


def test_full_marks_and_batches(client, exam):
    scan(client, exam, ["00000001", "00000002"], batch="Morning")
    scan(client, exam, ["00000003"], batch="Evening")
    res = client.get(f"/api/exams/{exam}/results").json
    assert [r["score"] for r in res["rows"]] == [400, 400, 400]
    assert {b["batch"] for b in res["batches"]} == {"01"}   # sheet's own batch code wins when the sheet has one
    assert res["review"] == 0


def test_changing_the_key_rescores_without_rescanning(client, exam):
    scan(client, exam, ["00000001"])
    wrong = ("B" if KEY[0] != "B" else "C") + KEY[1:]
    client.put(f"/api/exams/{exam}/keys", json={"set": "A", "text": wrong})
    row = client.get(f"/api/exams/{exam}/results").json["rows"][0]
    assert row["score"] == 400 - 4 - 1 and row["wrong"] == 1
    # accept both options for Q1 (disputed question)
    client.put(f"/api/exams/{exam}/keys", json={"set": "A", "text": f"(B{KEY[0]})" + KEY[1:]})
    assert client.get(f"/api/exams/{exam}/results").json["rows"][0]["score"] == 400


def test_key_problem_is_spotted(client, exam):
    bad_key = ("B" if KEY[4] != "B" else "C") + KEY[1:]
    client.put(f"/api/exams/{exam}/keys", json={"set": "A", "text": KEY[:4] + bad_key[0] + KEY[5:]})
    scan(client, exam, [f"0000000{i}" for i in range(1, 5)])
    stats = client.get(f"/api/exams/{exam}/results").json["stats"]
    assert [s["q"] for s in stats if s["suspicious"]] == [5]


def test_review_flow_and_duplicates(client, exam):
    ans = list(KEY)
    ans[9] = ""          # blank
    scan(client, exam, ["00000007"], answers=ans)
    scan(client, exam, ["00000007"])         # same roll again
    sheets = client.get(f"/api/exams/{exam}/sheets").json
    assert all("Duplicate roll number" in s["issues"] for s in sheets)
    assert client.get(f"/api/sheets/{sheets[0]['id']}").json["roll"] == "00000007"
    assert client.put(f"/api/sheets/{sheets[0]['id']}", json={"roll": "00000008", "answers": ans}).status_code == 200
    sheets = client.get(f"/api/exams/{exam}/sheets").json
    assert not any("Duplicate roll number" in s["issues"] for s in sheets)
    assert client.delete(f"/api/sheets/{sheets[1]['id']}").json["ok"]


def test_unreadable_sheet_is_not_scored_and_flagged(client, exam):
    img = np.full((1800, 1300, 3), 255, np.uint8)
    ok, enc = cv2.imencode(".jpg", img)
    r = client.post(f"/api/exams/{exam}/scan", data={"files": (io.BytesIO(enc.tobytes()), "blank.jpg")},
                    content_type="multipart/form-data")
    assert r.json["done"][0]["flags"] > 0
    sheets = client.get(f"/api/exams/{exam}/sheets").json
    assert sheets[0]["needs_review"] and sheets[0]["result"] is None


def test_machine_file_and_student_import(client, exam):
    csv_students = "Roll,Name,Batch\n00000001,Asha,B1\n"
    assert client.post("/api/students/import", data={"file": (io.BytesIO(csv_students.encode()), "s.csv")},
                       content_type="multipart/form-data").json["imported"] == 1
    csv_resp = f"Roll No,Set,Responses\n00000001,A,{KEY}\n00000002,A,{'-' + KEY[1:]}\n"
    r = client.post(f"/api/exams/{exam}/import_responses", data={"file": (io.BytesIO(csv_resp.encode()), "m.csv")},
                    content_type="multipart/form-data")
    assert r.json["imported"] == 2
    rows = client.get(f"/api/exams/{exam}/results").json["rows"]
    assert rows[0]["name"] == "Asha" and rows[0]["score"] == 400 and rows[1]["score"] == 400 - 4


def test_excel_export_and_key_from_master_sheet(client, exam):
    scan(client, exam, ["00000001"])
    x = client.get(f"/api/exams/{exam}/export.xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"
    master = _jpg(roll="00000000", batch="01", set_code="A", answers=list(KEY), seed=5, tilt=-1)
    r = client.post(f"/api/exams/{exam}/key_from_sheet", data={"image": (master, "master.jpg")},
                    content_type="multipart/form-data").json
    assert r["text"] == KEY and r["unclear"] == []


def test_demo_runs(client):
    eid = client.post("/api/demo").json["exam_id"]
    res = client.get(f"/api/exams/{eid}/results").json
    assert res["total"] == 12 and len(res["rows"]) == 12
