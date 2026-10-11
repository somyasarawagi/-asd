/* Tagore Career Institute - core: helpers, UI primitives, shell, login, profile, notifications */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN");
const safeUrl = u => /^https?:\/\//i.test(u || "") ? esc(u) : "#";
const fd = d => d ? new Date(d.slice(0, 10) + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
const fdShort = d => d ? new Date(d.slice(0, 10) + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "";
const ft = t => { if (!t) return ""; const [h, m] = t.split(":").map(Number); return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const todayISO = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const pct = v => v == null ? "–" : v + "%";

const S = { user: null, kid: null, page: "", unread: 0, pub: null };
const P = {};   // page id -> async (el) => void

async function api(path, method = "GET", data) {
  const r = await fetch("/api" + path, {
    method, credentials: "same-origin",
    headers: data !== undefined ? { "Content-Type": "application/json" } : {},
    body: data !== undefined ? JSON.stringify(data) : undefined
  });
  let j = {};
  try { j = await r.json(); } catch { /* empty body */ }
  if (!r.ok) {
    if (r.status === 401 && S.user) { S.user = null; showLogin("Session ended. Please login again."); }
    const e = new Error(j.error || "Request failed (" + r.status + ")"); e.status = r.status; throw e;
  }
  return j;
}
const kidQ = (pre = "?") => S.kid ? `${pre}student_id=${S.kid}` : "";

function toast(msg, kind = "") {
  const t = document.createElement("div"); t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").append(t); setTimeout(() => t.remove(), kind === "bad" ? 5000 : 2800);
}
const fail = e => toast(e.message || String(e), "bad");
const badge = (t, k = "") => `<span class="badge ${k}">${esc(t)}</span>`;
const statusBadge = s => badge(s, { paid: "ok", approved: "ok", resolved: "ok", done: "ok", accepted: "ok", present: "ok", pending: "warn", overdue: "bad", rejected: "bad", declined: "bad", open: "warn", in_progress: "", booked: "" }[s] || "");

/* event delegation: <button data-act="name" data-id="3"> */
function bind(root, handlers) {
  root.addEventListener("click", async ev => {
    const n = ev.target.closest("[data-act]");
    if (!n || !root.contains(n) || !handlers[n.dataset.act]) return;
    ev.preventDefault();
    try { await handlers[n.dataset.act](n.dataset, n, ev); } catch (e) { fail(e); }
  });
}

/* ---------- modal & forms ---------- */
function modal(inner, { wide = false, locked = false } = {}) {
  const m = document.createElement("div"); m.className = "modal";
  m.innerHTML = `<div class="sheet ${wide ? "wide" : ""}" role="dialog" aria-modal="true">${inner}</div>`;
  const close = () => { m.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape" && !locked) close(); };
  document.addEventListener("keydown", onKey);
  if (!locked) m.addEventListener("mousedown", e => { if (e.target === m) close(); });
  m.addEventListener("click", e => { if (e.target.closest("[data-close]")) close(); });
  document.body.append(m);
  const first = $("input,select,textarea", m); if (first) first.focus();
  return { el: m, close, $: s => $(s, m) };
}

function fieldHTML(f) {
  const id = "f_" + f.name, req = f.required ? "required" : "", v = f.value ?? "";
  const hint = f.hint ? `<div class="small muted">${esc(f.hint)}</div>` : "";
  if (f.type === "checkbox") return `<label class="chk"><input type="checkbox" id="${id}" ${f.value ? "checked" : ""}> ${esc(f.label)}</label>`;
  let inp;
  if (f.type === "select") inp = `<select id="${id}" ${req}>${(f.placeholder !== undefined || !f.required) ? `<option value="">${esc(f.placeholder ?? "— select —")}</option>` : ""}${(f.options || []).map(([val, lab]) => `<option value="${esc(val)}" ${String(val) === String(v) ? "selected" : ""}>${esc(lab)}</option>`).join("")}</select>`;
  else if (f.type === "textarea") inp = `<textarea id="${id}" ${req} placeholder="${esc(f.placeholder || "")}">${esc(v)}</textarea>`;
  else inp = `<input id="${id}" type="${f.type || "text"}" ${req} value="${esc(v)}" placeholder="${esc(f.placeholder || "")}" ${f.min !== undefined ? `min="${f.min}"` : ""} ${f.max !== undefined ? `max="${f.max}"` : ""} ${f.type === "number" ? 'step="any"' : ""} autocomplete="off">`;
  return `<label for="${id}">${esc(f.label)}${f.required ? " *" : ""}</label>${inp}${hint}`;
}

function openForm({ title, fields, submit, label = "Save", intro = "", wide = false }) {
  const m = modal(`<h2>${esc(title)}</h2>${intro}<form novalidate>${fields.map(fieldHTML).join("")}<div class="err" hidden></div>
    <div class="row gap"><button class="primary" type="submit">${esc(label)}</button><button type="button" data-close>Cancel</button></div></form>`, { wide });
  const form = $("form", m.el), err = $(".err", m.el);
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const vals = {};
    for (const f of fields) {
      const n = $("#f_" + f.name, m.el);
      if (f.type === "checkbox") vals[f.name] = n.checked;
      else if (f.type === "number") vals[f.name] = n.value === "" ? null : Number(n.value);
      else vals[f.name] = n.value.trim();
      if (f.required && (vals[f.name] === "" || vals[f.name] === null)) { err.hidden = false; err.textContent = `${f.label} is required`; n.focus(); return; }
    }
    const btn = $("button.primary", m.el); btn.disabled = true; err.hidden = true;
    try { const out = await submit(vals, m); if (out !== false) { m.close(); render(); } }
    catch (e) { err.hidden = false; err.textContent = e.message; }
    finally { btn.disabled = false; }
  });
  return m;
}

/* one-time credentials dialog (admission / reset) */
function showCreds(rows, note = "") {
  modal(`<h2>Login details</h2><p class="muted">Give these to the family. Passwords are shown only once; they must change it at first login.${note}</p>
    ${rows.map(r => `<div class="gap"><b>${esc(r.who)}</b><div>ID: <span class="cred">${esc(r.login_id)}</span></div>
    <div>${r.temp_password ? `Password: <span class="cred">${esc(r.temp_password)}</span>` : `<span class="muted">Existing login - same password as before</span>`}</div></div>`).join("")}
    <div class="row gap"><button class="primary" data-close>Done</button></div>`);
}

/* ---------- small renderers ---------- */
function table(cols, rows, empty = "Nothing here yet") {
  if (!rows.length) return `<div class="card empty">${esc(empty)}</div>`;
  return `<div class="tbl"><table><thead><tr>${cols.map(c => `<th class="${c[2] || ""}">${esc(c[0])}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c[2] || ""}">${c[1](r)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function bars(items, { max = 100, fmt = v => v + "%", tone = () => "" } = {}) {
  return `<div class="bars">${items.map(i => `<div><span>${esc(i.label)}</span><div class="bar ${tone(i.value)}"><i style="width:${Math.max(0, Math.min(100, (i.value ?? 0) / max * 100))}%"></i></div><b class="right">${i.value == null ? "–" : esc(fmt(i.value))}</b></div>`).join("")}</div>`;
}
function columns(items, max) {
  const m = max || Math.max(1, ...items.map(i => i.value || 0));
  return `<div class="cols">${items.map(i => `<div title="${esc(i.label)}: ${esc(i.value)}"><span>${esc(i.value ?? "")}</span><i style="height:${Math.max(2, (i.value || 0) / m * 100)}%"></i><span>${esc(i.label)}</span></div>`).join("")}</div>`;
}
const tile = (n, l, tone = "") => `<div class="tile ${tone}"><div class="n">${n}</div><div class="l">${esc(l)}</div></div>`;
const tone = v => v == null ? "" : v >= 75 ? "ok" : v >= 50 ? "warn" : "bad";
const pagehead = (title, extra = "") => `<div class="pagehead"><h1>${esc(title)}</h1>${extra}</div>`;
const loading = el => { el.innerHTML = `<div class="empty">Loading…</div>`; };
const optionsOf = (rows, v = "id", l = "name") => rows.map(r => [r[v], r[l]]);

/* ---------- navigation per role ---------- */
const SEC = "#";
const NAV = {
  student: [["dashboard", "🏠", "Home"], ["attendance", "🗓️", "Attendance"], ["timetable", "⏰", "Timetable"], ["homework", "📝", "Homework"],
    ["material", "📚", "Study material"], ["tests", "🧪", "Tests & results"], ["doubts", "❓", "Ask a doubt"], ["messages", "💬", "Messages"],
    ["fees", "💳", "Fees"], ["report", "📈", "Report card"], ["leaves", "🏖️", "Leave"], ["complaints", "📣", "Feedback"], ["notices", "📢", "Notices"]],
  parent: [["dashboard", "🏠", "Home"], ["attendance", "🗓️", "Attendance"], ["tests", "🧪", "Results"], ["homework", "📝", "Homework"],
    ["timetable", "⏰", "Timetable"], ["ptm", "🤝", "PTM meetings"], ["meet", "📅", "Request a meeting"], ["messages", "💬", "Chat with teachers"],
    ["fees", "💳", "Fees & receipts"], ["report", "📈", "Report card"], ["leaves", "🏖️", "Apply leave"], ["complaints", "📣", "Complaint / suggestion"], ["notices", "📢", "Notices"]],
  teacher: [["dashboard", "🏠", "Home"], ["attendance", "🗓️", "Attendance"], ["homework", "📝", "Homework"], ["material", "📚", "Study material"],
    ["tests", "🧪", "Tests & marks"], ["doubts", "❓", "Student doubts"], ["students", "🎓", "My students"], ["ptm", "🤝", "PTM"], ["meet", "📅", "Meeting requests"],
    ["messages", "💬", "Parent chat"], ["timetable", "⏰", "Timetable"], ["leaves", "🏖️", "Leave"], ["notices", "📢", "Notices"]],
  admin: [["dashboard", "🏠", "Home"], [SEC, "Admissions"], ["enquiries", "📞", "Enquiries"], ["students", "🎓", "Students"], ["batches", "🏫", "Batches & teachers"],
    ["timetable", "⏰", "Timetable"], [SEC, "Accounts"], ["fees", "💳", "Fees & collection"], ["accounts", "📒", "Accounts & expenses"],
    [SEC, "Connect"], ["ptm", "🤝", "PTM"], ["complaints", "📣", "Complaints"], ["leaves", "🏖️", "Leave requests"], ["notices", "📢", "Notices"], ["report", "📈", "Report cards"]],
};
NAV.superadmin = [["overview", "📊", "Director overview"], ...NAV.admin.slice(0), [SEC, "Director"], ["staff", "👥", "Staff & logins"], ["audit", "🛡️", "Activity log"], ["settings", "⚙️", "Settings"]];
const isFamily = () => S.user && (S.user.role === "student" || S.user.role === "parent");
const isOffice = () => S.user && (S.user.role === "admin" || S.user.role === "superadmin");

/* ---------- shell ---------- */
function showShell() {
  const u = S.user, nav = NAV[u.role];
  if (isFamily()) { const kids = u.children || []; if (!kids.find(k => k.id === S.kid)) S.kid = kids[0]?.id ?? null; }
  $("#app").innerHTML = `<div class="shell">
    <aside class="side" id="side"><div class="brand"><div class="logo">T</div><div>${esc(u.institute)}<div class="small" style="font-weight:400;opacity:.75">${esc(roleLabel(u.role))}</div></div></div>
      <nav class="nav">${nav.map(n => n[0] === SEC ? `<small>${esc(n[1])}</small>` : `<a href="#/${n[0]}" data-page="${n[0]}"><span class="ico">${n[1]}</span>${esc(n[2])}</a>`).join("")}</nav></aside>
    <div class="main"><header class="top"><button class="ham" id="ham" aria-label="Menu">☰</button><b id="ptitle" class="grow"></b>
      ${isFamily() && u.children.length > 1 ? `<select id="kidpick" style="width:auto" aria-label="Choose child">${u.children.map(k => `<option value="${k.id}" ${k.id === S.kid ? "selected" : ""}>${esc(k.name)}</option>`).join("")}</select>` : ""}
      <button class="bell" id="bell" aria-label="Notifications">🔔<b hidden id="bellN"></b></button>
      <button id="me" title="Profile">${esc(u.name.length > 14 ? u.name.slice(0, 13) + "…" : u.name)}</button><button id="out">Logout</button></header>
      <main class="content" id="view"></main></div></div>`;
  $("#ham").onclick = () => { const s = $("#side"); s.classList.toggle("open"); toggleScrim(s.classList.contains("open")); };
  $("#side").addEventListener("click", e => { if (e.target.closest("a")) { $("#side").classList.remove("open"); toggleScrim(false); } });
  $("#out").onclick = async () => { await api("/logout", "POST", {}); S.user = null; showLogin(); };
  $("#me").onclick = () => P.profile();
  $("#bell").onclick = openNotifications;
  const kp = $("#kidpick"); if (kp) kp.onchange = () => { S.kid = Number(kp.value); render(); };
  refreshBell();
}
function toggleScrim(on) { $(".scrim")?.remove(); if (on) { const s = document.createElement("div"); s.className = "scrim"; s.onclick = () => { $("#side").classList.remove("open"); s.remove(); }; document.body.append(s); } }
const roleLabel = r => ({ student: "Student", parent: "Parent", teacher: "Teacher", admin: "Office staff", superadmin: "Director" }[r]);

async function render() {
  if (!S.user) return;
  const nav = NAV[S.user.role], id = (location.hash.replace(/^#\//, "") || nav[0][0]).split("?")[0];
  const item = nav.find(n => n[0] === id) || nav[0];
  S.page = item[0];
  $$(".nav a").forEach(a => a.classList.toggle("on", a.dataset.page === S.page));
  $("#ptitle").textContent = item[2];
  const old = $("#view"), view = old.cloneNode(false); old.replaceWith(view);  // fresh node = no stale click handlers
  loading(view);
  try { await (P[S.page + ":" + S.user.role] || P[S.page])(view); }
  catch (e) { view.innerHTML = `<div class="card err">${esc(e.message)}</div>`; }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", render);

/* ---------- notifications ---------- */
async function refreshBell() {
  if (!S.user) return;
  try { const r = await api("/notifications"); S.unread = r.unread; const b = $("#bellN"); if (b) { b.hidden = !r.unread; b.textContent = r.unread; } } catch { /* offline */ }
}
async function openNotifications() {
  const r = await api("/notifications");
  const m = modal(`<h2>Notifications</h2><div class="list">${r.notifications.length ? r.notifications.map(n => `<div><div class="row"><b class="grow">${n.is_read ? "" : "● "}${esc(n.title)}</b><span class="small muted">${esc(n.created_at.slice(0, 16))}</span></div><div class="small muted">${esc(n.body)}</div></div>`).join("") : '<div class="empty">No notifications</div>'}</div>
    <div class="row gap"><button data-close>Close</button></div>`);
  await api("/notifications/read", "POST", {}); refreshBell();
}
setInterval(refreshBell, 60000);

/* ---------- profile / password ---------- */
P.profile = () => {
  const u = S.user;
  const m = modal(`<h2>${esc(u.name)}</h2><p class="muted">${esc(roleLabel(u.role))} · ID <span class="cred">${esc(u.login_id)}</span></p>
    <h3>Change password</h3><form id="pw"><label>Old password</label><input type="password" id="po" autocomplete="current-password" required>
    <label>New password (8+ characters)</label><input type="password" id="pn" autocomplete="new-password" minlength="8" required><div class="err" hidden></div>
    <div class="row gap"><button class="primary">Change</button><button type="button" data-close>Close</button></div></form>`);
  $("#pw", m.el).onsubmit = async ev => {
    ev.preventDefault();
    try { await api("/change-password", "POST", { old: $("#po", m.el).value, new: $("#pn", m.el).value }); S.user.must_change = 0; m.close(); toast("Password changed", "ok"); }
    catch (e) { const er = $(".err", m.el); er.hidden = false; er.textContent = e.message; }
  };
};
function forcePasswordChange() {
  const m = modal(`<h2>Set a new password</h2><p class="muted">For your safety please replace the temporary password before continuing.</p>
    <form id="pw"><label>Temporary password</label><input type="password" id="po" required><label>New password (8+ characters)</label><input type="password" id="pn" minlength="8" required>
    <div class="err" hidden></div><div class="row gap"><button class="primary">Save password</button></div></form>`, { locked: true });
  $("#pw", m.el).onsubmit = async ev => {
    ev.preventDefault();
    try { await api("/change-password", "POST", { old: $("#po", m.el).value, new: $("#pn", m.el).value }); S.user.must_change = 0; m.close(); toast("Password changed", "ok"); }
    catch (e) { const er = $(".err", m.el); er.hidden = false; er.textContent = e.message; }
  };
}

/* ---------- login ---------- */
function showLogin(msg = "") {
  const inst = S.pub?.institute || "Tagore Career Institute", demo = S.pub?.demo;
  $("#app").innerHTML = `<div class="login"><section class="hero"><div class="brand"><div class="logo">T</div>${esc(inst)}</div>
    <h1>One app for the whole institute</h1><p>Students, parents, teachers, office and director - everyone on the same page.</p>
    <ul><li>📅 Attendance, homework, timetable and tests</li><li>🤝 PTM booking, chat with teachers, meeting requests</li><li>💳 Fees, receipts and accounts</li><li>📊 Live director dashboard</li></ul></section>
    <section class="form"><form class="card" id="lf"><h2>Login</h2>${msg ? `<div class="err">${esc(msg)}</div>` : ""}
    <label for="lid">Student ID / Phone number / Staff ID</label><input id="lid" autocomplete="username" required autocapitalize="off">
    <label for="lpw">Password</label><input id="lpw" type="password" autocomplete="current-password" required><div class="err" id="lerr" hidden></div>
    <div class="row gap"><button class="primary grow" id="lgo">Login</button></div>
    <p class="small muted">Parents: your registered mobile number is your ID. Forgot password? Ask the office to reset it.</p>
    ${demo ? `<hr style="border:0;border-top:1px solid var(--line)"><div class="small muted">Demo mode - tap a role to fill the login (password <b>${esc(demo.password)}</b>):</div><div class="chips">${demo.logins.map(([l, id]) => `<button type="button" data-demo="${esc(id)}">${esc(l)}</button>`).join("")}</div>` : ""}</form></section></div>`;
  $$("[data-demo]").forEach(b => b.onclick = () => { $("#lid").value = b.dataset.demo; $("#lpw").value = demo.password; $("#lf").requestSubmit(); });
  $("#lf").onsubmit = async ev => {
    ev.preventDefault(); const btn = $("#lgo"); btn.disabled = true;
    try { const r = await api("/login", "POST", { login_id: $("#lid").value.trim(), password: $("#lpw").value }); S.user = r.user; S.kid = null; location.hash = ""; showShell(); await render(); if (S.user.must_change) forcePasswordChange(); }
    catch (e) { const er = $("#lerr"); er.hidden = false; er.textContent = e.message; }
    finally { btn.disabled = false; }
  };
}

/* ---------- printable dialogs ---------- */
function printDialog(inner) {
  modal(`<div class="printable">${inner}</div><div class="row gap noprint"><button class="primary" onclick="window.print()">🖨️ Print / Save as PDF</button><button data-close>Close</button></div>`, { wide: true });
}
