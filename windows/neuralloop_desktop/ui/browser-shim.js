// Development only (`python -m neuralloop_desktop --browser`): the window's bridge over local HTTP, so the app runs
// in an ordinary browser. In the app itself pywebview provides window.pywebview and this does nothing.
"use strict";
(() => {
  if (!new URLSearchParams(location.search).has("browser")) return;
  const base = location.pathname.split("/ui/")[0];
  const call = (name, args) => fetch(`${base}/rpc/${name}`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args) }).then(r => r.json()).then(r => { if (r.error) throw new Error(r.error); return r.result; });
  window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => call(name, args) }) };
  const poll = async () => {
    try {
      const events = await fetch(`${base}/events`).then(r => r.json());
      for (const e of events) window.NL && window.NL.event(e);
    } catch { /* the app went away */ }
    setTimeout(poll, 700);
  };
  setTimeout(() => { window.dispatchEvent(new Event("pywebviewready")); poll(); }, 0);
})();
