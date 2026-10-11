"""Local web server behind the desktop window. Everything stays on this PC."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory

from . import db, engine, report, samplegen, scoring

REVIEW_KINDS = {"layout", "roll", "set", "batch", "faint", "ghost", "missing"}
FLAG_TEXT = {
    "layout": "Sheet layout not recognised (wrong sheet / cut page / bad scan)",
    "roll": "Roll number unreadable", "set": "Set code unreadable",
    "batch": "Batch code unreadable", "faint": "faint mark", "ghost": "possible erased mark",
    "missing": "bubble missing", "multiple": "multiple marks",
}
STATIC = Path(__file__).parent / "static"


def default_data_dir() -> Path:
    env = os.environ.get("OMR_DATA")
    return Path(env) if env else Path.home() / "OMR-Reader-Data"


def flag_kind(flag: str) -> str:
    m = re.match(r"q\d+:(\w+)", flag)
    return m.group(1) if m else flag.split(":")[0]


def norm_roll(r: str) -> str:
    r = (r or "").strip()
    return r.lstrip("0") or ("0" if r else "")


def create_app(data_dir: Path | str | None = None) -> Flask:
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    (data_dir / "previews").mkdir(parents=True, exist_ok=True)
    (data_dir / "sheets").mkdir(parents=True, exist_ok=True)
    db.connect(data_dir).close()

    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
    pool = ThreadPoolExecutor(max_workers=max(2, min(4, os.cpu_count() or 2)))

    def conn():
        return db.connect(data_dir)

    class ApiError(Exception):
        def __init__(self, msg, code=400):
            super().__init__(msg)
            self.code = code

    @app.errorhandler(ApiError)
    def _api_error(e):
        return jsonify(error=str(e)), e.code

    @app.errorhandler(Exception)
    def _any_error(e):  # pragma: no cover - last resort
        import traceback
        traceback.print_exc()
        code = getattr(e, "code", 500)
        return jsonify(error=f"{type(e).__name__}: {e}"), code if isinstance(code, int) else 500

    # ------------------------------------------------------------------ helpers
    def load_exam(c, exam_id):
        row = c.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
        if not row:
            raise ApiError("Exam not found", 404)
        exam = db.row_to_dict(row, ["cfg"])
        trow = c.execute("SELECT * FROM templates WHERE id=?", (exam["template_id"],)).fetchone()
        exam["template"] = json.loads(trow["data"]) if trow else None
        exam["template_name"] = trow["name"] if trow else ""
        exam["keys"] = {r["set_code"]: scoring.parse_key(r["key"])
                        for r in c.execute("SELECT * FROM keys WHERE exam_id=?", (exam_id,))}
        return exam

    def students_map(c):
        return {norm_roll(r["roll"]): dict(r) for r in c.execute("SELECT * FROM students")}

    def evaluate(sheet: dict, exam: dict, students: dict) -> dict:
        """Add score / status / readable flags to a sheet dict (never stored)."""
        keys = exam["keys"]
        code = sheet["set_code"]
        if not code and len(keys) == 1:
            code = next(iter(keys))
        key = keys.get(code)
        res = None
        warn = []
        if not sheet["answers"]:
            warn.append("Answers could not be read - open the sheet to fix")
        elif key is not None:
            res = scoring.score_sheet(sheet["answers"], key, exam["cfg"])
        elif keys:
            warn.append(f"No answer key for set '{sheet['set_code'] or '?'}'")
        elif sheet["answers"]:
            warn.append("Answer key not entered yet")
        kinds = [flag_kind(f) for f in sheet["flags"]]
        needs_review = (not sheet["reviewed"]) and any(k in REVIEW_KINDS for k in kinds)
        issues = []
        for kind in sorted(set(kinds)):
            n = kinds.count(kind)
            if kind in FLAG_TEXT and (kind in REVIEW_KINDS or kind == "multiple"):
                issues.append(f"{n} {FLAG_TEXT[kind]}" if kind in ("faint", "ghost", "missing", "multiple") else FLAG_TEXT[kind])
        st = students.get(norm_roll(sheet["roll"])) if sheet["roll"] and "_" not in sheet["roll"] and "*" not in sheet["roll"] else None
        return {
            "id": sheet["id"], "roll": sheet["roll"], "name": st["name"] if st else "",
            "batch": sheet["batch"] or (st["batch"] if st else ""), "set": sheet["set_code"],
            "file": sheet["file"], "needs_review": needs_review, "reviewed": bool(sheet["reviewed"]),
            "issues": issues, "warnings": warn, "result": res,
            "has_preview": bool(sheet["preview"]),
        }

    def sheets_for(c, exam_id):
        out = []
        for r in c.execute("SELECT * FROM sheets WHERE exam_id=? ORDER BY id", (exam_id,)):
            out.append(db.row_to_dict(r, ["answers", "flags", "notes", "qboxes"]))
        return out

    def evaluated_sheets(c, exam):
        studs = students_map(c)
        raw = sheets_for(c, exam["id"])
        rows = [evaluate(s, exam, studs) for s in raw]
        seen: dict[str, list] = {}
        for r in rows:
            if r["roll"] and "_" not in r["roll"] and "*" not in r["roll"]:
                seen.setdefault(norm_roll(r["roll"]), []).append(r)
        for group in seen.values():
            if len(group) > 1:
                for r in group:
                    r["duplicate"] = True
                    r["issues"].append("Duplicate roll number")
        scored = [r for r in rows if r["result"]]
        flat = []
        for r in scored:
            flat.append({"score": r["result"]["score"], "row": r})
        scoring.assign_ranks(flat)
        for f in flat:
            f["row"]["rank"] = f["rank"]
        return rows, raw

    # ------------------------------------------------------------- sheet reading
    def save_preview(img, sub="sheets") -> str:
        h, w = img.shape[:2]
        scale = 1100 / w
        small = cv2.resize(img, (1100, int(h * scale)), interpolation=cv2.INTER_AREA)
        name = f"{uuid.uuid4().hex}.jpg"
        cv2.imwrite(str(data_dir / sub / name), small, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return f"{sub}/{name}"

    def read_one(label, img, template):
        scan, reading = engine.read_with_retry(img, template)
        reading["file"] = label
        reading["ref_w"], reading["ref_h"] = scan.image.shape[1], scan.image.shape[0]
        reading["preview"] = save_preview(scan.image)
        return reading

    def insert_sheet(c, exam_id, reading, batch_default):
        c.execute(
            "INSERT INTO sheets (exam_id,batch,file,roll,set_code,answers,flags,notes,qboxes,preview,ref_w,ref_h,reviewed)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (exam_id, reading.get("batch") or batch_default, reading["file"], reading["roll"], reading["set"],
             json.dumps(reading["answers"]), json.dumps(reading["flags"]), json.dumps(reading["notes"]),
             json.dumps(reading["qboxes"]), reading["preview"], reading["ref_w"], reading["ref_h"]))

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/files/<path:name>")
    def files(name):
        return send_from_directory(data_dir, name)

    # --------------------------------------------------------------- templates
    @app.post("/api/detect")
    def detect():
        f = request.files.get("image")
        if not f:
            raise ApiError("Choose a scanned sheet image")
        data = f.read()
        labels = (request.form.get("labels") or "ABCD").strip().upper()
        rotation = int(request.form.get("rotation") or 0)
        token = request.form.get("token") or uuid.uuid4().hex
        pages = list(engine.iter_pages(f.filename or "x.jpg", data))
        if not pages:
            raise ApiError("Could not open this file as an image")
        img = pages[0][1]
        cv2.imwrite(str(data_dir / "previews" / f"{token}.src.png"), img)
        return detect_response(token, img, labels, rotation)

    def detect_response(token, img, labels, rotation):
        scan = engine.analyze(img, rotation, len(labels))
        cv2.imwrite(str(data_dir / "previews" / f"{token}.jpg"), scan.image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        blocks = [{"index": b.index, "x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1, "rows": b.rows,
                   "cols": b.cols, "type": b.kind, "orient": b.orient} for b in scan.blocks]
        return jsonify(token=token, width=scan.image.shape[1], height=scan.image.shape[0], blocks=blocks,
                       signature=scan.signature, error=scan.error, rotation=rotation, labels=labels,
                       image=f"/files/previews/{token}.jpg?t={uuid.uuid4().hex[:6]}")

    @app.post("/api/redetect")
    def redetect():
        body = request.get_json()
        src = data_dir / "previews" / f"{body['token']}.src.png"
        if not src.exists():
            raise ApiError("Upload the sample sheet again")
        img = cv2.imread(str(src))
        return detect_response(body["token"], img, (body.get("labels") or "ABCD").upper(), int(body.get("rotation") or 0))

    @app.post("/api/templates/test")
    def template_test():
        body = request.get_json()
        src = data_dir / "previews" / f"{body['token']}.src.png"
        if not src.exists():
            raise ApiError("Upload the sample sheet again")
        img = cv2.imread(str(src))
        tpl = body["template"]
        scan = engine.analyze(img, int(body.get("rotation") or 0), len(tpl.get("labels") or "ABCD"))
        tpl = {**tpl, "signature": scan.signature}
        reading = engine.read_sheet(scan, tpl)
        return jsonify(reading)

    @app.get("/api/templates")
    def templates_list():
        with conn() as c:
            rows = c.execute("SELECT id,name,data FROM templates ORDER BY id DESC").fetchall()
        return jsonify([{"id": r["id"], "name": r["name"], **json.loads(r["data"])} for r in rows])

    @app.post("/api/templates")
    def templates_save():
        body = request.get_json()
        name = (body.get("name") or "").strip()
        if not name:
            raise ApiError("Give the sheet type a name")
        data = {k: body[k] for k in ("labels", "sensitivity", "blocks", "signature") if k in body}
        with conn() as c:
            if body.get("id"):
                c.execute("UPDATE templates SET name=?, data=? WHERE id=?", (name, json.dumps(data), body["id"]))
                tid = body["id"]
            else:
                tid = c.execute("INSERT INTO templates (name,data) VALUES (?,?)", (name, json.dumps(data))).lastrowid
        return jsonify(id=tid)

    @app.delete("/api/templates/<int:tid>")
    def templates_delete(tid):
        with conn() as c:
            if c.execute("SELECT 1 FROM exams WHERE template_id=?", (tid,)).fetchone():
                raise ApiError("This sheet type is used by an exam")
            c.execute("DELETE FROM templates WHERE id=?", (tid,))
        return jsonify(ok=True)

    # ------------------------------------------------------------------- exams
    def exam_summary(c, row):
        n = c.execute("SELECT COUNT(*) FROM sheets WHERE exam_id=?", (row["id"],)).fetchone()[0]
        keys = [r["set_code"] for r in c.execute("SELECT set_code FROM keys WHERE exam_id=? ORDER BY set_code", (row["id"],))]
        return {"id": row["id"], "name": row["name"], "date": row["date"], "template_id": row["template_id"],
                "cfg": json.loads(row["cfg"]), "sheets": n, "key_sets": keys}

    @app.get("/api/exams")
    def exams_list():
        with conn() as c:
            return jsonify([exam_summary(c, r) for r in c.execute("SELECT * FROM exams ORDER BY id DESC")])

    def clean_cfg(body):
        cfg = {
            "correct": float(body.get("correct", 1)), "wrong": float(body.get("wrong", 0)),
            "multi": body.get("multi", "wrong"), "default_set": (body.get("default_set") or "A").upper(),
            "sections": body.get("sections") if isinstance(body.get("sections"), list)
            else scoring.parse_sections(body.get("sections_text", "")),
        }
        return cfg

    @app.post("/api/exams")
    def exams_save():
        body = request.get_json()
        name = (body.get("name") or "").strip()
        if not name:
            raise ApiError("Give the exam a name")
        if not body.get("template_id"):
            raise ApiError("Choose the sheet type (set it up in step 1)")
        cfg = json.dumps(clean_cfg(body))
        with conn() as c:
            if body.get("id"):
                c.execute("UPDATE exams SET name=?, date=?, template_id=?, cfg=? WHERE id=?",
                          (name, body.get("date", ""), body["template_id"], cfg, body["id"]))
                eid = body["id"]
            else:
                eid = c.execute("INSERT INTO exams (name,date,template_id,cfg) VALUES (?,?,?,?)",
                                (name, body.get("date", ""), body["template_id"], cfg)).lastrowid
        return jsonify(id=eid)

    @app.delete("/api/exams/<int:eid>")
    def exams_delete(eid):
        with conn() as c:
            c.execute("DELETE FROM sheets WHERE exam_id=?", (eid,))
            c.execute("DELETE FROM keys WHERE exam_id=?", (eid,))
            c.execute("DELETE FROM exams WHERE id=?", (eid,))
        return jsonify(ok=True)

    # -------------------------------------------------------------------- keys
    @app.get("/api/exams/<int:eid>/keys")
    def keys_get(eid):
        with conn() as c:
            rows = c.execute("SELECT set_code,key FROM keys WHERE exam_id=? ORDER BY set_code", (eid,)).fetchall()
        return jsonify([{"set": r["set_code"], "text": r["key"], "count": len(scoring.parse_key(r["key"]))} for r in rows])

    @app.put("/api/exams/<int:eid>/keys")
    def keys_put(eid):
        body = request.get_json()
        set_code = (body.get("set") or "A").strip().upper()[:3] or "A"
        tokens = scoring.parse_key(body.get("text", ""))
        if not tokens:
            raise ApiError("Answer key is empty")
        text = scoring.key_to_text(tokens)
        with conn() as c:
            exam = load_exam(c, eid)
            labels = (exam["template"] or {}).get("labels", "ABCD")
            bad = [i + 1 for i, t in enumerate(tokens) if t not in ("*", "-", "") and any(ch not in labels for ch in t)]
            c.execute("INSERT OR REPLACE INTO keys (exam_id,set_code,key) VALUES (?,?,?)", (eid, set_code, text))
        return jsonify(set=set_code, count=len(tokens), text=text, invalid=bad)

    @app.delete("/api/exams/<int:eid>/keys/<set_code>")
    def keys_delete(eid, set_code):
        with conn() as c:
            c.execute("DELETE FROM keys WHERE exam_id=? AND set_code=?", (eid, set_code))
        return jsonify(ok=True)

    @app.post("/api/exams/<int:eid>/key_from_sheet")
    def key_from_sheet(eid):
        f = request.files.get("image")
        if not f:
            raise ApiError("Choose the scanned master (answer key) sheet")
        with conn() as c:
            exam = load_exam(c, eid)
        pages = list(engine.iter_pages(f.filename or "x.jpg", f.read()))
        if not pages:
            raise ApiError("Could not open this file as an image")
        _, reading = engine.read_with_retry(pages[0][1], exam["template"])
        if "layout" in reading["flags"]:
            raise ApiError("This does not look like the same sheet type: " + "; ".join(reading["notes"]))
        key = reading["answers"]      # 2 marked options on a master sheet = either is accepted
        unclear = [i + 1 for i, a in enumerate(reading["answers"]) if a == ""]
        return jsonify(text=scoring.key_to_text(key), set=reading["set"], unclear=unclear,
                       multi=[i + 1 for i, a in enumerate(reading["answers"]) if len(a) > 1])

    # ------------------------------------------------------------------- scan
    @app.post("/api/exams/<int:eid>/scan")
    def scan_upload(eid):
        files_ = request.files.getlist("files")
        batch = (request.form.get("batch") or "").strip()
        with conn() as c:
            exam = load_exam(c, eid)
        if not exam["template"]:
            raise ApiError("This exam has no sheet type")
        template = exam["template"]
        jobs = []
        for f in files_:
            data = f.read()
            try:
                pages = list(engine.iter_pages(f.filename or "x", data))
            except Exception as e:  # corrupt pdf etc.
                pages = []
            if not pages:
                jobs.append((f.filename, None))
            for label, img in pages:
                jobs.append((label, img))
        results = list(pool.map(lambda j: (j[0], None) if j[1] is None else (j[0], read_one(j[0], j[1], template)), jobs))
        out = []
        with conn() as c:
            for label, reading in results:
                if reading is None:
                    out.append({"file": label, "error": "Could not open this file"})
                    continue
                insert_sheet(c, eid, reading, batch)
                out.append({"file": label, "roll": reading["roll"], "flags": len(reading["flags"])})
        return jsonify(done=out)

    # ---------------------------------------------------------------- results
    @app.get("/api/exams/<int:eid>/sheets")
    def sheets_list(eid):
        with conn() as c:
            exam = load_exam(c, eid)
            rows, _ = evaluated_sheets(c, exam)
        return jsonify(rows)

    @app.get("/api/sheets/<int:sid>")
    def sheet_get(sid):
        with conn() as c:
            r = c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone()
            if not r:
                raise ApiError("Sheet not found", 404)
            sheet = db.row_to_dict(r, ["answers", "flags", "notes", "qboxes"])
            exam = load_exam(c, sheet["exam_id"])
            ev = evaluate(sheet, exam, students_map(c))
            siblings = [x["id"] for x in c.execute("SELECT id FROM sheets WHERE exam_id=? ORDER BY id", (sheet["exam_id"],))]
        keys = exam["keys"]
        code = sheet["set_code"] or (next(iter(keys)) if len(keys) == 1 else "")
        key = keys.get(code, [])
        bad_q = [int(m.group(1)) for f in sheet["flags"] if (m := re.match(r"q(\d+):(\w+)", f)) and m.group(2) in REVIEW_KINDS | {"multiple"}]
        return jsonify({
            **ev, "answers": sheet["answers"], "flags": sheet["flags"], "notes": sheet["notes"],
            "qboxes": sheet["qboxes"], "preview": f"/files/{sheet['preview']}" if sheet["preview"] else "",
            "ref_w": sheet["ref_w"], "ref_h": sheet["ref_h"], "key": key, "bad_q": bad_q,
            "labels": (exam["template"] or {}).get("labels", "ABCD"), "exam_id": sheet["exam_id"],
            "key_sets": list(keys), "ids": siblings,
        })

    @app.put("/api/sheets/<int:sid>")
    def sheet_put(sid):
        body = request.get_json()
        with conn() as c:
            r = c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone()
            if not r:
                raise ApiError("Sheet not found", 404)
            sets, vals = [], []
            for col, key in (("roll", "roll"), ("set_code", "set"), ("batch", "batch")):
                if key in body:
                    sets.append(f"{col}=?")
                    vals.append(str(body[key]).strip())
            if "answers" in body:
                sets.append("answers=?")
                vals.append(json.dumps([str(a).upper() for a in body["answers"]]))
            sets.append("reviewed=?")
            vals.append(1 if body.get("reviewed", True) else 0)
            c.execute(f"UPDATE sheets SET {','.join(sets)} WHERE id=?", (*vals, sid))
        return jsonify(ok=True)

    @app.delete("/api/sheets/<int:sid>")
    def sheet_delete(sid):
        with conn() as c:
            c.execute("DELETE FROM sheets WHERE id=?", (sid,))
        return jsonify(ok=True)

    @app.post("/api/exams/<int:eid>/clear")
    def sheets_clear(eid):
        with conn() as c:
            c.execute("DELETE FROM sheets WHERE exam_id=?", (eid,))
        return jsonify(ok=True)

    def results_payload(c, exam):
        rows, raw = evaluated_sheets(c, exam)
        scored = [r for r in rows if r["result"]]
        out = []
        for r in scored:
            res = r["result"]
            out.append({**{k: r[k] for k in ("id", "rank", "roll", "name", "batch", "set", "needs_review", "issues")},
                        "score": res["score"], "max": res["max"], "percent": res["percent"], "correct": res["correct"],
                        "wrong": res["wrong"], "blank": res["blank"], "multi": res["multi"], "sections": res["sections"]})
        out.sort(key=lambda r: (r["rank"] or 10**9, r["roll"]))
        batches: dict[str, list] = {}
        for r in out:
            batches.setdefault(r["batch"] or "-", []).append(r["score"])
        batch_rows = [{"batch": b, "students": len(v), "average": round(sum(v) / len(v), 2), "highest": max(v), "lowest": min(v)}
                      for b, v in sorted(batches.items())]
        stats = []
        labels = (exam["template"] or {}).get("labels", "ABCD")
        for code, key in exam["keys"].items():
            group = [s["answers"] for s, e in zip(raw, rows) if (e["set"] or (code if len(exam["keys"]) == 1 else "")) == code]
            for st in scoring.question_stats(group, key, labels):
                st["set"] = code
                stats.append(st)
        return {"rows": out, "batches": batch_rows, "stats": stats, "unscored": len(rows) - len(scored),
                "review": sum(1 for r in rows if r["needs_review"]), "total": len(rows)}

    @app.get("/api/exams/<int:eid>/results")
    def results(eid):
        with conn() as c:
            exam = load_exam(c, eid)
            return jsonify(results_payload(c, exam))

    @app.get("/api/exams/<int:eid>/export.xlsx")
    def export(eid):
        with conn() as c:
            exam = load_exam(c, eid)
            payload = results_payload(c, exam)
            rows, _ = evaluated_sheets(c, exam)
        data = report.build_workbook(exam, payload, [r for r in rows if r["needs_review"] or not r["result"]])
        safe = re.sub(r"[^\w\- ]+", "_", exam["name"]) or "results"
        return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{safe}-results.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------------- machine file / students
    def read_table(f) -> list[list[str]]:
        name = (f.filename or "").lower()
        data = f.read()
        if name.endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            return [["" if v is None else str(v).strip() for v in row] for row in ws.iter_rows(values_only=True)]
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t|") if text.strip() else csv.excel
        return [[v.strip() for v in row] for row in csv.reader(io.StringIO(text), dialect)]

    @app.post("/api/students/import")
    def students_import():
        f = request.files.get("file")
        if not f:
            raise ApiError("Choose a CSV / Excel file")
        table = read_table(f)
        if not table:
            raise ApiError("File is empty")
        head = [h.lower() for h in table[0]]
        def col(*names):
            for i, h in enumerate(head):
                if any(n in h for n in names):
                    return i
            return None
        ir, inm, ib = col("roll", "id", "reg"), col("name"), col("batch", "class")
        if ir is None:
            raise ApiError("First row must have a 'Roll' column (and optionally 'Name', 'Batch')")
        n = 0
        with conn() as c:
            for row in table[1:]:
                if len(row) > ir and row[ir]:
                    c.execute("INSERT OR REPLACE INTO students (roll,name,batch) VALUES (?,?,?)",
                              (row[ir], row[inm] if inm is not None and len(row) > inm else "",
                               row[ib] if ib is not None and len(row) > ib else ""))
                    n += 1
        return jsonify(imported=n)

    @app.post("/api/exams/<int:eid>/import_responses")
    def import_responses(eid):
        """Load responses exported by an OMR machine (CSV/Excel) instead of scanning."""
        f = request.files.get("file")
        if not f:
            raise ApiError("Choose the machine's CSV / Excel file")
        table = read_table(f)
        if len(table) < 2:
            raise ApiError("File has no data rows")
        head = [h.lower() for h in table[0]]

        def col(*names):
            for i, h in enumerate(head):
                if any(n in h for n in names):
                    return i
            return None
        ir, iset, ib = col("roll", "reg", "id"), col("set", "series", "booklet", "code"), col("batch")
        qcols = [i for i, h in enumerate(head) if re.fullmatch(r"q?\s*\d+", h)]
        ia = None if len(qcols) >= 5 else col("resp", "answer")
        if ir is None or (len(qcols) < 5 and ia is None):
            raise ApiError("Need a 'Roll' column and either one 'Responses' column or Q1..Qn columns")
        blank_chars = set(" -._0")
        def conv(ch):
            ch = ch.strip().upper()
            if ch == "" or ch in blank_chars:
                return ""
            if ch in "*?#" or len(ch) > 1:
                return ch if (ch.isalpha() and len(ch) > 1) else "**"
            return ch
        n = 0
        with conn() as c:
            for row in table[1:]:
                if len(row) <= ir or not row[ir]:
                    continue
                if ia is not None:
                    resp = row[ia] if len(row) > ia else ""
                    answers = [conv(ch) for ch in re.sub(r"\s", " ", resp)]
                else:
                    answers = [conv(row[i]) if len(row) > i else "" for i in qcols]
                insert_sheet(c, eid, {
                    "batch": row[ib] if ib is not None and len(row) > ib else "", "file": f.filename,
                    "roll": row[ir], "set": (row[iset].upper() if iset is not None and len(row) > iset else ""),
                    "answers": answers, "flags": [], "notes": [], "qboxes": {}, "preview": "", "ref_w": 0, "ref_h": 0,
                }, request.form.get("batch", ""))
                c.execute("UPDATE sheets SET reviewed=1 WHERE id=last_insert_rowid()")
                n += 1
        return jsonify(imported=n)

    # ------------------------------------------------------------------- demo
    @app.get("/api/sample/sheet.png")
    def sample_sheet():
        seed = int(request.args.get("seed", 1))
        rng = np.random.default_rng(seed)
        img = samplegen.make_sheet(roll=f"{2024000 + seed:08d}", batch="01", set_code="A",
                                   answers=samplegen.random_answers(rng), seed=seed, tilt=0.8)
        ok, enc = cv2.imencode(".png", img)
        return send_file(io.BytesIO(enc.tobytes()), mimetype="image/png", download_name=f"sample-sheet-{seed}.png")

    @app.post("/api/demo")
    def demo():
        """One click: sample sheet type + exam + key + 12 practice sheets."""
        tpl = samplegen.sample_template()
        rng = np.random.default_rng(7)
        n_q = samplegen.ROWS * len(samplegen.ANS_X)
        key_a = [str(rng.choice(list(samplegen.LABELS))) for _ in range(n_q)]
        key_b = [str(rng.choice(list(samplegen.LABELS))) for _ in range(n_q)]
        with conn() as c:
            tid = c.execute("INSERT INTO templates (name,data) VALUES (?,?)",
                            ("Sample sheet (demo)", json.dumps(tpl))).lastrowid
            cfg = {"correct": 4, "wrong": -1, "multi": "wrong", "default_set": "A",
                   "sections": [{"name": "Physics", "start": 1, "end": 50, "correct": None, "wrong": None},
                                {"name": "Chemistry", "start": 51, "end": 100, "correct": None, "wrong": None}]}
            eid = c.execute("INSERT INTO exams (name,date,template_id,cfg) VALUES (?,?,?,?)",
                            ("Demo test", "", tid, json.dumps(cfg))).lastrowid
            c.execute("INSERT INTO keys VALUES (?,?,?)", (eid, "A", "".join(key_a)))
            c.execute("INSERT INTO keys VALUES (?,?,?)", (eid, "B", "".join(key_b)))
            names = ["Aarav", "Diya", "Rohan", "Isha", "Kabir", "Meera", "Vivaan", "Anaya", "Aditya", "Saanvi", "Arjun", "Kiara"]
            for i, nm in enumerate(names):
                c.execute("INSERT OR REPLACE INTO students VALUES (?,?,?)", (f"{20240001 + i:08d}", nm, "Batch-A" if i % 2 == 0 else "Batch-B"))
        jobs = []
        for i in range(12):
            r = np.random.default_rng(100 + i)
            set_code = "A" if i % 3 else "B"
            key = key_a if set_code == "A" else key_b
            skill = 0.4 + 0.5 * r.random()
            ans = []
            for q in range(n_q):
                x = r.random()
                ans.append(key[q] if x < skill else "" if x < skill + 0.05 else str(r.choice(list(samplegen.LABELS))))
            if i == 3:
                ans[10] = ans[10] + ("A" if ans[10] != "A" else "B")      # a double mark
            img = samplegen.make_sheet(roll=f"{20240001 + i:08d}", batch="0" + str(i % 2 + 1), set_code=set_code,
                                       answers=ans, seed=i, tilt=float(r.uniform(-1.5, 1.5)),
                                       shift=(int(r.integers(-15, 15)), int(r.integers(-15, 15))))
            jobs.append((f"demo-sheet-{i + 1}.jpg", img))
        readings = list(pool.map(lambda j: read_one(j[0], j[1], tpl), jobs))
        with conn() as c:
            for rd in readings:
                insert_sheet(c, eid, rd, "")
        return jsonify(exam_id=eid)

    return app
