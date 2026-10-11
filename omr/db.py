"""SQLite storage. One file (omr.db) in the data folder - easy to back up."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, date TEXT DEFAULT '',
    template_id INTEGER, cfg TEXT NOT NULL DEFAULT '{}',
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS keys (
    exam_id INTEGER NOT NULL, set_code TEXT NOT NULL, key TEXT NOT NULL,
    PRIMARY KEY (exam_id, set_code)
);
CREATE TABLE IF NOT EXISTS sheets (
    id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL, batch TEXT DEFAULT '',
    file TEXT DEFAULT '', roll TEXT DEFAULT '', set_code TEXT DEFAULT '',
    answers TEXT NOT NULL DEFAULT '[]', flags TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '[]', qboxes TEXT NOT NULL DEFAULT '{}',
    preview TEXT DEFAULT '', ref_w INTEGER DEFAULT 0, ref_h INTEGER DEFAULT 0,
    reviewed INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS sheets_exam ON sheets(exam_id);
CREATE TABLE IF NOT EXISTS students (
    roll TEXT PRIMARY KEY, name TEXT DEFAULT '', batch TEXT DEFAULT ''
);
"""


def connect(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(data_dir) / "omr.db"), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def row_to_dict(row, json_fields=()):
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            d[f] = json.loads(d[f])
    return d
