"""Shared helpers: API blueprint, errors, validation, permissions, notifications."""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime
from functools import wraps

from flask import Blueprint, g, jsonify, request, session

from . import db

api = Blueprint("api", __name__, url_prefix="/api")
STAFF = ("admin", "superadmin")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters


class ApiError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.msg, self.code = msg, code


@api.errorhandler(ApiError)
def _api_error(e: ApiError):
    return jsonify(error=e.msg), e.code


# ---------------------------------------------------------------- auth ----
def me() -> dict | None:
    if "user" not in g:
        uid = session.get("uid")
        g.user = db.q1("SELECT * FROM users WHERE id=? AND active=1", (uid,)) if uid else None
    return g.user


def roles(*allowed: str):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            u = me()
            if not u:
                raise ApiError("Please login first", 401)
            if allowed and u["role"] not in allowed:
                raise ApiError("You are not allowed to do this", 403)
            return f(*a, **k)
        return wrapper
    return deco


def gen_password(n: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


# ---------------------------------------------------------- validation ----
def body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ApiError("JSON body required")
    return d


def text(d: dict, key: str, required: bool = False, maxlen: int = 500) -> str:
    v = d.get(key)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise ApiError(f"'{key}' is required")
    if len(v) > maxlen:
        raise ApiError(f"'{key}' is too long (max {maxlen})")
    return v


def num(d: dict, key: str, required: bool = False, lo=None, hi=None, default=None):
    v = d.get(key)
    if v in (None, ""):
        if required:
            raise ApiError(f"'{key}' is required")
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ApiError(f"'{key}' must be a number")
    if v != v or v in (float("inf"), float("-inf")):
        raise ApiError(f"'{key}' must be a number")
    if lo is not None and v < lo:
        raise ApiError(f"'{key}' must be at least {lo}")
    if hi is not None and v > hi:
        raise ApiError(f"'{key}' must be at most {hi}")
    return int(v) if v == int(v) else v


def iso(v, name: str = "date", required: bool = True) -> str:
    v = "" if v is None else str(v).strip()
    if not v:
        if required:
            raise ApiError(f"'{name}' is required")
        return ""
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ApiError(f"'{name}' must look like 2026-04-25")
    return v


def hhmm(v, name: str) -> str:
    v = str(v or "").strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ApiError(f"'{name}' must look like 14:30")
    return v


def url(v: str, name: str = "url") -> str:
    v = (v or "").strip()
    if not re.match(r"https?://[^\s]+$", v, re.I) or len(v) > 1000:
        raise ApiError(f"'{name}' must be a full http(s) link")
    return v


def choice(v, allowed, name: str):
    if v not in allowed:
        raise ApiError(f"'{name}' must be one of: {', '.join(map(str, allowed))}")
    return v


def phone10(v) -> str:
    digits = re.sub(r"\D", "", str(v or ""))[-10:]
    if len(digits) != 10:
        raise ApiError("Phone number must have 10 digits")
    return digits


def today() -> str:
    return date.today().isoformat()


def next_code(prefix: str, width: int) -> str:
    rows = db.q("SELECT login_id FROM users WHERE login_id LIKE ?", (prefix + "%",))
    best = 0
    for r in rows:
        tail = r["login_id"][len(prefix):]
        if tail.isdigit():
            best = max(best, int(tail))
    return f"{prefix}{best + 1:0{width}d}"


# ------------------------------------------------------- log / notify -----
def audit(action: str, detail: str = "") -> None:
    u = me()
    db.ex("INSERT INTO audit_log(user_id,action,detail,ip) VALUES(?,?,?,?)",
          (u["id"] if u else None, action, detail[:500], request.remote_addr))


def notify(user_ids, title: str, body_text: str = "", kind: str = "info") -> None:
    ids = {i for i in user_ids if i}
    if ids:
        db.execmany("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)",
                    [(i, title, body_text, kind) for i in ids])


def student_users(student_ids) -> list[int]:
    student_ids = list(student_ids)
    if not student_ids:
        return []
    ph = ",".join("?" * len(student_ids))
    return [r["user_id"] for r in db.q(f"SELECT user_id FROM students WHERE id IN ({ph})", student_ids)]


def parent_users(student_ids) -> list[int]:
    student_ids = list(student_ids)
    if not student_ids:
        return []
    ph = ",".join("?" * len(student_ids))
    return [r["parent_user_id"] for r in
            db.q(f"SELECT DISTINCT parent_user_id FROM parent_students WHERE student_id IN ({ph})", student_ids)]


def batch_student_ids(batch_id: int) -> list[int]:
    return [r["id"] for r in db.q("SELECT id FROM students WHERE batch_id=? AND status='active'", (batch_id,))]


def notify_batch(batch_id: int, title: str, body_text: str = "", kind: str = "info",
                 students: bool = True, parents: bool = True) -> None:
    ids = batch_student_ids(batch_id)
    to = (student_users(ids) if students else []) + (parent_users(ids) if parents else [])
    notify(to, title, body_text, kind)


# ------------------------------------------------------------ scoping -----
def my_children(u: dict) -> list[dict]:
    """Students visible to a student (self) or parent (children)."""
    if u["role"] == "student":
        return db.q("SELECT s.*, u.name, u.login_id FROM students s JOIN users u ON u.id=s.user_id "
                    "WHERE s.user_id=?", (u["id"],))
    if u["role"] == "parent":
        return db.q("SELECT s.*, u.name, u.login_id FROM parent_students ps "
                    "JOIN students s ON s.id=ps.student_id JOIN users u ON u.id=s.user_id "
                    "WHERE ps.parent_user_id=? ORDER BY u.name", (u["id"],))
    return []


def teacher_batch_ids(uid: int) -> list[int]:
    return [r["batch_id"] for r in
            db.q("SELECT DISTINCT batch_id FROM batch_subjects WHERE teacher_user_id=?", (uid,))]


def user_batch_ids(u: dict) -> list[int] | None:
    """Batches a user can see. None means all batches (staff)."""
    if u["role"] in STAFF:
        return None
    if u["role"] == "teacher":
        return teacher_batch_ids(u["id"])
    return sorted({c["batch_id"] for c in my_children(u) if c["batch_id"]})


def in_clause(ids: list[int]) -> str:
    return ",".join("?" * len(ids)) if ids else "NULL"


def can_manage_batch(u: dict, batch_id: int) -> bool:
    return u["role"] in STAFF or (u["role"] == "teacher" and batch_id in teacher_batch_ids(u["id"]))


def require_batch(u: dict, batch_id) -> int:
    try:
        batch_id = int(batch_id)
    except (TypeError, ValueError):
        raise ApiError("'batch_id' is required")
    if not db.q1("SELECT 1 FROM batches WHERE id=?", (batch_id,)):
        raise ApiError("Batch not found", 404)
    if not can_manage_batch(u, batch_id):
        raise ApiError("You do not teach this batch", 403)
    return batch_id


def student_or_403(u: dict, sid) -> dict:
    """Return the student row if this user may look at it, else raise."""
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        raise ApiError("Student not found", 404)
    s = db.q1("SELECT s.*, u.name, u.login_id, u.phone FROM students s JOIN users u ON u.id=s.user_id "
              "WHERE s.id=?", (sid,))
    if not s:
        raise ApiError("Student not found", 404)
    ok = (u["role"] in STAFF
          or (u["role"] == "student" and s["user_id"] == u["id"])
          or (u["role"] == "parent" and db.q1(
              "SELECT 1 FROM parent_students WHERE parent_user_id=? AND student_id=?", (u["id"], sid)))
          or (u["role"] == "teacher" and s["batch_id"] in teacher_batch_ids(u["id"])))
    if not ok:
        raise ApiError("You cannot see this student", 403)
    return s


def pick_student(u: dict, sid=None) -> dict:
    """For student/parent screens: the child being viewed (defaults to first)."""
    kids = my_children(u)
    if not kids:
        raise ApiError("No student linked to this account", 404)
    if sid in (None, ""):
        if len(kids) > 1:
            raise ApiError("Please choose which child (student_id)")
        return kids[0]
    for k in kids:
        if str(k["id"]) == str(sid):
            return k
    raise ApiError("You cannot see this student", 403)


def rank_rows(rows: list[dict], key: str = "marks") -> list[dict]:
    """Competition ranking (1,2,2,4). Absent / ungraded rows get no rank."""
    graded = sorted((r for r in rows if r.get(key) is not None), key=lambda r: -r[key])
    rank, prev = 0, None
    for i, r in enumerate(graded, 1):
        if r[key] != prev:
            rank, prev = i, r[key]
        r["rank"] = rank
    for r in rows:
        r.setdefault("rank", None)
    return rows
