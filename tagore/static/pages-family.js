/* Student + parent screens, and pages shared by every role (timetable, homework, material, doubts, messages, leaves, notices, report) */
"use strict";
const reg = (id, roles, fn) => roles.forEach(r => { P[id + ":" + r] = fn; });
const FAM = ["student", "parent"];

/* ============ dashboard ============ */
reg("dashboard", FAM, async el => {
  const d = await api("/dashboard" + kidQ());
  const a = d.attendance.percent, dayN = { P: "Present", A: "Absent", L: "Leave" };
  el.innerHTML = `<div class="card"><h2>${esc(d.student.name)}</h2><div class="muted">${esc(d.student.batch || "")} · Roll ${esc(d.student.roll)}</div></div>
    <div class="grid gap">${tile(pct(a), "Attendance", tone(a))}${tile(inr(d.fees.due), "Fees pending" + (d.fees.overdue ? ` (${inr(d.fees.overdue)} overdue)` : ""), d.fees.overdue ? "bad" : d.fees.due ? "warn" : "ok")}
    ${tile(d.homework.length, "Homework due", d.homework.length ? "warn" : "")}${tile(d.recent_tests.length ? d.recent_tests[0].marks + "/" + d.recent_tests[0].max_marks : "–", d.recent_tests.length ? "Latest: " + d.recent_tests[0].name : "No results yet")}</div>
    ${d.open_tests.length && S.user.role === "student" ? `<div class="card"><h2>🧪 Online tests waiting</h2>${d.open_tests.map(t => `<div class="row"><b class="grow">${esc(t.name)} <span class="muted small">(${t.duration_min} min)</span></b><button class="primary" data-act="exam" data-id="${t.id}">Start</button></div>`).join("")}</div>` : ""}
    ${d.ptm.length ? `<div class="card"><h2>🤝 Parent-Teacher Meeting</h2>${d.ptm.map(p => `<div class="row"><b class="grow">${esc(p.title)} · ${fd(p.date)}</b>${S.user.role === "parent" ? '<a class="btn" href="#/ptm">Book slot</a>' : ""}</div>`).join("")}</div>` : ""}
    <div class="grid g2 gap"><div class="card"><h2>Today's classes</h2>${d.classes_today.length ? `<div class="list">${d.classes_today.map(c => `<div><b>${esc(c.subject)}</b> <span class="muted">${ft(c.start_time)}–${ft(c.end_time)}</span><div class="small muted">${esc(c.teacher || "")} ${c.room ? "· " + esc(c.room) : ""}</div></div>`).join("")}</div>` : '<div class="empty">No class today</div>'}</div>
    <div class="card"><h2>Homework</h2>${d.homework.length ? `<div class="list">${d.homework.map(h => `<div><b>${esc(h.title)}</b> <span class="muted small">due ${fdShort(h.due_date)}</span></div>`).join("")}</div>` : '<div class="empty">All clear 🎉</div>'}</div>
    <div class="card"><h2>Last 7 days</h2><div class="row">${d.attendance.last7.length ? d.attendance.last7.map(x => `${badge(fdShort(x.date) + " " + dayN[x.status], x.status === "P" ? "ok" : x.status === "A" ? "bad" : "warn")}`).join("") : '<span class="muted">No attendance yet</span>'}</div></div>
    <div class="card"><h2>Notices</h2>${d.notices.length ? `<div class="list">${d.notices.map(n => `<div>${esc(n.title)} <span class="muted small">${fdShort(n.created_at)}</span></div>`).join("")}</div>` : '<div class="empty">No notices</div>'}</div></div>`;
  bind(el, { exam: x => startExam(Number(x.id)) });
});

/* ============ attendance ============ */
reg("attendance", FAM, async el => {
  let month = todayISO().slice(0, 7);
  const draw = async () => {
    const r = await api(`/attendance/student/${S.kid}?month=${month}`);
    const [y, m] = month.split("-").map(Number), first = (new Date(y, m - 1, 1).getDay() + 6) % 7, n = new Date(y, m, 0).getDate();
    const map = Object.fromEntries(r.records.map(x => [x.date, x.status])), o = r.overall;
    el.innerHTML = `${pagehead("Attendance")}<div class="grid">${tile(pct(o.percent), "Overall attendance", tone(o.percent))}${tile(o.present, "Days present", "ok")}${tile(o.absent, "Days absent", o.absent ? "bad" : "")}${tile(o.leave, "On leave")}</div>
      <div class="card"><div class="row"><button data-act="prev">◀</button><b class="grow center">${new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</b><button data-act="next">▶</button></div>
      <div class="cal gap">${["M", "T", "W", "T", "F", "S", "S"].map(d => `<div class="h">${d}</div>`).join("")}${Array(first).fill("<div class='h'></div>").join("")}${Array.from({ length: n }, (_, i) => { const dd = `${month}-${String(i + 1).padStart(2, "0")}`; return `<div class="${map[dd] || ""}" title="${dd}">${i + 1}</div>`; }).join("")}</div>
      <p class="small muted">🟢 Present · 🔴 Absent · 🟡 Leave · blank = no class / not marked</p></div>`;
  };
  bind(el, { prev: () => { const [y, m] = month.split("-").map(Number); month = new Date(y, m - 2, 1).toISOString().slice(0, 7); draw(); }, next: () => { const [y, m] = month.split("-").map(Number); month = new Date(y, m, 1).toISOString().slice(0, 7); draw(); } });
  await draw();
});

/* ============ timetable (everyone) ============ */
P.timetable = async el => {
  const r = await api("/timetable" + (isFamily() ? kidQ() : ""));
  const wd = (new Date().getDay() + 6) % 7;
  el.innerHTML = pagehead("Weekly timetable") + (r.timetable.length ? DAYS.map((d, i) => {
    const rows = r.timetable.filter(t => t.weekday === i); if (!rows.length) return "";
    return `<div class="card"><h3>${d} ${i === wd ? badge("Today", "ok") : ""}</h3><div class="list">${rows.map(t => `<div class="row"><b style="min-width:120px">${ft(t.start_time)}–${ft(t.end_time)}</b><span class="grow"><b>${esc(t.subject)}</b> <span class="muted">${esc(t.batch)}${t.teacher && S.user.role !== "teacher" ? " · " + esc(t.teacher) : ""}${t.room ? " · " + esc(t.room) : ""}</span></span></div>`).join("")}</div></div>`;
  }).join("") : '<div class="card empty">Timetable not published yet</div>');
};

/* ============ homework (everyone; teachers/office can post) ============ */
P.homework = async el => {
  const canPost = S.user.role === "teacher" || isOffice();
  const r = await api("/homework" + (isFamily() ? kidQ() : ""));
  el.innerHTML = pagehead("Homework", canPost ? '<button class="primary" data-act="add">+ Give homework</button>' : "") +
    (r.homework.length ? `<div class="grid g2">${r.homework.map(h => {
      const st = !h.due_date ? "" : h.due_date < r.today ? badge("Past due", "bad") : h.due_date === r.today ? badge("Due today", "warn") : badge("Due " + fdShort(h.due_date), "ok");
      return `<div class="card"><div class="row"><b class="grow">${esc(h.title)}</b>${st}</div><div class="small muted">${esc(h.subject || "")} · ${esc(h.batch)} · ${esc(h.teacher || "")}</div><p>${esc(h.description)}</p>${canPost ? `<button class="sm danger" data-act="del" data-id="${h.id}">Delete</button>` : ""}</div>`;
    }).join("")}</div>` : '<div class="card empty">No homework</div>');
  bind(el, {
    add: async () => { const [b, s] = await Promise.all([api("/batches"), api("/subjects")]); openForm({ title: "New homework", fields: [
      { name: "batch_id", label: "Batch", type: "select", required: true, options: optionsOf(b.batches) }, { name: "subject_id", label: "Subject", type: "select", options: optionsOf(s.subjects) },
      { name: "title", label: "Title", required: true }, { name: "description", label: "Details", type: "textarea" }, { name: "due_date", label: "Due date", type: "date", value: "" }],
      submit: v => api("/homework", "POST", v) }); },
    del: async x => { if (confirm("Delete this homework?")) { await api("/homework/" + x.id, "DELETE"); render(); } }
  });
};

/* ============ study material ============ */
P.material = async el => {
  const canPost = S.user.role === "teacher" || isOffice();
  const r = await api("/materials" + (isFamily() ? kidQ() : ""));
  const ico = { note: "📄", video: "🎬", dpp: "📝", pdf: "📕", link: "🔗" };
  el.innerHTML = pagehead("Study material", canPost ? '<button class="primary" data-act="add">+ Add material</button>' : "") +
    table([["", m => ico[m.kind]], ["Title", m => `<b>${esc(m.title)}</b><div class="small muted">${esc(m.subject || "")} · ${esc(m.batch)}</div>`], ["Added", m => fdShort(m.created_at)],
      ["", m => `<a class="btn sm" href="${safeUrl(m.url)}" target="_blank" rel="noopener noreferrer">Open</a> ${canPost ? `<button class="sm danger" data-act="del" data-id="${m.id}">✕</button>` : ""}`]], r.materials, "No study material yet");
  bind(el, {
    add: async () => { const [b, s] = await Promise.all([api("/batches"), api("/subjects")]); openForm({ title: "Add study material", intro: '<p class="muted small">Paste a link (Google Drive, YouTube, PDF…).</p>', fields: [
      { name: "batch_id", label: "Batch", type: "select", required: true, options: optionsOf(b.batches) }, { name: "subject_id", label: "Subject", type: "select", options: optionsOf(s.subjects) },
      { name: "title", label: "Title", required: true }, { name: "kind", label: "Type", type: "select", required: true, options: [["note", "Notes"], ["pdf", "PDF"], ["dpp", "DPP / practice sheet"], ["video", "Video lecture"], ["link", "Other link"]] },
      { name: "url", label: "Link (https://…)", required: true }], submit: v => api("/materials", "POST", v) }); },
    del: async x => { if (confirm("Remove this material?")) { await api("/materials/" + x.id, "DELETE"); render(); } }
  });
};

/* ============ tests & results (student / parent) ============ */
reg("tests", FAM, async el => {
  const [t, res] = await Promise.all([api("/tests" + kidQ()), api(`/students/${S.kid}/results`)]);
  const isStudent = S.user.role === "student", got = Object.fromEntries(res.results.map(x => [x.id, x]));
  el.innerHTML = pagehead("Tests & results") + (res.results.length ? `<div class="card"><h2>Progress</h2>${columns(res.results.map(x => ({ label: fdShort(x.date), value: x.percent })), 100)}<p class="small muted">Score % in each test (latest on the right)</p></div>` : "") +
    `<div class="gap"></div>` + table([["Test", x => `<b>${esc(x.name)}</b><div class="small muted">${esc(x.subject || "")} · ${fd(x.date)} · ${x.mode === "online" ? "Online" : "Paper"}</div>`],
      ["Score", x => got[x.id] ? `<b>${got[x.id].marks}</b> / ${x.max_marks} <span class="muted">(${got[x.id].percent}%)</span>` : x.mode === "online" && !x.attempted ? badge("Not attempted", "warn") : "–", "num"],
      ["Rank", x => got[x.id] ? `#${got[x.id].rank} <span class="muted small">of ${got[x.id].students}</span>` : "–", "num"],
      ["", x => x.mode === "online" ? (x.attempted ? `<button class="sm" data-act="review" data-id="${x.id}">Review answers</button>` : isStudent ? `<button class="sm primary" data-act="exam" data-id="${x.id}">Start (${x.duration_min} min)</button>` : "") : got[x.id] ? `<button class="sm" data-act="detail" data-id="${x.id}">Details</button>` : ""]], t.tests, "No tests published yet");
  bind(el, {
    exam: x => startExam(Number(x.id)),
    detail: x => { const g = got[x.id], tt = t.tests.find(q => q.id === Number(x.id));
      modal(`<h2>${esc(tt.name)}</h2>${bars([{ label: "You", value: g.percent }, { label: "Class average", value: g.average ? Math.round(1000 * g.average / tt.max_marks) / 10 : null }, { label: "Topper", value: Math.round(1000 * g.highest / tt.max_marks) / 10 }], { tone })}
        <p>Your marks: <b>${g.marks}/${tt.max_marks}</b> · Rank <b>#${g.rank}</b> of ${g.students}</p><div class="row"><button data-close>Close</button></div>`); },
    review: async x => { const r = await api(`/tests/${x.id}/review` + kidQ()); modal(`<h2>Answer review · ${r.score} marks${r.late ? " (late - 0)" : ""}</h2>${r.questions.map((q, i) => `<div class="card"><b>${i + 1}. ${esc(q.text)}</b>${Object.entries(q.options).map(([k, v]) => `<div class="${k === q.correct ? "badge ok" : k === q.given ? "badge bad" : ""}" style="display:block;margin:.2rem 0">${k}. ${esc(v)}${k === q.correct ? " ✔" : k === q.given ? " ✘ your answer" : ""}</div>`).join("")}</div>`).join("")}<div class="row gap"><button data-close>Close</button></div>`, { wide: true }); }
  });
});

/* ---- online exam runner ---- */
async function startExam(tid) {
  const paper = await api(`/tests/${tid}/start`, "POST", {});
  const key = "tci_exam_" + tid, saved = { ...paper.saved, ...(JSON.parse(localStorage.getItem(key) || "{}")) };
  let left = paper.seconds_left, done = false;
  const m = modal(`<div class="row"><h2 class="grow">${esc(paper.test.name)}</h2><b id="clock" class="badge warn" style="font-size:1rem"></b></div>
    <p class="small muted">Correct answer gives marks, wrong answer cuts marks, unattempted = 0. The test auto-submits when time ends.</p>
    ${paper.questions.map((q, i) => `<div class="card"><b>${i + 1}. ${esc(q.text)}</b> <span class="small muted">(+${q.marks} / −${q.neg})</span>
      ${Object.entries(q.options).map(([k, v]) => `<label class="chk"><input type="radio" name="q${q.id}" value="${k}" ${saved[q.id] === k ? "checked" : ""}> ${k}. ${esc(v)}</label>`).join("")}
      <button type="button" class="sm" data-clear="${q.id}">Clear</button></div>`).join("")}
    <div class="row gap"><button class="primary" id="sub">Submit test</button></div>`, { wide: true, locked: true });
  const collect = () => { const a = {}; paper.questions.forEach(q => { const c = $(`input[name=q${q.id}]:checked`, m.el); if (c) a[q.id] = c.value; }); return a; };
  m.el.addEventListener("change", () => localStorage.setItem(key, JSON.stringify(collect())));
  m.el.addEventListener("click", e => { const c = e.target.dataset.clear; if (c) { $$(`input[name=q${c}]`, m.el).forEach(i => i.checked = false); localStorage.setItem(key, JSON.stringify(collect())); } });
  const submit = async auto => {
    if (done) return; if (!auto && !confirm("Submit the test now?")) return; done = true; clearInterval(timer);
    try { const r = await api(`/tests/${tid}/submit`, "POST", { answers: collect() }); localStorage.removeItem(key); m.close();
      modal(`<h2>${r.late ? "Time was over" : "Test submitted ✔"}</h2><p>Your score: <b>${r.score} / ${r.max_marks}</b></p><div class="row"><button class="primary" data-close>OK</button></div>`); render(); }
    catch (e) { done = false; fail(e); }
  };
  const tick = () => { const mm = Math.floor(left / 60), ss = left % 60; $("#clock", m.el).textContent = `⏱ ${mm}:${String(ss).padStart(2, "0")}`; if (left <= 0) submit(true); left--; };
  const timer = setInterval(tick, 1000); tick();
  $("#sub", m.el).onclick = () => submit(false);
}

/* ============ doubts ============ */
P.doubts = async el => {
  const r = await api("/doubts"), role = S.user.role, canAnswer = role === "teacher" || isOffice();
  el.innerHTML = pagehead("Doubts", role === "student" ? '<button class="primary" data-act="ask">+ Ask a doubt</button>' : "") +
    (r.doubts.length ? r.doubts.map(d => `<div class="card"><div class="row"><b class="grow">${esc(d.question)}</b>${d.answer ? badge("Answered", "ok") : badge("Waiting", "warn")}</div>
      <div class="small muted">${esc(d.student)} · ${esc(d.subject || "General")} · ${fdShort(d.created_at)}</div>
      ${d.answer ? `<div class="gap"><b>Answer</b> <span class="small muted">by ${esc(d.answered_by)}</span><p>${esc(d.answer)}</p></div>` : (canAnswer ? `<button class="sm primary" data-act="answer" data-id="${d.id}">Answer</button>` : "")}</div>`).join("") : '<div class="card empty">No doubts yet</div>');
  bind(el, {
    ask: async () => { const s = await api("/subjects"); openForm({ title: "Ask your teacher", fields: [{ name: "subject_id", label: "Subject", type: "select", options: optionsOf(s.subjects) }, { name: "question", label: "Your doubt", type: "textarea", required: true }], submit: v => api("/doubts", "POST", v), label: "Send" }); },
    answer: x => openForm({ title: "Answer doubt", fields: [{ name: "answer", label: "Answer", type: "textarea", required: true }], submit: v => api(`/doubts/${x.id}/answer`, "POST", v), label: "Send answer" })
  });
};

/* ============ fees (student / parent) ============ */
reg("fees", FAM, async el => {
  const r = await api("/fees" + kidQ());
  const tot = r.fees.reduce((a, f) => ({ pay: a.pay + f.amount - f.discount, paid: a.paid + f.paid, due: a.due + Math.max(0, f.due) }), { pay: 0, paid: 0, due: 0 });
  el.innerHTML = pagehead("Fees") + `<div class="grid">${tile(inr(tot.pay), "Total payable")}${tile(inr(tot.paid), "Paid", "ok")}${tile(inr(tot.due), "Pending", tot.due ? "bad" : "ok")}</div><div class="gap"></div>` +
    table([["Instalment", f => `<b>${esc(f.title)}</b>`], ["Due date", f => fd(f.due_date)], ["Amount", f => inr(f.amount - f.discount) + (f.discount ? `<div class="small muted">after ${inr(f.discount)} discount</div>` : ""), "num"],
      ["Paid", f => inr(f.paid), "num"], ["Pending", f => inr(Math.max(0, f.due)), "num"], ["Status", f => statusBadge(f.status)],
      ["Receipts", f => f.payments.map(p => `<button class="sm" data-act="rcpt" data-id="${p.id}">${esc(p.receipt_no)}</button>`).join(" ")]], r.fees, "No fee entries") +
    '<p class="muted small">Pay at the institute office by cash / UPI / cheque. The receipt appears here as soon as the office records your payment.</p>';
  bind(el, { rcpt: showReceipt });
});
async function showReceipt(x) {
  const { receipt: r } = await api(`/payments/${x.id}/receipt`);
  printDialog(`<div class="center"><h2>${esc(r.institute)}</h2><div class="muted small">${esc(r.address)}</div><h3>FEE RECEIPT</h3></div>
    <table><tr><td>Receipt no.</td><td><b>${esc(r.receipt_no)}</b></td><td>Date</td><td>${fd(r.paid_on)}</td></tr>
    <tr><td>Student</td><td><b>${esc(r.student)}</b></td><td>Roll / ID</td><td>${esc(r.roll)}</td></tr><tr><td>Batch</td><td>${esc(r.batch || "")}</td><td>For</td><td>${esc(r.title)}</td></tr>
    <tr><td>Mode</td><td>${esc(r.mode.toUpperCase())} ${esc(r.ref || "")}</td><td>Received by</td><td>${esc(r.received_by || "")}</td></tr>
    <tr><td><b>Amount received</b></td><td colspan="3"><b style="font-size:1.3rem">${inr(r.amount)}</b></td></tr><tr><td>Balance of this instalment</td><td colspan="3">${inr(r.balance)}</td></tr></table>
    <p class="small muted center">This is a computer generated receipt.</p>`);
}

/* ============ PTM (parent) ============ */
reg("ptm", ["parent", "student"], async el => {
  const r = await api("/ptm"), isParent = S.user.role === "parent", kids = S.user.children;
  const mineAll = r.events.flatMap(e => e.slots.filter(s => s.mine).map(s => ({ ...s, ev: e })));
  el.innerHTML = pagehead("Parent-Teacher Meetings") + (isParent ? "" : '<div class="card muted">Parents book PTM slots. Ask your parent to open this page.</div>') +
    (mineAll.length ? `<div class="card"><h2>My bookings</h2><div class="list">${mineAll.map(s => `<div><div class="row"><b class="grow">${fd(s.ev.date)} · ${ft(s.slot_time)} with ${esc(s.teacher)} <span class="muted">${esc(s.subject || "")}</span></b>${statusBadge(s.status)}</div>
      <div class="small muted">For ${esc(s.student)} · ${s.ev.mode === "online" ? "Online" : "At the institute"}</div>
      ${s.ev.mode === "online" && s.ev.meeting_link ? `<a class="btn sm primary" href="${safeUrl(s.ev.meeting_link)}" target="_blank" rel="noopener noreferrer">Join video meeting</a>` : ""}
      ${s.remarks ? `<p><b>Teacher's remarks:</b> ${esc(s.remarks)}</p>` : ""}
      ${s.status === "booked" ? `<button class="sm" data-act="resched" data-id="${s.id}" data-ev="${s.ev.id}">Change time</button> <button class="sm danger" data-act="cancel" data-id="${s.id}">Cancel</button>` : ""}
      ${s.status === "done" && !s.feedback_rating ? `<button class="sm primary" data-act="fb" data-id="${s.id}">Rate this meeting</button>` : s.feedback_rating ? `<span class="small muted">Your rating: ${"★".repeat(s.feedback_rating)}</span>` : ""}</div>`).join("")}</div></div>` : "") +
    (r.events.length ? r.events.map(e => {
      const by = {}; e.slots.forEach(s => (by[s.teacher] ||= []).push(s));
      return `<div class="card"><h2>${esc(e.title)}</h2><div class="muted">${fd(e.date)} · ${ft(e.start_time)}–${ft(e.end_time)} · ${e.slot_minutes} min each · ${e.mode === "online" ? "💻 Online" : "🏫 At institute"}</div>${e.note ? `<p>${esc(e.note)}</p>` : ""}
        ${Object.entries(by).map(([t, ss]) => `<div class="gap"><b>${esc(t)}</b> <span class="muted small">${esc(ss[0].subject || "")}</span><div class="row gap" style="margin-top:.3rem">${ss.map(s => s.mine ? `<button class="sm primary" disabled>${ft(s.slot_time)} ✔ yours</button>` : s.status === "open" && isParent ? `<button class="sm" data-act="book" data-id="${s.id}">${ft(s.slot_time)}</button>` : `<button class="sm" disabled style="text-decoration:line-through">${ft(s.slot_time)}</button>`).join("")}</div></div>`).join("")}</div>`;
    }).join("") : '<div class="card empty">No PTM scheduled right now</div>');
  const pickKid = async () => kids.length === 1 ? kids[0].id : new Promise(res => openForm({ title: "Which child is this meeting for?", fields: [{ name: "k", label: "Child", type: "select", required: true, options: optionsOf(kids), value: S.kid }], submit: v => { res(Number(v.k)); return true; }, label: "Continue" }));
  bind(el, {
    book: async x => { const kid = await pickKid(); await api(`/ptm/slots/${x.id}/book`, "POST", { student_id: kid }); toast("Slot booked ✔", "ok"); render(); },
    cancel: async x => { if (confirm("Cancel this meeting?")) { await api(`/ptm/slots/${x.id}/cancel`, "POST", {}); render(); } },
    resched: x => { const ev = r.events.find(e => e.id === Number(x.ev)); const opts = ev.slots.filter(s => s.status === "open").map(s => [s.id, `${ft(s.slot_time)} · ${s.teacher}`]);
      if (!opts.length) return toast("No free slots to move to", "bad");
      openForm({ title: "Change meeting time", fields: [{ name: "to", label: "New slot", type: "select", required: true, options: opts }], submit: v => api(`/ptm/slots/${x.id}/reschedule`, "POST", { to_slot_id: Number(v.to) }) }); },
    fb: x => openForm({ title: "How was the meeting?", fields: [{ name: "rating", label: "Rating (1-5)", type: "number", required: true, min: 1, max: 5 }, { name: "text", label: "Comment (optional)", type: "textarea" }], submit: v => api(`/ptm/slots/${x.id}/feedback`, "POST", v) })
  });
});

/* ============ request a meeting (parent) ============ */
reg("meet", ["parent"], async el => {
  const [r, b] = await Promise.all([api("/meeting-requests"), api("/batches")]);
  el.innerHTML = pagehead("Request a meeting", '<button class="primary" data-act="new">+ New request</button>') + '<p class="muted">Need to talk to a teacher outside the PTM day? Send a request - the teacher will confirm a time.</p>' +
    table([["Teacher", q => `<b>${esc(q.teacher)}</b><div class="small muted">for ${esc(q.student)}</div>`], ["Reason", q => esc(q.reason)], ["Status", q => statusBadge(q.status)],
      ["When", q => q.meet_on ? `${fd(q.meet_on)} ${ft(q.meet_time)}<div class="small muted">${esc(q.teacher_note || "")}</div>` : esc(q.teacher_note || "")]], r.requests, "No requests yet");
  bind(el, { new: () => {
    const kid = S.user.children.find(k => k.id === S.kid), batch = b.batches.find(x => x.id === kid?.batch_id);
    openForm({ title: "Request a meeting for " + (kid?.name || ""), fields: [{ name: "teacher_user_id", label: "Teacher", type: "select", required: true, options: (batch?.subjects || []).filter(s => s.teacher_user_id).map(s => [s.teacher_user_id, `${s.teacher} (${s.subject})`]) },
      { name: "reason", label: "What do you want to discuss?", type: "textarea", required: true }, { name: "preferred_date", label: "Preferred date", type: "date" }],
      submit: v => api("/meeting-requests", "POST", { ...v, student_id: S.kid }), label: "Send request" }); } });
});

/* ============ chat (parent/student <-> teacher) ============ */
P.messages = async el => {
  const r = await api("/messages/threads"), teacher = S.user.role === "teacher";
  const rows = teacher ? r.threads : r.threads.filter(t => t.student_id === S.kid);
  el.innerHTML = pagehead(teacher ? "Parent chat" : "Chat with teachers") + (rows.length ? `<div class="card list">${rows.map(t => `<div class="row"><div class="grow"><b>${esc(teacher ? t.student + " (parent)" : t.teacher)}</b> <span class="muted small">${esc(t.subject || "")}</span><div class="small muted">${esc(t.last_message || "Say hello 👋")}</div></div>${t.unread ? badge(t.unread + " new", "bad") : ""}<button class="sm primary" data-act="open" data-s="${t.student_id}" data-t="${t.teacher_user_id}" data-n="${esc(teacher ? t.student : t.teacher)}">Open</button></div>`).join("")}</div>` : `<div class="card empty">${teacher ? "No parent has messaged yet" : "No teachers found"}</div>`);
  bind(el, { open: x => openChat(Number(x.s), Number(x.t), x.n) });
};
async function openChat(sid, tid, name) {
  const m = modal(`<h2>${esc(name)}</h2><div class="chat" id="chat"></div><form id="cf" class="row gap"><input id="cb" class="grow" placeholder="Type a message" maxlength="1500" autocomplete="off" required><button class="primary">Send</button></form><div class="row gap"><button data-close>Close</button></div>`, { wide: true });
  const load = async () => {
    if (!document.body.contains(m.el)) return clearInterval(poll);
    const r = await api(`/messages?student_id=${sid}&teacher_user_id=${tid}`), box = $("#chat", m.el), atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = r.messages.length ? r.messages.map(x => `<div class="msg ${x.sender_user_id === r.me ? "me" : ""}"><small>${esc(x.sender)} · ${esc(x.created_at.slice(5, 16))}</small>${esc(x.body)}</div>`).join("") : '<div class="empty">No messages yet</div>';
    if (atEnd) box.scrollTop = box.scrollHeight;
  };
  const poll = setInterval(() => load().catch(() => { }), 8000);
  $("#cf", m.el).onsubmit = async ev => { ev.preventDefault(); const i = $("#cb", m.el); try { await api("/messages", "POST", { student_id: sid, teacher_user_id: tid, body: i.value }); i.value = ""; await load(); $("#chat", m.el).scrollTop = 1e9; } catch (e) { fail(e); } };
  await load(); $("#chat", m.el).scrollTop = 1e9;
}

/* ============ report card (family; teacher/office pick a student) ============ */
function reportHTML(r) {
  return `<div class="center"><h2>${esc(r.institute)}</h2><h3>PROGRESS REPORT</h3></div>
    <table><tr><td>Student</td><td><b>${esc(r.student.name)}</b></td><td>Roll / ID</td><td>${esc(r.student.roll)}</td></tr><tr><td>Batch</td><td>${esc(r.student.batch || "")}</td><td>Father</td><td>${esc(r.student.father_name || "")}</td></tr></table>
    <h3 class="gap">Attendance</h3><p><b>${pct(r.attendance.percent)}</b> · present ${r.attendance.present}, absent ${r.attendance.absent}, leave ${r.attendance.leave} (of ${r.attendance.days} days)</p>
    <h3>Performance${r.average_percent != null ? ` · overall <b>${r.average_percent}%</b>` : ""}</h3>${r.subjects.length ? bars(r.subjects.map(s => ({ label: s.subject, value: s.average })), { tone }) : '<p class="muted">No results yet</p>'}
    ${table([["Test", t => esc(t.name)], ["Date", t => fdShort(t.date)], ["Marks", t => `${t.marks}/${t.max_marks}`, "num"], ["%", t => t.percent + "%", "num"]], r.tests, "No tests")}
    <h3 class="gap">Teachers' remarks</h3>${r.remarks.length ? r.remarks.map(x => `<p>${x.kind === "praise" ? "🌟" : x.kind === "concern" ? "⚠️" : "💬"} ${esc(x.body)} <span class="muted small">— ${esc(x.teacher)}, ${fdShort(x.created_at)}</span></p>`).join("") : '<p class="muted">No remarks yet</p>'}
    <p class="small muted">Generated on ${fd(r.generated_on)}</p>`;
}
reg("report", FAM, async el => { const r = await api(`/students/${S.kid}/report`); el.innerHTML = pagehead("Report card", '<button class="primary" data-act="print">🖨️ Print</button>') + `<div class="card">${reportHTML(r)}</div>`; bind(el, { print: () => printDialog(reportHTML(r)) }); });
reg("report", ["admin", "superadmin"], async el => {
  const st = await api("/students?status=active");
  el.innerHTML = pagehead("Report cards") + `<div class="card"><label>Choose a student</label><select id="sp"><option value="">— select —</option>${st.students.map(s => `<option value="${s.id}">${esc(s.name)} · ${esc(s.batch || "")} · ${esc(s.login_id)}</option>`).join("")}</select></div><div id="rp"></div>`;
  $("#sp", el).onchange = async e => { if (!e.target.value) return; const r = await api(`/students/${e.target.value}/report`); $("#rp", el).innerHTML = `<div class="card">${reportHTML(r)}</div><div class="row gap"><button class="primary" id="pr">🖨️ Print</button></div>`; $("#pr", el).onclick = () => printDialog(reportHTML(r)); };
});

/* ============ leaves ============ */
P.leaves = async el => {
  const r = await api("/leaves"), role = S.user.role, canApply = ["student", "parent", "teacher"].includes(role), canDecide = role === "teacher" || isOffice();
  el.innerHTML = pagehead("Leave", canApply ? '<button class="primary" data-act="apply">+ Apply for leave</button>' : "") +
    table([["Who", l => `<b>${esc(l.student || l.applicant)}</b><div class="small muted">${l.student ? "Student · by " + esc(l.applicant) : "Staff"}</div>`], ["Dates", l => `${fdShort(l.from_date)} – ${fdShort(l.to_date)}`], ["Reason", l => esc(l.reason)],
      ["Status", l => statusBadge(l.status) + (l.remark ? `<div class="small muted">${esc(l.remark)}</div>` : "")],
      ["", l => l.status === "pending" && canDecide && (l.applicant !== S.user.name || l.student) ? `<button class="sm primary" data-act="ok" data-id="${l.id}">Approve</button> <button class="sm danger" data-act="no" data-id="${l.id}">Reject</button>` : ""]], r.leaves, "No leave requests");
  const decide = status => x => openForm({ title: status === "approved" ? "Approve leave" : "Reject leave", fields: [{ name: "remark", label: "Remark (optional)" }], submit: v => api(`/leaves/${x.id}/decide`, "POST", { status, remark: v.remark }) });
  bind(el, { apply: () => openForm({ title: "Apply for leave", fields: [{ name: "from_date", label: "From", type: "date", required: true, value: todayISO() }, { name: "to_date", label: "To", type: "date", required: true, value: todayISO() }, { name: "reason", label: "Reason", type: "textarea", required: true }], submit: v => api("/leaves", "POST", { ...v, student_id: S.kid }) }), ok: decide("approved"), no: decide("rejected") });
};

/* ============ complaints / suggestions (family) ============ */
reg("complaints", FAM, async el => {
  const r = await api("/complaints");
  el.innerHTML = pagehead("Complaint / suggestion", '<button class="primary" data-act="new">+ Write to the office</button>') +
    (r.complaints.length ? r.complaints.map(c => `<div class="card"><div class="row"><b class="grow">${esc(c.category)}</b>${statusBadge(c.status)}</div><p>${esc(c.body)}</p>${c.response ? `<div class="small"><b>Reply (${esc(c.responded_by_name || "Office")}):</b> ${esc(c.response)}</div>` : ""}<div class="small muted">${fd(c.created_at)}</div></div>`).join("") : '<div class="card empty">Nothing submitted</div>');
  bind(el, { new: () => openForm({ title: "Write to the office", fields: [{ name: "category", label: "About", type: "select", required: true, options: r.categories.map(c => [c, c[0].toUpperCase() + c.slice(1)]) }, { name: "body", label: "Your message", type: "textarea", required: true }], submit: v => api("/complaints", "POST", { ...v, student_id: S.kid }), label: "Submit" }) });
});

/* ============ notices (everyone) ============ */
P.notices = async el => {
  const r = await api("/notices"), role = S.user.role, canPost = role === "teacher" || isOffice();
  el.innerHTML = pagehead("Notices", canPost ? '<button class="primary" data-act="new">+ Post notice</button>' : "") +
    (r.notices.length ? r.notices.map(n => `<div class="card"><div class="row"><b class="grow">${n.pinned ? "📌 " : ""}${esc(n.title)}</b>${badge(n.batch || n.audience)}</div><p>${esc(n.body)}</p><div class="small muted">${esc(n.author || "")} · ${fd(n.created_at)} ${canPost && (role === "superadmin" || n.created_by === S.user.id) ? `<button class="sm danger" data-act="del" data-id="${n.id}">Delete</button>` : ""}</div></div>`).join("") : '<div class="card empty">No notices</div>');
  bind(el, {
    new: async () => { const b = await api("/batches"), t = role === "teacher";
      openForm({ title: "Post a notice", fields: [{ name: "title", label: "Title", required: true }, { name: "body", label: "Details", type: "textarea" },
        { name: "audience", label: "For", type: "select", required: true, value: t ? "parents" : "all", options: t ? [["students", "Students"], ["parents", "Parents"]] : [["all", "Everyone"], ["students", "Students"], ["parents", "Parents"], ["teachers", "Teachers"], ["staff", "Office staff"]] },
        { name: "batch_id", label: t ? "Batch" : "Only for batch (optional)", type: "select", required: t, options: optionsOf(b.batches) }, ...(t ? [] : [{ name: "pinned", label: "Pin on top", type: "checkbox" }])],
        submit: v => api("/notices", "POST", v), label: "Publish" }); },
    del: async x => { if (confirm("Delete notice?")) { await api("/notices/" + x.id, "DELETE"); render(); } }
  });
};
