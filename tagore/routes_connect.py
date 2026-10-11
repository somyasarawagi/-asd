"""Parent-connect features: PTM reschedule / reminders / report, meeting requests, parent-teacher chat,
complaints, teacher remarks and the student report card."""
from __future__ import annotations

from datetime import date, timedelta

from flask import jsonify, request

from . import db
from .core import (STAFF, ApiError, api, audit, batch_student_ids, body, choice, hhmm, in_clause, iso, me,
                   my_children, notify, num, parent_users, pick_student, roles, student_or_403, student_users, text,
                   today)


# ------------------------------------------------------------- helpers ----
def student_brief(sid: int) -> dict:
    """One-glance picture of a student, shown to the teacher before a PTM."""
    att = db.q1("SELECT COUNT(*) AS n, SUM(status='P') AS p FROM attendance WHERE student_id=?", (sid,))
    perf = db.q1("SELECT COUNT(*) AS n, AVG(100.0*m.marks/t.max_marks) AS avg FROM test_marks m "
                 "JOIN tests t ON t.id=m.test_id WHERE m.student_id=? AND m.marks IS NOT NULL AND t.published=1", (sid,))
    return {"attendance_percent": round(100 * (att["p"] or 0) / att["n"], 1) if att["n"] else None,
            "tests_taken": perf["n"], "average_percent": round(perf["avg"], 1) if perf["avg"] is not None else None,
            "remarks": db.q("SELECT r.kind, r.body, r.created_at, u.name AS teacher FROM student_remarks r "
                            "JOIN users u ON u.id=r.teacher_user_id WHERE r.student_id=? ORDER BY r.id DESC LIMIT 3",
                            (sid,))}


def teaches(teacher_id: int, batch_id: int) -> bool:
    return bool(db.q1("SELECT 1 FROM batch_subjects WHERE batch_id=? AND teacher_user_id=?", (batch_id, teacher_id)))


# ---------------------------------------------------- PTM: more tools -----
def send_ptm_reminders() -> int:
    """Remind parent + teacher of meetings today / tomorrow. Safe to call repeatedly (once per slot)."""
    horizon = (date.today() + timedelta(days=1)).isoformat()
    rows = db.q("SELECT p.id, p.slot_time, p.teacher_user_id, p.booked_by, p.student_id, e.date, e.mode, e.title "
                "FROM ptm_slots p JOIN ptm_events e ON e.id=p.ptm_id WHERE p.status='booked' AND p.reminded=0 "
                "AND e.date BETWEEN ? AND ?", (today(), horizon))
    for r in rows:
        when = "today" if r["date"] == today() else "tomorrow"
        kid = db.q1("SELECT u.name FROM students s JOIN users u ON u.id=s.user_id WHERE s.id=?", (r["student_id"],))
        notify([r["booked_by"]], "PTM reminder", f"{r['title']}: meeting {when} at {r['slot_time']} ({r['mode']}).", "ptm")
        notify([r["teacher_user_id"]], "PTM reminder",
               f"Meeting {when} at {r['slot_time']} about {kid['name'] if kid else 'a student'}.", "ptm")
        db.ex("UPDATE ptm_slots SET reminded=1 WHERE id=?", (r["id"],))
    return len(rows)


@api.post("/ptm/remind")
@roles(*STAFF)
def remind_ptm():
    return jsonify(reminded=send_ptm_reminders())


@api.post("/ptm/slots/<int:slot_id>/reschedule")
@roles("parent")
def reschedule_slot(slot_id):
    """Move an existing booking to another open slot (same teacher or another)."""
    u, d = me(), body()
    old = db.q1("SELECT p.*, e.date FROM ptm_slots p JOIN ptm_events e ON e.id=p.ptm_id WHERE p.id=?", (slot_id,))
    if not old or old["booked_by"] != u["id"] or old["status"] != "booked":
        raise ApiError("This is not your booking", 403)
    new = db.q1("SELECT p.*, e.date, e.batch_id AS event_batch FROM ptm_slots p JOIN ptm_events e ON e.id=p.ptm_id "
                "WHERE p.id=?", (num(d, "to_slot_id", True),))
    if not new or new["ptm_id"] != old["ptm_id"]:
        raise ApiError("Pick a slot of the same PTM")
    if new["date"] < today():
        raise ApiError("This PTM is over")
    kid = pick_student(u, old["student_id"])
    if not teaches(new["teacher_user_id"], kid["batch_id"]):
        raise ApiError("This teacher does not teach your child", 403)
    if db.q1("SELECT 1 FROM ptm_slots WHERE ptm_id=? AND booked_by=? AND slot_time=? AND id<>?",
             (new["ptm_id"], u["id"], new["slot_time"], slot_id)):
        raise ApiError("You already have another meeting at this time", 409)
    if new["teacher_user_id"] != old["teacher_user_id"] and db.q1(
            "SELECT 1 FROM ptm_slots WHERE ptm_id=? AND teacher_user_id=? AND student_id=?",
            (new["ptm_id"], new["teacher_user_id"], kid["id"])):
        raise ApiError("You already booked this teacher for this child", 409)
    cur = db.get().execute("UPDATE ptm_slots SET status='booked', student_id=?, booked_by=?, reminded=0 "
                           "WHERE id=? AND status='open'", (kid["id"], u["id"], new["id"]))
    if cur.rowcount != 1:
        raise ApiError("Sorry, that slot was just taken. Pick another.", 409)
    db.ex("UPDATE ptm_slots SET status='open', student_id=NULL, booked_by=NULL, reminded=0 WHERE id=?", (slot_id,))
    notify([old["teacher_user_id"]], "PTM meeting moved", f"A parent moved their {old['slot_time']} meeting.", "ptm")
    if new["teacher_user_id"] != old["teacher_user_id"]:
        notify([new["teacher_user_id"]], "PTM slot booked", f"{u['name']} booked {new['slot_time']} for {kid['name']}.",
               "ptm")
    return jsonify(ok=True)


@api.get("/ptm/<int:pid>/report")
@roles(*STAFF)
def ptm_report(pid):
    e = db.q1("SELECT * FROM ptm_events WHERE id=?", (pid,))
    if not e:
        raise ApiError("PTM not found", 404)
    per_teacher = db.q("SELECT u.name AS teacher, COUNT(*) AS slots, SUM(p.status<>'open') AS booked, "
                       "SUM(p.status='done') AS done, SUM(p.parent_attended=1) AS attended, "
                       "SUM(p.parent_attended=0) AS no_show, ROUND(AVG(p.feedback_rating),1) AS rating "
                       "FROM ptm_slots p JOIN users u ON u.id=p.teacher_user_id WHERE p.ptm_id=? "
                       "GROUP BY p.teacher_user_id ORDER BY u.name", (pid,))
    for r in per_teacher:
        for k in ("booked", "done", "attended", "no_show"):
            r[k] = r[k] or 0
    tot = {k: sum(r[k] for r in per_teacher) for k in ("slots", "booked", "done", "attended", "no_show")}
    ids = batch_student_ids(e["batch_id"]) if e["batch_id"] else \
        [r["id"] for r in db.q("SELECT id FROM students WHERE status='active'")]
    met = {r["student_id"] for r in db.q("SELECT DISTINCT student_id FROM ptm_slots WHERE ptm_id=? AND "
                                         "student_id IS NOT NULL", (pid,))}
    missing = db.q(f"SELECT s.id, u.name, u.login_id, "
                   f"(SELECT group_concat(p.phone) FROM parent_students ps JOIN users p ON p.id=ps.parent_user_id "
                   f"WHERE ps.student_id=s.id) AS parent_phone FROM students s JOIN users u ON u.id=s.user_id "
                   f"WHERE s.id IN ({in_clause(ids)}) ORDER BY u.name", ids)
    missing = [m for m in missing if m["id"] not in met]
    return jsonify(event=e, totals=tot, teachers=per_teacher, families=len(ids), not_booked=missing,
                   coverage_percent=round(100 * len(met) / len(ids), 1) if ids else None)


@api.post("/ptm/<int:pid>/nudge")
@roles(*STAFF)
def nudge_unbooked(pid):
    rep = ptm_report(pid).get_json()
    sids = [m["id"] for m in rep["not_booked"]]
    notify(parent_users(sids), "Book your PTM slot",
           f"{rep['event']['title']} on {rep['event']['date']}: you have not booked a meeting yet.", "ptm")
    return jsonify(nudged=len(sids))


# ---------------------------------------------------- meeting requests ----
@api.get("/meeting-requests")
@roles("parent", "teacher", *STAFF)
def list_requests():
    u = me()
    sql = ("SELECT r.*, x.name AS student, t.name AS teacher, p.name AS parent FROM meeting_requests r "
           "JOIN students s ON s.id=r.student_id JOIN users x ON x.id=s.user_id JOIN users t ON t.id=r.teacher_user_id "
           "JOIN users p ON p.id=r.parent_user_id")
    if u["role"] == "parent":
        rows = db.q(sql + " WHERE r.parent_user_id=? ORDER BY r.id DESC LIMIT 100", (u["id"],))
    elif u["role"] == "teacher":
        rows = db.q(sql + " WHERE r.teacher_user_id=? ORDER BY r.status='pending' DESC, r.id DESC LIMIT 100", (u["id"],))
    else:
        rows = db.q(sql + " ORDER BY r.id DESC LIMIT 200")
    return jsonify(requests=rows)


@api.post("/meeting-requests")
@roles("parent")
def request_meeting():
    u, d = me(), body()
    kid = pick_student(u, d.get("student_id"))
    tid = num(d, "teacher_user_id", True)
    if not teaches(tid, kid["batch_id"]):
        raise ApiError("This teacher does not teach your child", 403)
    pref = iso(d.get("preferred_date"), "preferred_date", False) or None
    if pref and pref < today():
        raise ApiError("Preferred date cannot be in the past")
    rid = db.ex("INSERT INTO meeting_requests(student_id,parent_user_id,teacher_user_id,reason,preferred_date) "
                "VALUES(?,?,?,?,?)", (kid["id"], u["id"], tid, text(d, "reason", True, 500), pref))
    notify([tid], "Meeting request", f"{u['name']} wants to meet you about {kid['name']}.", "ptm")
    return jsonify(id=rid), 201


@api.post("/meeting-requests/<int:rid>/respond")
@roles("teacher")
def respond_request(rid):
    u, d = me(), body()
    r = db.q1("SELECT * FROM meeting_requests WHERE id=?", (rid,))
    if not r or r["teacher_user_id"] != u["id"]:
        raise ApiError("Not found", 404)
    if r["status"] not in ("pending", "accepted"):
        raise ApiError("This request is already closed", 409)
    action = choice(d.get("action"), ("accept", "decline", "done"), "action")
    note = text(d, "note", False, 300)
    if action == "accept":
        on = iso(d.get("meet_on"), "meet_on")
        if on < today():
            raise ApiError("Meeting date cannot be in the past")
        db.ex("UPDATE meeting_requests SET status='accepted', meet_on=?, meet_time=?, teacher_note=? WHERE id=?",
              (on, hhmm(d.get("meet_time"), "meet_time"), note, rid))
        msg = f"Your meeting is set for {on} at {d.get('meet_time')}. {note}"
    elif action == "decline":
        db.ex("UPDATE meeting_requests SET status='declined', teacher_note=? WHERE id=?", (note, rid))
        msg = f"Teacher could not accept the request. {note}"
    else:
        db.ex("UPDATE meeting_requests SET status='done', teacher_note=COALESCE(NULLIF(?, ''), teacher_note) "
              "WHERE id=?", (note, rid))
        msg = "Meeting marked as done."
    notify([r["parent_user_id"]], "Meeting request update", msg.strip(), "ptm")
    return jsonify(ok=True)


# ------------------------------------------------------------ messages ----
def _thread_access(u: dict, sid: int, tid: int) -> dict:
    s = db.q1("SELECT s.*, x.name FROM students s JOIN users x ON x.id=s.user_id WHERE s.id=?", (sid,))
    if not s:
        raise ApiError("Student not found", 404)
    if u["role"] == "teacher":
        if u["id"] != tid or not teaches(u["id"], s["batch_id"]):
            raise ApiError("Not allowed", 403)
    elif u["role"] in ("parent", "student"):
        student_or_403(u, sid)
        if not teaches(tid, s["batch_id"]):
            raise ApiError("This teacher does not teach this student", 403)
    else:
        raise ApiError("Office staff cannot read private parent-teacher chats", 403)
    return s


@api.get("/messages/threads")
@roles("parent", "student", "teacher")
def threads():
    u = me()
    if u["role"] == "teacher":
        rows = db.q("SELECT m.student_id, x.name AS student, m.teacher_user_id, MAX(m.id) AS last_id, "
                    "SUM(m.is_read=0 AND m.sender_user_id<>?1) AS unread FROM messages m "
                    "JOIN students s ON s.id=m.student_id JOIN users x ON x.id=s.user_id "
                    "WHERE m.teacher_user_id=?1 GROUP BY m.student_id ORDER BY last_id DESC", (u["id"],))
        for r in rows:
            r["teacher"] = u["name"]
    else:
        rows = []
        for kid in my_children(u):
            for t in db.q("SELECT DISTINCT bs.teacher_user_id, tu.name AS teacher, sub.name AS subject "
                          "FROM batch_subjects bs JOIN users tu ON tu.id=bs.teacher_user_id "
                          "JOIN subjects sub ON sub.id=bs.subject_id WHERE bs.batch_id=? AND tu.active=1 "
                          "ORDER BY tu.name", (kid["batch_id"],)):
                last = db.q1("SELECT MAX(id) AS i, SUM(is_read=0 AND sender_user_id<>?) AS un FROM messages "
                             "WHERE student_id=? AND teacher_user_id=?", (u["id"], kid["id"], t["teacher_user_id"]))
                rows.append({"student_id": kid["id"], "student": kid["name"], "teacher_user_id": t["teacher_user_id"],
                             "teacher": t["teacher"], "subject": t["subject"], "last_id": last["i"],
                             "unread": last["un"] or 0})
        rows.sort(key=lambda r: -(r["last_id"] or 0))
    for r in rows:
        r["unread"] = r["unread"] or 0
        m = db.q1("SELECT body, created_at FROM messages WHERE id=?", (r["last_id"],)) if r["last_id"] else None
        r["last_message"], r["last_at"] = (m["body"][:80], m["created_at"]) if m else (None, None)
    return jsonify(threads=rows)


@api.get("/messages")
@roles("parent", "student", "teacher")
def thread_messages():
    u = me()
    sid, tid = num(request.args, "student_id", True), num(request.args, "teacher_user_id", True)
    _thread_access(u, sid, tid)
    rows = db.q("SELECT m.id, m.body, m.created_at, m.sender_user_id, x.name AS sender, x.role AS sender_role "
                "FROM messages m JOIN users x ON x.id=m.sender_user_id WHERE m.student_id=? AND m.teacher_user_id=? "
                "ORDER BY m.id DESC LIMIT 200", (sid, tid))[::-1]
    db.ex("UPDATE messages SET is_read=1 WHERE student_id=? AND teacher_user_id=? AND sender_user_id<>?",
          (sid, tid, u["id"]))
    return jsonify(messages=rows, me=u["id"])


@api.post("/messages")
@roles("parent", "student", "teacher")
def send_message():
    u, d = me(), body()
    sid, tid = num(d, "student_id", True), num(d, "teacher_user_id", True)
    s = _thread_access(u, sid, tid)
    mid = db.ex("INSERT INTO messages(student_id,teacher_user_id,sender_user_id,body) VALUES(?,?,?,?)",
                (sid, tid, u["id"], text(d, "body", True, 1500)))
    if u["role"] == "teacher":
        notify(parent_users([sid]) + student_users([sid]), f"Message from {u['name']}", text(d, "body")[:80], "message")
    else:
        notify([tid], f"Message about {s['name']}", text(d, "body")[:80], "message")
    return jsonify(id=mid), 201


# ---------------------------------------------------------- complaints ----
CATEGORIES = ("academic", "fees", "facility", "teacher", "transport", "other")


@api.get("/complaints")
@roles("parent", "student", *STAFF)
def list_complaints():
    u = me()
    sql = ("SELECT c.*, p.name AS by_name, p.role AS by_role, x.name AS student, r.name AS responded_by_name "
           "FROM complaints c JOIN users p ON p.id=c.user_id LEFT JOIN students s ON s.id=c.student_id "
           "LEFT JOIN users x ON x.id=s.user_id LEFT JOIN users r ON r.id=c.responded_by")
    if u["role"] in STAFF:
        rows = db.q(sql + " ORDER BY c.status='resolved', c.id DESC LIMIT 300")
    else:
        rows = db.q(sql + " WHERE c.user_id=? ORDER BY c.id DESC LIMIT 100", (u["id"],))
    return jsonify(complaints=rows, categories=CATEGORIES)


@api.post("/complaints")
@roles("parent", "student")
def add_complaint():
    u, d = me(), body()
    kid = pick_student(u, d.get("student_id"))
    cid = db.ex("INSERT INTO complaints(user_id,student_id,category,body) VALUES(?,?,?,?)",
                (u["id"], kid["id"], choice(d.get("category"), CATEGORIES, "category"), text(d, "body", True, 2000)))
    notify([r["id"] for r in db.q("SELECT id FROM users WHERE role IN ('admin','superadmin') AND active=1")],
           "New complaint / suggestion", f"{u['name']} ({d.get('category')}).", "complaint")
    return jsonify(id=cid), 201


@api.post("/complaints/<int:cid>/respond")
@roles(*STAFF)
def respond_complaint(cid):
    u, d = me(), body()
    c = db.q1("SELECT * FROM complaints WHERE id=?", (cid,))
    if not c:
        raise ApiError("Not found", 404)
    status = choice(d.get("status"), ("in_progress", "resolved"), "status")
    db.ex("UPDATE complaints SET status=?, response=?, responded_by=? WHERE id=?",
          (status, text(d, "response", status == "resolved", 2000), u["id"], cid))
    notify([c["user_id"]], f"Your complaint is {status.replace('_', ' ')}", text(d, "response")[:100], "complaint")
    audit("complaint", f"{cid} {status}")
    return jsonify(ok=True)


# ------------------------------------------------- remarks & report card --
@api.get("/students/<int:sid>/remarks")
@roles()
def get_remarks(sid):
    s = student_or_403(me(), sid)
    return jsonify(remarks=db.q("SELECT r.id, r.kind, r.body, r.created_at, u.name AS teacher FROM student_remarks r "
                                "JOIN users u ON u.id=r.teacher_user_id WHERE r.student_id=? ORDER BY r.id DESC LIMIT 50",
                                (s["id"],)))


@api.post("/students/<int:sid>/remarks")
@roles("teacher")
def add_remark(sid):
    u, d = me(), body()
    s = student_or_403(u, sid)
    if not teaches(u["id"], s["batch_id"]):
        raise ApiError("You do not teach this student", 403)
    kind = choice(d.get("kind") or "general", ("praise", "concern", "general"), "kind")
    rid = db.ex("INSERT INTO student_remarks(student_id,teacher_user_id,kind,body) VALUES(?,?,?,?)",
                (s["id"], u["id"], kind, text(d, "body", True, 600)))
    notify(parent_users([s["id"]]), f"Teacher remark for {s['name']}", text(d, "body")[:100], "remark")
    return jsonify(id=rid), 201


@api.get("/students/<int:sid>/report")
@roles()
def report_card(sid):
    u = me()
    s = student_or_403(u, sid)
    fam = u["role"] in ("student", "parent")
    tests = db.q("SELECT t.id, t.name, t.date, t.max_marks, sub.name AS subject, m.marks FROM test_marks m "
                 "JOIN tests t ON t.id=m.test_id LEFT JOIN subjects sub ON sub.id=t.subject_id "
                 "WHERE m.student_id=? AND m.marks IS NOT NULL" + (" AND t.published=1" if fam else "") +
                 " ORDER BY t.date", (s["id"],))
    by_subject: dict[str, list[float]] = {}
    for t in tests:
        t["percent"] = round(100 * t["marks"] / t["max_marks"], 1)
        by_subject.setdefault(t["subject"] or "General", []).append(t["percent"])
    att = db.q1("SELECT COUNT(*) AS n, SUM(status='P') AS p, SUM(status='A') AS a, SUM(status='L') AS l "
                "FROM attendance WHERE student_id=?", (s["id"],))
    avg = round(sum(t["percent"] for t in tests) / len(tests), 1) if tests else None
    batch = db.q1("SELECT name FROM batches WHERE id=?", (s["batch_id"],))
    return jsonify(
        institute=db.setting("institute_name", "Tagore Career Institute"),
        student={"name": s["name"], "roll": s["login_id"], "batch": batch and batch["name"],
                 "father_name": s["father_name"]},
        attendance={"days": att["n"], "present": att["p"] or 0, "absent": att["a"] or 0, "leave": att["l"] or 0,
                    "percent": round(100 * (att["p"] or 0) / att["n"], 1) if att["n"] else None},
        tests=tests, average_percent=avg,
        subjects=[{"subject": k, "average": round(sum(v) / len(v), 1), "tests": len(v)} for k, v in sorted(by_subject.items())],
        remarks=db.q("SELECT r.kind, r.body, r.created_at, u.name AS teacher FROM student_remarks r "
                     "JOIN users u ON u.id=r.teacher_user_id WHERE r.student_id=? ORDER BY r.id DESC LIMIT 10",
                     (s["id"],)),
        generated_on=today())
