"""Login, accounts, batches, teachers, students, timetable."""
from __future__ import annotations

import json
import time
from datetime import date

from flask import current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .core import (STAFF, ApiError, api, audit, body, choice, gen_password, hhmm, in_clause, iso, me, my_children,
                   next_code, num, phone10, roles, student_or_403, teacher_batch_ids, text)

# ------------------------------------------------------------- login ------
MAX_FAILS, WINDOW = 5, 600


def _fail_log() -> dict:
    """Wrong-password log, kept per app instance (in memory)."""
    return current_app.extensions.setdefault("login_fails", {})


def _locked(key) -> bool:
    now = time.time()
    fails = _fail_log()
    hits = [t for t in fails.get(key, []) if now - t < WINDOW]
    fails[key] = hits
    return len(hits) >= MAX_FAILS


def public_user(u: dict) -> dict:
    out = {k: u[k] for k in ("id", "role", "login_id", "name", "phone", "email", "must_change")}
    out["institute"] = db.setting("institute_name", "Tagore Career Institute")
    if u["role"] in ("student", "parent"):
        out["children"] = [{"id": c["id"], "name": c["name"], "login_id": c["login_id"],
                            "batch_id": c["batch_id"]} for c in my_children(u)]
    return out


@api.get("/public")
def public_info():
    """Shown on the login screen. Demo quick-logins appear only on a database filled by `run_tagore.py demo`."""
    demo = db.setting("demo_logins", "")
    return jsonify(institute=db.setting("institute_name", "Tagore Career Institute"),
                   demo=json.loads(demo) if demo else None)


@api.post("/login")
def login():
    d = body()
    lid, pw = text(d, "login_id", True, 60), str(d.get("password") or "")
    key = (lid.lower(), request.remote_addr)
    if _locked(key):
        raise ApiError("Too many wrong attempts. Try again after 10 minutes.", 429)
    u = db.q1("SELECT * FROM users WHERE login_id=?", (lid,))
    if not u or not u["active"] or not check_password_hash(u["password_hash"], pw):
        _fail_log().setdefault(key, []).append(time.time())
        raise ApiError("Wrong ID or password", 401)
    _fail_log().pop(key, None)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    g.user = u
    audit("login")
    from .routes_connect import send_ptm_reminders
    send_ptm_reminders()  # cheap + idempotent: keeps PTM reminders flowing without a scheduler
    return jsonify(user=public_user(u))


@api.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@api.get("/me")
@roles()
def whoami():
    return jsonify(user=public_user(me()))


@api.post("/change-password")
@roles()
def change_password():
    d, u = body(), me()
    new = str(d.get("new") or "")
    if len(new) < 8:
        raise ApiError("New password must have at least 8 characters")
    if not check_password_hash(u["password_hash"], str(d.get("old") or "")):
        raise ApiError("Old password is wrong", 400)
    db.ex("UPDATE users SET password_hash=?, must_change=0 WHERE id=?", (generate_password_hash(new), u["id"]))
    audit("change_password")
    return jsonify(ok=True)


# ------------------------------------------------------ staff accounts ----
@api.get("/users")
@roles("superadmin")
def list_users():
    rows = db.q("SELECT u.id,u.role,u.login_id,u.name,u.phone,u.email,u.active,t.subject,t.qualification "
                "FROM users u LEFT JOIN teachers t ON t.user_id=u.id "
                "WHERE u.role IN ('teacher','admin','superadmin') ORDER BY u.role, u.name")
    return jsonify(users=rows)


@api.post("/users")
@roles("superadmin")
def create_staff():
    d = body()
    role = choice(d.get("role"), ("teacher", "admin", "superadmin"), "role")
    name = text(d, "name", True, 80)
    prefix = {"teacher": "TCI-T", "admin": "TCI-A", "superadmin": "TCI-D"}[role]
    login_id = text(d, "login_id", False, 40) or next_code(prefix, 3)
    if db.q1("SELECT 1 FROM users WHERE login_id=?", (login_id,)):
        raise ApiError("This login ID already exists", 409)
    pw = gen_password()
    phone = phone10(d["phone"]) if d.get("phone") else None
    uid = db.ex("INSERT INTO users(role,login_id,password_hash,name,phone,email,must_change) VALUES(?,?,?,?,?,?,1)",
                (role, login_id, generate_password_hash(pw), name, phone, text(d, "email", False, 120) or None))
    if role == "teacher":
        db.ex("INSERT INTO teachers(user_id,subject,qualification,experience_years) VALUES(?,?,?,?)",
              (uid, text(d, "subject", False, 60), text(d, "qualification", False, 100),
               num(d, "experience_years", False, 0, 60, 0)))
    audit("create_user", f"{role} {login_id}")
    return jsonify(id=uid, login_id=login_id, temp_password=pw), 201


@api.post("/users/<int:uid>/reset-password")
@roles("admin", "superadmin")
def reset_password(uid):
    target, actor = db.q1("SELECT * FROM users WHERE id=?", (uid,)), me()
    if not target:
        raise ApiError("User not found", 404)
    allowed = ("student", "parent") if actor["role"] == "admin" else ("student", "parent", "teacher", "admin")
    if target["role"] not in allowed or target["id"] == actor["id"]:
        raise ApiError("You cannot reset this account's password", 403)
    pw = gen_password()
    db.ex("UPDATE users SET password_hash=?, must_change=1 WHERE id=?", (generate_password_hash(pw), uid))
    audit("reset_password", target["login_id"])
    return jsonify(login_id=target["login_id"], temp_password=pw)


@api.post("/users/<int:uid>/active")
@roles("superadmin")
def set_active(uid):
    d, actor = body(), me()
    target = db.q1("SELECT * FROM users WHERE id=?", (uid,))
    if not target:
        raise ApiError("User not found", 404)
    if target["id"] == actor["id"]:
        raise ApiError("You cannot deactivate yourself")
    db.ex("UPDATE users SET active=? WHERE id=?", (1 if d.get("active") else 0, uid))
    audit("set_active", f"{target['login_id']} -> {bool(d.get('active'))}")
    return jsonify(ok=True)


@api.get("/audit")
@roles("superadmin")
def audit_log():
    rows = db.q("SELECT a.id,a.action,a.detail,a.ip,a.at,u.name,u.role FROM audit_log a "
                "LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200")
    return jsonify(log=rows)


@api.get("/settings")
@roles()
def get_settings():
    return jsonify(institute_name=db.setting("institute_name", "Tagore Career Institute"),
                   address=db.setting("address", ""), phone=db.setting("phone", ""))


@api.post("/settings")
@roles("superadmin")
def put_settings():
    d = body()
    for k in ("institute_name", "address", "phone"):
        if k in d:
            db.ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (k, text(d, k, False, 200)))
    audit("settings")
    return jsonify(ok=True)


# ------------------------------------------------- batches & subjects -----
@api.get("/batches")
@roles()
def list_batches():
    u = me()
    ids = None
    if u["role"] not in STAFF:
        ids = teacher_batch_ids(u["id"]) if u["role"] == "teacher" else \
            sorted({c["batch_id"] for c in my_children(u) if c["batch_id"]})
    where = "" if ids is None else f"WHERE b.id IN ({in_clause(ids)})"
    rows = db.q(f"SELECT b.*, (SELECT COUNT(*) FROM students s WHERE s.batch_id=b.id AND s.status='active') AS students "
                f"FROM batches b {where} ORDER BY b.active DESC, b.name", ids or [])
    for b in rows:
        b["subjects"] = db.q("SELECT bs.subject_id, s.name AS subject, bs.teacher_user_id, u.name AS teacher "
                             "FROM batch_subjects bs JOIN subjects s ON s.id=bs.subject_id "
                             "LEFT JOIN users u ON u.id=bs.teacher_user_id WHERE bs.batch_id=? ORDER BY s.name",
                             (b["id"],))
    return jsonify(batches=rows)


@api.post("/batches")
@roles(*STAFF)
def create_batch():
    d = body()
    name = text(d, "name", True, 80)
    if db.q1("SELECT 1 FROM batches WHERE name=?", (name,)):
        raise ApiError("A batch with this name already exists", 409)
    bid = db.ex("INSERT INTO batches(name,course,session,start_date,fee_total) VALUES(?,?,?,?,?)",
                (name, text(d, "course", False, 60), text(d, "session", False, 20),
                 iso(d.get("start_date"), "start_date", False) or None, num(d, "fee_total", False, 0, 10 ** 8, 0)))
    audit("create_batch", name)
    return jsonify(id=bid), 201


@api.get("/subjects")
@roles()
def list_subjects():
    return jsonify(subjects=db.q("SELECT * FROM subjects ORDER BY name"))


@api.post("/subjects")
@roles(*STAFF)
def create_subject():
    name = text(body(), "name", True, 60)
    row = db.q1("SELECT id FROM subjects WHERE name=? COLLATE NOCASE", (name,))
    return jsonify(id=row["id"] if row else db.ex("INSERT INTO subjects(name) VALUES(?)", (name,))), 201


@api.post("/batches/<int:bid>/assign")
@roles(*STAFF)
def assign_teacher(bid):
    d = body()
    if not db.q1("SELECT 1 FROM batches WHERE id=?", (bid,)):
        raise ApiError("Batch not found", 404)
    sid = num(d, "subject_id", True)
    tid = num(d, "teacher_user_id", False)
    if not db.q1("SELECT 1 FROM subjects WHERE id=?", (sid,)):
        raise ApiError("Subject not found", 404)
    if tid and not db.q1("SELECT 1 FROM users WHERE id=? AND role='teacher' AND active=1", (tid,)):
        raise ApiError("Teacher not found", 404)
    db.ex("INSERT INTO batch_subjects(batch_id,subject_id,teacher_user_id) VALUES(?,?,?) "
          "ON CONFLICT(batch_id,subject_id) DO UPDATE SET teacher_user_id=excluded.teacher_user_id",
          (bid, sid, tid or None))
    audit("assign_teacher", f"batch {bid} subject {sid} teacher {tid}")
    return jsonify(ok=True)


@api.get("/teachers")
@roles("teacher", *STAFF)
def list_teachers():
    rows = db.q("SELECT u.id, u.name, u.login_id, u.phone, u.active, t.subject, t.qualification, t.experience_years "
                "FROM users u LEFT JOIN teachers t ON t.user_id=u.id WHERE u.role='teacher' ORDER BY u.name")
    for t in rows:
        t["batches"] = [r["name"] for r in db.q(
            "SELECT DISTINCT b.name FROM batch_subjects bs JOIN batches b ON b.id=bs.batch_id "
            "WHERE bs.teacher_user_id=?", (t["id"],))]
    return jsonify(teachers=rows)


# ------------------------------------------------------------ students ----
def create_student(d: dict, creator_id: int | None) -> dict:
    """Create student login (+ parent login). Returns one-time credentials."""
    name = text(d, "name", True, 80)
    batch_id = num(d, "batch_id", True)
    if not db.q1("SELECT 1 FROM batches WHERE id=? AND active=1", (batch_id,)):
        raise ApiError("Batch not found", 404)
    login_id = next_code(f"TCI{date.today().strftime('%y')}S", 4)
    pw = gen_password()
    phone = phone10(d["phone"]) if d.get("phone") else None
    uid = db.ex("INSERT INTO users(role,login_id,password_hash,name,phone,must_change) VALUES('student',?,?,?,?,1)",
                (login_id, generate_password_hash(pw), name, phone))
    sid = db.ex("INSERT INTO students(user_id,batch_id,father_name,mother_name,dob,address,school) "
                "VALUES(?,?,?,?,?,?,?)",
                (uid, batch_id, text(d, "father_name", False, 80), text(d, "mother_name", False, 80),
                 iso(d.get("dob"), "dob", False) or None, text(d, "address", False, 300),
                 text(d, "school", False, 120)))
    out = {"student_id": sid, "student": {"login_id": login_id, "temp_password": pw}, "parent": None}
    if d.get("parent_phone"):
        pphone = phone10(d["parent_phone"])
        parent = db.q1("SELECT * FROM users WHERE login_id=? AND role='parent'", (pphone,))
        if parent:
            out["parent"] = {"login_id": pphone, "temp_password": None, "existing": True}
        else:
            if db.q1("SELECT 1 FROM users WHERE login_id=?", (pphone,)):
                raise ApiError("This phone is already used by a non-parent login", 409)
            ppw = gen_password()
            pid = db.ex("INSERT INTO users(role,login_id,password_hash,name,phone,must_change) "
                        "VALUES('parent',?,?,?,?,1)",
                        (pphone, generate_password_hash(ppw),
                         text(d, "parent_name", False, 80) or text(d, "father_name", False, 80) or f"Parent of {name}",
                         pphone))
            parent = {"id": pid}
            out["parent"] = {"login_id": pphone, "temp_password": ppw, "existing": False}
        db.ex("INSERT OR IGNORE INTO parent_students(parent_user_id,student_id,relation) VALUES(?,?,?)",
              (parent["id"], sid, text(d, "relation", False, 20) or "Parent"))
    for f in d.get("fees") or []:
        db.ex("INSERT INTO fees(student_id,title,amount,due_date,created_by) VALUES(?,?,?,?,?)",
              (sid, text(f, "title", True, 80), num(f, "amount", True, 1, 10 ** 8),
               iso(f.get("due_date"), "due_date"), creator_id))
    return out


@api.get("/students")
@roles("teacher", *STAFF)
def list_students():
    u = me()
    where, args = ["1=1"], []
    if u["role"] == "teacher":
        ids = teacher_batch_ids(u["id"])
        where.append(f"s.batch_id IN ({in_clause(ids)})")
        args += ids
    if request.args.get("batch_id"):
        where.append("s.batch_id=?")
        args.append(request.args["batch_id"])
    if request.args.get("status") in ("active", "left"):
        where.append("s.status=?")
        args.append(request.args["status"])
    if request.args.get("q"):
        where.append("(u.name LIKE ? OR u.login_id LIKE ? OR u.phone LIKE ?)")
        args += [f"%{request.args['q']}%"] * 3
    rows = db.q(f"SELECT s.id, u.id AS user_id, u.name, u.login_id, u.phone, s.batch_id, b.name AS batch, "
                f"s.father_name, s.status, s.admission_date, "
                f"(SELECT group_concat(p.phone) FROM parent_students ps JOIN users p ON p.id=ps.parent_user_id "
                f" WHERE ps.student_id=s.id) AS parent_phone "
                f"FROM students s JOIN users u ON u.id=s.user_id LEFT JOIN batches b ON b.id=s.batch_id "
                f"WHERE {' AND '.join(where)} ORDER BY u.name LIMIT 1000", args)
    return jsonify(students=rows)


@api.post("/students")
@roles(*STAFF)
def add_student():
    out = create_student(body(), me()["id"])
    audit("admission", out["student"]["login_id"])
    return jsonify(out), 201


@api.get("/students/<int:sid>")
@roles()
def student_profile(sid):
    s = student_or_403(me(), sid)
    s["batch"] = (db.q1("SELECT name FROM batches WHERE id=?", (s["batch_id"],)) or {}).get("name")
    s["parents"] = db.q("SELECT u.name, u.phone, ps.relation FROM parent_students ps "
                        "JOIN users u ON u.id=ps.parent_user_id WHERE ps.student_id=?", (sid,))
    return jsonify(student=s)


@api.put("/students/<int:sid>")
@roles(*STAFF)
def edit_student(sid):
    d = body()
    s = student_or_403(me(), sid)
    if d.get("name"):
        db.ex("UPDATE users SET name=? WHERE id=?", (text(d, "name", True, 80), s["user_id"]))
    if d.get("phone"):
        db.ex("UPDATE users SET phone=? WHERE id=?", (phone10(d["phone"]), s["user_id"]))
    fields = {"father_name": 80, "mother_name": 80, "address": 300, "school": 120}
    sets, args = [], []
    for k, ml in fields.items():
        if k in d:
            sets.append(f"{k}=?")
            args.append(text(d, k, False, ml))
    if d.get("dob"):
        sets.append("dob=?")
        args.append(iso(d["dob"], "dob"))
    if d.get("batch_id"):
        if not db.q1("SELECT 1 FROM batches WHERE id=?", (num(d, "batch_id", True),)):
            raise ApiError("Batch not found", 404)
        sets.append("batch_id=?")
        args.append(int(d["batch_id"]))
    if d.get("status"):
        sets.append("status=?")
        args.append(choice(d["status"], ("active", "left"), "status"))
        if d["status"] == "left":
            db.ex("UPDATE users SET active=0 WHERE id=?", (s["user_id"],))
        else:
            db.ex("UPDATE users SET active=1 WHERE id=?", (s["user_id"],))
    if sets:
        db.ex(f"UPDATE students SET {','.join(sets)} WHERE id=?", args + [sid])
    audit("edit_student", s["login_id"])
    return jsonify(ok=True)


# ----------------------------------------------------------- timetable ----
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@api.get("/timetable")
@roles()
def timetable():
    u = me()
    sql = ("SELECT t.id, t.batch_id, b.name AS batch, t.subject_id, s.name AS subject, t.weekday, t.start_time, "
           "t.end_time, t.room, tu.name AS teacher, bs.teacher_user_id FROM timetable t "
           "JOIN batches b ON b.id=t.batch_id JOIN subjects s ON s.id=t.subject_id "
           "LEFT JOIN batch_subjects bs ON bs.batch_id=t.batch_id AND bs.subject_id=t.subject_id "
           "LEFT JOIN users tu ON tu.id=bs.teacher_user_id")
    where, args = [], []
    if u["role"] == "teacher":
        where.append("bs.teacher_user_id=?")
        args.append(u["id"])
    elif u["role"] in ("student", "parent"):
        ids = sorted({c["batch_id"] for c in my_children(u) if c["batch_id"]})
        if request.args.get("student_id"):
            kid = next((c for c in my_children(u) if str(c["id"]) == request.args["student_id"]), None)
            if not kid:
                raise ApiError("You cannot see this student", 403)
            ids = [kid["batch_id"]]
        where.append(f"t.batch_id IN ({in_clause(ids)})")
        args += ids
    if request.args.get("batch_id") and u["role"] in STAFF:
        where.append("t.batch_id=?")
        args.append(request.args["batch_id"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = db.q(sql + " ORDER BY t.weekday, t.start_time", args)
    return jsonify(timetable=rows, days=DAYS)


@api.post("/timetable")
@roles(*STAFF)
def add_lecture():
    d = body()
    bid, sid = num(d, "batch_id", True), num(d, "subject_id", True)
    if not db.q1("SELECT 1 FROM batch_subjects WHERE batch_id=? AND subject_id=?", (bid, sid)):
        raise ApiError("Assign this subject to the batch first")
    start, end = hhmm(d.get("start_time"), "start_time"), hhmm(d.get("end_time"), "end_time")
    if end <= start:
        raise ApiError("End time must be after start time")
    wd = num(d, "weekday", True, 0, 6)
    clash = db.q1("SELECT 1 FROM timetable WHERE batch_id=? AND weekday=? AND start_time<? AND end_time>?",
                  (bid, wd, end, start))
    if clash:
        raise ApiError("Another lecture of this batch overlaps this time", 409)
    tid = db.ex("INSERT INTO timetable(batch_id,subject_id,weekday,start_time,end_time,room) VALUES(?,?,?,?,?,?)",
                (bid, sid, wd, start, end, text(d, "room", False, 30)))
    return jsonify(id=tid), 201


@api.delete("/timetable/<int:tid>")
@roles(*STAFF)
def del_lecture(tid):
    db.ex("DELETE FROM timetable WHERE id=?", (tid,))
    return jsonify(ok=True)
