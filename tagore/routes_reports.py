"""Role-specific dashboards and the director's overview."""
from __future__ import annotations

from datetime import date, timedelta

from flask import jsonify, request

from . import db
from .core import (STAFF, api, in_clause, me, my_children, pick_student, roles, teacher_batch_ids, today,
                   user_batch_ids)
from .routes_finance import FEE_SELECT, _decorate


def _latest_notices(u: dict, n: int = 4) -> list[dict]:
    from .routes_comms import AUDIENCE_OF
    if u["role"] in STAFF:
        return db.q("SELECT id,title,created_at FROM notices ORDER BY pinned DESC, id DESC LIMIT ?", (n,))
    ids = user_batch_ids(u) or []
    return db.q(f"SELECT id,title,created_at FROM notices WHERE (audience='all' OR audience=?) AND "
                f"(batch_id IS NULL OR batch_id IN ({in_clause(ids)})) ORDER BY pinned DESC, id DESC LIMIT ?",
                [AUDIENCE_OF[u["role"]]] + ids + [n])


def _family_dashboard(u: dict) -> dict:
    kids = my_children(u)
    s = pick_student(u, request.args.get("student_id") or (kids[0]["id"] if kids else None))
    att = db.q1("SELECT COUNT(*) AS n, SUM(status='P') AS p FROM attendance WHERE student_id=?", (s["id"],))
    last7 = db.q("SELECT date,status FROM attendance WHERE student_id=? ORDER BY date DESC LIMIT 7", (s["id"],))
    wd = date.today().weekday()
    classes = db.q("SELECT t.start_time,t.end_time,sub.name AS subject,tu.name AS teacher,t.room FROM timetable t "
                   "JOIN subjects sub ON sub.id=t.subject_id LEFT JOIN batch_subjects bs ON bs.batch_id=t.batch_id "
                   "AND bs.subject_id=t.subject_id LEFT JOIN users tu ON tu.id=bs.teacher_user_id "
                   "WHERE t.batch_id=? AND t.weekday=? ORDER BY t.start_time", (s["batch_id"], wd))
    hw = db.q("SELECT id,title,due_date FROM homework WHERE batch_id=? AND (due_date IS NULL OR due_date>=?) "
              "ORDER BY due_date LIMIT 5", (s["batch_id"], today()))
    tests = db.q("SELECT t.id,t.name,t.date,t.max_marks,m.marks FROM test_marks m JOIN tests t ON t.id=m.test_id "
                 "WHERE m.student_id=? AND t.published=1 ORDER BY t.date DESC, t.id DESC LIMIT 5", (s["id"],))
    open_online = db.q("SELECT t.id,t.name,t.duration_min FROM tests t WHERE t.batch_id=? AND t.mode='online' AND "
                       "t.published=1 AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.test_id=t.id AND a.student_id=? "
                       "AND a.submitted_at IS NOT NULL)", (s["batch_id"], s["id"]))
    fees = _decorate(db.q(f"{FEE_SELECT} WHERE f.student_id=?", (s["id"],)))
    due = sum(f["due"] for f in fees if f["due"] > 0)
    overdue = sum(f["due"] for f in fees if f["status"] == "overdue")
    batch = db.q1("SELECT name FROM batches WHERE id=?", (s["batch_id"],))
    ptm = db.q("SELECT e.id,e.title,e.date FROM ptm_events e WHERE e.date>=? AND (e.batch_id IS NULL OR e.batch_id=?) "
               "ORDER BY e.date LIMIT 2", (today(), s["batch_id"]))
    return {"student": {"id": s["id"], "name": s["name"], "roll": s["login_id"], "batch": batch and batch["name"]},
            "attendance": {"percent": round(100 * (att["p"] or 0) / att["n"], 1) if att["n"] else None,
                           "days": att["n"], "last7": last7[::-1]},
            "classes_today": classes, "homework": hw, "recent_tests": tests, "open_tests": open_online,
            "fees": {"due": due, "overdue": overdue}, "ptm": ptm, "notices": _latest_notices(u)}


def _teacher_dashboard(u: dict) -> dict:
    ids = teacher_batch_ids(u["id"])
    wd = date.today().weekday()
    classes = db.q("SELECT t.start_time,t.end_time,b.name AS batch,sub.name AS subject,t.room FROM timetable t "
                   "JOIN batch_subjects bs ON bs.batch_id=t.batch_id AND bs.subject_id=t.subject_id "
                   "JOIN batches b ON b.id=t.batch_id JOIN subjects sub ON sub.id=t.subject_id "
                   "WHERE bs.teacher_user_id=? AND t.weekday=? ORDER BY t.start_time", (u["id"], wd))
    batches = db.q(f"SELECT b.id,b.name,(SELECT COUNT(*) FROM students s WHERE s.batch_id=b.id AND s.status='active') "
                   f"AS students FROM batches b WHERE b.id IN ({in_clause(ids)})", ids)
    marked = {r["batch_id"] for r in db.q("SELECT DISTINCT batch_id FROM attendance WHERE date=?", (today(),))}
    for b in batches:
        b["attendance_done"] = b["id"] in marked
    pending_doubts = db.q1(
        "SELECT COUNT(*) AS n FROM doubts d JOIN students st ON st.id=d.student_id WHERE d.answer IS NULL AND "
        "EXISTS (SELECT 1 FROM batch_subjects bs WHERE bs.batch_id=st.batch_id AND bs.teacher_user_id=? AND "
        "(bs.subject_id=d.subject_id OR d.subject_id IS NULL))", (u["id"],))["n"]
    ptm = db.q("SELECT e.title,e.date,p.slot_time,x.name AS student FROM ptm_slots p JOIN ptm_events e ON e.id=p.ptm_id "
               "LEFT JOIN students s ON s.id=p.student_id LEFT JOIN users x ON x.id=s.user_id "
               "WHERE p.teacher_user_id=? AND e.date>=? AND p.status='booked' ORDER BY e.date, p.slot_time LIMIT 8",
               (u["id"], today()))
    pend_leaves = db.q1(f"SELECT COUNT(*) AS n FROM leaves l JOIN students s ON s.id=l.student_id "
                        f"WHERE l.status='pending' AND s.batch_id IN ({in_clause(ids)})", ids)["n"]
    return {"classes_today": classes, "batches": batches, "pending_doubts": pending_doubts, "ptm": ptm,
            "pending_leaves": pend_leaves, "notices": _latest_notices(u)}


def _office_numbers() -> dict:
    t = today()
    month = t[:8] + "01"
    fees = _decorate(db.q(FEE_SELECT))
    return {
        "students": db.q1("SELECT COUNT(*) AS n FROM students WHERE status='active'")["n"],
        "today_collection": db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM payments WHERE paid_on=?", (t,))["x"],
        "month_collection": db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM payments WHERE paid_on>=?", (month,))["x"],
        "month_expenses": db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM expenses WHERE date>=?", (month,))["x"],
        "total_due": sum(f["due"] for f in fees if f["due"] > 0),
        "total_overdue": sum(f["due"] for f in fees if f["status"] == "overdue"),
        "new_enquiries": db.q1("SELECT COUNT(*) AS n FROM enquiries WHERE status='new'")["n"],
        "followups_today": db.q("SELECT id,name,phone,course FROM enquiries WHERE follow_up<=? AND "
                                "status NOT IN ('admitted','lost') ORDER BY follow_up LIMIT 8", (t,)),
        "pending_leaves": db.q1("SELECT COUNT(*) AS n FROM leaves WHERE status='pending'")["n"],
        "upcoming_ptm": db.q("SELECT id,title,date FROM ptm_events WHERE date>=? ORDER BY date LIMIT 3", (t,)),
    }


@api.get("/dashboard")
@roles()
def dashboard():
    u = me()
    if u["role"] in ("student", "parent"):
        data = _family_dashboard(u)
    elif u["role"] == "teacher":
        data = _teacher_dashboard(u)
    else:
        data = _office_numbers()
        data["notices"] = _latest_notices(u)
    return jsonify(role=u["role"], **data)


@api.get("/reports/overview")
@roles("superadmin")
def overview():
    t = date.today()
    # last 6 months fee collection vs expenses
    months = []
    for i in range(5, -1, -1):
        y, m = t.year, t.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")
    money = []
    for m in months:
        inc = db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM payments WHERE paid_on LIKE ?", (m + "-%",))["x"]
        exp = db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM expenses WHERE date LIKE ?", (m + "-%",))["x"]
        money.append({"month": m, "income": inc, "expenses": exp})
    since = (t - timedelta(days=30)).isoformat()
    att = db.q("SELECT b.name AS batch, COUNT(a.id) AS n, SUM(a.status='P') AS p FROM batches b "
               "LEFT JOIN attendance a ON a.batch_id=b.id AND a.date>=? WHERE b.active=1 GROUP BY b.id ORDER BY b.name",
               (since,))
    for r in att:
        r["percent"] = round(100 * (r["p"] or 0) / r["n"], 1) if r["n"] else None
    perf = db.q("SELECT b.name AS batch, COUNT(m.marks) AS n, AVG(100.0*m.marks/t.max_marks) AS avg FROM batches b "
                "LEFT JOIN tests t ON t.batch_id=b.id AND t.published=1 LEFT JOIN test_marks m ON m.test_id=t.id "
                "AND m.marks IS NOT NULL WHERE b.active=1 GROUP BY b.id ORDER BY b.name")
    for r in perf:
        r["avg"] = round(r["avg"], 1) if r["avg"] is not None else None
    batches = db.q("SELECT b.name AS batch, COUNT(s.id) AS students FROM batches b LEFT JOIN students s ON "
                   "s.batch_id=b.id AND s.status='active' WHERE b.active=1 GROUP BY b.id ORDER BY b.name")
    funnel = db.q("SELECT status, COUNT(*) AS n FROM enquiries GROUP BY status")
    spend = db.q("SELECT category, SUM(amount) AS amount FROM expenses WHERE date>=? GROUP BY category "
                 "ORDER BY amount DESC", (t.strftime("%Y-%m-01"),))
    teachers = db.q("SELECT u.name, t.subject, (SELECT COUNT(DISTINCT bs.batch_id) FROM batch_subjects bs "
                    "WHERE bs.teacher_user_id=u.id) AS batches, (SELECT COUNT(*) FROM doubts d JOIN students st ON "
                    "st.id=d.student_id WHERE d.answered_by=u.id) AS doubts_solved, "
                    "(SELECT ROUND(AVG(feedback_rating),1) FROM ptm_slots p WHERE p.teacher_user_id=u.id AND "
                    "p.feedback_rating IS NOT NULL) AS ptm_rating FROM users u LEFT JOIN teachers t ON t.user_id=u.id "
                    "WHERE u.role='teacher' AND u.active=1 ORDER BY u.name")
    return jsonify(office=_office_numbers(), money=money, attendance=att, performance=perf, batches=batches,
                   funnel=funnel, spend=spend, teachers=teachers,
                   staff={"teachers": len(teachers),
                          "office": db.q1("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1")["n"]})
