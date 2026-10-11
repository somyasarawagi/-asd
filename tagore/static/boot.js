/* start-up: find out who is logged in, then show login or the app */
"use strict";
(async function boot() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => { });
  try { S.pub = await api("/public"); } catch { /* server asleep - login screen still shows */ }
  document.title = (S.pub?.institute || "Tagore Career Institute");
  try { const r = await api("/me"); S.user = r.user; showShell(); await render(); if (S.user.must_change) forcePasswordChange(); }
  catch { showLogin(); }
})();
