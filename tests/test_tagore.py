"""Tagore ecosystem: role permissions and the money / exam / PTM flows."""
import sqlite3
from datetime import date, timedelta

import pytest

from tagore import create_app
from tagore.seed import DEMO_PASSWORD, seed_demo


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp("tagore"))
    info = seed_demo(app)
    return app, info


def client(world, login):
    app, _ = world
    c = app.test_client()
    r = c.post("/api/login", json={"login_id": login, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.get_json()
    return c


def db_exec(world, sql, args=()):
    con = sqlite3.connect(world[0].config["DB_PATH"])
    cur = con.execute(sql, args)
    con.commit()
    out = cur.fetchall()
    con.close()
    return out


def single_child_parents(world, batch_id):
    return [r[0] for r in db_exec(
        world, "SELECT p.login_id FROM parent_students ps JOIN users p ON p.id=ps.parent_user_id "
               "WHERE ps.parent_user_id IN (SELECT parent_user_id FROM parent_students GROUP BY parent_user_id "
               "HAVING COUNT(*)=1) AND ps.student_id IN (SELECT id FROM students WHERE batch_id=?) "
               "ORDER BY p.login_id", (batch_id,))]


# --------------------------------------------------------------- login ----
def test_login_and_lockout(tmp_path):
    app = create_app(tmp_path)
    seed = seed_demo(app)
    c = app.test_client()
    assert c.get("/api/me").status_code == 401
    for _ in range(5):
        assert c.post("/api/login", json={"login_id": "director", "password": "nope"}).status_code == 401
    # locked even for the right password now
    assert c.post("/api/login", json={"login_id": "director", "password": seed["password"]}).status_code == 429


def test_five_roles_can_login(world):
    _, info = world
    for login, role in [(info["director"], "superadmin"), (info["office"][0], "admin"),
                        (info["teachers"][0], "teacher"), (info["student"], "student"), (info["parent"], "parent")]:
        r = client(world, login).get("/api/me").get_json()
        assert r["user"]["role"] == role


# ------------------------------------------------------ role isolation ----
def test_role_walls(world):
    _, info = world
    student, parent = client(world, info["student"]), client(world, info["parent"])
    teacher, office = client(world, info["teachers"][0]), client(world, info["office"][0])
    assert student.get("/api/students").status_code == 403
    assert student.get("/api/accounts/summary").status_code == 403
    assert student.post("/api/homework", json={"batch_id": 1, "title": "x"}).status_code == 403
    assert teacher.get("/api/fees").status_code == 403
    assert teacher.get("/api/accounts/summary").status_code == 403
    assert teacher.post("/api/users", json={"role": "teacher", "name": "x"}).status_code == 403
    assert office.post("/api/users", json={"role": "teacher", "name": "x"}).status_code == 403
    assert office.get("/api/reports/overview").status_code == 403
    assert office.get("/api/audit").status_code == 403
    assert parent.get("/api/enquiries").status_code == 403


def test_family_cannot_read_other_students(world):
    _, info = world
    parent = client(world, info["parent"])
    mine = {c["id"] for c in parent.get("/api/me").get_json()["user"]["children"]}
    other = db_exec(world, "SELECT id FROM students WHERE id NOT IN (%s) LIMIT 1" % ",".join(map(str, mine)))[0][0]
    for path in (f"/api/students/{other}", f"/api/attendance/student/{other}", f"/api/students/{other}/results"):
        assert parent.get(path).status_code == 403, path
    assert parent.get(f"/api/fees?student_id={other}").get_json()["fees"] == []
    assert parent.get(f"/api/dashboard?student_id={other}").status_code == 403


def test_teacher_only_manages_own_batches(world):
    _, info = world
    bio = client(world, info["teachers"][3])  # Biology: teaches only NEET batch
    batches = bio.get("/api/batches").get_json()["batches"]
    assert [b["name"] for b in batches] == ["NEET 2027 Target"]
    jee = db_exec(world, "SELECT id FROM batches WHERE name='JEE 2027 Dropper'")[0][0]
    assert bio.get(f"/api/attendance/sheet?batch_id={jee}").status_code == 403
    assert bio.post("/api/attendance", json={"batch_id": jee, "date": date.today().isoformat(),
                                             "records": [{"student_id": 1, "status": "P"}]}).status_code == 403
    assert len(bio.get("/api/students").get_json()["students"]) == 8


def test_attendance_validations_and_parent_alert(world):
    _, info = world
    phy = client(world, info["teachers"][0])
    jee = db_exec(world, "SELECT id FROM batches WHERE name='JEE 2027 Dropper'")[0][0]
    sheet = phy.get(f"/api/attendance/sheet?batch_id={jee}").get_json()["students"]
    future = (date.today() + timedelta(days=1)).isoformat()
    assert phy.post("/api/attendance", json={"batch_id": jee, "date": future,
                                             "records": [{"student_id": sheet[0]["student_id"], "status": "P"}]}
                    ).status_code == 400
    sid = sheet[0]["student_id"]
    r = phy.post("/api/attendance", json={"batch_id": jee, "date": date.today().isoformat(),
                                          "records": [{"student_id": sid, "status": "A"}]})
    assert r.get_json()["absent"] == 1
    puser = db_exec(world, "SELECT u.login_id FROM parent_students ps JOIN users u ON u.id=ps.parent_user_id "
                           "WHERE ps.student_id=?", (sid,))[0][0]
    notes = client(world, puser).get("/api/notifications").get_json()
    assert any(n["title"] == "Absent today" for n in notes["notifications"])
    # re-saving the same absence does not spam the parent again
    before = notes["unread"]
    phy.post("/api/attendance", json={"batch_id": jee, "date": date.today().isoformat(),
                                      "records": [{"student_id": sid, "status": "A"}]})
    assert client(world, puser).get("/api/notifications").get_json()["unread"] == before


# ------------------------------------------------------------- finance ----
def test_fee_payment_rules_and_receipt(world):
    _, info = world
    office, director = client(world, info["office"][0]), client(world, info["director"])
    fee = next(f for f in office.get("/api/fees?status=pending").get_json()["fees"] +
               office.get("/api/fees?status=overdue").get_json()["fees"] if f["due"] > 1000)
    assert office.post("/api/payments", json={"fee_id": fee["id"], "amount": fee["due"] + 1, "mode": "cash"}
                       ).status_code == 400
    assert office.post("/api/payments", json={"fee_id": fee["id"], "amount": 0, "mode": "cash"}).status_code == 400
    assert office.post("/api/payments", json={"fee_id": fee["id"], "amount": 500, "mode": "gold"}).status_code == 400
    assert office.post("/api/payments", json={"fee_id": fee["id"], "amount": 500.5, "mode": "cash"}).status_code == 400
    r = office.post("/api/payments", json={"fee_id": fee["id"], "amount": 500, "mode": "upi", "ref": "UTR1"})
    assert r.status_code == 201 and r.get_json()["receipt_no"].startswith("TCI/")
    after = next(f for f in office.get(f"/api/fees?student_id={fee['student_id']}").get_json()["fees"]
                 if f["id"] == fee["id"])
    assert after["paid"] == fee["paid"] + 500 and after["due"] == fee["due"] - 500
    # only the director can give a discount, and never below what is already paid
    assert office.post(f"/api/fees/{fee['id']}/discount", json={"discount": 100}).status_code == 403
    assert director.post(f"/api/fees/{fee['id']}/discount", json={"discount": fee["amount"]}).status_code == 400
    assert director.post(f"/api/fees/{fee['id']}/discount", json={"discount": 100}).status_code == 200
    # the right family sees the receipt; another family and teachers do not
    pid = r.get_json()["id"]
    sid = fee["student_id"]
    plogin = db_exec(world, "SELECT u.login_id FROM parent_students ps JOIN users u ON u.id=ps.parent_user_id "
                            "WHERE ps.student_id=?", (sid,))[0][0]
    assert client(world, plogin).get(f"/api/payments/{pid}/receipt").status_code == 200
    assert client(world, info["teachers"][0]).get(f"/api/payments/{pid}/receipt").status_code == 403
    others = db_exec(world, "SELECT u.login_id FROM parent_students ps JOIN users u ON u.id=ps.parent_user_id "
                            "WHERE ps.student_id<>? AND u.login_id<>? LIMIT 1", (sid, plogin))[0][0]
    assert client(world, others).get(f"/api/payments/{pid}/receipt").status_code == 403


def test_ledger_balances(world):
    _, info = world
    office = client(world, info["office"][0])
    q = "?from=2000-01-01&to=2100-01-01"
    summ = office.get("/api/accounts/summary" + q).get_json()
    led = office.get("/api/accounts/ledger" + q).get_json()
    assert summ["income"] == led["credit"] and summ["expenses"] == led["debit"]
    assert led["ledger"][-1]["balance"] == summ["net"]
    assert office.post("/api/expenses", json={"category": "Rent", "amount": 5, "date": "2999-01-01"}).status_code == 400
    assert office.delete("/api/expenses/1").status_code == 403  # only director deletes


def test_dues_list(world):
    _, info = world
    d = client(world, info["office"][0]).get("/api/accounts/dues").get_json()
    assert d["total_due"] > 0 and d["total_overdue"] <= d["total_due"]
    assert d["dues"] == sorted(d["dues"], key=lambda s: (-s["overdue"], -s["due"]))


# --------------------------------------------------------------- tests ----
def test_marks_import_and_rank_ties(world):
    _, info = world
    phy = client(world, info["teachers"][0])
    jee = db_exec(world, "SELECT id FROM batches WHERE name='JEE 2027 Dropper'")[0][0]
    tid = phy.post("/api/tests", json={"batch_id": jee, "name": "Import Test", "max_marks": 50}).get_json()["id"]
    sheet = phy.get(f"/api/tests/{tid}/sheet").get_json()["students"]
    rolls = [s["login_id"] for s in sheet[:4]]
    csv_text = f"Roll,Name,Marks\n{rolls[0]},a,40\n{rolls[1]},b,40\n{rolls[2]},c,AB\n{rolls[3]},d,25\nNOPE,e,10\n"
    r = phy.post(f"/api/tests/{tid}/marks/import", json={"csv": csv_text}).get_json()
    assert r["saved"] == 4 and r["not_found"] == ["NOPE"]
    assert phy.post(f"/api/tests/{tid}/marks", json={"records": [{"student_id": sheet[5]["student_id"], "marks": 51}]}
                    ).status_code == 400  # more than max
    res = phy.get(f"/api/tests/{tid}/results").get_json()
    ranks = {x["login_id"]: x["rank"] for x in res["results"]}
    assert ranks[rolls[0]] == ranks[rolls[1]] == 1 and ranks[rolls[3]] == 3 and ranks[rolls[2]] is None
    # unpublished: family cannot see it
    stu = client(world, rolls[0])
    assert stu.get(f"/api/tests/{tid}/results").status_code == 403
    phy.post(f"/api/tests/{tid}/publish", json={})
    mine = stu.get(f"/api/tests/{tid}/results").get_json()
    assert [x["login_id"] for x in mine["results"]] == [rolls[0]] and mine["results"][0]["rank"] == 1


def test_online_test_scoring_and_one_attempt(world):
    _, info = world
    tid = db_exec(world, "SELECT id FROM tests WHERE mode='online'")[0][0]
    qs = db_exec(world, "SELECT id, answer FROM questions WHERE test_id=? ORDER BY id", (tid,))
    stu = client(world, info["student"])
    paper = stu.post(f"/api/tests/{tid}/start").get_json()
    assert "answer" not in str(paper["questions"][0]).lower().replace("answers", "")
    assert paper["seconds_left"] > 0
    wrong = {"A": "B", "B": "A", "C": "A", "D": "A"}
    ans = {str(qs[0][0]): qs[0][1], str(qs[1][0]): qs[1][1], str(qs[2][0]): wrong[qs[2][1]]}  # 2 right, 1 wrong
    res = stu.post(f"/api/tests/{tid}/submit", json={"answers": ans}).get_json()
    assert res["score"] == 4 + 4 - 1 and res["late"] is False
    assert stu.post(f"/api/tests/{tid}/submit", json={"answers": ans}).status_code == 409
    assert stu.post(f"/api/tests/{tid}/start").status_code == 409
    rev = stu.get(f"/api/tests/{tid}/review").get_json()
    assert rev["questions"][0]["correct"] == qs[0][1]
    # the marks flow into the normal result sheet / ranking
    mine = stu.get(f"/api/tests/{tid}/results").get_json()["results"]
    assert mine[0]["marks"] == 7
    # teacher cannot tamper with questions once students started
    phy = client(world, info["teachers"][0])
    assert phy.post(f"/api/tests/{tid}/questions", json={"questions": [
        {"text": "q", "a": "1", "b": "2", "answer": "A"}]}).status_code == 409


def test_late_online_submission_scores_zero(world):
    _, info = world
    tid = db_exec(world, "SELECT id FROM tests WHERE mode='online'")[0][0]
    # a second student of the same batch starts, then the clock runs out
    login = db_exec(world, "SELECT u.login_id FROM students s JOIN users u ON u.id=s.user_id WHERE s.batch_id="
                           "(SELECT batch_id FROM tests WHERE id=?) AND u.login_id<>? ORDER BY s.id LIMIT 1",
                    (tid, info["student"]))[0][0]
    stu = client(world, login)
    stu.post(f"/api/tests/{tid}/start")
    db_exec(world, "UPDATE attempts SET started_at='2000-01-01T00:00:00' WHERE test_id=? AND student_id="
                   "(SELECT s.id FROM students s JOIN users u ON u.id=s.user_id WHERE u.login_id=?)", (tid, login))
    qid = db_exec(world, "SELECT id, answer FROM questions WHERE test_id=? LIMIT 1", (tid,))[0]
    res = stu.post(f"/api/tests/{tid}/submit", json={"answers": {str(qid[0]): qid[1]}}).get_json()
    assert res["late"] is True and res["score"] == 0


def test_links_must_be_http(world):
    _, info = world
    phy = client(world, info["teachers"][0])
    jee = db_exec(world, "SELECT id FROM batches WHERE name='JEE 2027 Dropper'")[0][0]
    for bad in ("javascript:alert(1)", "ftp://x.y/z", "example.com", ""):
        assert phy.post("/api/materials", json={"batch_id": jee, "title": "t", "kind": "link", "url": bad}
                        ).status_code == 400, bad


# ----------------------------------------------------------------- PTM ----
def test_ptm_booking_rules_and_privacy(world):
    _, info = world

    jee = db_exec(world, "SELECT id FROM batches WHERE name='JEE 2027 Dropper'")[0][0]
    logins = single_child_parents(world, jee)
    a, b = client(world, logins[0]), client(world, logins[1])
    slots = a.get("/api/ptm").get_json()["events"][0]["slots"]
    first = next(s for s in slots if s["status"] == "open")
    assert a.post(f"/api/ptm/slots/{first['id']}/book", json={}).status_code == 200
    # the same slot cannot be taken twice
    assert b.post(f"/api/ptm/slots/{first['id']}/book", json={}).status_code == 409
    # the same parent cannot be in two rooms at once
    clash = next(s for s in slots if s["slot_time"] == first["slot_time"] and s["id"] != first["id"])
    assert a.post(f"/api/ptm/slots/{clash['id']}/book", json={}).status_code == 409
    # privacy: the other parent sees "booked" but no names
    seen = next(s for s in b.get("/api/ptm").get_json()["events"][0]["slots"] if s["id"] == first["id"])
    assert seen["status"] == "booked" and seen["student"] is None and not seen["mine"]
    # a non-owner cannot cancel; the owner can
    assert b.post(f"/api/ptm/slots/{first['id']}/cancel").status_code == 403
    assert a.post(f"/api/ptm/slots/{first['id']}/cancel").status_code == 200
    # a teacher sees only their own slots
    t = client(world, db_exec(world, "SELECT login_id FROM users WHERE id=?", (first["teacher_user_id"],))[0][0])
    ts = t.get("/api/ptm").get_json()["events"][0]["slots"]
    assert {s["teacher_user_id"] for s in ts} == {first["teacher_user_id"]}


def test_parent_of_other_batch_cannot_book(world):
    _, info = world
    neet = db_exec(world, "SELECT p.login_id FROM students s JOIN parent_students ps ON ps.student_id=s.id "
                          "JOIN users p ON p.id=ps.parent_user_id JOIN batches b ON b.id=s.batch_id "
                          "WHERE b.name='NEET 2027 Target' LIMIT 1")[0][0]
    ev = client(world, neet).get("/api/ptm").get_json()["events"]
    assert ev == []  # PTM was created for the JEE batch only
    slot = db_exec(world, "SELECT id FROM ptm_slots WHERE status='open' LIMIT 1")[0][0]
    assert client(world, neet).post(f"/api/ptm/slots/{slot}/book", json={}).status_code == 403


# ------------------------------------------------------ admissions etc ----
def test_admission_creates_logins_and_sibling_reuses_parent(world):
    _, info = world
    office = client(world, info["office"][0])
    bid = office.get("/api/batches").get_json()["batches"][0]["id"]
    r1 = office.post("/api/students", json={"name": "Test Kid", "batch_id": bid, "parent_phone": "9123456780"}).get_json()
    assert r1["parent"]["temp_password"] and not r1["parent"]["existing"]
    r2 = office.post("/api/students", json={"name": "Test Sib", "batch_id": bid, "parent_phone": "91234 56780"}).get_json()
    assert r2["parent"]["existing"] and r2["parent"]["temp_password"] is None
    # first login forces a password change flag and works with the temp password
    app, _ = world
    cl = app.test_client()
    u = cl.post("/api/login", json={"login_id": r1["student"]["login_id"], "password": r1["student"]["temp_password"]})
    assert u.get_json()["user"]["must_change"] == 1
    assert cl.post("/api/change-password", json={"old": "wrong", "new": "longenough1"}).status_code == 400
    assert cl.post("/api/change-password", json={"old": r1["student"]["temp_password"], "new": "short"}
                   ).status_code == 400
    assert cl.post("/api/change-password", json={"old": r1["student"]["temp_password"], "new": "longenough1"}
                   ).status_code == 200
    assert cl.get("/api/me").get_json()["user"]["must_change"] == 0
    assert office.post("/api/students", json={"name": "x", "batch_id": bid, "parent_phone": "123"}).status_code == 400


def test_enquiry_to_admission(world):
    _, info = world
    office = client(world, info["office"][0])
    eid = office.post("/api/enquiries", json={"name": "Lead A", "phone": "9000011111"}).get_json()["id"]
    assert office.put(f"/api/enquiries/{eid}", json={"status": "admitted"}).status_code == 400  # must use admit
    bid = office.get("/api/batches").get_json()["batches"][0]["id"]
    r = office.post(f"/api/enquiries/{eid}/admit", json={"batch_id": bid})
    assert r.status_code == 201 and office.post(f"/api/enquiries/{eid}/admit", json={"batch_id": bid}).status_code == 409


def test_deactivated_user_is_locked_out(world):
    _, info = world
    director = client(world, info["director"])
    t = client(world, info["teachers"][4])
    uid = t.get("/api/me").get_json()["user"]["id"]
    assert director.post(f"/api/users/{uid}/active", json={"active": False}).status_code == 200
    assert t.get("/api/me").status_code == 401  # existing session dies at once
    assert director.post(f"/api/users/{uid}/active", json={"active": True}).status_code == 200


def test_director_overview_and_dashboards(world):
    _, info = world
    ov = client(world, info["director"]).get("/api/reports/overview").get_json()
    assert len(ov["money"]) == 6 and ov["office"]["students"] > 20 and ov["teachers"]
    for login in (info["student"], info["parent"], info["teachers"][0], info["office"][0], info["director"]):
        assert client(world, login).get("/api/dashboard").status_code == 200


# ---------------------------------------------------- PTM-connect extras --
def _jee(world):
    return db_exec(world, "SELECT id FROM batches WHERE name='JEE 2027 Dropper'")[0][0]


def test_parent_with_two_children_must_choose(world):
    _, info = world
    p = client(world, info["parent"])  # has a JEE child and a Foundation sibling
    kids = p.get("/api/me").get_json()["user"]["children"]
    assert len(kids) == 2
    slot = db_exec(world, "SELECT id FROM ptm_slots WHERE status='open' LIMIT 1")[0][0]
    assert p.post("/api/meeting-requests", json={"teacher_user_id": 1, "reason": "x"}).status_code == 400
    r = p.post(f"/api/ptm/slots/{slot}/book", json={})
    assert r.status_code == 400 and "choose" in r.get_json()["error"].lower()
    assert p.get("/api/dashboard").status_code == 200  # dashboard just opens the first child


def test_ptm_online_link_only_for_booked_family(world):
    _, info = world
    a, b = [client(world, l) for l in single_child_parents(world, _jee(world))[2:4]]
    ev = a.get("/api/ptm").get_json()["events"][0]
    assert ev["mode"] == "online" and ev["meeting_link"] is None
    slot = next(s for s in ev["slots"] if s["status"] == "open")
    assert a.post(f"/api/ptm/slots/{slot['id']}/book", json={}).status_code == 200
    assert a.get("/api/ptm").get_json()["events"][0]["meeting_link"].startswith("https://")
    assert b.get("/api/ptm").get_json()["events"][0]["meeting_link"] is None
    # teacher gets a pre-meeting brief about the student
    t = client(world, db_exec(world, "SELECT login_id FROM users WHERE id=?", (slot["teacher_user_id"],))[0][0])
    mine = next(s for s in t.get("/api/ptm").get_json()["events"][0]["slots"] if s["id"] == slot["id"])
    assert "attendance_percent" in mine["brief"] and "average_percent" in mine["brief"]
    # reschedule to another open slot of the same event
    other = next(s for s in a.get("/api/ptm").get_json()["events"][0]["slots"]
                 if s["status"] == "open" and s["slot_time"] != slot["slot_time"] and
                 s["teacher_user_id"] == slot["teacher_user_id"])
    assert a.post(f"/api/ptm/slots/{slot['id']}/reschedule", json={"to_slot_id": other["id"]}).status_code == 200
    assert b.post(f"/api/ptm/slots/{other['id']}/reschedule", json={"to_slot_id": slot["id"]}).status_code == 403
    after = {s["id"]: s for s in a.get("/api/ptm").get_json()["events"][0]["slots"]}
    assert after[slot["id"]]["status"] == "open" and after[other["id"]]["status"] == "booked"
    # teacher completes it: remarks + parent attendance, parent then rates
    assert t.post(f"/api/ptm/slots/{other['id']}/remarks", json={"remarks": "Doing well", "attended": True}
                  ).status_code == 200
    assert a.post(f"/api/ptm/slots/{other['id']}/feedback", json={"rating": 5, "text": "Helpful"}).status_code == 200
    assert a.post(f"/api/ptm/slots/{other['id']}/feedback", json={"rating": 9}).status_code == 400


def test_ptm_reminders_once_and_report(world):
    _, info = world
    office = client(world, info["office"][0])
    parent = client(world, single_child_parents(world, _jee(world))[1])
    ev = office.get("/api/ptm").get_json()["events"][0]
    free = next(s for s in parent.get("/api/ptm").get_json()["events"][0]["slots"] if s["status"] == "open")
    assert parent.post(f"/api/ptm/slots/{free['id']}/book", json={}).status_code == 200
    # move the event to tomorrow so the 24h reminder applies
    db_exec(world, "UPDATE ptm_events SET date=? WHERE id=?", ((date.today() + timedelta(days=1)).isoformat(), ev["id"]))
    db_exec(world, "UPDATE ptm_slots SET reminded=0")
    n = office.post("/api/ptm/remind").get_json()["reminded"]
    assert n >= 1
    assert any(x["title"] == "PTM reminder" for x in parent.get("/api/notifications").get_json()["notifications"])
    assert office.post("/api/ptm/remind").get_json()["reminded"] == 0  # not twice
    rep = office.get(f"/api/ptm/{ev['id']}/report").get_json()
    assert rep["totals"]["booked"] >= 1 and rep["families"] >= 8 and rep["not_booked"]
    assert rep["coverage_percent"] is not None
    assert office.post(f"/api/ptm/{ev['id']}/nudge").get_json()["nudged"] == len(rep["not_booked"])
    assert client(world, info["student"]).get(f"/api/ptm/{ev['id']}/report").status_code == 403


def test_meeting_request_flow(world):
    _, info = world
    login = single_child_parents(world, _jee(world))[4]
    p = client(world, login)
    th = [t for t in p.get("/api/messages/threads").get_json()["threads"]]
    phy_id = next(t["teacher_user_id"] for t in th if t["subject"] == "Physics")
    bio_id = db_exec(world, "SELECT id FROM users WHERE login_id=?", (info["teachers"][3],))[0][0]
    assert p.post("/api/meeting-requests", json={"teacher_user_id": bio_id, "reason": "x"}).status_code == 403
    rid = p.post("/api/meeting-requests", json={"teacher_user_id": phy_id, "reason": "Marks are dropping"}
                 ).get_json()["id"]
    phy = client(world, info["teachers"][0])
    assert client(world, info["teachers"][1]).post(f"/api/meeting-requests/{rid}/respond",
                                                   json={"action": "decline"}).status_code == 404
    day = (date.today() + timedelta(days=2)).isoformat()
    assert phy.post(f"/api/meeting-requests/{rid}/respond", json={"action": "accept", "meet_on": "2001-01-01",
                                                                  "meet_time": "17:00"}).status_code == 400
    assert phy.post(f"/api/meeting-requests/{rid}/respond", json={"action": "accept", "meet_on": day,
                                                                  "meet_time": "17:00"}).status_code == 200
    got = p.get("/api/meeting-requests").get_json()["requests"][0]
    assert got["status"] == "accepted" and got["meet_time"] == "17:00"
    assert any(n["title"] == "Meeting request update" for n in p.get("/api/notifications").get_json()["notifications"])


def test_chat_is_private(world):
    _, info = world
    jee = _jee(world)
    pa, pb = single_child_parents(world, jee)[5:7]
    a, b = client(world, pa), client(world, pb)
    phy_login, phy_id = info["teachers"][0], db_exec(world, "SELECT id FROM users WHERE login_id=?",
                                                     (info["teachers"][0],))[0][0]
    kid = a.get("/api/me").get_json()["user"]["children"][0]
    assert a.post("/api/messages", json={"student_id": kid["id"], "teacher_user_id": phy_id, "body": "Hello sir"}
                  ).status_code == 201
    # another family cannot read or write into this thread
    q = f"?student_id={kid['id']}&teacher_user_id={phy_id}"
    assert b.get("/api/messages" + q).status_code == 403
    assert b.post("/api/messages", json={"student_id": kid["id"], "teacher_user_id": phy_id, "body": "x"}
                  ).status_code == 403
    # office staff cannot read it either; the teacher can and gets an unread count
    assert client(world, info["office"][0]).get("/api/messages" + q).status_code == 403
    t = client(world, phy_login)
    th = next(x for x in t.get("/api/messages/threads").get_json()["threads"] if x["student_id"] == kid["id"])
    assert th["unread"] == 1
    assert [m["body"] for m in t.get("/api/messages" + q).get_json()["messages"]] == ["Hello sir"]
    assert next(x for x in t.get("/api/messages/threads").get_json()["threads"]
                if x["student_id"] == kid["id"])["unread"] == 0
    # a teacher who does not teach this batch is refused
    assert client(world, info["teachers"][3]).get("/api/messages" + q).status_code == 403
    bio_id = db_exec(world, "SELECT id FROM users WHERE login_id=?", (info["teachers"][3],))[0][0]
    assert a.post("/api/messages", json={"student_id": kid["id"], "teacher_user_id": bio_id, "body": "x"}
                  ).status_code == 403


def test_complaints_and_remarks_and_report_card(world):
    _, info = world
    p = client(world, single_child_parents(world, _jee(world))[0])
    kid = p.get("/api/me").get_json()["user"]["children"][0]
    cid = p.post("/api/complaints", json={"category": "facility", "body": "Fan broken"}).get_json()["id"]
    assert p.post("/api/complaints", json={"category": "nonsense", "body": "x"}).status_code == 400
    assert p.get("/api/complaints").get_json()["complaints"][0]["id"] == cid
    assert p.post(f"/api/complaints/{cid}/respond", json={"status": "resolved", "response": "x"}).status_code == 403
    office = client(world, info["office"][1])
    assert office.post(f"/api/complaints/{cid}/respond", json={"status": "resolved"}).status_code == 400  # needs reply
    assert office.post(f"/api/complaints/{cid}/respond", json={"status": "resolved", "response": "Repaired"}
                       ).status_code == 200
    # teacher remark -> parent sees it in report card; non-teaching teacher cannot add one
    phy = client(world, info["teachers"][0])
    assert phy.post(f"/api/students/{kid['id']}/remarks", json={"kind": "praise", "body": "Great effort"}
                    ).status_code == 201
    assert client(world, info["teachers"][3]).post(f"/api/students/{kid['id']}/remarks",
                                                   json={"body": "x"}).status_code == 403
    rc = p.get(f"/api/students/{kid['id']}/report").get_json()
    assert rc["remarks"][0]["body"] == "Great effort" and rc["tests"] and rc["subjects"]
    assert 0 <= rc["average_percent"] <= 100 and rc["attendance"]["percent"] is not None
    other = db_exec(world, "SELECT id FROM students WHERE id<>? LIMIT 1", (kid["id"],))[0][0]
    assert p.get(f"/api/students/{other}/report").status_code == 403
