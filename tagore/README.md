# Tagore Career Institute - Ecosystem (Student · Parent · Teacher · Office · Director)

Ek hi app, 5 alag login. Phone par bhi chalta hai (install-able web app / PWA), computer par bhi.

## Chalane ka tarika
```
pip install -r requirements.txt
python run_tagore.py demo               # demo data ke saath (fresh folder me) -> http://127.0.0.1:5800
python run_tagore.py create-director    # asli use: pehla director login banao
python run_tagore.py --host 0.0.0.0     # same WiFi ke phones se kholne ke liye
```
Data `./tagore-data/` me rehta hai (`TAGORE_DATA=/path` se badal sakte ho). Internet par daalte time HTTPS lagao aur
`TAGORE_HTTPS=1` set karo.

Demo me login screen par har role ka button aata hai (password `demo1234`). Demo sirf `demo` command se bane database
me dikhta hai, asli database me nahi.

## Kaun kya kar sakta hai
| | Student | Parent | Teacher | Office (admin) | Director |
|---|:-:|:-:|:-:|:-:|:-:|
| Dashboard, notices, notifications | ✅ | ✅ | ✅ | ✅ | ✅ |
| Attendance dekhna / lagana | dekhna | dekhna | **lagana** (apne batch) | – | – |
| Timetable | dekhna | dekhna | dekhna | **banana** | **banana** |
| Homework / study material | dekhna | dekhna | **dena** | – | – |
| Tests: paper marks / OMR CSV import / online MCQ | dena, result | result | **banana, marks, publish** | – | – |
| Doubts | **poochna** | dekhna | **answer** | – | – |
| Fees, receipt (print/PDF) | dekhna | dekhna | ❌ | **collect, due, reminder** | + **discount** |
| Accounts: ledger, expenses | – | – | – | ✅ | ✅ (delete bhi) |
| Admission enquiries → admission (login auto-ban jaate hain) | – | – | – | ✅ | ✅ |
| PTM | – | **slot book/change/cancel, rating** | **remarks, brief** | **schedule, report, reminder** | ✅ |
| Parent-Teacher chat (private) | ✅ | ✅ | ✅ | ❌ (office nahi padh sakta) | ❌ |
| Meeting request, complaint/suggestion | – | ✅ | meeting jawab | complaint jawab | ✅ |
| Leave | apply | apply | apply, student leave approve | approve | approve |
| Report card (print) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Staff logins, activity log, settings, analytics | – | – | – | – | ✅ |

## PTM Connect-style features
PTM event (offline ya online video link) → har teacher ke slots auto-bante hain → parents ko notification →
parent bachche ke teachers ke slot book / **time change** / cancel karta hai → ek slot do log nahi le sakte, ek parent ek
time par do jagah nahi ho sakta → **24 ghante pehle reminder** (parent + teacher) → teacher ko meeting se pehle student
ka **brief** (attendance %, average score, pichhle remarks) → meeting ke baad teacher ke remarks + parent aaya ya nahi →
parent rating → office ko **PTM report** (kitne families ne book kiya, no-show, teacher-wise rating, jinhone book nahi kiya
unko ek click me reminder). PTM ke bahar: parent **meeting request** bhej sakta hai, aur teacher se **private chat**.

> Note: `ptmconnect.com` is build ke time open nahi ho paya, isliye ye features aam PTM-app wali list se banaye gaye hain,
> us site ki exact list se nahi. Agar us site ka koi feature chhoot gaya ho to bata do.

## Suraksha (security) jo laga hai
* Passwords hashed. Naye student/parent/staff ko random temporary password milta hai, pehle login par badalna padta hai.
* 5 galat password ke baad 10 minute lock. Disable kiya hua user ka login turant band.
* Har endpoint par role + ownership check (parent sirf apne bachche ka data dekh sakta hai, teacher sirf apne batch ka).
* Fee discount sirf director; expense delete sirf director; sab important kaam **activity log** me.
* Online test: jawab server par check hote hain, student ko sahi answer submit ke baad hi dikhta hai, time khatam hone ke baad
  submit karne par score 0.

## Developer notes
```
tagore/db.py              schema (SQLite)          tagore/core.py        permissions, validation, notifications
tagore/routes_people.py   login, staff, batches, students, timetable
tagore/routes_learning.py attendance, homework, material, doubts, tests (paper + online)
tagore/routes_comms.py    notices, notifications, PTM, leave
tagore/routes_connect.py  PTM reschedule/reminders/report, meeting requests, chat, complaints, remarks, report card
tagore/routes_finance.py  fees, payments, receipts, expenses, ledger, enquiries
tagore/routes_reports.py  dashboards + director overview
tagore/static/*           UI (plain JavaScript, no build step)       tagore/seed.py  demo data
pytest tests/test_tagore.py
```

## Abhi nahi bana (agle steps)
Hindi/English language toggle · SMS / WhatsApp alerts (abhi sirf in-app notifications) · online payment gateway (abhi
office par collection) · video lecture hosting (abhi links) · Play Store / App Store app (abhi install-able web app) ·
OMR Reader se direct import (abhi CSV paste) · biometric / QR attendance · staff payroll · transport & hostel.
