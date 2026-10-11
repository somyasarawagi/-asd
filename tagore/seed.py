"""Fill a fresh database with realistic demo data so every login can be tried at once.

Everything is created through the real API (so the demo also exercises the app).
All demo accounts get the password  demo1234.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from flask import Flask
from werkzeug.security import generate_password_hash

from . import create_superadmin, db

DEMO_PASSWORD = "demo1234"
FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Kabir", "Rohan", "Arjun", "Dev", "Yash", "Harsh", "Ananya", "Diya",
         "Saanvi", "Kavya", "Riya", "Priya", "Neha", "Pooja", "Isha", "Tanvi", "Mohit", "Karan", "Nikhil", "Shreya"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Yadav", "Mishra", "Patel", "Jain", "Agarwal", "Kumar", "Tiwari", "Joshi"]


class Seeder:
    def __init__(self, app: Flask):
        self.app, self.rnd = app, random.Random(42)
        self.c = app.test_client()

    def call(self, method: str, path: str, data=None):
        r = getattr(self.c, method)(path, json=data) if data is not None else getattr(self.c, method)(path)
        if r.status_code >= 300:
            raise RuntimeError(f"Seed failed: {method.upper()} {path} {data} -> {r.status_code} {r.get_json()}")
        return r.get_json()

    def login(self, login_id: str):
        self.c.post("/api/logout")
        self.call("post", "/api/login", {"login_id": login_id, "password": DEMO_PASSWORD})

    def run(self) -> dict:
        today = date.today()
        iso = lambda d: d.isoformat()  # noqa: E731
        create_superadmin(self.app, "director", "Dr. R. K. Tagore", DEMO_PASSWORD)
        self._demo_password()
        self.login("director")
        self.call("post", "/api/settings", {"institute_name": "Tagore Career Institute",
                                            "address": "Main Road, Opp. City Mall", "phone": "9876500000"})

        subj = {n: self.call("post", "/api/subjects", {"name": n})["id"]
                for n in ("Physics", "Chemistry", "Mathematics", "Biology", "English")}
        staff = {}
        for key, name, role, subject in [
                ("phy", "Rajesh Kumar", "teacher", "Physics"), ("che", "Sunita Mehra", "teacher", "Chemistry"),
                ("mat", "Amit Saxena", "teacher", "Mathematics"), ("bio", "Dr. Neelam Rao", "teacher", "Biology"),
                ("eng", "Pallavi Dixit", "teacher", "English"),
                ("acc", "Manoj Pandey", "admin", ""), ("desk", "Rekha Soni", "admin", "")]:
            r = self.call("post", "/api/users", {"role": role, "name": name, "subject": subject,
                                                 "qualification": "M.Sc" if role == "teacher" else "",
                                                 "experience_years": 6, "phone": f"98{self.rnd.randint(10**7, 10**8 - 1)}"})
            staff[key] = r
        self._demo_password()
        by_login = {u["login_id"]: u["id"] for u in self.call("get", "/api/users")["users"]}
        t = {k: by_login[v["login_id"]] for k, v in staff.items()}

        batches = {}
        plan = [("JEE 2027 Dropper", "JEE", 120000, ["Physics", "Chemistry", "Mathematics"]),
                ("NEET 2027 Target", "NEET", 110000, ["Physics", "Chemistry", "Biology"]),
                ("Foundation Class 10", "Foundation", 45000, ["Physics", "Mathematics", "English"])]
        teach = {"Physics": "phy", "Chemistry": "che", "Mathematics": "mat", "Biology": "bio", "English": "eng"}
        for name, course, fee, subs in plan:
            bid = self.call("post", "/api/batches", {"name": name, "course": course, "session": "2026-27",
                                                     "fee_total": fee, "start_date": iso(today - timedelta(days=90))})["id"]
            batches[name] = bid
            for i, s in enumerate(subs):
                self.call("post", f"/api/batches/{bid}/assign", {"subject_id": subj[s], "teacher_user_id": t[teach[s]]})
                for k, wd in enumerate((i, i + 3)):
                    start = 8 + (i * 2)
                    self.call("post", "/api/timetable", {"batch_id": bid, "subject_id": subj[s], "weekday": wd,
                                                         "start_time": f"{start:02d}:00", "end_time": f"{start + 1:02d}:30",
                                                         "room": f"Room {101 + i}"})

        students = {}  # batch -> [student_id]
        phone = 9000000000
        for bname, bid in batches.items():
            students[bname] = []
            for n in range(8):
                nm = f"{self.rnd.choice(FIRST)} {self.rnd.choice(LAST)}"
                phone += 1
                out = self.call("post", "/api/students", {
                    "name": nm, "batch_id": bid, "father_name": f"Mr. {nm.split()[1]}", "parent_phone": str(phone),
                    "parent_name": f"Mr. {nm.split()[1]}", "phone": "7" + str(phone)[1:],
                    "dob": "2008-05-15", "school": "City Public School", "address": "Civil Lines"})
                students[bname].append(out["student_id"])
        # one parent with two children (sibling login demo)
        sib = self.call("post", "/api/students", {"name": "Aarohi Sharma", "batch_id": batches["Foundation Class 10"],
                                                  "parent_phone": "9000000001", "father_name": "Mr. Sharma"})
        students["Foundation Class 10"].append(sib["student_id"])
        self._demo_password()

        # fees: 3 instalments per batch, first two mostly paid
        for name, course, fee, _ in plan:
            bid = batches[name]
            for i, title in enumerate(("Instalment 1", "Instalment 2", "Instalment 3")):
                due = today - timedelta(days=75 - 40 * i)
                self.call("post", "/api/fees/assign", {"batch_id": bid, "title": title, "amount": fee // 3,
                                                       "due_date": iso(due)})
        self.login("TCI-A001")
        for f in self.call("get", "/api/fees")["fees"]:
            roll = self.rnd.random()
            if f["title"] == "Instalment 3" and roll < 0.8:
                continue
            if f["title"] == "Instalment 2" and roll < 0.25:
                continue
            amt = f["amount"] if roll > 0.15 else f["amount"] // 2
            self.call("post", "/api/payments", {"fee_id": f["id"], "amount": amt,
                                                "mode": self.rnd.choice(["cash", "upi", "upi", "cheque", "bank"]),
                                                "paid_on": iso(max(today - timedelta(days=self.rnd.randint(0, 60)),
                                                                   date.fromisoformat(f["due_date"]) - timedelta(days=15)))})
        for cat, amt, vendor in [("Salary", 180000, "Staff payroll"), ("Rent", 65000, "Building owner"),
                                 ("Electricity", 14800, "State Electricity Board"), ("Internet", 2400, "Fibernet"),
                                 ("Printing & Stationery", 9600, "Sharma Printers"), ("Marketing", 22000, "City Pamphlets")]:
            self.call("post", "/api/expenses", {"category": cat, "amount": amt, "vendor": vendor,
                                                "date": iso(today - timedelta(days=self.rnd.randint(0, 20)))})
        for n, p, c, s in [("Rahul Chauhan", "9811111111", "JEE 2027 Dropper", "Hoarding"),
                           ("Meera Bansal", "9822222222", "NEET 2027 Target", "Friend referral"),
                           ("Sandeep Nair", "9833333333", "Foundation Class 10", "Instagram")]:
            self.call("post", "/api/enquiries", {"name": n, "phone": p, "course": c, "source": s,
                                                 "follow_up": iso(today + timedelta(days=self.rnd.randint(-1, 3)))})

        # teachers: attendance, homework, material, tests, notices
        for key, bnames in (("phy", list(batches)), ("che", list(batches)[:2]), ("mat", [list(batches)[0], list(batches)[2]])):
            self.login(staff[key]["login_id"])
            for bname in bnames:
                bid, sids = batches[bname], students[bname]
                for back in range(1, 22):
                    d = today - timedelta(days=back)
                    if d.weekday() == 6 or key != "phy":
                        continue
                    recs = [{"student_id": s, "status": "A" if self.rnd.random() < 0.12 else "P"} for s in sids]
                    self.call("post", "/api/attendance", {"batch_id": bid, "date": iso(d), "records": recs})
                sub = subj[{"phy": "Physics", "che": "Chemistry", "mat": "Mathematics"}[key]]
                self.call("post", "/api/homework", {"batch_id": bid, "subject_id": sub, "title": {"phy": "Physics", "che": "Chemistry", "mat": "Maths"}[key] + " - DPP 12",
                                                    "description": "Solve all questions of DPP 12 and bring doubts.",
                                                    "due_date": iso(today + timedelta(days=2))})
                self.call("post", "/api/materials", {"batch_id": bid, "subject_id": sub, "title": {"phy": "Physics", "che": "Chemistry", "mat": "Maths"}[key] + " notes - Unit 3",
                                                     "kind": "pdf", "url": "https://example.com/notes-unit3.pdf"})
                for i in range(3):
                    tid = self.call("post", "/api/tests", {"batch_id": bid, "subject_id": sub, "name": f"Unit Test {i + 1}",
                                                           "date": iso(today - timedelta(days=40 - 14 * i)),
                                                           "max_marks": 100})["id"]
                    base = self.rnd.randint(35, 70)
                    recs = [{"student_id": s, "marks": max(0, min(100, int(self.rnd.gauss(base + 4 * i, 15))))}
                            if self.rnd.random() > 0.05 else {"student_id": s, "absent": True} for s in sids]
                    self.call("post", f"/api/tests/{tid}/marks", {"records": recs})
                    self.call("post", f"/api/tests/{tid}/publish", {})
        # online MCQ test by physics teacher
        self.login(staff["phy"]["login_id"])
        bid = batches["JEE 2027 Dropper"]
        tid = self.call("post", "/api/tests", {"batch_id": bid, "subject_id": subj["Physics"], "mode": "online",
                                               "name": "Online Quiz - Kinematics", "date": iso(today), "duration_min": 20})["id"]
        qs = [("A car moves at 20 m/s. Distance in 5 s?", "50 m", "100 m", "20 m", "4 m", "B"),
              ("SI unit of force is", "Joule", "Newton", "Watt", "Pascal", "B"),
              ("Acceleration due to gravity near Earth (m/s^2)", "9.8", "1.6", "3.7", "24.8", "A"),
              ("Which is a vector quantity?", "Speed", "Mass", "Velocity", "Time", "C"),
              ("Work done is zero when angle between force and displacement is", "0 deg", "45 deg", "90 deg", "180 deg", "C")]
        self.call("post", f"/api/tests/{tid}/questions", {"questions": [
            {"text": a, "a": b, "b": c, "c": d, "d": e, "answer": f, "marks": 4, "neg": 1} for a, b, c, d, e, f in qs]})
        self.call("post", f"/api/tests/{tid}/publish", {})
        self.call("post", "/api/notices", {"title": "Sunday doubt class at 10 AM", "body": "Bring your DPP copy.",
                                           "audience": "students", "batch_id": bid})
        # student: doubt, leave
        sl = self.call("get", f"/api/students/{students['JEE 2027 Dropper'][0]}")["student"]  # child of parent 9000000001
        self.login(sl["login_id"])
        self.call("post", "/api/doubts", {"subject_id": subj["Physics"], "question": "Sir, why is displacement a vector?"})
        # office: notice, PTM, reminder
        self.login("TCI-A002")
        self.call("post", "/api/notices", {"title": "Fee due date reminder", "body": "Please clear Instalment 3 by month-end "
                                           "to avoid late fee.", "audience": "parents", "pinned": True})
        self.call("post", "/api/ptm", {"title": "PTM - Term 1 Review", "date": iso(today + timedelta(days=5)),
                                       "start_time": "10:00", "end_time": "12:00", "slot_minutes": 15,
                                       "batch_id": batches["JEE 2027 Dropper"], "note": "Please bring the report card.",
                                       "mode": "online", "meeting_link": "https://meet.example.com/tagore-ptm-term1"})
        # parent: chat with the physics teacher + a suggestion
        self.login("9000000002")
        me = self.call("get", "/api/me")["user"]
        kid = me["children"][0]
        self.call("post", "/api/messages", {"student_id": kid["id"], "teacher_user_id": t["phy"],
                                            "body": "Sir, my son is finding kinematics difficult. Any extra practice?"})
        self.call("post", "/api/complaints", {"category": "facility", "student_id": kid["id"],
                                              "body": "Classroom AC is not working in the afternoon batch."})
        self.c.post("/api/logout")
        self._demo_password()
        import json as _json
        con = db.connect(self.app.config["DB_PATH"])
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_logins',?)", (_json.dumps({
            "password": DEMO_PASSWORD,
            "logins": [["Student", sl["login_id"]], ["Parent", "9000000001"], ["Teacher", staff["phy"]["login_id"]],
                       ["Office staff", "TCI-A001"], ["Director", "director"]]}),))
        con.commit()
        con.close()
        return {"director": "director", "office": ["TCI-A001", "TCI-A002"], "teachers": [staff[k]["login_id"] for k in
                ("phy", "che", "mat", "bio", "eng")], "student": sl["login_id"], "parent": "9000000001",
                "password": DEMO_PASSWORD}

    def _demo_password(self):
        con = db.connect(self.app.config["DB_PATH"])
        con.execute("UPDATE users SET password_hash=?, must_change=0", (generate_password_hash(DEMO_PASSWORD),))
        con.commit()
        con.close()


def seed_demo(app: Flask) -> dict:
    return Seeder(app).run()
