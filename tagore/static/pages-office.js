/* Office staff (admin) + director (superadmin) screens */
"use strict";
const OFF = ["admin", "superadmin"];

/* ============ dashboard ============ */
reg("dashboard", OFF, async el => {
  const d = await api("/dashboard");
  el.innerHTML = `<div class="grid">${tile(d.students, "Active students")}${tile(inr(d.today_collection), "Collected today", "ok")}${tile(inr(d.month_collection), "Collected this month", "ok")}${tile(inr(d.month_expenses), "Expenses this month")}
    ${tile(inr(d.total_due), "Total fees pending", d.total_due ? "warn" : "ok")}${tile(inr(d.total_overdue), "Overdue", d.total_overdue ? "bad" : "ok")}${tile(d.new_enquiries, "New enquiries", d.new_enquiries ? "warn" : "")}${tile(d.pending_leaves, "Leave requests", d.pending_leaves ? "warn" : "")}</div>
    <div class="grid g2 gap"><div class="card"><h2>📞 Enquiry follow-ups due</h2>${d.followups_today.length ? `<div class="list">${d.followups_today.map(f => `<div><b>${esc(f.name)}</b> · ${esc(f.phone)} <span class="muted small">${esc(f.course || "")}</span></div>`).join("")}</div><a class="btn sm" href="#/enquiries">Open enquiries</a>` : '<div class="empty">No follow-ups due 🎉</div>'}</div>
    <div class="card"><h2>🤝 Upcoming PTM</h2>${d.upcoming_ptm.length ? `<div class="list">${d.upcoming_ptm.map(p => `<div><b>${esc(p.title)}</b> · ${fd(p.date)}</div>`).join("")}</div><a class="btn sm" href="#/ptm">Manage PTM</a>` : '<div class="empty">None scheduled</div>'}</div>
    <div class="card"><h2>📢 Latest notices</h2>${d.notices.length ? `<div class="list">${d.notices.map(n => `<div>${esc(n.title)} <span class="muted small">${fdShort(n.created_at)}</span></div>`).join("")}</div>` : '<div class="empty">None</div>'}</div></div>`;
});

/* ============ director overview ============ */
reg("overview", ["superadmin"], async el => {
  const o = await api("/reports/overview"), f = o.office;
  const mx = Math.max(1, ...o.money.flatMap(m => [m.income, m.expenses]));
  el.innerHTML = pagehead("Director overview") + `<div class="grid">${tile(f.students, "Students")}${tile(o.staff.teachers, "Teachers")}${tile(inr(f.month_collection), "Fees this month", "ok")}${tile(inr(f.month_collection - f.month_expenses), "Net this month", f.month_collection >= f.month_expenses ? "ok" : "bad")}${tile(inr(f.total_due), "Fees pending", "warn")}${tile(inr(f.total_overdue), "Overdue", f.total_overdue ? "bad" : "ok")}</div>
    <div class="grid g2 gap"><div class="card"><h2>Income vs expenses (6 months)</h2><div class="cols">${o.money.map(m => `<div title="${m.month}"><span class="small">${m.income ? Math.round(m.income / 1000) + "k" : ""}</span><div style="display:flex;gap:2px;align-items:flex-end;height:100%;width:100%"><i style="height:${m.income / mx * 100}%"></i><i style="height:${m.expenses / mx * 100}%;background:var(--accent)"></i></div><span>${m.month.slice(5)}</span></div>`).join("")}</div><p class="small muted">🔵 income (fees) · 🟠 expenses</p></div>
    <div class="card"><h2>Expenses this month</h2>${o.spend.length ? bars(o.spend.map(s => ({ label: s.category, value: s.amount })), { max: Math.max(...o.spend.map(s => s.amount)), fmt: inr }) : '<div class="empty">No expenses</div>'}</div>
    <div class="card"><h2>Attendance (last 30 days)</h2>${bars(o.attendance.map(a => ({ label: a.batch, value: a.percent })), { tone })}</div>
    <div class="card"><h2>Average test score</h2>${bars(o.performance.map(a => ({ label: a.batch, value: a.avg })), { tone })}</div>
    <div class="card"><h2>Batch strength</h2>${bars(o.batches.map(b => ({ label: b.batch, value: b.students })), { max: Math.max(1, ...o.batches.map(b => b.students)), fmt: v => v })}</div>
    <div class="card"><h2>Admission funnel</h2>${o.funnel.length ? bars(o.funnel.map(x => ({ label: x.status, value: x.n })), { max: Math.max(...o.funnel.map(x => x.n)), fmt: v => v }) : '<div class="empty">No enquiries</div>'}</div></div>
    <div class="gap"></div><h2>Teachers</h2>${table([["Teacher", t => `<b>${esc(t.name)}</b><div class="small muted">${esc(t.subject || "")}</div>`], ["Batches", t => t.batches, "num"], ["Doubts solved", t => t.doubts_solved, "num"], ["PTM rating", t => t.ptm_rating ? "★ " + t.ptm_rating : "–", "num"]], o.teachers)}`;
});

/* ============ enquiries ============ */
reg("enquiries", OFF, async el => {
  const [r, b] = await Promise.all([api("/enquiries"), api("/batches")]);
  const stages = ["new", "contacted", "visited", "admitted", "lost"];
  el.innerHTML = pagehead("Admission enquiries", '<button class="primary" data-act="new">+ New enquiry</button>') + `<div class="row">${stages.map(s => badge(s + ": " + r.enquiries.filter(e => e.status === s).length, s === "admitted" ? "ok" : s === "lost" ? "bad" : "")).join("")}</div><div class="gap"></div>` +
    table([["Student", e => `<b>${esc(e.name)}</b><div class="small muted">📞 ${esc(e.phone)} · ${esc(e.source || "")}</div>`], ["Interested in", e => esc(e.course || "")], ["Follow-up", e => e.follow_up ? (e.follow_up < r.today && !["admitted", "lost"].includes(e.status) ? badge(fdShort(e.follow_up) + " overdue", "bad") : fdShort(e.follow_up)) : ""],
      ["Notes", e => esc(e.notes || "")], ["Status", e => statusBadge(e.status)],
      ["", e => ["admitted", "lost"].includes(e.status) ? "" : `<button class="sm" data-act="upd" data-id="${e.id}" data-s="${e.status}" data-f="${e.follow_up || ""}">Update</button> <button class="sm primary" data-act="admit" data-id="${e.id}" data-n="${esc(e.name)}">Admit</button>`]], r.enquiries, "No enquiries yet");
  bind(el, {
    new: () => openForm({ title: "New enquiry", fields: [{ name: "name", label: "Student name", required: true }, { name: "phone", label: "Parent phone (10 digits)", required: true, type: "tel" }, { name: "course", label: "Interested course", type: "select", options: b.batches.map(x => [x.name, x.name]) },
      { name: "source", label: "How did they hear?", type: "select", options: ["Hoarding", "Instagram", "Friend referral", "Walk-in", "Newspaper", "Other"].map(x => [x, x]) }, { name: "follow_up", label: "Follow-up date", type: "date" }, { name: "notes", label: "Notes", type: "textarea" }], submit: v => api("/enquiries", "POST", v) }),
    upd: x => openForm({ title: "Update enquiry", fields: [{ name: "status", label: "Status", type: "select", required: true, value: x.s, options: [["new", "New"], ["contacted", "Contacted"], ["visited", "Visited institute"], ["lost", "Lost"]] }, { name: "follow_up", label: "Next follow-up", type: "date", value: x.f }, { name: "notes", label: "Notes", type: "textarea" }], submit: v => api("/enquiries/" + x.id, "PUT", v) }),
    admit: x => admissionForm({ title: "Admit " + x.n, path: `/enquiries/${x.id}/admit`, name: x.n, batches: b.batches })
  });
});

function admissionForm({ title, path, name = "", batches }) {
  openForm({ title, wide: true, fields: [{ name: "name", label: "Student name", required: true, value: name }, { name: "batch_id", label: "Batch", type: "select", required: true, options: batches.map(x => [x.id, `${x.name}`]) },
    { name: "father_name", label: "Father's name" }, { name: "parent_phone", label: "Parent mobile (becomes parent's login ID)", type: "tel", required: true }, { name: "phone", label: "Student mobile", type: "tel" }, { name: "dob", label: "Date of birth", type: "date" }, { name: "school", label: "School" }, { name: "address", label: "Address", type: "textarea" }],
    submit: async v => { const o = await api(path, "POST", v); showCreds([{ who: "Student: " + v.name, ...o.student }, ...(o.parent ? [{ who: "Parent", ...o.parent }] : [])]); }, label: "Admit & create logins" });
}

/* ============ students ============ */
reg("students", OFF, async el => {
  const b = await api("/batches"); let batch = "", q = "";
  const draw = async () => {
    const r = await api(`/students?batch_id=${batch}&q=${encodeURIComponent(q)}`);
    $("#tb").innerHTML = table([["Student", s => `<b>${esc(s.name)}</b>${s.status === "left" ? " " + badge("Left", "bad") : ""}<div class="small muted">${esc(s.login_id)}</div>`], ["Batch", s => esc(s.batch || "")], ["Father", s => esc(s.father_name || "")], ["Parent login", s => esc(s.parent_phone || "")],
      ["", s => `<button class="sm" data-act="more" data-id="${s.id}">Manage</button>`]], r.students, "No students found");
  };
  el.innerHTML = pagehead("Students", '<button class="primary" data-act="new">+ New admission</button>') + `<div class="card row"><select id="bf" style="width:auto"><option value="">All batches</option>${b.batches.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select><input id="qf" class="grow" placeholder="Search name / ID / phone" style="min-width:180px"></div><div class="gap"></div><div id="tb"></div>`;
  $("#bf").onchange = e => { batch = e.target.value; draw(); }; let t; $("#qf").oninput = e => { clearTimeout(t); t = setTimeout(() => { q = e.target.value; draw(); }, 250); };
  bind(el, {
    new: () => admissionForm({ title: "New admission", path: "/students", batches: b.batches }),
    more: async x => { const s = (await api("/students/" + x.id)).student;
      const m = modal(`<h2>${esc(s.name)}</h2><p class="muted">${esc(s.login_id)} · ${esc(s.batch || "")}<br>Parents: ${s.parents.map(p => esc(p.name) + " (" + esc(p.phone) + ")").join(", ") || "–"}</p>
        <div class="row"><button data-m="fees">💳 Fee account</button><button data-m="rep">📈 Report card</button><button data-m="pw">🔑 Reset student password</button><button data-m="batch">🏫 Change batch</button><button class="danger" data-m="left">${s.status === "left" ? "Re-activate" : "Mark as left"}</button></div><div class="row gap"><button data-close>Close</button></div>`);
      m.el.addEventListener("click", async e => { const k = e.target.dataset.m; if (!k) return; m.close();
        try {
          if (k === "fees") feeAccount(s.id);
          if (k === "rep") printDialog(reportHTML(await api(`/students/${s.id}/report`)));
          if (k === "pw") { const o = await api(`/users/${s.user_id}/reset-password`, "POST", {}); showCreds([{ who: s.name, login_id: o.login_id, temp_password: o.temp_password }]); }
          if (k === "batch") openForm({ title: "Change batch", fields: [{ name: "batch_id", label: "New batch", type: "select", required: true, value: s.batch_id, options: optionsOf(b.batches) }], submit: v => api("/students/" + s.id, "PUT", v) });
          if (k === "left" && confirm(s.status === "left" ? "Re-activate this student?" : "Mark as left? Their login will be disabled.")) { await api("/students/" + s.id, "PUT", { status: s.status === "left" ? "active" : "left" }); draw(); }
        } catch (er) { fail(er); } }); }
  });
  await draw();
});

/* ============ batches ============ */
reg("batches", OFF, async el => {
  const [b, t, s] = await Promise.all([api("/batches"), api("/teachers"), api("/subjects")]);
  el.innerHTML = pagehead("Batches & teachers", '<button class="primary" data-act="new">+ New batch</button>') + `<div class="grid g2">${b.batches.map(x => `<div class="card"><div class="row"><h2 class="grow">${esc(x.name)}</h2>${badge(x.students + " students")}</div><div class="muted small">${esc(x.course || "")} · ${esc(x.session || "")} · Fee ${inr(x.fee_total)}</div>
    <div class="list gap">${x.subjects.map(sb => `<div class="row"><b class="grow">${esc(sb.subject)}</b><span class="muted">${esc(sb.teacher || "No teacher")}</span></div>`).join("") || '<div class="muted">No subjects yet</div>'}</div>
    <button class="sm gap" data-act="assign" data-id="${x.id}">+ Subject / change teacher</button></div>`).join("")}</div>
    <h2 class="gap">Teachers</h2>${table([["Teacher", x => `<b>${esc(x.name)}</b><div class="small muted">${esc(x.login_id)}</div>`], ["Subject", x => esc(x.subject || "")], ["Teaches", x => esc(x.batches.join(", "))], ["Phone", x => esc(x.phone || "")]], t.teachers)}`;
  bind(el, {
    new: () => openForm({ title: "New batch", fields: [{ name: "name", label: "Batch name", required: true, placeholder: "JEE 2028 Dropper" }, { name: "course", label: "Course", placeholder: "JEE / NEET / Foundation" }, { name: "session", label: "Session", value: "2026-27" }, { name: "start_date", label: "Start date", type: "date" }, { name: "fee_total", label: "Total fee (₹)", type: "number" }], submit: v => api("/batches", "POST", v) }),
    assign: x => openForm({ title: "Assign teacher to subject", fields: [{ name: "subject_id", label: "Subject", type: "select", required: true, options: optionsOf(s.subjects) }, { name: "teacher_user_id", label: "Teacher", type: "select", options: optionsOf(t.teachers.filter(z => z.active)) }], submit: v => api(`/batches/${x.id}/assign`, "POST", v) })
  });
});

/* ============ timetable (office edit) ============ */
reg("timetable", OFF, async el => {
  const [b, s] = await Promise.all([api("/batches"), api("/subjects")]); let batch = b.batches[0]?.id;
  const draw = async () => {
    const r = await api("/timetable?batch_id=" + batch), bt = b.batches.find(x => x.id === batch);
    el.innerHTML = pagehead("Timetable", '<button class="primary" data-act="add">+ Add lecture</button>') + `<div class="card"><select id="tb" style="width:auto">${b.batches.map(x => `<option value="${x.id}" ${x.id === batch ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></div><div class="gap"></div>` +
      table([["Day", t => DAYS[t.weekday]], ["Time", t => `${ft(t.start_time)}–${ft(t.end_time)}`], ["Subject", t => `<b>${esc(t.subject)}</b>`], ["Teacher", t => esc(t.teacher || "")], ["Room", t => esc(t.room || "")], ["", t => `<button class="sm danger" data-act="del" data-id="${t.id}">✕</button>`]], r.timetable, "No lectures scheduled");
    $("#tb").onchange = e => { batch = Number(e.target.value); draw(); };
    el._bt = bt;
  };
  bind(el, {
    add: () => openForm({ title: "Add lecture", fields: [{ name: "subject_id", label: "Subject", type: "select", required: true, options: (el._bt?.subjects || []).map(x => [x.subject_id, x.subject]) }, { name: "weekday", label: "Day", type: "select", required: true, options: DAYS.map((d, i) => [i, d]) },
      { name: "start_time", label: "Start", type: "time", required: true, value: "09:00" }, { name: "end_time", label: "End", type: "time", required: true, value: "10:30" }, { name: "room", label: "Room" }], submit: v => api("/timetable", "POST", { ...v, batch_id: batch }), intro: '<p class="muted small">Subjects come from the batch\'s teacher assignments (Batches page).</p>' }),
    del: async x => { if (confirm("Remove this lecture?")) { await api("/timetable/" + x.id, "DELETE"); draw(); } }
  });
  if (!batch) { el.innerHTML = '<div class="card empty">Create a batch first</div>'; return; }
  await draw();
});

/* ============ fees ============ */
reg("fees", OFF, async el => {
  const [d, b] = await Promise.all([api("/accounts/dues"), api("/batches")]); let sel = new Set();
  el.innerHTML = pagehead("Fees & collection", '<button data-act="assign">+ Add fee to batch / student</button><button data-act="coll">📄 Collections</button>') + `<div class="grid">${tile(inr(d.total_due), "Total pending", "warn")}${tile(inr(d.total_overdue), "Overdue", d.total_overdue ? "bad" : "ok")}${tile(d.dues.length, "Students with dues")}</div>
    <div class="row gap"><button data-act="remind" class="primary">🔔 Send reminder to selected</button><span class="muted small">Tick students, then send a reminder to their parents' app.</span></div>` +
    table([["", s => `<input type="checkbox" data-sel="${s.student_id}" style="width:auto">`], ["Student", s => `<b>${esc(s.student)}</b><div class="small muted">${esc(s.roll)} · ${esc(s.batch || "")}</div>`], ["Pending", s => inr(s.due), "num"], ["Overdue", s => s.overdue ? `<b style="color:var(--bad)">${inr(s.overdue)}</b>` : "–", "num"], ["Since", s => fdShort(s.oldest_due)], ["", s => `<button class="sm primary" data-act="acct" data-id="${s.student_id}">Collect</button>`]], d.dues, "No pending fees 🎉");
  el.addEventListener("change", e => { const id = e.target.dataset.sel; if (id) e.target.checked ? sel.add(Number(id)) : sel.delete(Number(id)); });
  bind(el, {
    acct: x => feeAccount(Number(x.id)),
    remind: async () => { const ids = d.dues.filter(s => sel.has(s.student_id)).flatMap(s => s.fee_ids); if (!ids.length) return toast("Tick at least one student", "bad"); const r = await api("/fees/remind", "POST", { fee_ids: ids }); toast(`${r.sent} reminders sent`, "ok"); },
    assign: async () => { const st = await api("/students?status=active"); openForm({ title: "Add a fee instalment", intro: '<p class="muted small">Choose a whole batch <b>or</b> one student.</p>', fields: [{ name: "batch_id", label: "Batch (everyone in it)", type: "select", options: optionsOf(b.batches) }, { name: "student_id", label: "…or a single student", type: "select", options: st.students.map(z => [z.id, `${z.name} (${z.login_id})`]) }, { name: "title", label: "Title", required: true, placeholder: "Instalment 4" }, { name: "amount", label: "Amount (₹)", type: "number", required: true }, { name: "due_date", label: "Due date", type: "date", required: true }],
      submit: v => v.student_id ? api("/fees/assign", "POST", { ...v, student_id: Number(v.student_id), batch_id: undefined }) : api("/fees/assign", "POST", { ...v, student_id: undefined }) }); },
    coll: async () => { const r = await api("/payments"); modal(`<h2>Collections this month · ${inr(r.total)}</h2>${table([["Receipt", p => `<button class="sm" data-rc="${p.id}">${esc(p.receipt_no)}</button>`], ["Date", p => fdShort(p.paid_on)], ["Student", p => esc(p.student)], ["Mode", p => esc(p.mode)], ["Amount", p => inr(p.amount), "num"]], r.payments, "No payments yet")}<div class="row gap"><button data-close>Close</button></div>`, { wide: true }).el.addEventListener("click", e => { if (e.target.dataset.rc) showReceipt({ id: e.target.dataset.rc }); }); }
  });
});

async function feeAccount(sid) {
  const [f, s] = await Promise.all([api("/fees?student_id=" + sid), api("/students/" + sid)]);
  const st = s.student, open = f.fees.filter(x => x.due > 0), director = S.user.role === "superadmin";
  const m = modal(`<h2>Fee account · ${esc(st.name)}</h2><p class="muted">${esc(st.login_id)} · ${esc(st.batch || "")}</p>
    ${table([["Instalment", x => `<b>${esc(x.title)}</b><div class="small muted">due ${fdShort(x.due_date)}</div>`], ["Amount", x => inr(x.amount - x.discount) + (x.discount ? `<div class="small muted">−${inr(x.discount)} disc.</div>` : ""), "num"], ["Paid", x => inr(x.paid), "num"], ["Pending", x => inr(Math.max(0, x.due)), "num"], ["", x => statusBadge(x.status)],
      ["", x => `${x.due > 0 ? `<button class="sm primary" data-pay="${x.id}">Receive</button>` : ""}${director ? ` <button class="sm" data-disc="${x.id}">Discount</button>` : ""}`]], f.fees, "No fee entries for this student")}<div class="row gap"><button data-close>Close</button></div>`, { wide: true });
  m.el.addEventListener("click", ev => {
    const pay = ev.target.dataset.pay, disc = ev.target.dataset.disc;
    if (pay) { const fee = f.fees.find(x => x.id === Number(pay));
      openForm({ title: `Receive payment · ${fee.title}`, fields: [{ name: "amount", label: "Amount (₹)", type: "number", required: true, value: fee.due, max: fee.due, min: 1 }, { name: "mode", label: "Mode", type: "select", required: true, value: "cash", options: [["cash", "Cash"], ["upi", "UPI"], ["card", "Card"], ["cheque", "Cheque"], ["bank", "Bank transfer"]] }, { name: "ref", label: "Reference / UTR / cheque no." }, { name: "paid_on", label: "Date", type: "date", value: todayISO(), max: todayISO() }],
        submit: async v => { const r = await api("/payments", "POST", { ...v, fee_id: fee.id }); m.close(); toast("Receipt " + r.receipt_no, "ok"); showReceipt({ id: r.id }); return true; }, label: "Save & print receipt" }); }
    if (disc) { const fee = f.fees.find(x => x.id === Number(disc));
      openForm({ title: "Discount · " + fee.title, fields: [{ name: "discount", label: "Total discount for this instalment (₹)", type: "number", required: true, value: fee.discount }], submit: async v => { await api(`/fees/${fee.id}/discount`, "POST", v); m.close(); feeAccount(sid); } }); }
  });
}

/* ============ accounts ============ */
reg("accounts", OFF, async el => {
  let from = todayISO().slice(0, 8) + "01", to = todayISO();
  const draw = async () => {
    const [s, l, e] = await Promise.all([api(`/accounts/summary?from=${from}&to=${to}`), api(`/accounts/ledger?from=${from}&to=${to}`), api(`/expenses?from=${from}&to=${to}`)]);
    el.innerHTML = pagehead("Accounts & expenses", '<button class="primary" data-act="exp">+ Add expense</button>') + `<div class="card row"><label style="margin:0">From</label><input type="date" id="f1" value="${from}" style="width:auto"><label style="margin:0">To</label><input type="date" id="f2" value="${to}" style="width:auto"></div><div class="gap"></div>
      <div class="grid">${tile(inr(s.income), "Fees received", "ok")}${tile(inr(s.expenses), "Expenses", "warn")}${tile(inr(s.net), "Net", s.net >= 0 ? "ok" : "bad")}</div>
      <div class="grid g2 gap"><div class="card"><h2>Received by mode</h2>${s.by_mode.length ? bars(s.by_mode.map(x => ({ label: x.mode, value: x.amount })), { max: Math.max(...s.by_mode.map(x => x.amount)), fmt: inr }) : '<div class="empty">None</div>'}</div>
      <div class="card"><h2>Expenses by category</h2>${s.by_category.length ? bars(s.by_category.map(x => ({ label: x.category, value: x.amount })), { max: Math.max(...s.by_category.map(x => x.amount)), fmt: inr }) : '<div class="empty">None</div>'}</div></div>
      <h2 class="gap">Expenses</h2>${table([["Date", x => fdShort(x.date)], ["Category", x => `<b>${esc(x.category)}</b>`], ["Vendor / note", x => esc([x.vendor, x.note].filter(Boolean).join(" · "))], ["Amount", x => inr(x.amount), "num"], ["", x => S.user.role === "superadmin" ? `<button class="sm danger" data-act="delx" data-id="${x.id}">✕</button>` : ""]], e.expenses, "No expenses in this range")}
      <h2 class="gap">Ledger</h2>${table([["Date", x => fdShort(x.date)], ["Particulars", x => esc(x.particulars)], ["Credit", x => x.credit ? inr(x.credit) : "", "num"], ["Debit", x => x.debit ? inr(x.debit) : "", "num"], ["Balance", x => inr(x.balance), "num"]], l.ledger, "No entries")}`;
    $("#f1").onchange = ev => { from = ev.target.value || from; draw(); }; $("#f2").onchange = ev => { to = ev.target.value || to; draw(); };
    el._cats = e.categories;
  };
  bind(el, {
    exp: () => openForm({ title: "Add expense", fields: [{ name: "category", label: "Category", type: "select", required: true, options: (el._cats || []).map(c => [c, c]) }, { name: "amount", label: "Amount (₹)", type: "number", required: true, min: 1 }, { name: "date", label: "Date", type: "date", required: true, value: todayISO(), max: todayISO() }, { name: "vendor", label: "Paid to" }, { name: "note", label: "Note" }], submit: v => api("/expenses", "POST", v) }),
    delx: async x => { if (confirm("Delete this expense?")) { await api("/expenses/" + x.id, "DELETE"); draw(); } }
  });
  await draw();
});

/* ============ PTM management ============ */
reg("ptm", OFF, async el => {
  const [r, b] = await Promise.all([api("/ptm"), api("/batches")]);
  el.innerHTML = pagehead("PTM management", '<button class="primary" data-act="new">+ Schedule PTM</button><button data-act="remind">🔔 Send 24h reminders</button>') +
    (r.events.length ? r.events.map(e => `<div class="card"><div class="row"><h2 class="grow">${esc(e.title)}</h2>${badge(e.mode === "online" ? "Online" : "At institute")}</div><div class="muted">${fd(e.date)} · ${ft(e.start_time)}–${ft(e.end_time)} · ${e.slot_minutes} min slots · ${esc(e.batch || "All batches")}</div>
      <div class="small muted">${e.slots.filter(s => s.status !== "open").length} / ${e.slots.length} slots booked</div><div class="row gap"><button class="sm primary" data-act="rep" data-id="${e.id}">Report</button><button class="sm" data-act="nudge" data-id="${e.id}">Remind parents who haven't booked</button></div></div>`).join("") : '<div class="card empty">No PTM yet</div>');
  bind(el, {
    new: () => openForm({ title: "Schedule a PTM", wide: true, intro: '<p class="muted small">Slots are created automatically for every teacher of the batch, and parents are notified to book.</p>', fields: [{ name: "title", label: "Title", required: true, value: "PTM - Term Review" }, { name: "date", label: "Date", type: "date", required: true },
      { name: "start_time", label: "Start", type: "time", required: true, value: "10:00" }, { name: "end_time", label: "End", type: "time", required: true, value: "13:00" }, { name: "slot_minutes", label: "Minutes per meeting", type: "number", required: true, value: 15 },
      { name: "batch_id", label: "Batch (blank = all teachers)", type: "select", options: optionsOf(b.batches) }, { name: "mode", label: "Mode", type: "select", required: true, value: "offline", options: [["offline", "At the institute"], ["online", "Online video meeting"]] },
      { name: "meeting_link", label: "Meeting link (online only, https://…)" }, { name: "note", label: "Note for parents", type: "textarea" }], submit: v => api("/ptm", "POST", v), label: "Schedule & notify" }),
    remind: async () => toast((await api("/ptm/remind", "POST", {})).reminded + " reminders sent", "ok"),
    nudge: async x => toast((await api(`/ptm/${x.id}/nudge`, "POST", {})).nudged + " parents reminded", "ok"),
    rep: async x => { const p = await api(`/ptm/${x.id}/report`);
      modal(`<h2>${esc(p.event.title)} · report</h2><div class="grid">${tile(pct(p.coverage_percent), "Families booked", tone(p.coverage_percent))}${tile(p.totals.booked + "/" + p.totals.slots, "Slots booked")}${tile(p.totals.attended, "Parents attended", "ok")}${tile(p.totals.no_show, "No-shows", p.totals.no_show ? "bad" : "")}</div><div class="gap"></div>
        ${table([["Teacher", t => `<b>${esc(t.teacher)}</b>`], ["Booked", t => t.booked + "/" + t.slots, "num"], ["Done", t => t.done, "num"], ["Attended", t => t.attended, "num"], ["Rating", t => t.rating ? "★ " + t.rating : "–", "num"]], p.teachers)}
        <h3 class="gap">Not booked yet (${p.not_booked.length})</h3>${p.not_booked.length ? `<div class="small">${p.not_booked.map(n => `${esc(n.name)} <span class="muted">${esc(n.parent_phone || "")}</span>`).join(" · ")}</div>` : '<p class="muted">Everyone has booked 🎉</p>'}<div class="row gap"><button data-close>Close</button></div>`, { wide: true }); }
  });
});

/* ============ complaints (office) ============ */
reg("complaints", OFF, async el => {
  const r = await api("/complaints");
  el.innerHTML = pagehead("Complaints & suggestions") + (r.complaints.length ? r.complaints.map(c => `<div class="card"><div class="row"><b class="grow">${esc(c.category)} · ${esc(c.by_name)} <span class="muted small">(${esc(c.by_role)}${c.student ? ", " + esc(c.student) : ""})</span></b>${statusBadge(c.status)}</div><p>${esc(c.body)}</p>
    ${c.response ? `<div class="small"><b>Reply:</b> ${esc(c.response)}</div>` : ""}<div class="small muted">${fd(c.created_at)}</div>${c.status !== "resolved" ? `<button class="sm primary" data-act="reply" data-id="${c.id}">Reply / resolve</button>` : ""}</div>`).join("") : '<div class="card empty">No complaints 🎉</div>');
  bind(el, { reply: x => openForm({ title: "Reply", fields: [{ name: "status", label: "Status", type: "select", required: true, value: "resolved", options: [["in_progress", "In progress"], ["resolved", "Resolved"]] }, { name: "response", label: "Reply to parent / student", type: "textarea", required: true }], submit: v => api(`/complaints/${x.id}/respond`, "POST", v) }) });
});

/* ============ director: staff, audit, settings ============ */
reg("staff", ["superadmin"], async el => {
  const r = await api("/users");
  el.innerHTML = pagehead("Staff & logins", '<button class="primary" data-act="new">+ New staff login</button>') + table([["Name", u => `<b>${esc(u.name)}</b>${u.active ? "" : " " + badge("Disabled", "bad")}<div class="small muted">${esc(u.login_id)}</div>`], ["Role", u => badge({ teacher: "Teacher", admin: "Office staff", superadmin: "Director" }[u.role])], ["Subject", u => esc(u.subject || "")], ["Phone", u => esc(u.phone || "")],
    ["", u => u.id === S.user.id ? "" : `<button class="sm" data-act="pw" data-id="${u.id}" data-l="${esc(u.login_id)}">Reset password</button> <button class="sm ${u.active ? "danger" : ""}" data-act="tog" data-id="${u.id}" data-a="${u.active ? 0 : 1}">${u.active ? "Disable" : "Enable"}</button>`]], r.users);
  bind(el, {
    new: () => openForm({ title: "New staff login", fields: [{ name: "role", label: "Role", type: "select", required: true, value: "teacher", options: [["teacher", "Teacher"], ["admin", "Office / non-academic staff"], ["superadmin", "Director (full access)"]] }, { name: "name", label: "Full name", required: true }, { name: "phone", label: "Phone", type: "tel" }, { name: "subject", label: "Subject (teachers)" }, { name: "qualification", label: "Qualification (teachers)" }, { name: "experience_years", label: "Experience (years)", type: "number" }],
      submit: async v => { const o = await api("/users", "POST", v); showCreds([{ who: v.name, login_id: o.login_id, temp_password: o.temp_password }]); }, label: "Create login" }),
    pw: async x => { if (confirm("Reset password for " + x.l + "?")) { const o = await api(`/users/${x.id}/reset-password`, "POST", {}); showCreds([{ who: x.l, login_id: o.login_id, temp_password: o.temp_password }]); } },
    tog: async x => { await api(`/users/${x.id}/active`, "POST", { active: x.a === "1" }); render(); }
  });
});
reg("audit", ["superadmin"], async el => { const r = await api("/audit"); el.innerHTML = pagehead("Activity log") + table([["When", a => esc(a.at.slice(0, 16))], ["Who", a => `${esc(a.name || "–")} <span class="muted small">${esc(a.role || "")}</span>`], ["Action", a => `<b>${esc(a.action)}</b>`], ["Detail", a => esc(a.detail || "")]], r.log, "Nothing yet"); });
reg("settings", ["superadmin"], async el => {
  const r = await api("/settings");
  el.innerHTML = pagehead("Settings") + `<form class="card" id="sf" style="max-width:520px"><label>Institute name</label><input id="s1" value="${esc(r.institute_name)}" required><label>Address (printed on receipts)</label><input id="s2" value="${esc(r.address)}"><label>Phone</label><input id="s3" value="${esc(r.phone)}"><div class="row gap"><button class="primary">Save</button></div></form>`;
  $("#sf", el).onsubmit = async e => { e.preventDefault(); try { await api("/settings", "POST", { institute_name: $("#s1").value, address: $("#s2").value, phone: $("#s3").value }); toast("Saved", "ok"); } catch (x) { fail(x); } };
});
