"""Notices, notifications, PTM (parent-teacher meeting) booking, leave requests."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import jsonify

from . import db
from .core import (STAFF, ApiError, api, audit, batch_student_ids, body, can_manage_batch, choice, hhmm, in_clause, iso,
                   me, my_children, notify, notify_batch, num, parent_users, pick_student, require_batch, roles,
                   teacher_batch_ids, text, today, url, user_batch_ids)

# ------------------------------------------------------------- notices ----
AUDIENCE_OF = {"student": "students", "parent": "parents", "teacher": "teachers", "admin": "staff",
               "superadmin": "staff"}


@api.get("/notices")
@roles()
def list_notices():
    u = me()
    sql = ("SELECT n.id, n.title, n.body, n.audience, n.batch_id, b.name AS batch, n.pinned, n.created_at, "
           "n.created_by, x.name AS author FROM notices n LEFT JOIN batches b ON b.id=n.batch_id "
           "LEFT JOIN users x ON x.id=n.created_by")
    if u["role"] in STAFF:
        rows = db.q(sql + " ORDER BY n.pinned DESC, n.id DESC LIMIT 100")
    else:
        ids = user_batch_ids(u) or []
        rows = db.q(sql + f" WHERE (n.audience='all' OR n.audience=?) AND (n.batch_id IS NULL OR n.batch_id IN "
                          f"({in_clause(ids)})) ORDER BY n.pinned DESC, n.id DESC LIMIT 100",
                    [AUDIENCE_OF[u["role"]]] + ids)
    return jsonify(notices=rows)


@api.post("/notices")
@roles("teacher", *STAFF)
def post_notice():
    d, u = body(), me()
    aud = choice(d.get("audience") or "all", ("all", "students", "parents", "teachers", "staff"), "audience")
    bid = num(d, "batch_id", False)
    if u["role"] == "teacher":
        if not bid or aud not in ("students", "parents"):
            raise ApiError("Teachers can post notices to students/parents of their own batch only", 403)
        require_batch(u, bid)
    elif bid and not db.q1("SELECT 1 FROM batches WHERE id=?", (bid,)):
        raise ApiError("Batch not found", 404)
    title = text(d, "title", True, 150)
    nid = db.ex("INSERT INTO notices(title,body,audience,batch_id,pinned,created_by) VALUES(?,?,?,?,?,?)",
                (title, text(d, "body", False, 4000), aud, bid, 1 if d.get("pinned") and u["role"] in STAFF else 0,
                 u["id"]))
    # push to everyone concerned
    if bid:
        notify_batch(bid, "Notice", title, "notice", students=aud in ("all", "students"),
                     parents=aud in ("all", "parents"))
    else:
        roles_ = {"all": ("student", "parent", "teacher", "admin", "superadmin"), "students": ("student",),
                  "parents": ("parent",), "teachers": ("teacher",), "staff": ("admin", "superadmin")}[aud]
        users = db.q(f"SELECT id FROM users WHERE active=1 AND role IN ({in_clause(list(roles_))})", list(roles_))
        notify([r["id"] for r in users if r["id"] != u["id"]], "Notice", title, "notice")
    audit("notice", title)
    return jsonify(id=nid), 201


@api.delete("/notices/<int:nid>")
@roles("teacher", *STAFF)
def del_notice(nid):
    u, n = me(), db.q1("SELECT * FROM notices WHERE id=?", (nid,))
    if not n:
        raise ApiError("Not found", 404)
    if u["role"] != "superadmin" and n["created_by"] != u["id"]:
        raise ApiError("Only the author or the director can delete this notice", 403)
    db.ex("DELETE FROM notices WHERE id=?", (nid,))
    return jsonify(ok=True)


# ------------------------------------------------------- notifications ----
@api.get("/notifications")
@roles()
def my_notifications():
    u = me()
    rows = db.q("SELECT id,title,body,kind,is_read,created_at FROM notifications WHERE user_id=? "
                "ORDER BY id DESC LIMIT 60", (u["id"],))
    unread = db.q1("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND is_read=0", (u["id"],))["n"]
    return jsonify(notifications=rows, unread=unread)


@api.post("/notifications/read")
@roles()
def read_notifications():
    u, ids = me(), body().get("ids")
    if isinstance(ids, list) and ids:
        ids = [int(i) for i in ids if str(i).isdigit()]
        db.ex(f"UPDATE notifications SET is_read=1 WHERE user_id=? AND id IN ({in_clause(ids)})", [u["id"]] + ids)
    else:
        db.ex("UPDATE notifications SET is_read=1 WHERE user_id=?", (u["id"],))
    return jsonify(ok=True)


# ----------------------------------------------------------------- PTM ----
def _slot_times(start: str, end: str, step: int) -> list[str]:
    t, stop = datetime.strptime(start, "%H:%M"), datetime.strptime(end, "%H:%M")
    out = []
    while t + timedelta(minutes=step) <= stop:
        out.append(t.strftime("%H:%M"))
        t += timedelta(minutes=step)
    return out


@api.post("/ptm")
@roles(*STAFF)
def create_ptm():
    d, u = body(), me()
    start, end = hhmm(d.get("start_time"), "start_time"), hhmm(d.get("end_time"), "end_time")
    step = num(d, "slot_minutes", True, 5, 60)
    times = _slot_times(start, end, step)
    if not times:
        raise ApiError("Time window is too short for even one slot")
    bid = num(d, "batch_id", False)
    if bid and not db.q1("SELECT 1 FROM batches WHERE id=?", (bid,)):
        raise ApiError("Batch not found", 404)
    tids = d.get("teacher_ids")
    if not tids:  # default: every teacher teaching that batch (or all teachers)
        sql = "SELECT DISTINCT teacher_user_id AS id FROM batch_subjects WHERE teacher_user_id IS NOT NULL"
        tids = [r["id"] for r in (db.q(sql + " AND batch_id=?", (bid,)) if bid else db.q(sql))]
    if not isinstance(tids, list) or not tids:
        raise ApiError("No teachers found for this PTM")
    ok = {r["id"] for r in db.q(f"SELECT id FROM users WHERE role='teacher' AND active=1 AND id IN ({in_clause(tids)})",
                               tids)}
    if set(tids) - ok:
        raise ApiError("Some teachers were not found")
    if len(times) * len(tids) > 600:
        raise ApiError("Too many slots; shorten the window or pick fewer teachers")
    mode = choice(d.get("mode") or "offline", ("offline", "online"), "mode")
    link = url(d.get("meeting_link"), "meeting_link") if mode == "online" else None
    pid = db.ex("INSERT INTO ptm_events(title,date,start_time,end_time,slot_minutes,batch_id,note,mode,meeting_link,"
                "created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (text(d, "title", True, 150), iso(d.get("date"), "date"), start, end, step, bid,
                 text(d, "note", False, 1000), mode, link, u["id"]))
    db.execmany("INSERT INTO ptm_slots(ptm_id,teacher_user_id,slot_time) VALUES(?,?,?)",
                [(pid, t, tm) for t in sorted(ok) for tm in times])
    ids = batch_student_ids(bid) if bid else [r["id"] for r in db.q("SELECT id FROM students WHERE status='active'")]
    notify(parent_users(ids) + sorted(ok), "PTM scheduled",
           f"{text(d, 'title', True)} on {d.get('date')}. Parents: open PTM and book your slot.", "ptm")
    audit("create_ptm", text(d, "title", True))
    return jsonify(id=pid, slots=len(times) * len(ok)), 201


@api.get("/ptm")
@roles()
def list_ptm():
    u = me()
    events = db.q("SELECT e.*, b.name AS batch FROM ptm_events e LEFT JOIN batches b ON b.id=e.batch_id "
                  "ORDER BY e.date DESC, e.id DESC LIMIT 30")
    kids = my_children(u) if u["role"] in ("student", "parent") else []
    kid_ids = {k["id"] for k in kids}
    kid_batches = {k["batch_id"] for k in kids}
    out = []
    for e in events:
        if u["role"] in ("student", "parent") and e["batch_id"] and e["batch_id"] not in kid_batches:
            continue
        slots = db.q("SELECT p.id, p.teacher_user_id, t.name AS teacher, tt.subject, p.slot_time, p.status, "
                     "p.student_id, p.booked_by, x.name AS student, p.remarks, p.feedback_rating, p.feedback_text "
                     "FROM ptm_slots p JOIN users t ON t.id=p.teacher_user_id "
                     "LEFT JOIN teachers tt ON tt.user_id=p.teacher_user_id "
                     "LEFT JOIN students s ON s.id=p.student_id LEFT JOIN users x ON x.id=s.user_id "
                     "WHERE p.ptm_id=? ORDER BY p.slot_time, t.name", (e["id"],))
        if u["role"] == "teacher":
            slots = [s for s in slots if s["teacher_user_id"] == u["id"]]
            if not slots:
                continue
            from .routes_connect import student_brief
            for s in slots:
                s["brief"] = student_brief(s["student_id"]) if s["student_id"] else None
        elif u["role"] in ("student", "parent"):
            my_teachers = {r["teacher_user_id"] for r in db.q(
                f"SELECT DISTINCT teacher_user_id FROM batch_subjects WHERE batch_id IN ({in_clause(list(kid_batches))})",
                list(kid_batches))}
            slots = [s for s in slots if s["teacher_user_id"] in my_teachers]
            for s in slots:
                s["mine"] = s["student_id"] in kid_ids
                if not s["mine"]:  # privacy: hide other families' details
                    s["student"] = s["remarks"] = s["feedback_text"] = s["student_id"] = s["booked_by"] = None
                    s["feedback_rating"] = None
        if u["role"] in ("student", "parent") and not any(s.get("mine") for s in slots):
            e["meeting_link"] = None  # the online link is shared only with families who booked
        e["slots"] = slots
        out.append(e)
    return jsonify(events=out, today=today())


def _slot(slot_id: int) -> dict:
    s = db.q1("SELECT p.*, e.date, e.title, e.batch_id AS event_batch FROM ptm_slots p "
              "JOIN ptm_events e ON e.id=p.ptm_id WHERE p.id=?", (slot_id,))
    if not s:
        raise ApiError("Slot not found", 404)
    return s


@api.post("/ptm/slots/<int:slot_id>/book")
@roles("parent")
def book_slot(slot_id):
    u, d = me(), body()
    s, kid = _slot(slot_id), pick_student(u, d.get("student_id"))
    if s["date"] < today():
        raise ApiError("This PTM is over")
    if s["event_batch"] and s["event_batch"] != kid["batch_id"]:
        raise ApiError("This PTM is not for your child's batch", 403)
    if not db.q1("SELECT 1 FROM batch_subjects WHERE batch_id=? AND teacher_user_id=?",
                 (kid["batch_id"], s["teacher_user_id"])):
        raise ApiError("This teacher does not teach your child", 403)
    if db.q1("SELECT 1 FROM ptm_slots WHERE ptm_id=? AND teacher_user_id=? AND student_id=?",
             (s["ptm_id"], s["teacher_user_id"], kid["id"])):
        raise ApiError("You already booked this teacher for this child", 409)
    if db.q1("SELECT 1 FROM ptm_slots WHERE ptm_id=? AND booked_by=? AND slot_time=?",
             (s["ptm_id"], u["id"], s["slot_time"])):
        raise ApiError("You already have another meeting at this time", 409)
    cur = db.get().execute("UPDATE ptm_slots SET status='booked', student_id=?, booked_by=? "
                           "WHERE id=? AND status='open'", (kid["id"], u["id"], slot_id))
    if cur.rowcount != 1:
        raise ApiError("Sorry, this slot was just taken. Pick another.", 409)
    notify([s["teacher_user_id"]], "PTM slot booked",
           f"{u['name']} booked {s['slot_time']} on {s['date']} for {kid['name']}.", "ptm")
    return jsonify(ok=True)


@api.post("/ptm/slots/<int:slot_id>/cancel")
@roles("parent", *STAFF)
def cancel_slot(slot_id):
    u, s = me(), _slot(slot_id)
    if s["status"] != "booked":
        raise ApiError("Only a booked slot can be cancelled", 409)
    if u["role"] == "parent" and s["booked_by"] != u["id"]:
        raise ApiError("This is not your booking", 403)
    db.ex("UPDATE ptm_slots SET status='open', student_id=NULL, booked_by=NULL WHERE id=?", (slot_id,))
    notify([s["teacher_user_id"]], "PTM booking cancelled", f"Slot {s['slot_time']} on {s['date']} is free again.", "ptm")
    return jsonify(ok=True)


@api.post("/ptm/slots/<int:slot_id>/remarks")
@roles("teacher")
def slot_remarks(slot_id):
    u, s = me(), _slot(slot_id)
    if s["teacher_user_id"] != u["id"]:
        raise ApiError("This is not your slot", 403)
    if s["status"] == "open":
        raise ApiError("Nobody booked this slot", 409)
    d = body()
    attended = d.get("attended")
    db.ex("UPDATE ptm_slots SET status='done', remarks=?, parent_attended=? WHERE id=?",
          (text(d, "remarks", True, 3000), None if attended is None else (1 if attended else 0), slot_id))
    notify([s["booked_by"]], "PTM remarks from teacher", "Your teacher added remarks about your meeting.", "ptm")
    return jsonify(ok=True)


@api.post("/ptm/slots/<int:slot_id>/feedback")
@roles("parent")
def slot_feedback(slot_id):
    u, d, s = me(), body(), _slot(slot_id)
    if s["booked_by"] != u["id"] or s["status"] != "done":
        raise ApiError("You can give feedback after the teacher completes your meeting", 403)
    db.ex("UPDATE ptm_slots SET feedback_rating=?, feedback_text=? WHERE id=?",
          (num(d, "rating", True, 1, 5), text(d, "text", False, 1000), slot_id))
    return jsonify(ok=True)


# -------------------------------------------------------------- leaves ----
@api.get("/leaves")
@roles()
def list_leaves():
    u = me()
    sql = ("SELECT l.*, a.name AS applicant, a.role AS applicant_role, x.name AS student, d.name AS decided_by_name "
           "FROM leaves l JOIN users a ON a.id=l.applicant_user_id LEFT JOIN students s ON s.id=l.student_id "
           "LEFT JOIN users x ON x.id=s.user_id LEFT JOIN users d ON d.id=l.decided_by")
    if u["role"] in STAFF:
        rows = db.q(sql + " ORDER BY l.status='pending' DESC, l.id DESC LIMIT 200")
    elif u["role"] == "teacher":
        ids = teacher_batch_ids(u["id"])
        rows = db.q(sql + f" WHERE l.applicant_user_id=? OR s.batch_id IN ({in_clause(ids)}) "
                          f"ORDER BY l.status='pending' DESC, l.id DESC LIMIT 200", [u["id"]] + ids)
    else:
        kids = [c["id"] for c in my_children(u)]
        rows = db.q(sql + f" WHERE l.applicant_user_id=? OR l.student_id IN ({in_clause(kids)}) "
                          f"ORDER BY l.id DESC LIMIT 100", [u["id"]] + kids)
    return jsonify(leaves=rows)


@api.post("/leaves")
@roles("student", "parent", "teacher")
def apply_leave():
    d, u = body(), me()
    f, t = iso(d.get("from_date"), "from_date"), iso(d.get("to_date") or d.get("from_date"), "to_date")
    if t < f:
        raise ApiError("'to_date' cannot be before 'from_date'")
    sid = None
    if u["role"] in ("student", "parent"):
        sid = pick_student(u, d.get("student_id"))["id"]
    lid = db.ex("INSERT INTO leaves(applicant_user_id,student_id,from_date,to_date,reason) VALUES(?,?,?,?,?)",
                (u["id"], sid, f, t, text(d, "reason", True, 500)))
    if sid:
        batch = db.q1("SELECT batch_id FROM students WHERE id=?", (sid,))["batch_id"]
        notify([r["teacher_user_id"] for r in db.q("SELECT teacher_user_id FROM batch_subjects WHERE batch_id=?",
                                                    (batch,))], "Leave request", f"{u['name']} applied for leave.",
               "leave")
    else:
        notify([r["id"] for r in db.q("SELECT id FROM users WHERE role IN ('admin','superadmin') AND active=1")],
               "Staff leave request", f"{u['name']} applied for leave.", "leave")
    return jsonify(id=lid), 201


@api.post("/leaves/<int:lid>/decide")
@roles("teacher", *STAFF)
def decide_leave(lid):
    u, d = me(), body()
    lv = db.q1("SELECT * FROM leaves WHERE id=?", (lid,))
    if not lv:
        raise ApiError("Not found", 404)
    if lv["status"] != "pending":
        raise ApiError("This request is already decided", 409)
    if lv["student_id"]:
        batch = db.q1("SELECT batch_id FROM students WHERE id=?", (lv["student_id"],))["batch_id"]
        if not can_manage_batch(u, batch):
            raise ApiError("Not allowed", 403)
    elif u["role"] not in STAFF:
        raise ApiError("Only the office can decide staff leave", 403)
    status = choice(d.get("status"), ("approved", "rejected"), "status")
    db.ex("UPDATE leaves SET status=?, decided_by=?, remark=? WHERE id=?",
          (status, u["id"], text(d, "remark", False, 300), lid))
    notify([lv["applicant_user_id"]], f"Leave {status}", text(d, "remark", False, 300), "leave")
    return jsonify(ok=True)
