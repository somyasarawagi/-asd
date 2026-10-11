"""Attendance, homework, study material, doubts, tests (offline marks + online MCQ)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from flask import jsonify, request

from . import db
from .core import (STAFF, ApiError, api, body, can_manage_batch, choice, in_clause, iso, me, my_children,
                   notify, notify_batch, num, parent_users, pick_student, rank_rows, require_batch, roles,
                   student_or_403, student_users, text, today, url, user_batch_ids)

# ---------------------------------------------------------- attendance ----


@api.get("/attendance/sheet")
@roles("teacher", *STAFF)
def attendance_sheet():
    u = me()
    bid = require_batch(u, request.args.get("batch_id"))
    day = iso(request.args.get("date") or today(), "date")
    rows = db.q("SELECT s.id AS student_id, x.name, x.login_id, a.status FROM students s "
                "JOIN users x ON x.id=s.user_id LEFT JOIN attendance a ON a.student_id=s.id AND a.date=? "
                "WHERE s.batch_id=? AND s.status='active' ORDER BY x.name", (day, bid))
    return jsonify(date=day, students=rows)


@api.post("/attendance")
@roles("teacher", *STAFF)
def mark_attendance():
    d, u = body(), me()
    bid = require_batch(u, d.get("batch_id"))
    day = iso(d.get("date"), "date")
    if day > today():
        raise ApiError("You cannot mark attendance for a future date")
    recs = d.get("records")
    if not isinstance(recs, list) or not recs:
        raise ApiError("'records' is required")
    valid = set(batch_ids_students(bid))
    absent = []
    for r in recs:
        sid, st = r.get("student_id"), choice(r.get("status"), ("P", "A", "L"), "status")
        if sid not in valid:
            raise ApiError(f"Student {sid} is not in this batch")
        prev = db.q1("SELECT status FROM attendance WHERE student_id=? AND date=?", (sid, day))
        db.ex("INSERT INTO attendance(student_id,batch_id,date,status,marked_by) VALUES(?,?,?,?,?) "
              "ON CONFLICT(student_id,date) DO UPDATE SET status=excluded.status, marked_by=excluded.marked_by, "
              "batch_id=excluded.batch_id", (sid, bid, day, st, u["id"]))
        if st == "A" and (not prev or prev["status"] != "A"):
            absent.append(sid)
    if absent:
        names = {r["id"]: r["name"] for r in db.q(
            f"SELECT s.id, x.name FROM students s JOIN users x ON x.id=s.user_id WHERE s.id IN ({in_clause(absent)})",
            absent)}
        for sid in absent:
            notify(parent_users([sid]), "Absent today", f"{names[sid]} was marked absent on {day}.", "attendance")
    return jsonify(ok=True, absent=len(absent))


def batch_ids_students(bid: int) -> list[int]:
    return [r["id"] for r in db.q("SELECT id FROM students WHERE batch_id=? AND status='active'", (bid,))]


@api.get("/attendance/student/<int:sid>")
@roles()
def student_attendance(sid):
    s = student_or_403(me(), sid)
    month = request.args.get("month") or today()[:7]
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise ApiError("'month' must look like 2026-04")
    rows = db.q("SELECT date, status FROM attendance WHERE student_id=? AND date LIKE ? ORDER BY date",
                (s["id"], month + "-%"))
    tot = db.q1("SELECT COUNT(*) AS n, SUM(status='P') AS p, SUM(status='A') AS a, SUM(status='L') AS l "
                "FROM attendance WHERE student_id=?", (s["id"],))
    pct = round(100 * (tot["p"] or 0) / tot["n"], 1) if tot["n"] else None
    return jsonify(month=month, records=rows,
                   overall={"days": tot["n"], "present": tot["p"] or 0, "absent": tot["a"] or 0,
                            "leave": tot["l"] or 0, "percent": pct})


@api.get("/attendance/summary")
@roles("teacher", *STAFF)
def attendance_summary():
    bid = require_batch(me(), request.args.get("batch_id"))
    rows = db.q("SELECT s.id AS student_id, x.name, x.login_id, COUNT(a.id) AS days, SUM(a.status='P') AS present, "
                "SUM(a.status='A') AS absent FROM students s JOIN users x ON x.id=s.user_id "
                "LEFT JOIN attendance a ON a.student_id=s.id WHERE s.batch_id=? AND s.status='active' "
                "GROUP BY s.id ORDER BY x.name", (bid,))
    for r in rows:
        r["present"], r["absent"] = r["present"] or 0, r["absent"] or 0
        r["percent"] = round(100 * r["present"] / r["days"], 1) if r["days"] else None
    return jsonify(students=rows)


# ------------------------------------------- homework & study material ----
def _scope_batches(u: dict):
    """(sql fragment, args) restricting a table's batch_id to what this user may see."""
    ids = user_batch_ids(u)
    if request.args.get("student_id") and u["role"] in ("student", "parent"):
        ids = [pick_student(u, request.args["student_id"])["batch_id"]]
    if request.args.get("batch_id"):
        want = int(request.args["batch_id"]) if request.args["batch_id"].isdigit() else -1
        if ids is not None and want not in ids:
            raise ApiError("You cannot see this batch", 403)
        ids = [want]
    if ids is None:
        return "1=1", []
    return f"x.batch_id IN ({in_clause(ids)})", ids


@api.get("/homework")
@roles()
def list_homework():
    cond, args = _scope_batches(me())
    rows = db.q(f"SELECT x.id, x.batch_id, b.name AS batch, x.subject_id, s.name AS subject, x.title, "
                f"x.description, x.due_date, x.created_at, u.name AS teacher FROM homework x "
                f"JOIN batches b ON b.id=x.batch_id LEFT JOIN subjects s ON s.id=x.subject_id "
                f"LEFT JOIN users u ON u.id=x.created_by WHERE {cond} ORDER BY x.due_date DESC, x.id DESC LIMIT 200",
                args)
    return jsonify(homework=rows, today=today())


@api.post("/homework")
@roles("teacher", *STAFF)
def add_homework():
    d, u = body(), me()
    bid = require_batch(u, d.get("batch_id"))
    title = text(d, "title", True, 150)
    hid = db.ex("INSERT INTO homework(batch_id,subject_id,title,description,due_date,created_by) VALUES(?,?,?,?,?,?)",
                (bid, num(d, "subject_id", False), title, text(d, "description", False, 2000),
                 iso(d.get("due_date"), "due_date", False) or None, u["id"]))
    notify_batch(bid, "New homework", title, "homework")
    return jsonify(id=hid), 201


@api.delete("/homework/<int:hid>")
@roles("teacher", *STAFF)
def del_homework(hid):
    row = db.q1("SELECT * FROM homework WHERE id=?", (hid,))
    if not row:
        raise ApiError("Not found", 404)
    if not can_manage_batch(me(), row["batch_id"]):
        raise ApiError("You do not teach this batch", 403)
    db.ex("DELETE FROM homework WHERE id=?", (hid,))
    return jsonify(ok=True)


@api.get("/materials")
@roles()
def list_materials():
    cond, args = _scope_batches(me())
    rows = db.q(f"SELECT x.id, x.batch_id, b.name AS batch, x.subject_id, s.name AS subject, x.title, x.kind, "
                f"x.url, x.created_at, u.name AS teacher FROM materials x JOIN batches b ON b.id=x.batch_id "
                f"LEFT JOIN subjects s ON s.id=x.subject_id LEFT JOIN users u ON u.id=x.created_by "
                f"WHERE {cond} ORDER BY x.id DESC LIMIT 300", args)
    return jsonify(materials=rows)


@api.post("/materials")
@roles("teacher", *STAFF)
def add_material():
    d, u = body(), me()
    bid = require_batch(u, d.get("batch_id"))
    mid = db.ex("INSERT INTO materials(batch_id,subject_id,title,kind,url,created_by) VALUES(?,?,?,?,?,?)",
                (bid, num(d, "subject_id", False), text(d, "title", True, 150),
                 choice(d.get("kind"), ("note", "video", "dpp", "pdf", "link"), "kind"), url(d.get("url")), u["id"]))
    notify_batch(bid, "New study material", text(d, "title", True), "material", parents=False)
    return jsonify(id=mid), 201


@api.delete("/materials/<int:mid>")
@roles("teacher", *STAFF)
def del_material(mid):
    row = db.q1("SELECT * FROM materials WHERE id=?", (mid,))
    if not row:
        raise ApiError("Not found", 404)
    if not can_manage_batch(me(), row["batch_id"]):
        raise ApiError("You do not teach this batch", 403)
    db.ex("DELETE FROM materials WHERE id=?", (mid,))
    return jsonify(ok=True)


# -------------------------------------------------------------- doubts ----
@api.get("/doubts")
@roles()
def list_doubts():
    u = me()
    base = ("SELECT d.id, d.student_id, x.name AS student, d.subject_id, s.name AS subject, d.question, d.answer, "
            "d.created_at, d.answered_at, t.name AS answered_by FROM doubts d JOIN students st ON st.id=d.student_id "
            "JOIN users x ON x.id=st.user_id LEFT JOIN subjects s ON s.id=d.subject_id "
            "LEFT JOIN users t ON t.id=d.answered_by")
    if u["role"] in STAFF:
        rows = db.q(base + " ORDER BY d.id DESC LIMIT 200")
    elif u["role"] == "teacher":
        rows = db.q(base + " WHERE EXISTS (SELECT 1 FROM batch_subjects bs WHERE bs.batch_id=st.batch_id "
                    "AND bs.teacher_user_id=? AND (bs.subject_id=d.subject_id OR d.subject_id IS NULL)) "
                    "ORDER BY d.id DESC LIMIT 200", (u["id"],))
    else:
        ids = [c["id"] for c in my_children(u)]
        rows = db.q(base + f" WHERE d.student_id IN ({in_clause(ids)}) ORDER BY d.id DESC LIMIT 200", ids)
    return jsonify(doubts=rows)


@api.post("/doubts")
@roles("student")
def ask_doubt():
    d, u = body(), me()
    s = pick_student(u)
    sub = num(d, "subject_id", False)
    did = db.ex("INSERT INTO doubts(student_id,subject_id,question) VALUES(?,?,?)",
                (s["id"], sub, text(d, "question", True, 2000)))
    teachers = [r["teacher_user_id"] for r in db.q(
        "SELECT teacher_user_id FROM batch_subjects WHERE batch_id=? AND (subject_id=? OR ? IS NULL)",
        (s["batch_id"], sub, sub))]
    notify(teachers, "New doubt", f"{s['name']} asked a doubt.", "doubt")
    return jsonify(id=did), 201


@api.post("/doubts/<int:did>/answer")
@roles("teacher", *STAFF)
def answer_doubt(did):
    u = me()
    row = db.q1("SELECT d.*, st.batch_id FROM doubts d JOIN students st ON st.id=d.student_id WHERE d.id=?", (did,))
    if not row:
        raise ApiError("Not found", 404)
    if not can_manage_batch(u, row["batch_id"]):
        raise ApiError("This student is not in your batch", 403)
    db.ex("UPDATE doubts SET answer=?, answered_by=?, answered_at=datetime('now') WHERE id=?",
          (text(body(), "answer", True, 4000), u["id"], did))
    notify(student_users([row["student_id"]]), "Doubt answered", "Your teacher answered your doubt.", "doubt")
    return jsonify(ok=True)


# --------------------------------------------------------------- tests ----
def _test_or_404(tid: int) -> dict:
    t = db.q1("SELECT * FROM tests WHERE id=?", (tid,))
    if not t:
        raise ApiError("Test not found", 404)
    return t


def _test_manage(tid: int) -> dict:
    t = _test_or_404(tid)
    if not can_manage_batch(me(), t["batch_id"]):
        raise ApiError("You do not teach this batch", 403)
    return t


def _test_visible(u: dict, t: dict) -> None:
    ids = user_batch_ids(u)
    if ids is not None and t["batch_id"] not in ids:
        raise ApiError("You cannot see this test", 403)


@api.get("/tests")
@roles()
def list_tests():
    u = me()
    cond, args = _scope_batches(u)
    cond = cond.replace("x.batch_id", "t.batch_id")
    rows = db.q(f"SELECT t.*, b.name AS batch, s.name AS subject, "
                f"(SELECT COUNT(*) FROM test_marks m WHERE m.test_id=t.id) AS graded, "
                f"(SELECT COUNT(*) FROM questions q WHERE q.test_id=t.id) AS question_count "
                f"FROM tests t JOIN batches b ON b.id=t.batch_id LEFT JOIN subjects s ON s.id=t.subject_id "
                f"WHERE {cond} ORDER BY t.date DESC, t.id DESC LIMIT 200", args)
    if u["role"] in ("student", "parent"):
        rows = [r for r in rows if r["published"]]
        kids = {c["id"] for c in my_children(u)}
        for r in rows:
            at = db.q1("SELECT submitted_at FROM attempts WHERE test_id=? AND student_id IN (%s)" %
                       ",".join(map(str, kids)), (r["id"],)) if kids else None
            r["attempted"] = bool(at and at["submitted_at"])
    return jsonify(tests=rows, today=today())


@api.post("/tests")
@roles("teacher", *STAFF)
def create_test():
    d, u = body(), me()
    bid = require_batch(u, d.get("batch_id"))
    mode = choice(d.get("mode") or "offline", ("offline", "online"), "mode")
    tid = db.ex("INSERT INTO tests(batch_id,subject_id,name,date,max_marks,mode,duration_min,created_by) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (bid, num(d, "subject_id", False), text(d, "name", True, 120), iso(d.get("date") or today(), "date"),
                 num(d, "max_marks", mode == "offline", 1, 10000, 100), mode, num(d, "duration_min", False, 5, 600, 60),
                 u["id"]))
    return jsonify(id=tid), 201


@api.get("/tests/<int:tid>/sheet")
@roles("teacher", *STAFF)
def marks_sheet(tid):
    t = _test_manage(tid)
    rows = db.q("SELECT s.id AS student_id, x.name, x.login_id, m.marks, COALESCE(m.absent,0) AS absent "
                "FROM students s JOIN users x ON x.id=s.user_id "
                "LEFT JOIN test_marks m ON m.student_id=s.id AND m.test_id=? "
                "WHERE s.batch_id=? AND s.status='active' ORDER BY x.name", (tid, t["batch_id"]))
    return jsonify(test=t, students=rows)


def _save_marks(t: dict, recs: list[dict]) -> int:
    valid = set(batch_ids_students(t["batch_id"]))
    n = 0
    for r in recs:
        sid = r.get("student_id")
        if sid not in valid:
            raise ApiError(f"Student {sid} is not in this batch")
        absent = bool(r.get("absent"))
        marks = None if absent or r.get("marks") in (None, "") else num(r, "marks", True, -t["max_marks"], t["max_marks"])
        if marks is None and not absent:
            db.ex("DELETE FROM test_marks WHERE test_id=? AND student_id=?", (t["id"], sid))
            continue
        db.ex("INSERT INTO test_marks(test_id,student_id,marks,absent) VALUES(?,?,?,?) "
              "ON CONFLICT(test_id,student_id) DO UPDATE SET marks=excluded.marks, absent=excluded.absent",
              (t["id"], sid, marks, 1 if absent else 0))
        n += 1
    return n


@api.post("/tests/<int:tid>/marks")
@roles("teacher", *STAFF)
def save_marks(tid):
    t = _test_manage(tid)
    if t["mode"] == "online":
        raise ApiError("Online test marks come from student attempts")
    recs = body().get("records")
    if not isinstance(recs, list):
        raise ApiError("'records' is required")
    return jsonify(saved=_save_marks(t, recs))


@api.post("/tests/<int:tid>/marks/import")
@roles("teacher", *STAFF)
def import_marks(tid):
    """CSV with a roll column and a marks column (e.g. exported from OMR Reader)."""
    t = _test_manage(tid)
    if t["mode"] == "online":
        raise ApiError("Online test marks come from student attempts")
    raw = text(body(), "csv", True, 2_000_000)
    rows = list(csv.reader(io.StringIO(raw)))
    if len(rows) < 2:
        raise ApiError("CSV needs a header row and at least one student")
    head = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        raise ApiError(f"CSV needs a column named one of: {', '.join(names)}")
    ri = col("roll", "roll no", "roll_no", "rollno", "login_id", "id")
    mi = col("marks", "total", "score")
    by_roll = {r["login_id"].lower(): r["id"] for r in db.q(
        "SELECT s.id, x.login_id FROM students s JOIN users x ON x.id=s.user_id WHERE s.batch_id=?", (t["batch_id"],))}
    recs, missing = [], []
    for line in rows[1:]:
        if len(line) <= max(ri, mi) or not line[ri].strip():
            continue
        sid = by_roll.get(line[ri].strip().lower())
        if sid is None:
            missing.append(line[ri].strip())
            continue
        mk = line[mi].strip()
        if mk.lower() in ("a", "ab", "absent"):
            recs.append({"student_id": sid, "absent": True})
        else:
            recs.append({"student_id": sid, "marks": mk})
    return jsonify(saved=_save_marks(t, recs), not_found=missing)


@api.post("/tests/<int:tid>/publish")
@roles("teacher", *STAFF)
def publish_test(tid):
    t = _test_manage(tid)
    flag = 1 if body().get("published", True) else 0
    if flag and t["mode"] == "online" and not db.q1("SELECT 1 FROM questions WHERE test_id=?", (tid,)):
        raise ApiError("Add questions before publishing an online test")
    if flag and t["mode"] == "offline" and not db.q1("SELECT 1 FROM test_marks WHERE test_id=?", (tid,)):
        raise ApiError("Enter marks before publishing")
    db.ex("UPDATE tests SET published=? WHERE id=?", (flag, tid))
    if flag and not t["published"]:
        msg = "Test is open - attempt it now." if t["mode"] == "online" else "Result is out."
        notify_batch(t["batch_id"], f"{t['name']}", msg, "test")
    return jsonify(ok=True)


@api.get("/tests/<int:tid>/results")
@roles()
def test_results(tid):
    u, t = me(), _test_or_404(tid)
    _test_visible(u, t)
    rows = db.q("SELECT s.id AS student_id, x.name, x.login_id, m.marks, m.absent FROM test_marks m "
                "JOIN students s ON s.id=m.student_id JOIN users x ON x.id=s.user_id WHERE m.test_id=?", (tid,))
    rank_rows(rows)
    scored = [r["marks"] for r in rows if r["marks"] is not None]
    stats = {"count": len(scored), "average": round(sum(scored) / len(scored), 2) if scored else None,
             "highest": max(scored) if scored else None, "lowest": min(scored) if scored else None,
             "max_marks": t["max_marks"]}
    if u["role"] in ("student", "parent"):
        if not t["published"]:
            raise ApiError("Result not published yet", 403)
        mine = {c["id"] for c in my_children(u)}
        rows = [r for r in rows if r["student_id"] in mine]
    elif not (t["published"] or can_manage_batch(u, t["batch_id"])):
        raise ApiError("Not allowed", 403)
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"]))
    return jsonify(test=t, results=rows, stats=stats)


@api.get("/students/<int:sid>/results")
@roles()
def student_results(sid):
    s = student_or_403(me(), sid)
    viewer_is_family = me()["role"] in ("student", "parent")
    tests = db.q("SELECT t.id, t.name, t.date, t.max_marks, t.mode, sub.name AS subject FROM tests t "
                 "LEFT JOIN subjects sub ON sub.id=t.subject_id WHERE t.batch_id=? "
                 + ("AND t.published=1 " if viewer_is_family else "") + "ORDER BY t.date, t.id", (s["batch_id"],))
    out = []
    for t in tests:
        allm = db.q("SELECT student_id, marks FROM test_marks WHERE test_id=?", (t["id"],))
        mine = next((m for m in allm if m["student_id"] == s["id"]), None)
        if mine is None:
            continue
        rank_rows(allm)
        scored = [m["marks"] for m in allm if m["marks"] is not None]
        me_row = next(m for m in allm if m["student_id"] == s["id"])
        out.append({**t, "marks": mine["marks"], "rank": me_row["rank"], "students": len(scored),
                    "average": round(sum(scored) / len(scored), 2) if scored else None,
                    "highest": max(scored) if scored else None,
                    "percent": round(100 * mine["marks"] / t["max_marks"], 1) if mine["marks"] is not None else None})
    return jsonify(results=out)


# --- online MCQ tests ---
@api.get("/tests/<int:tid>/questions")
@roles("teacher", *STAFF)
def get_questions(tid):
    _test_manage(tid)
    return jsonify(questions=db.q("SELECT * FROM questions WHERE test_id=? ORDER BY id", (tid,)))


def _sync_max(tid: int) -> None:
    tot = db.q1("SELECT COALESCE(SUM(marks),0) AS m FROM questions WHERE test_id=?", (tid,))["m"]
    db.ex("UPDATE tests SET max_marks=? WHERE id=?", (max(int(tot), 1), tid))


@api.post("/tests/<int:tid>/questions")
@roles("teacher", *STAFF)
def add_questions(tid):
    t = _test_manage(tid)
    if t["mode"] != "online":
        raise ApiError("Questions can be added to online tests only")
    if db.q1("SELECT 1 FROM attempts WHERE test_id=?", (tid,)):
        raise ApiError("Students have already started this test; questions are locked", 409)
    qs = body().get("questions")
    if not isinstance(qs, list) or not qs or len(qs) > 200:
        raise ApiError("Send 1-200 questions")
    for q in qs:
        db.ex("INSERT INTO questions(test_id,text,opt_a,opt_b,opt_c,opt_d,answer,marks,neg) VALUES(?,?,?,?,?,?,?,?,?)",
              (tid, text(q, "text", True, 2000), text(q, "a", True, 500), text(q, "b", True, 500),
               text(q, "c", False, 500) or None, text(q, "d", False, 500) or None,
               choice(str(q.get("answer", "")).upper(), ("A", "B", "C", "D"), "answer"),
               num(q, "marks", False, 0, 100, 4), num(q, "neg", False, 0, 100, 1)))
    _sync_max(tid)
    return jsonify(ok=True, added=len(qs)), 201


@api.delete("/questions/<int:qid>")
@roles("teacher", *STAFF)
def del_question(qid):
    q = db.q1("SELECT * FROM questions WHERE id=?", (qid,))
    if not q:
        raise ApiError("Not found", 404)
    _test_manage(q["test_id"])
    if db.q1("SELECT 1 FROM attempts WHERE test_id=?", (q["test_id"],)):
        raise ApiError("Students have already started this test; questions are locked", 409)
    db.ex("DELETE FROM questions WHERE id=?", (qid,))
    _sync_max(q["test_id"])
    return jsonify(ok=True)


GRACE_SECONDS = 60


def _paper(tid: int) -> list[dict]:
    rows = db.q("SELECT id, text, opt_a, opt_b, opt_c, opt_d, marks, neg FROM questions WHERE test_id=? ORDER BY id",
                (tid,))
    return [{"id": r["id"], "text": r["text"], "marks": r["marks"], "neg": r["neg"],
             "options": {k: r["opt_" + k.lower()] for k in "ABCD" if r["opt_" + k.lower()]}} for r in rows]


def _my_online_test(tid: int) -> tuple[dict, dict]:
    u = me()
    t, s = _test_or_404(tid), pick_student(u)
    if t["mode"] != "online" or not t["published"] or t["batch_id"] != s["batch_id"]:
        raise ApiError("This test is not available for you", 403)
    return t, s


@api.post("/tests/<int:tid>/start")
@roles("student")
def start_attempt(tid):
    t, s = _my_online_test(tid)
    at = db.q1("SELECT * FROM attempts WHERE test_id=? AND student_id=?", (tid, s["id"]))
    if at and at["submitted_at"]:
        raise ApiError("You have already submitted this test", 409)
    if not at:
        now = datetime.now().isoformat(timespec="seconds")
        db.ex("INSERT INTO attempts(test_id,student_id,started_at) VALUES(?,?,?)", (tid, s["id"], now))
        at = {"started_at": now, "answers": None}
    end = datetime.fromisoformat(at["started_at"]) + timedelta(minutes=t["duration_min"])
    left = int((end - datetime.now()).total_seconds())
    return jsonify(test={"id": t["id"], "name": t["name"], "duration_min": t["duration_min"]},
                   seconds_left=max(left, 0), questions=_paper(tid),
                   saved=json.loads(at["answers"]) if at.get("answers") else {})


@api.post("/tests/<int:tid>/submit")
@roles("student")
def submit_attempt(tid):
    t, s = _my_online_test(tid)
    at = db.q1("SELECT * FROM attempts WHERE test_id=? AND student_id=?", (tid, s["id"]))
    if not at:
        raise ApiError("Start the test first", 409)
    if at["submitted_at"]:
        raise ApiError("You have already submitted this test", 409)
    answers = body().get("answers") or {}
    if not isinstance(answers, dict):
        raise ApiError("'answers' must be an object")
    elapsed = (datetime.now() - datetime.fromisoformat(at["started_at"])).total_seconds()
    late = elapsed > t["duration_min"] * 60 + GRACE_SECONDS
    score, clean = 0.0, {}
    for q in db.q("SELECT id, answer, marks, neg FROM questions WHERE test_id=?", (tid,)):
        a = str(answers.get(str(q["id"]), "")).upper()
        if a not in ("A", "B", "C", "D"):
            continue
        clean[str(q["id"])] = a
        score += q["marks"] if a == q["answer"] else -q["neg"]
    if late:
        score = 0.0
    now = datetime.now().isoformat(timespec="seconds")
    db.ex("UPDATE attempts SET submitted_at=?, answers=?, score=?, late=? WHERE id=?",
          (now, json.dumps(clean), score, 1 if late else 0, at["id"]))
    db.ex("INSERT INTO test_marks(test_id,student_id,marks,absent) VALUES(?,?,?,0) "
          "ON CONFLICT(test_id,student_id) DO UPDATE SET marks=excluded.marks, absent=0", (tid, s["id"], score))
    notify(parent_users([s["id"]]), "Test submitted", f"{s['name']} finished {t['name']}: {score:g}/{t['max_marks']}.",
           "test")
    return jsonify(score=score, max_marks=t["max_marks"], late=late)


@api.get("/tests/<int:tid>/review")
@roles("student", "parent")
def review_attempt(tid):
    u = me()
    s = pick_student(u, request.args.get("student_id"))
    at = db.q1("SELECT * FROM attempts WHERE test_id=? AND student_id=? AND submitted_at IS NOT NULL", (tid, s["id"]))
    if not at:
        raise ApiError("No submitted attempt found", 404)
    given = json.loads(at["answers"] or "{}")
    qs = db.q("SELECT * FROM questions WHERE test_id=? ORDER BY id", (tid,))
    return jsonify(score=at["score"], late=bool(at["late"]), questions=[
        {"id": q["id"], "text": q["text"], "correct": q["answer"], "given": given.get(str(q["id"])),
         "options": {k: q["opt_" + k.lower()] for k in "ABCD" if q["opt_" + k.lower()]}} for q in qs])
