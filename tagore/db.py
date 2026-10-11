"""SQLite storage for the Tagore Career Institute ecosystem."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  role TEXT NOT NULL CHECK(role IN ('student','parent','teacher','admin','superadmin')),
  login_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  phone TEXT, email TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  must_change INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS teachers(
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  subject TEXT, qualification TEXT, experience_years INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS batches(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE, course TEXT, session TEXT,
  start_date TEXT, fee_total INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);

CREATE TABLE IF NOT EXISTS batch_subjects(
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  subject_id INTEGER NOT NULL REFERENCES subjects(id),
  teacher_user_id INTEGER REFERENCES users(id),
  PRIMARY KEY(batch_id, subject_id)
);

CREATE TABLE IF NOT EXISTS students(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  batch_id INTEGER REFERENCES batches(id),
  father_name TEXT, mother_name TEXT, dob TEXT, address TEXT, school TEXT,
  admission_date TEXT NOT NULL DEFAULT (date('now')),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','left'))
);

CREATE TABLE IF NOT EXISTS parent_students(
  parent_user_id INTEGER NOT NULL REFERENCES users(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  relation TEXT DEFAULT 'Parent',
  PRIMARY KEY(parent_user_id, student_id)
);

CREATE TABLE IF NOT EXISTS timetable(
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  subject_id INTEGER NOT NULL REFERENCES subjects(id),
  weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
  start_time TEXT NOT NULL, end_time TEXT NOT NULL, room TEXT
);

CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id),
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('P','A','L')),
  marked_by INTEGER REFERENCES users(id),
  UNIQUE(student_id, date)
);

CREATE TABLE IF NOT EXISTS homework(
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  subject_id INTEGER REFERENCES subjects(id),
  title TEXT NOT NULL, description TEXT, due_date TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS materials(
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  subject_id INTEGER REFERENCES subjects(id),
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('note','video','dpp','pdf','link')),
  url TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tests(
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  subject_id INTEGER REFERENCES subjects(id),
  name TEXT NOT NULL, date TEXT NOT NULL,
  max_marks INTEGER NOT NULL DEFAULT 100,
  mode TEXT NOT NULL DEFAULT 'offline' CHECK(mode IN ('offline','online')),
  duration_min INTEGER NOT NULL DEFAULT 60,
  published INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS test_marks(
  test_id INTEGER NOT NULL REFERENCES tests(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  marks REAL, absent INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(test_id, student_id)
);

CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY,
  test_id INTEGER NOT NULL REFERENCES tests(id),
  text TEXT NOT NULL,
  opt_a TEXT NOT NULL, opt_b TEXT NOT NULL, opt_c TEXT, opt_d TEXT,
  answer TEXT NOT NULL CHECK(answer IN ('A','B','C','D')),
  marks REAL NOT NULL DEFAULT 4, neg REAL NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS attempts(
  id INTEGER PRIMARY KEY,
  test_id INTEGER NOT NULL REFERENCES tests(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  started_at TEXT NOT NULL, submitted_at TEXT,
  answers TEXT, score REAL, late INTEGER NOT NULL DEFAULT 0,
  UNIQUE(test_id, student_id)
);

CREATE TABLE IF NOT EXISTS doubts(
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id),
  subject_id INTEGER REFERENCES subjects(id),
  question TEXT NOT NULL, answer TEXT,
  answered_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')), answered_at TEXT
);

CREATE TABLE IF NOT EXISTS notices(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL, body TEXT,
  audience TEXT NOT NULL DEFAULT 'all' CHECK(audience IN ('all','students','parents','teachers','staff')),
  batch_id INTEGER REFERENCES batches(id),
  pinned INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL, body TEXT, kind TEXT DEFAULT 'info',
  is_read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id, is_read);

CREATE TABLE IF NOT EXISTS ptm_events(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL, date TEXT NOT NULL,
  start_time TEXT NOT NULL, end_time TEXT NOT NULL, slot_minutes INTEGER NOT NULL,
  batch_id INTEGER REFERENCES batches(id), note TEXT,
  mode TEXT NOT NULL DEFAULT 'offline' CHECK(mode IN ('offline','online')),
  meeting_link TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ptm_slots(
  id INTEGER PRIMARY KEY,
  ptm_id INTEGER NOT NULL REFERENCES ptm_events(id),
  teacher_user_id INTEGER NOT NULL REFERENCES users(id),
  slot_time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','booked','done')),
  student_id INTEGER REFERENCES students(id),
  booked_by INTEGER REFERENCES users(id),
  remarks TEXT, feedback_rating INTEGER, feedback_text TEXT,
  parent_attended INTEGER,
  reminded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meeting_requests(
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id),
  parent_user_id INTEGER NOT NULL REFERENCES users(id),
  teacher_user_id INTEGER NOT NULL REFERENCES users(id),
  reason TEXT NOT NULL, preferred_date TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','declined','done')),
  meet_on TEXT, meet_time TEXT, teacher_note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id),
  teacher_user_id INTEGER NOT NULL REFERENCES users(id),
  sender_user_id INTEGER NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_msg_thread ON messages(student_id, teacher_user_id);

CREATE TABLE IF NOT EXISTS complaints(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  student_id INTEGER REFERENCES students(id),
  category TEXT NOT NULL CHECK(category IN ('academic','fees','facility','teacher','transport','other')),
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','resolved')),
  response TEXT, responded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS student_remarks(
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id),
  teacher_user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL CHECK(kind IN ('praise','concern','general')),
  body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leaves(
  id INTEGER PRIMARY KEY,
  applicant_user_id INTEGER NOT NULL REFERENCES users(id),
  student_id INTEGER REFERENCES students(id),
  from_date TEXT NOT NULL, to_date TEXT NOT NULL, reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
  decided_by INTEGER REFERENCES users(id), remark TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fees(
  id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id),
  title TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(amount > 0),
  discount INTEGER NOT NULL DEFAULT 0 CHECK(discount >= 0),
  due_date TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY,
  fee_id INTEGER NOT NULL REFERENCES fees(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  amount INTEGER NOT NULL CHECK(amount > 0),
  mode TEXT NOT NULL CHECK(mode IN ('cash','upi','card','cheque','bank')),
  ref TEXT, note TEXT, paid_on TEXT NOT NULL,
  receipt_no TEXT UNIQUE,
  received_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY,
  category TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
  date TEXT NOT NULL, vendor TEXT, note TEXT,
  added_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enquiries(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, phone TEXT NOT NULL, course TEXT, source TEXT,
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','contacted','visited','admitted','lost')),
  follow_up TEXT, notes TEXT,
  student_id INTEGER REFERENCES students(id),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY,
  user_id INTEGER, action TEXT NOT NULL, detail TEXT, ip TEXT,
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db(path: Path | str) -> None:
    con = connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def get() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def q(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in get().execute(sql, args).fetchall()]


def q1(sql: str, args=()) -> dict | None:
    r = get().execute(sql, args).fetchone()
    return dict(r) if r else None


def ex(sql: str, args=()) -> int:
    return get().execute(sql, args).lastrowid


def execmany(sql: str, rows) -> None:
    get().executemany(sql, rows)


def setting(key: str, default: str = "") -> str:
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default
