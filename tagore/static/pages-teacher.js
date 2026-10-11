/* Teacher screens */
"use strict";

reg("dashboard", ["teacher"], async el => {
  const d = await api("/dashboard");
  el.innerHTML = `<div class="grid">${tile(d.batches.length, "My batches")}${tile(d.pending_doubts, "Doubts waiting", d.pending_doubts ? "warn" : "ok")}${tile(d.pending_leaves, "Leave requests", d.pending_leaves ? "warn" : "")}${tile(d.ptm.length, "Upcoming PTM meetings")}</div>
    <div class="grid g2 gap"><div class="card"><h2>Today's lectures</h2>${d.classes_today.length ? `<div class="list">${d.classes_today.map(c => `<div><b>${ft(c.start_time)}–${ft(c.end_time)}</b> · ${esc(c.subject)} <span class="muted">${esc(c.batch)} ${c.room ? "· " + esc(c.room) : ""}</span></div>`).join("")}</div>` : '<div class="empty">No lecture today</div>'}</div>
    <div class="card"><h2>Attendance today</h2><div class="list">${d.batches.map(b => `<div class="row"><b class="grow">${esc(b.name)} <span class="muted small">${b.students} students</span></b>${b.attendance_done ? badge("Done", "ok") : '<a class="btn sm primary" href="#/attendance">Mark</a>'}</div>`).join("") || '<div class="empty">No batch assigned</div>'}</div></div>
    <div class="card"><h2>Booked PTM meetings</h2>${d.ptm.length ? `<div class="list">${d.ptm.map(p => `<div>${fdShort(p.date)} ${ft(p.slot_time)} · ${esc(p.student || "")} <span class="muted small">${esc(p.title)}</span></div>`).join("")}</div>` : '<div class="empty">None yet</div>'}</div>
    <div class="card"><h2>Notices</h2>${d.notices.length ? `<div class="list">${d.notices.map(n => `<div>${esc(n.title)} <span class="muted small">${fdShort(n.created_at)}</span></div>`).join("")}</div>` : '<div class="empty">No notices</div>'}</div></div>`;
});

/* ============ attendance ============ */
reg("attendance", ["teacher"], async el => {
  const b = await api("/batches");
  if (!b.batches.length) { el.innerHTML = '<div class="card empty">No batch is assigned to you yet. Ask the office.</div>'; return; }
  let batch = b.batches[0].id, date = todayISO(), rows = [], view = "mark";
  const draw = async () => {
    if (view === "mark") rows = (await api(`/attendance/sheet?batch_id=${batch}&date=${date}`)).students;
    const sum = view === "sum" ? (await api(`/attendance/summary?batch_id=${batch}`)).students : [];
    el.innerHTML = pagehead("Attendance") + `<div class="card"><div class="row"><select id="ab" style="width:auto">${b.batches.map(x => `<option value="${x.id}" ${x.id === batch ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
      <input type="date" id="ad" value="${date}" max="${todayISO()}" style="width:auto"><div class="tabs grow" style="margin:0"><button data-act="v" data-v="mark" class="${view === "mark" ? "on" : ""}">Mark</button><button data-act="v" data-v="sum" class="${view === "sum" ? "on" : ""}">Summary</button></div></div></div><div class="gap"></div>` +
      (view === "mark" ? `<div class="row" style="margin-bottom:.6rem"><button data-act="allp">Mark all present</button><span class="muted small grow" id="cnt"></span><button class="primary" data-act="save">Save attendance</button></div>` +
        table([["Student", s => `<b>${esc(s.name)}</b><div class="small muted">${esc(s.login_id)}</div>`], ["", s => `<div class="seg" data-sid="${s.student_id}">${["P", "A", "L"].map(k => `<button type="button" data-act="set" data-s="${s.student_id}" data-k="${k}" class="${s.status === k ? "on " + k : ""}">${k === "P" ? "Present" : k === "A" ? "Absent" : "Leave"}</button>`).join("")}</div>`]], rows, "No students in this batch")
        : table([["Student", s => esc(s.name)], ["Days", s => s.days, "num"], ["Present", s => s.present, "num"], ["Absent", s => s.absent, "num"], ["%", s => `<b>${pct(s.percent)}</b>`, "num"]], sum));
    $("#ab").onchange = e => { batch = Number(e.target.value); draw(); };
    $("#ad").onchange = e => { date = e.target.value || todayISO(); draw(); };
    count();
  };
  const count = () => { const c = $("#cnt"); if (c) c.textContent = `${rows.filter(r => r.status === "P").length} present · ${rows.filter(r => r.status === "A").length} absent · ${rows.filter(r => !r.status).length} not marked`; };
  bind(el, {
    v: (x) => { view = x.v; draw(); },
    set: (x, n) => { const r = rows.find(r => r.student_id === Number(x.s)); r.status = x.k; $$("button", n.parentElement).forEach(bt => bt.className = bt.dataset.k === x.k ? "on " + x.k : ""); count(); },
    allp: () => { rows.forEach(r => r.status = "P"); $$(".seg").forEach(sg => $$("button", sg).forEach(bt => bt.className = bt.dataset.k === "P" ? "on P" : "")); count(); },
    save: async () => {
      if (rows.some(r => !r.status) && !confirm(`${rows.filter(r => !r.status).length} students are not marked and will be skipped. Save anyway?`)) return;
      const records = rows.filter(r => r.status).map(r => ({ student_id: r.student_id, status: r.status }));
      if (!records.length) return toast("Mark at least one student", "bad");
      const r = await api("/attendance", "POST", { batch_id: batch, date, records }); toast(`Saved. ${r.absent} parent(s) notified of absence.`, "ok");
    }
  });
  await draw();
});

/* ============ tests & marks (teacher) ============ */
reg("tests", ["teacher"], async el => {
  const [t, b, s] = await Promise.all([api("/tests"), api("/batches"), api("/subjects")]);
  el.innerHTML = pagehead("Tests & marks", '<button class="primary" data-act="new">+ New test</button>') +
    table([["Test", x => `<b>${esc(x.name)}</b><div class="small muted">${esc(x.batch)} · ${esc(x.subject || "")} · ${fd(x.date)}</div>`], ["Type", x => x.mode === "online" ? badge("Online MCQ") + `<div class="small muted">${x.question_count} questions · ${x.duration_min} min</div>` : badge("Paper test")],
      ["Max", x => x.max_marks, "num"], ["Graded", x => x.graded, "num"], ["Status", x => x.published ? badge("Published", "ok") : badge("Draft", "warn")],
      ["", x => `<div class="row">${x.mode === "online" ? `<button class="sm" data-act="qs" data-id="${x.id}">Questions</button>` : `<button class="sm" data-act="marks" data-id="${x.id}">Enter marks</button><button class="sm" data-act="imp" data-id="${x.id}">Import CSV</button>`}<button class="sm" data-act="res" data-id="${x.id}">Results</button><button class="sm ${x.published ? "" : "primary"}" data-act="pub" data-id="${x.id}" data-p="${x.published ? 0 : 1}">${x.published ? "Unpublish" : "Publish"}</button></div>`]], t.tests, "No tests yet");
  bind(el, {
    new: () => openForm({ title: "New test", fields: [{ name: "batch_id", label: "Batch", type: "select", required: true, options: optionsOf(b.batches) }, { name: "subject_id", label: "Subject", type: "select", options: optionsOf(s.subjects) },
      { name: "name", label: "Test name", required: true, placeholder: "Unit Test 4" }, { name: "date", label: "Date", type: "date", required: true, value: todayISO() },
      { name: "mode", label: "Type", type: "select", required: true, value: "offline", options: [["offline", "Paper test (I will enter marks / import OMR result)"], ["online", "Online MCQ test (students attempt in app)"]] },
      { name: "max_marks", label: "Maximum marks (paper test)", type: "number", value: 100 }, { name: "duration_min", label: "Duration in minutes (online test)", type: "number", value: 60 }], submit: v => api("/tests", "POST", v), label: "Create" }),
    pub: async x => { await api(`/tests/${x.id}/publish`, "POST", { published: x.p === "1" }); toast(x.p === "1" ? "Published - students & parents notified" : "Hidden from students", "ok"); render(); },
    marks: x => marksSheet(Number(x.id)), imp: x => importMarks(Number(x.id)), qs: x => questionEditor(Number(x.id)), res: x => showResults(Number(x.id))
  });
});

async function marksSheet(tid) {
  const r = await api(`/tests/${tid}/sheet`), max = r.test.max_marks;
  const m = modal(`<h2>${esc(r.test.name)} · marks out of ${max}</h2><form id="mf"><div class="tbl"><table><thead><tr><th>Student</th><th>Marks</th><th>Absent</th></tr></thead><tbody>${r.students.map(s => `<tr><td><b>${esc(s.name)}</b><div class="small muted">${esc(s.login_id)}</div></td><td><input type="number" step="any" min="${-max}" max="${max}" data-s="${s.student_id}" value="${s.marks ?? ""}" style="width:110px"></td><td><input type="checkbox" data-a="${s.student_id}" ${s.absent ? "checked" : ""} style="width:auto"></td></tr>`).join("")}</tbody></table></div>
    <div class="err" hidden></div><div class="row gap"><button class="primary">Save marks</button><button type="button" data-close>Close</button></div></form>`, { wide: true });
  $("#mf", m.el).onsubmit = async ev => {
    ev.preventDefault();
    const records = r.students.map(s => ({ student_id: s.student_id, marks: $(`[data-s="${s.student_id}"]`, m.el).value, absent: $(`[data-a="${s.student_id}"]`, m.el).checked }));
    try { const o = await api(`/tests/${tid}/marks`, "POST", { records }); toast(`${o.saved} saved`, "ok"); m.close(); render(); } catch (e) { const er = $(".err", m.el); er.hidden = false; er.textContent = e.message; }
  };
}
function importMarks(tid) {
  openForm({ title: "Import marks from CSV", intro: '<p class="muted small">Paste a CSV that has a <b>Roll</b> column (student ID like TCI26S0001) and a <b>Marks</b> column - for example the file exported by the OMR Reader app. Use <b>AB</b> for absent.</p>',
    fields: [{ name: "csv", label: "CSV text", type: "textarea", required: true, placeholder: "Roll,Marks\nTCI26S0001,72\nTCI26S0002,AB" }],
    submit: async v => { const o = await api(`/tests/${tid}/marks/import`, "POST", { csv: v.csv }); toast(`${o.saved} marks saved` + (o.not_found.length ? `; not found: ${o.not_found.join(", ")}` : ""), o.not_found.length ? "bad" : "ok"); }, label: "Import" });
}
async function showResults(tid) {
  const r = await api(`/tests/${tid}/results`), st = r.stats;
  modal(`<h2>${esc(r.test.name)} · results</h2><div class="grid">${tile(st.count, "Students graded")}${tile(st.average ?? "–", "Average")}${tile(st.highest ?? "–", "Highest")}${tile(st.lowest ?? "–", "Lowest")}</div><div class="gap"></div>
    ${table([["Rank", x => x.rank ? "#" + x.rank : "–", "num"], ["Student", x => esc(x.name)], ["Marks", x => x.absent ? badge("Absent", "warn") : `${x.marks}/${st.max_marks}`, "num"]], r.results, "No marks entered")}<div class="row gap"><button data-close>Close</button></div>`, { wide: true });
}

/* ---- online question editor ---- */
function parseQuestions(raw) {
  return raw.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean).map((blk, i) => {
    const lines = blk.split("\n").map(l => l.trim()).filter(Boolean), q = { text: [], a: "", b: "", c: "", d: "", answer: "" };
    for (const l of lines) {
      let mm;
      if ((mm = l.match(/^\(?([A-Da-d])[).:]\s*(.+)$/))) q[mm[1].toLowerCase()] = mm[2];
      else if ((mm = l.match(/^ans(?:wer)?\s*[:=-]\s*\(?([A-Da-d])\)?/i))) q.answer = mm[1].toUpperCase();
      else q.text.push(l);
    }
    q.text = q.text.join(" ");
    if (!q.text || !q.a || !q.b || !q.answer) throw new Error(`Question ${i + 1}: needs text, at least options A and B, and "Ans: X"`);
    if (!q[q.answer.toLowerCase()]) throw new Error(`Question ${i + 1}: answer ${q.answer} has no option`);
    return q;
  });
}
async function questionEditor(tid) {
  const r = await api(`/tests/${tid}/questions`);
  const m = modal(`<h2>Questions (${r.questions.length})</h2>${r.questions.map((q, i) => `<div class="row"><span class="grow">${i + 1}. ${esc(q.text)} <span class="badge ok">Ans ${q.answer}</span></span><button class="sm danger" data-del="${q.id}">✕</button></div>`).join("") || '<p class="muted">No questions yet</p>'}
    <h3 class="gap">Add questions (paste many at once)</h3><p class="small muted">Leave a blank line between questions:<br><code>Which is a vector quantity?<br>A) Speed<br>B) Mass<br>C) Velocity<br>D) Time<br>Ans: C</code></p>
    <form id="qf"><textarea id="qt" style="min-height:160px" required></textarea><div class="row"><div class="grow"><label>Marks per question</label><input type="number" id="qm" value="4" step="any"></div><div class="grow"><label>Negative marks</label><input type="number" id="qn" value="1" step="any"></div></div>
    <div class="err" hidden></div><div class="row gap"><button class="primary">Add questions</button><button type="button" data-close>Close</button></div></form>`, { wide: true });
  m.el.addEventListener("click", async e => { const id = e.target.dataset.del; if (id) { try { await api("/questions/" + id, "DELETE"); m.close(); questionEditor(tid); } catch (x) { fail(x); } } });
  $("#qf", m.el).onsubmit = async ev => {
    ev.preventDefault();
    try { const qs = parseQuestions($("#qt", m.el).value).map(q => ({ ...q, marks: Number($("#qm", m.el).value), neg: Number($("#qn", m.el).value) })); await api(`/tests/${tid}/questions`, "POST", { questions: qs }); m.close(); toast(qs.length + " questions added", "ok"); render(); }
    catch (e) { const er = $(".err", m.el); er.hidden = false; er.textContent = e.message; }
  };
}

/* ============ my students ============ */
reg("students", ["teacher"], async el => {
  const [b, st] = await Promise.all([api("/batches"), api("/students?status=active")]);
  el.innerHTML = pagehead("My students") + `<div class="card"><select id="bf" style="width:auto"><option value="">All my batches</option>${b.batches.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div><div class="gap"></div><div id="tb"></div>`;
  const draw = () => { const f = $("#bf").value; $("#tb").innerHTML = table([["Student", s => `<b>${esc(s.name)}</b><div class="small muted">${esc(s.login_id)} · ${esc(s.batch)}</div>`], ["Parent phone", s => esc(s.parent_phone || "")],
    ["", s => `<button class="sm" data-act="rep" data-id="${s.id}">Report card</button> <button class="sm primary" data-act="rem" data-id="${s.id}" data-n="${esc(s.name)}">+ Remark</button>`]], st.students.filter(s => !f || String(s.batch_id) === f)); };
  $("#bf").onchange = draw; draw();
  bind(el, {
    rep: async x => printDialog(reportHTML(await api(`/students/${x.id}/report`))),
    rem: x => openForm({ title: "Remark for " + x.n, intro: '<p class="muted small">Parents are notified and see this in the report card.</p>', fields: [{ name: "kind", label: "Type", type: "select", required: true, value: "general", options: [["praise", "🌟 Praise"], ["concern", "⚠️ Concern"], ["general", "💬 General"]] }, { name: "body", label: "Remark", type: "textarea", required: true }], submit: v => api(`/students/${x.id}/remarks`, "POST", v) })
  });
});

/* ============ PTM (teacher) ============ */
reg("ptm", ["teacher"], async el => {
  const r = await api("/ptm");
  el.innerHTML = pagehead("My PTM schedule") + (r.events.length ? r.events.map(e => `<div class="card"><h2>${esc(e.title)}</h2><div class="muted">${fd(e.date)} · ${e.mode === "online" ? "💻 Online" : "🏫 At institute"}${e.meeting_link ? ` · <a href="${safeUrl(e.meeting_link)}" target="_blank" rel="noopener noreferrer">meeting link</a>` : ""}</div>
    ${table([["Time", s => `<b>${ft(s.slot_time)}</b>`], ["Student", s => s.student ? `<b>${esc(s.student)}</b>${s.brief ? `<div class="small muted">Attendance ${pct(s.brief.attendance_percent)} · Avg score ${pct(s.brief.average_percent)}${s.brief.remarks[0] ? "<br>Last remark: " + esc(s.brief.remarks[0].body) : ""}</div>` : ""}` : '<span class="muted">Free</span>'],
      ["Status", s => s.status === "open" ? "" : statusBadge(s.status) + (s.parent_attended === 0 ? " " + badge("No-show", "bad") : "")], ["Feedback", s => s.feedback_rating ? "★".repeat(s.feedback_rating) + (s.feedback_text ? `<div class="small muted">${esc(s.feedback_text)}</div>` : "") : ""],
      ["", s => s.status === "booked" ? `<button class="sm primary" data-act="done" data-id="${s.id}">Complete</button>` : s.remarks ? `<span class="small muted">${esc(s.remarks.slice(0, 40))}…</span>` : ""]], e.slots, "No slots")}</div>`).join("") : '<div class="card empty">No PTM scheduled for you</div>');
  bind(el, { done: x => openForm({ title: "Complete meeting", fields: [{ name: "remarks", label: "Discussion summary / advice (parent will see this)", type: "textarea", required: true }, { name: "attended", label: "Parent attended the meeting", type: "checkbox", value: true }], submit: v => api(`/ptm/slots/${x.id}/remarks`, "POST", v), label: "Save & notify parent" }) });
});

/* ============ meeting requests (teacher) ============ */
reg("meet", ["teacher"], async el => {
  const r = await api("/meeting-requests");
  el.innerHTML = pagehead("Meeting requests") + table([["Parent", q => `<b>${esc(q.parent)}</b><div class="small muted">about ${esc(q.student)} · ${fdShort(q.created_at)}</div>`], ["Reason", q => esc(q.reason) + (q.preferred_date ? `<div class="small muted">prefers ${fdShort(q.preferred_date)}</div>` : "")], ["Status", q => statusBadge(q.status) + (q.meet_on ? `<div class="small muted">${fdShort(q.meet_on)} ${ft(q.meet_time)}</div>` : "")],
    ["", q => q.status === "pending" ? `<button class="sm primary" data-act="acc" data-id="${q.id}" data-d="${q.preferred_date || ""}">Accept</button> <button class="sm danger" data-act="dec" data-id="${q.id}">Decline</button>` : q.status === "accepted" ? `<button class="sm" data-act="fin" data-id="${q.id}">Mark done</button>` : ""]], r.requests, "No requests");
  const send = (id, body) => api(`/meeting-requests/${id}/respond`, "POST", body);
  bind(el, {
    acc: x => openForm({ title: "Fix a meeting time", fields: [{ name: "meet_on", label: "Date", type: "date", required: true, value: x.d || todayISO() }, { name: "meet_time", label: "Time", type: "time", required: true, value: "17:00" }, { name: "note", label: "Note for parent (optional)" }], submit: v => send(x.id, { action: "accept", ...v }), label: "Confirm" }),
    dec: x => openForm({ title: "Decline request", fields: [{ name: "note", label: "Reason / alternative" }], submit: v => send(x.id, { action: "decline", note: v.note }) }),
    fin: async x => { await send(x.id, { action: "done" }); render(); }
  });
});
