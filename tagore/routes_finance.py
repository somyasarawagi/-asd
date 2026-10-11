"""Fees, payments & receipts, expenses, ledger, admission enquiries."""
from __future__ import annotations

import secrets
from flask import jsonify, request

from . import db
from .core import (STAFF, ApiError, api, audit, batch_student_ids, body, choice, in_clause, iso, me, my_children,
                   notify, num, parent_users, phone10, roles, student_or_403, student_users, text, today)
from .routes_people import create_student

EXPENSE_CATEGORIES = ("Salary", "Rent", "Electricity", "Internet", "Printing & Stationery", "Marketing",
                      "Maintenance", "Study Material", "Events", "Other")

FEE_SELECT = ("SELECT f.id, f.student_id, f.title, f.amount, f.discount, f.due_date, u.name AS student, "
              "u.login_id AS roll, b.name AS batch, "
              "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.fee_id=f.id),0) AS paid "
              "FROM fees f JOIN students s ON s.id=f.student_id JOIN users u ON u.id=s.user_id "
              "LEFT JOIN batches b ON b.id=s.batch_id")


def _decorate(rows: list[dict]) -> list[dict]:
    t = today()
    for r in rows:
        r["due"] = r["amount"] - r["discount"] - r["paid"]
        r["status"] = "paid" if r["due"] <= 0 else ("overdue" if r["due_date"] < t else "pending")
    return rows


@api.get("/fees")
@roles()
def list_fees():
    u = me()
    where, args = ["1=1"], []
    if u["role"] in ("student", "parent"):
        ids = [c["id"] for c in my_children(u)]
        where.append(f"f.student_id IN ({in_clause(ids)})")
        args += ids
        if request.args.get("student_id"):
            where.append("f.student_id=?")
            args.append(request.args["student_id"])
    elif u["role"] in STAFF:
        for k, col in (("student_id", "f.student_id"), ("batch_id", "s.batch_id")):
            if request.args.get(k):
                where.append(f"{col}=?")
                args.append(request.args[k])
    else:
        raise ApiError("You are not allowed to do this", 403)
    rows = _decorate(db.q(f"{FEE_SELECT} WHERE {' AND '.join(where)} ORDER BY f.due_date, f.id LIMIT 2000", args))
    if request.args.get("status") in ("paid", "pending", "overdue"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if u["role"] in ("student", "parent"):
        for r in rows:
            r["payments"] = db.q("SELECT id, amount, mode, paid_on, receipt_no FROM payments WHERE fee_id=? "
                                 "ORDER BY id", (r["id"],))
    return jsonify(fees=rows)


@api.post("/fees/assign")
@roles(*STAFF)
def assign_fee():
    """Charge a fee instalment to one student or a whole batch."""
    d, u = body(), me()
    title, amount = text(d, "title", True, 80), num(d, "amount", True, 1, 10 ** 8)
    due = iso(d.get("due_date"), "due_date")
    if d.get("student_id"):
        student_or_403(u, d["student_id"])
        sids = [int(d["student_id"])]
    elif d.get("batch_id"):
        sids = batch_student_ids(int(d["batch_id"]))
    else:
        raise ApiError("Send 'student_id' or 'batch_id'")
    if not sids:
        raise ApiError("No active students found")
    db.execmany("INSERT INTO fees(student_id,title,amount,due_date,created_by) VALUES(?,?,?,?,?)",
                [(s, title, amount, due, u["id"]) for s in sids])
    notify(parent_users(sids) + student_users(sids), "New fee instalment",
           f"{title}: Rs {amount} due by {due}.", "fee")
    audit("assign_fee", f"{title} Rs{amount} x{len(sids)}")
    return jsonify(created=len(sids)), 201


@api.post("/fees/<int:fid>/discount")
@roles("superadmin")
def set_discount(fid):
    f = db.q1("SELECT * FROM fees WHERE id=?", (fid,))
    if not f:
        raise ApiError("Fee not found", 404)
    disc = num(body(), "discount", True, 0, f["amount"])
    paid = db.q1("SELECT COALESCE(SUM(amount),0) AS p FROM payments WHERE fee_id=?", (fid,))["p"]
    if f["amount"] - disc < paid:
        raise ApiError("Discount is too large: student already paid more than the new payable amount")
    db.ex("UPDATE fees SET discount=? WHERE id=?", (disc, fid))
    audit("discount", f"fee {fid}: Rs {disc}")
    return jsonify(ok=True)


@api.post("/fees/remind")
@roles(*STAFF)
def remind():
    ids = body().get("fee_ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError("'fee_ids' is required")
    ids = [int(i) for i in ids if str(i).isdigit()]
    rows = _decorate(db.q(f"{FEE_SELECT} WHERE f.id IN ({in_clause(ids)})", ids))
    sent = 0
    for r in rows:
        if r["due"] > 0:
            notify(parent_users([r["student_id"]]) + student_users([r["student_id"]]), "Fee reminder",
                   f"{r['title']}: Rs {r['due']} pending (due {r['due_date']}).", "fee")
            sent += 1
    return jsonify(sent=sent)


@api.post("/payments")
@roles(*STAFF)
def take_payment():
    d, u = body(), me()
    fee = _decorate(db.q(f"{FEE_SELECT} WHERE f.id=?", (num(d, "fee_id", True),)))
    if not fee:
        raise ApiError("Fee not found", 404)
    fee = fee[0]
    amount = num(d, "amount", True, 1, 10 ** 8)
    if amount != int(amount):
        raise ApiError("Amount must be in whole rupees")
    if amount > fee["due"]:
        raise ApiError(f"Amount is more than the pending Rs {fee['due']}")
    paid_on = iso(d.get("paid_on") or today(), "paid_on")
    if paid_on > today():
        raise ApiError("Payment date cannot be in the future")
    pid = db.ex("INSERT INTO payments(fee_id,student_id,amount,mode,ref,note,paid_on,receipt_no,received_by) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (fee["id"], fee["student_id"], amount, choice(d.get("mode"), ("cash", "upi", "card", "cheque", "bank"),
                                                              "mode"),
                 text(d, "ref", False, 60), text(d, "note", False, 200), paid_on, "tmp-" + secrets.token_hex(6),
                 u["id"]))
    receipt = f"TCI/{paid_on[:4]}/{pid:05d}"
    db.ex("UPDATE payments SET receipt_no=? WHERE id=?", (receipt, pid))
    notify(parent_users([fee["student_id"]]) + student_users([fee["student_id"]]), "Payment received",
           f"Rs {amount} received for {fee['title']}. Receipt {receipt}.", "fee")
    audit("payment", f"{receipt} Rs{amount} {fee['roll']}")
    return jsonify(id=pid, receipt_no=receipt), 201


@api.get("/payments")
@roles(*STAFF)
def list_payments():
    f, t = iso(request.args.get("from") or today()[:8] + "01", "from"), iso(request.args.get("to") or today(), "to")
    rows = db.q("SELECT p.id, p.receipt_no, p.amount, p.mode, p.ref, p.paid_on, fe.title, u.name AS student, "
                "u.login_id AS roll, r.name AS received_by FROM payments p JOIN fees fe ON fe.id=p.fee_id "
                "JOIN students s ON s.id=p.student_id JOIN users u ON u.id=s.user_id "
                "LEFT JOIN users r ON r.id=p.received_by WHERE p.paid_on BETWEEN ? AND ? ORDER BY p.id DESC LIMIT 1000",
                (f, t))
    return jsonify(payments=rows, total=sum(r["amount"] for r in rows))


@api.get("/payments/<int:pid>/receipt")
@roles()
def receipt(pid):
    p = db.q1("SELECT p.*, fe.title, fe.amount AS fee_amount, fe.discount, r.name AS received_by FROM payments p "
              "JOIN fees fe ON fe.id=p.fee_id LEFT JOIN users r ON r.id=p.received_by WHERE p.id=?", (pid,))
    if not p:
        raise ApiError("Receipt not found", 404)
    s = student_or_403(me(), p["student_id"])
    if me()["role"] == "teacher":
        raise ApiError("You are not allowed to do this", 403)
    paid = db.q1("SELECT SUM(amount) AS x FROM payments WHERE fee_id=?", (p["fee_id"],))["x"]
    batch = db.q1("SELECT name FROM batches WHERE id=?", (s["batch_id"],))
    return jsonify(receipt={**p, "student": s["name"], "roll": s["login_id"], "batch": batch and batch["name"],
                            "balance": p["fee_amount"] - p["discount"] - paid,
                            "institute": db.setting("institute_name", "Tagore Career Institute"),
                            "address": db.setting("address", "")})


@api.get("/accounts/dues")
@roles(*STAFF)
def dues():
    rows = [r for r in _decorate(db.q(f"{FEE_SELECT} ORDER BY f.due_date LIMIT 5000")) if r["due"] > 0]
    by_student: dict[int, dict] = {}
    for r in rows:
        s = by_student.setdefault(r["student_id"], {"student_id": r["student_id"], "student": r["student"],
                                                    "roll": r["roll"], "batch": r["batch"], "due": 0, "overdue": 0,
                                                    "fee_ids": [], "oldest_due": r["due_date"]})
        s["due"] += r["due"]
        s["overdue"] += r["due"] if r["status"] == "overdue" else 0
        s["fee_ids"].append(r["id"])
    out = sorted(by_student.values(), key=lambda s: (-s["overdue"], -s["due"]))
    return jsonify(dues=out, total_due=sum(s["due"] for s in out), total_overdue=sum(s["overdue"] for s in out))


# ------------------------------------------------------------ expenses ----
@api.get("/expenses")
@roles(*STAFF)
def list_expenses():
    f, t = iso(request.args.get("from") or today()[:8] + "01", "from"), iso(request.args.get("to") or today(), "to")
    rows = db.q("SELECT e.*, u.name AS added_by_name FROM expenses e LEFT JOIN users u ON u.id=e.added_by "
                "WHERE e.date BETWEEN ? AND ? ORDER BY e.date DESC, e.id DESC LIMIT 1000", (f, t))
    return jsonify(expenses=rows, total=sum(r["amount"] for r in rows), categories=EXPENSE_CATEGORIES)


@api.post("/expenses")
@roles(*STAFF)
def add_expense():
    d, u = body(), me()
    day = iso(d.get("date") or today(), "date")
    if day > today():
        raise ApiError("Expense date cannot be in the future")
    amount = num(d, "amount", True, 1, 10 ** 8)
    eid = db.ex("INSERT INTO expenses(category,amount,date,vendor,note,added_by) VALUES(?,?,?,?,?,?)",
                (choice(d.get("category"), EXPENSE_CATEGORIES, "category"), amount, day,
                 text(d, "vendor", False, 100), text(d, "note", False, 300), u["id"]))
    audit("expense", f"Rs{amount} {d.get('category')}")
    return jsonify(id=eid), 201


@api.delete("/expenses/<int:eid>")
@roles("superadmin")
def del_expense(eid):
    db.ex("DELETE FROM expenses WHERE id=?", (eid,))
    audit("delete_expense", str(eid))
    return jsonify(ok=True)


@api.get("/accounts/summary")
@roles(*STAFF)
def accounts_summary():
    f, t = iso(request.args.get("from") or today()[:8] + "01", "from"), iso(request.args.get("to") or today(), "to")
    income = db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM payments WHERE paid_on BETWEEN ? AND ?", (f, t))["x"]
    spent = db.q1("SELECT COALESCE(SUM(amount),0) AS x FROM expenses WHERE date BETWEEN ? AND ?", (f, t))["x"]
    return jsonify(
        range={"from": f, "to": t}, income=income, expenses=spent, net=income - spent,
        by_mode=db.q("SELECT mode, SUM(amount) AS amount FROM payments WHERE paid_on BETWEEN ? AND ? GROUP BY mode",
                     (f, t)),
        by_category=db.q("SELECT category, SUM(amount) AS amount FROM expenses WHERE date BETWEEN ? AND ? "
                         "GROUP BY category ORDER BY amount DESC", (f, t)),
        daily=db.q("SELECT paid_on AS date, SUM(amount) AS amount FROM payments WHERE paid_on BETWEEN ? AND ? "
                   "GROUP BY paid_on ORDER BY paid_on", (f, t)))


@api.get("/accounts/ledger")
@roles(*STAFF)
def ledger():
    f, t = iso(request.args.get("from") or today()[:8] + "01", "from"), iso(request.args.get("to") or today(), "to")
    rows = db.q("SELECT p.paid_on AS date, 'Fee ' || p.receipt_no || ' - ' || u.name AS particulars, "
                "p.amount AS credit, 0 AS debit, p.mode AS mode FROM payments p JOIN students s ON s.id=p.student_id "
                "JOIN users u ON u.id=s.user_id WHERE p.paid_on BETWEEN ?1 AND ?2 "
                "UNION ALL SELECT e.date, e.category || COALESCE(' - ' || NULLIF(e.vendor,''), ''), 0, e.amount, '' "
                "FROM expenses e WHERE e.date BETWEEN ?1 AND ?2 ORDER BY 1, 2", (f, t))
    bal = 0
    for r in rows:
        bal += r["credit"] - r["debit"]
        r["balance"] = bal
    return jsonify(ledger=rows, credit=sum(r["credit"] for r in rows), debit=sum(r["debit"] for r in rows))


# ---------------------------------------------------------- enquiries ----
@api.get("/enquiries")
@roles(*STAFF)
def list_enquiries():
    rows = db.q("SELECT e.*, u.name AS created_by_name FROM enquiries e LEFT JOIN users u ON u.id=e.created_by "
                "ORDER BY e.status IN ('admitted','lost'), e.follow_up IS NULL, e.follow_up, e.id DESC LIMIT 1000")
    return jsonify(enquiries=rows, today=today())


@api.post("/enquiries")
@roles(*STAFF)
def add_enquiry():
    d = body()
    eid = db.ex("INSERT INTO enquiries(name,phone,course,source,follow_up,notes,created_by) VALUES(?,?,?,?,?,?,?)",
                (text(d, "name", True, 80), phone10(d.get("phone")), text(d, "course", False, 80),
                 text(d, "source", False, 40), iso(d.get("follow_up"), "follow_up", False) or None,
                 text(d, "notes", False, 500), me()["id"]))
    return jsonify(id=eid), 201


@api.put("/enquiries/<int:eid>")
@roles(*STAFF)
def update_enquiry(eid):
    d = body()
    e = db.q1("SELECT * FROM enquiries WHERE id=?", (eid,))
    if not e:
        raise ApiError("Not found", 404)
    status = choice(d.get("status", e["status"]), ("new", "contacted", "visited", "admitted", "lost"), "status")
    if status == "admitted" and not e["student_id"]:
        raise ApiError("Use 'Admit' to enrol this student so a login gets created")
    db.ex("UPDATE enquiries SET status=?, follow_up=?, notes=? WHERE id=?",
          (status, iso(d.get("follow_up", e["follow_up"]), "follow_up", False) or None,
           text(d, "notes", False, 500) if "notes" in d else e["notes"], eid))
    return jsonify(ok=True)


@api.post("/enquiries/<int:eid>/admit")
@roles(*STAFF)
def admit_enquiry(eid):
    d = body()
    e = db.q1("SELECT * FROM enquiries WHERE id=?", (eid,))
    if not e:
        raise ApiError("Not found", 404)
    if e["student_id"]:
        raise ApiError("Already admitted", 409)
    out = create_student({**d, "name": d.get("name") or e["name"], "parent_phone": d.get("parent_phone") or e["phone"]},
                         me()["id"])
    db.ex("UPDATE enquiries SET status='admitted', student_id=? WHERE id=?", (out["student_id"], eid))
    audit("admission", out["student"]["login_id"])
    return jsonify(out), 201
