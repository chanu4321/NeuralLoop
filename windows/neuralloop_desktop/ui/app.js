// NeuralLoop for Windows: the window. The shelf, settings, the tray's quick panel, and first launch live here;
// a book and its five steps are in book.js. Everything the app knows comes from Python (window.pywebview.api);
// changes come back as events (NL.event).
"use strict";

const NL = {
  api: null, base: "", shelf: null, view: { kind: "library" }, panel: location.hash === "#panel",
  lastInput: Date.now(), focused: document.hasFocus(), handlers: {},
  on(name, fn) { (this.handlers[name] ||= []).push(fn); },
  event(e) {
    for (const fn of this.handlers[e.name] || []) { try { fn(e.data); } catch (err) { console.error(err); } }
  },
};
window.NL = NL;

const $ = sel => document.querySelector(sel);
const app = () => $("#app");

function icon(name) {
  const paths = {
    plus: "M12 5v14M5 12h14", back: "M15 18l-6-6 6-6", gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
    arrow: "M5 12h14M13 6l6 6-6 6", map: "M5 6a2 2 0 1 0 0-.01M19 6a2 2 0 1 0 0-.01M12 18a2 2 0 1 0 0-.01M6.5 7.5l4.5 9M17.5 7.5l-4.5 9M7 6h10",
    check: "M5 12l5 5 9-10", lock: "M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3", more: "M5 12h.01M12 12h.01M19 12h.01",
    play: "M7 5l12 7-12 7z", pause: "M7 5h4v14H7zM13 5h4v14h-4z",
  };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = `<path d="${paths[name] || ""}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
  return svg;
}

function toast(text, seconds = 5) {
  const t = $("#toast");
  t.textContent = text; t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, seconds * 1000);
}

/** A small dialog: title, words, and buttons [{label, kind, action}]. Esc closes it. */
function dialog(title, words, buttons = [{ label: "OK", kind: "primary" }]) {
  return new Promise(resolve => {
    const d = $("#dialog");
    const card = el("div", { class: "card" }, el("h3", {}, title), words ? el("p", { class: "muted" }, words) : "");
    const row = el("div", { class: "row", style: "justify-content:flex-end" });
    const close = value => { d.hidden = true; d.innerHTML = ""; document.removeEventListener("keydown", esc); resolve(value); };
    const esc = e => { if (e.key === "Escape") close(null); };
    for (const b of buttons) row.append(btn(b.label, () => close(b.value ?? b.label), b.kind || ""));
    card.append(row);
    d.innerHTML = ""; d.append(card); d.hidden = false;
    document.addEventListener("keydown", esc);
    (row.querySelector(".primary") || row.lastChild)?.focus();
  });
}

function pipSlot(pose, size) { return pip(pose, size); }

function fillPips(root = document) {
  root.querySelectorAll(".pip-slot").forEach(slot => {
    slot.replaceWith(pip(slot.dataset.pose, Number(slot.dataset.size || 100)));
  });
}

// Boot.

window.addEventListener("pywebviewready", boot);
if (window.pywebview && window.pywebview.api) boot();

async function boot() {
  if (NL.api) return;
  NL.api = window.pywebview.api;
  if (window.PIP_CSS) document.head.append(el("style", {}, window.PIP_CSS));
  fillPips();
  if (NL.panel) document.body.classList.add("panel");
  await refreshShelf();
  if (NL.panel) return renderPanel();
  wireWindow();
  const first = await NL.api.first_run();
  render();
  if (!first.done) welcome();
}

async function refreshShelf() {
  NL.shelf = await NL.api.shelf();
  NL.base = NL.shelf.base;
  if (NL.shelf.message) toast(NL.shelf.message, 8);
}

function render() {
  if (NL.panel) return renderPanel();
  const v = NL.view;
  if (v.kind === "book") return window.BookScreen.open(v.id, v.n, v.review);
  if (v.kind === "settings") return renderSettings(v.page || "account");
  renderLibrary();
}

function go(view) {
  if (NL.view.kind === "book" && view.kind !== "book") window.BookScreen.close();
  NL.view = view;
  render();
  app().querySelector(".page, .chapter-main, .content")?.scrollTo?.(0, 0);
}

NL.on("shelf", shelf => {
  NL.shelf = { ...shelf, base: NL.base };
  if (shelf.message) toast(shelf.message, 8);
  if (NL.panel) return renderPanel();
  if (NL.view.kind === "library") renderLibrary(true);
  if (NL.view.kind === "book") window.BookScreen.shelfChanged();
});
NL.on("line", ({ id, line }) => {
  const card = document.querySelector(`[data-book="${id}"] .line`);
  if (card && line) card.textContent = line;
});
NL.on("message", text => toast(text, 8));
NL.on("open", id => go({ kind: "book", id }));
NL.on("page", page => {
  if (page === "settings") go({ kind: "settings", page: "account" });
  else if (page === "resume" && NL.shelf.summary.resume) go({ kind: "book", id: NL.shelf.summary.resume.id, n: NL.shelf.summary.resume.n });
  else if (page === "review") reviewAnything();
  else go({ kind: "library" });
});
NL.on("panel", async () => { await refreshShelf(); renderPanel(); });

function wireWindow() {
  const input = () => { NL.lastInput = Date.now(); };
  for (const type of ["mousemove", "keydown", "wheel", "pointerdown", "scroll"]) document.addEventListener(type, input, { passive: true, capture: true });
  window.addEventListener("focus", () => { NL.focused = true; NL.api.active(true); });
  window.addEventListener("blur", () => { NL.focused = false; NL.api.active(false); });
  document.addEventListener("visibilitychange", () => NL.api.active(!document.hidden && document.hasFocus()));
  NL.api.active(document.hasFocus());
  // Dropping a book anywhere: Python reads the file's full path (the page only shows where to drop it).
  const drop = $("#drop");
  let depth = 0;
  document.addEventListener("dragenter", e => { if (hasFiles(e)) { depth++; drop.hidden = false; } });
  document.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) drop.hidden = true; });
  document.addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", () => { depth = 0; drop.hidden = true; setTimeout(refreshAndRender, 400); });
  // Pip's study clock: 15-second ticks while a book is open and NeuralLoop is in front.
  setInterval(() => {
    if (NL.view.kind === "book" && NL.focused && !document.hidden) NL.api.tick(NL.view.id, 15);
  }, 15000);
}
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
async function refreshAndRender() { await refreshShelf(); if (NL.view.kind === "library") renderLibrary(true); }

// The shelf.

const COVERS = [["--accent-soft", "--accent"], ["--mint-soft", "--mint"], ["--sky-soft", "--sky"], ["--rose-soft", "--rose"], ["--butter-soft", "--accent"]];

function cover(title, index, preparing, compact = false) {
  const [soft, strong] = COVERS[index % COVERS.length];
  const c = el("div", { class: "cover", style: `background:linear-gradient(135deg,var(${soft}),color-mix(in srgb,var(${strong}) 45%,transparent));--strong:var(${strong})` },
    el("span", { class: "ghost", "aria-hidden": "true" }, "📕"), el("h3", {}, title));
  if (preparing && !compact) { const p = pip("study", 70); p.classList.add("pip-corner"); c.append(p); }
  return c;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning!" : h < 18 ? "Good afternoon!" : "Good evening!";
}

function subline(s, books) {
  if (!books.length) return "Give Pip a book and it becomes small learning loops: listen, read, recall, map, remember.";
  if (s.preparing) {
    const one = books.find(b => b.preparing);
    return `Pip is preparing ${s.preparing === 1 ? one.title : s.preparing + " books"}. Ready chapters are open already.`;
  }
  if (s.dueCards > 0) return "A few cards are ready for a quick review. Two minutes is plenty.";
  return "Everything's up to date. Rest counts too.";
}

function stat(emoji, value, label, tint) {
  return el("div", { class: "stat" }, el("span", { class: "dot", style: `background:color-mix(in srgb,var(${tint}) 15%,transparent)` }, emoji),
    el("div", {}, el("b", {}, value), el("span", {}, label)));
}

function renderLibrary(keepScroll = false) {
  const page = app().querySelector(".page.library");
  const scroll = keepScroll && page ? page.scrollTop : 0;
  const { books, summary: s, year } = NL.shelf;
  const inner = el("div", { class: "page-inner" });
  const hero = el("section", { class: "hero" }, pip(s.preparing ? "study" : s.dueCards > 0 ? "play" : "read", 150),
    el("div", { class: "col grow", style: "z-index:1" }, el("h1", {}, greeting()),
      el("p", { class: "muted", style: "max-width:520px" }, subline(s, books)),
      el("div", { class: "row", style: "margin-top:4px" },
        btn([icon("plus"), "Add a book"], () => NL.api.add_book(), "primary big"),
        el("span", { class: "small faint" }, "or drop a PDF or EPUB anywhere here"))));
  if (books.length) {
    hero.append(el("div", { class: "stats" },
      stat("🕒", s.weekText, "this week", "--sky"),
      stat("🃏", String(s.dueCards), s.dueCards === 1 ? "card ready" : "cards ready", "--mint"),
      stat("✅", String(s.loopsClosedThisWeek), s.loopsClosedThisWeek === 1 ? "loop closed" : "loops closed", "--accent")));
  }
  const settingsButton = btn([icon("gear"), "Settings"], () => go({ kind: "settings", page: "account" }), "small");
  inner.append(el("div", { class: "row", style: "margin-bottom:-20px" }, el("span", { class: "caps" }, "Library"), el("span", { class: "spacer" }), settingsButton), hero);
  if (!books.length) inner.append(emptyShelf());
  else {
    if (s.resume) inner.append(resumeCard(s.resume));
    const shelf = el("div", { class: "shelf" });
    for (const b of books) shelf.append(bookCard(b));
    const add = el("button", { class: "add", type: "button" }, el("span", { class: "plus" }, "+"), el("h4", { class: "muted" }, "Add a book"), el("span", { class: "small faint" }, "PDF or EPUB"));
    add.onclick = () => NL.api.add_book();
    shelf.append(add);
    inner.append(section("Your shelf", `${books.length} book${books.length === 1 ? "" : "s"}`, shelf));
    inner.append(section("Your year with Pip", "Every minute you study, across all your books", yearLog(year)));
  }
  const fresh = el("main", { class: "page library", id: "main" }, inner);
  app().replaceChildren(fresh);
  fresh.scrollTop = scroll;
}

function section(title, detail, body) {
  return el("section", {}, el("div", { class: "section-head" }, el("h2", {}, title), el("span", { class: "small faint" }, detail)), body);
}

function emptyShelf() {
  const steps = el("ol", { class: "muted", style: "text-align:left;max-width:460px" },
    el("li", {}, "Drag a PDF or EPUB onto this window (or click Add a book)."),
    el("li", {}, "Pip splits it into chapters and starts preparing the first one."),
    el("li", {}, "Study each chapter's loop: listen, read, recall, map, remember."));
  return el("div", { class: "card sunk col", style: "align-items:center;padding:26px 20px;gap:16px" },
    el("h2", { class: "center" }, "Your shelf is empty, and that's a fine place to start."), pip("hug", 150), steps,
    el("div", { class: "row" }, btn("Add a book", () => NL.api.add_book(), "primary big"), btn("Try the sample book", () => NL.api.add_sample(), "big")));
}

function bookCard(b) {
  const card = el("div", { class: "book", role: "button", tabindex: 0, "data-book": b.id, "aria-label": b.title });
  const open = () => go({ kind: "book", id: b.id });
  card.onclick = open;
  card.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  card.oncontextmenu = e => { e.preventDefault(); bookMenu(b); };
  const body = el("div", { class: "book-body" });
  if (b.dots.length) {
    body.append(el("div", { class: "dots", "aria-hidden": "true" }, b.dots.map(d => el("i", { class: d }))));
    body.append(el("div", { class: "small muted" }, b.counts));
  }
  if (b.problem) {
    const why = el("button", { class: "btn link small", type: "button" }, "What happened?");
    why.onclick = e => { e.stopPropagation(); dialog(b.problem.card, b.problem.detail); };
    body.append(el("div", { class: "problem" }, el("span", { "aria-hidden": "true" }, "🩹"), el("span", {}, b.problem.card)), why);
  } else if (b.preparing && b.working) {
    const w = b.working;
    body.append(el("div", { class: "tiny" }, `Chapter ${w.n}: ${w.step || "making the " + w.item}${w.percent ? " · " + w.percent : ""}`),
      progressBar(w.fraction), el("div", { class: "tiny faint line" }, b.line));
  } else {
    body.append(el("div", { class: "row tiny faint" }, b.preparing ? el("span", { class: "spinner" }) : "", el("span", { class: "line" }, b.preparing ? b.line : b.madeWith)));
  }
  card.append(cover(b.title, b.cover, b.preparing), body);
  return card;
}

async function bookMenu(b) {
  const answer = await dialog(b.title, "What would you like to do with this book?", [
    { label: "Show in folder", value: "folder" }, { label: "Remove book…", value: "remove", kind: "danger" }, { label: "Open", value: "open", kind: "primary" }]);
  if (answer === "open") go({ kind: "book", id: b.id });
  if (answer === "folder") NL.api.show_in_folder(b.id);
  if (answer === "remove") confirmRemove(b.id, b.title);
}

async function confirmRemove(id, title) {
  const answer = await dialog(`Remove “${title}”?`, "Its chapters, podcasts, videos, and your progress go to the Recycle Bin.",
    [{ label: "Keep it", value: "keep" }, { label: "Remove book", value: "remove", kind: "primary" }]);
  if (answer !== "remove") return false;
  await NL.api.remove_book(id);
  go({ kind: "library" });
  return true;
}

function progressBar(fraction, slow = false) {
  const bar = el("div", { class: "bar" + (fraction == null ? " moving" : "") + (slow ? " slow" : "") });
  bar.append(el("i", { style: `width:${Math.round((fraction ?? 0.3) * 100)}%` }));
  return bar;
}

function resumeCard(r) {
  const card = el("section", { class: "resume" }, cover(r.title, r.cover, false, true));
  const col = el("div", { class: "col grow", style: "gap:8px" }, el("div", { class: "caps" }, "Pick up where you left off"),
    el("h2", {}, r.title), el("p", { class: "small muted" }, `${r.book} · next: ${r.stageLabel}`));
  const row = el("div", { class: "row wrap" }, btn(["Continue", icon("arrow")], () => go({ kind: "book", id: r.id, n: r.n }), "primary big"));
  if (r.audio) row.append(window.BookScreen.podcast(r.id, r.n, `${NL.base}/book/${r.id}/${r.audio}`, true));
  col.append(row);
  card.append(col);
  return card;
}

function yearLog(year) {
  const { grid, stats } = year;
  const pills = el("div", { class: "row wrap" },
    stat("🕒", year.totalText, "this year", "--sky"), stat("📅", String(stats.days), stats.days === 1 ? "day with Pip" : "days with Pip", "--mint"),
    stat("🔥", String(stats.longestRun), "longest run of days", "--accent"));
  if (stats.best) pills.append(stat("⭐", formatMinutes(stats.best.seconds), "best day, " + pretty(stats.best.date), "--rose"));
  const months = el("div", { class: "months" });
  let last = -9;
  for (const m of grid.months) { if (m.week - last >= 3) { months.append(el("span", { style: `left:${m.week * 15}px` }, m.label)); last = m.week; } }
  const cells = el("div", { class: "year-grid", role: "img", "aria-label": `${stats.days} days with Pip this year` });
  for (const week of grid.weeks) for (const d of week) {
    cells.append(el("i", { class: d.future ? "f" : d.level ? "l" + d.level : "", title: d.future ? "" : `${pretty(d.date)}: ${d.seconds ? formatMinutes(d.seconds) : "rest day"}` }));
  }
  return el("div", { class: "card col", style: "gap:16px" }, pills, el("div", { class: "year" }, months, cells));
}

function formatMinutes(seconds) {
  const m = seconds > 0 ? Math.max(1, Math.round(seconds / 60)) : 0;
  if (m < 60) return `${m} min`;
  return m % 60 === 0 ? `${m / 60} h` : `${Math.floor(m / 60)} h ${m % 60} min`;
}
function pretty(day) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

async function reviewAnything() {
  const r = NL.shelf.summary.resume;
  const withDue = NL.shelf.books.find(b => b.id === r?.id) || NL.shelf.books[0];
  if (withDue) go({ kind: "book", id: withDue.id, review: true });
}

// The tray's quick panel.

function renderPanel() {
  if (!NL.shelf) return;
  const { summary: s, books } = NL.shelf;
  const inner = el("div", { class: "panel-inner" });
  inner.append(el("div", { class: "row" }, pip(s.preparing ? "study" : s.dueCards ? "play" : "read", 64),
    el("div", { class: "col grow", style: "gap:2px" }, el("h4", {}, greeting()), el("p", { class: "small muted" }, subline(s, books)))));
  if (s.resume) {
    inner.append(el("div", { class: "card col", style: "padding:12px;gap:6px" }, el("div", { class: "caps" }, "Pick up where you left off"),
      el("b", {}, s.resume.title), el("span", { class: "small muted" }, `${s.resume.book} · next: ${s.resume.stageLabel}`),
      btn("Continue", () => NL.api.show_main(s.resume.id), "primary small")));
    if (s.resume.audio) inner.append(window.BookScreen.podcast(s.resume.id, s.resume.n, `${NL.base}/book/${s.resume.id}/${s.resume.audio}`, true));
  }
  if (s.dueCards) inner.append(btn(`Review ${s.dueCards} card${s.dueCards === 1 ? "" : "s"}`, () => NL.api.show_main(s.resume?.id || books[0]?.id), ""));
  const preparing = books.filter(b => b.preparing);
  for (const b of preparing.slice(0, 3)) {
    inner.append(el("div", { class: "col", style: "gap:4px" }, el("span", { class: "small" }, b.title),
      b.working ? progressBar(b.working.fraction) : "", el("span", { class: "tiny faint" }, b.line)));
  }
  inner.append(el("div", { class: "row" }, btn("Open NeuralLoop", () => NL.api.show_main(null), "small"),
    btn("Pause nudges until tomorrow", async () => { await NL.api.pause_until_tomorrow(); toast("Pip will stay quiet until tomorrow morning."); }, "small"),
    el("span", { class: "spacer" }), btn("Close", () => NL.api.hide_panel(), "small link")));
  app().replaceChildren(inner);
}

// First launch: sign in with Google for NotebookLM (or not now), then a book.

async function welcome() {
  const d = $("#dialog");
  const status = el("p", { class: "small muted" }, "");
  const card = el("div", { class: "card", style: "max-width:520px;align-items:center;text-align:center" },
    pip("hug", 140), el("h2", {}, "Hi! I'm Pip."),
    el("p", { class: "muted" }, "Give me a book you own and I'll turn each chapter into a small loop: a podcast and video, a reading plan, recall, a map, and flashcards."),
    el("p", { class: "small muted" }, "NotebookLM makes the podcasts and videos with your Google account. Without it, I use the AI you choose in Settings."), status);
  const row = el("div", { class: "row", style: "justify-content:center" });
  const later = btn("Not now", async () => { await NL.api.cancel_sign_in(); done(); });
  const signIn = btn("Sign in with Google", async () => {
    signIn.disabled = true; status.textContent = "A browser window is opening. Sign in to Google there, then come back.";
    const result = await NL.api.sign_in();
    if (result.ok) { status.textContent = `Signed in as ${result.account.email || "you"}.`; setTimeout(done, 900); }
    else if (!result.cancelled) { status.textContent = result.message || "Sign-in didn't finish. You can try again from Settings."; signIn.disabled = false; }
  }, "primary");
  row.append(later, signIn);
  card.append(row);
  NL.on("signin", text => { status.textContent = text; });
  d.replaceChildren(card); d.hidden = false;
  signIn.focus();
  async function done() {
    d.hidden = true; d.replaceChildren();
    await NL.api.finish_first_run();
  }
}

// Settings.

const PAGES = [
  ["account", "Account", "Google, NotebookLM, and your library"],
  ["ai", "Your AI", "Engine, models, and keys"],
  ["voices", "Voices", "The podcast hosts' voices"],
  ["nudges", "Nudges", "Gentle reminders from Pip"],
];

async function renderSettings(page) {
  const nav = el("nav", { "aria-label": "Settings pages" });
  for (const [id, title, sub] of PAGES) {
    const b = el("button", { type: "button", class: id === page ? "on" : "", "aria-current": id === page ? "page" : "" }, el("b", {}, title), el("span", {}, sub));
    b.onclick = () => go({ kind: "settings", page: id });
    nav.append(b);
  }
  nav.append(el("p", { class: "tiny faint", style: "padding:12px" }, "Keys stay in Windows Credential Manager. Only the chapter being prepared is ever sent to an AI."));
  const content = el("div", { class: "content", id: "main" }, el("div", { class: "row" }, el("span", { class: "spinner" }), "One moment…"));
  const top = topbar("Settings", () => go({ kind: "library" }));
  app().replaceChildren(top, el("div", { class: "settings" }, nav, content));
  const body = page === "ai" ? await aiPage() : page === "voices" ? await voicesPage() : page === "nudges" ? await nudgesPage() : await accountPage();
  content.replaceChildren(body);
}

function topbar(title, back, ...extra) {
  const bar = el("header", { class: "topbar" });
  const b = btn([icon("back"), "Library"], back, "small");
  bar.append(b, el("span", { class: "title" }, title), el("span", { class: "spacer" }), ...extra);
  return bar;
}

function card(title, ...kids) { return el("section", { class: "card col" }, title ? el("h3", {}, title) : "", ...kids); }

async function accountPage() {
  const col = el("div", { class: "col" });
  const who = el("div", { class: "row" }, el("span", { class: "spinner" }), "Checking your Google account…");
  const google = card("Google account", el("p", { class: "small muted" }, "One sign-in for NotebookLM, which makes podcasts, videos, and study material with your Google account."), who);
  col.append(google);
  const usage = card("NotebookLM's allowance", usageView(NL.shelf.usage));
  col.append(usage);
  const info = await NL.api.library_info();
  col.append(card("Your library", el("p", { class: "small muted" }, `Your books take ${info.text} on this PC, in ${info.folder}.`),
    el("div", { class: "row" }, btn("Remove every book…", async () => {
      const answer = await dialog("Remove every book?", "Every book, its chapters, podcasts, videos, and your progress go to the Recycle Bin.",
        [{ label: "Keep them", value: "keep" }, { label: "Remove every book", value: "remove", kind: "primary" }]);
      if (answer === "remove") { await NL.api.remove_all_books(); toast("Your shelf is empty again."); go({ kind: "library" }); }
    }, "danger small"))));
  NL.api.account().then(account => {
    who.replaceChildren();
    if (account.signedIn) {
      who.append(el("span", { class: "ok" }, "●"), el("span", {}, `Signed in as ${account.email || "you"}`), el("span", { class: "spacer" }),
        btn("Sign out", async () => { await NL.api.sign_out(); go({ kind: "settings", page: "account" }); }, "small"));
    } else {
      const status = el("span", { class: "small muted" }, "");
      NL.on("signin", text => { status.textContent = text; });
      const signIn = btn("Sign in with Google", async () => {
        signIn.disabled = true; status.textContent = "A browser window is opening. Sign in there, then come back.";
        const result = await NL.api.sign_in();
        if (result.ok) go({ kind: "settings", page: "account" });
        else { signIn.disabled = false; status.textContent = result.message || "Sign-in didn't finish."; }
      }, "primary");
      who.append(el("span", { class: "faint" }, "○"), el("span", {}, "Not signed in"), el("span", { class: "spacer" }), signIn);
      who.after(status);
    }
  });
  return col;
}

function usageView(usage) {
  if (!usage || !usage.known) return el("p", { class: "small muted" }, "Sign in with Google to see how much NotebookLM can still make.");
  const meter = (label, w) => w ? el("div", { class: "meter" }, el("div", { class: "row" }, el("h3", {}, `${Math.round(w.remaining)}%`), el("span", { class: "small faint" }, "left")),
    progressBar(w.remaining / 100), el("span", { class: "tiny faint" }, `${label} · resets ${new Date(w.resetsAt).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}`)) : "";
  return el("div", { class: "row wrap", style: "gap:24px" }, meter("Five hours", usage.fiveHour), meter("This week", usage.weekly),
    el("p", { class: "small muted" }, `Podcast now: ${usage.podcast ? "yes" : "not yet"} · Video now: ${usage.video ? "yes" : "not yet"}`));
}

const ENGINE_ICONS = { auto: "✨", notebooklm: "📒", local: "💻" };
const ENGINE_NOTES = { auto: "Your AI steps in whenever NotebookLM can't, so books always finish.",
  notebooklm: "Wait for NotebookLM, even when it's busy or out of daily uses.", local: "Free and private with Ollama, or the models and keys you choose." };

async function aiPage() {
  const s = await NL.api.ai_settings();
  const state = { engine: s.config.engine, makePreset: s.makePreset || "ollama", makeModel: s.config.make.model || "",
    makeBaseUrl: s.config.make.baseUrl || "", recallPreset: s.recallPreset || "ollama", recallModel: s.config.recall.model || "",
    recallBaseUrl: s.config.recall.baseUrl || "", keys: {}, prepareEverything: s.prepareEverything, hermesTools: s.config.hermesTools };
  const col = el("div", { class: "col" });
  const choices = el("div", { class: "choices" });
  const drawChoices = () => {
    choices.replaceChildren(...Object.entries(s.engines).map(([id, title]) => {
      const b = el("button", { type: "button", class: "choice" + (state.engine === id ? " on" : ""), "aria-pressed": state.engine === id },
        el("b", {}, `${ENGINE_ICONS[id]} ${title.split(",")[0]}`), el("span", { class: "small muted" }, ENGINE_NOTES[id]));
      b.onclick = () => { state.engine = id; drawChoices(); drawMake(); };
      return b;
    }));
  };
  drawChoices();
  col.append(card("How Pip makes your books", choices,
    switchRow("Prepare whole books right away", "Off: each chapter is prepared just before you reach it, so your allowance goes to what you're about to study.",
      state.prepareEverything, v => { state.prepareEverything = v; })));
  const make = el("div", { class: "col" });
  const drawMake = () => {
    make.replaceChildren();
    if (state.engine === "notebooklm") { make.append(el("p", { class: "small muted" }, "Pip waits for NotebookLM for everything. Sign in under Account.")); return; }
    make.append(modelPicker(s, state, "make"));
    if (!s.ollama && state.makePreset === "ollama") {
      make.append(el("div", { class: "card sunk small" }, "Ollama isn't installed on this PC yet. ", link("Get Ollama for Windows", "https://ollama.com/download/windows"),
        " then come back and press Set up my PC's AI."));
    }
  };
  drawMake();
  col.append(card("Your AI", el("p", { class: "small muted" }, "Writes the reading guides, maps, quizzes, flashcards, and podcast scripts when NotebookLM can't."), make));
  col.append(card("Checking recall", el("p", { class: "small muted" }, "A small model checks your answers in your own words, one key point at a time. Word matching takes over if it can't."),
    modelPicker(s, state, "recall")));
  const report = el("div", { class: "col", style: "gap:6px" });
  const setupLine = el("p", { class: "small muted" });
  NL.on("setup", text => { setupLine.textContent = text; });
  const saveTest = btn("Save and test", async () => {
    saveTest.disabled = true; report.replaceChildren(el("div", { class: "row small" }, el("span", { class: "spinner" }), "Pip is asking each model a small question…"));
    await NL.api.save_ai(state);
    const result = await NL.api.check_ai();
    report.replaceChildren(...Object.entries(result).map(([role, r]) => el("div", { class: "check-row" },
      el("span", { class: r.ok ? "ok" : "bad" }, r.ok ? "✓" : "✗"),
      el("b", {}, role === "make" ? "Your AI" : role === "recall" ? "Recall" : role.replace("task:", "")),
      el("span", { class: "muted" }, r.ok ? `${r.name || r.provider} · ${r.model || ""} answered in ${Math.round(r.seconds || 0)} s` : r.message || "didn't answer"))));
    saveTest.disabled = false;
  }, "primary big");
  const setup = btn("Set up my PC's AI", async () => {
    setup.disabled = true; setupLine.textContent = "Starting…";
    const result = await NL.api.setup();
    setupLine.textContent = result.ok ? "Your PC's AI and voices are ready." : (result.lines.at(-1) || "Setup didn't finish.");
    setup.disabled = false;
  });
  col.append(el("div", { class: "row wrap" }, btn("Save without testing", async () => { await NL.api.save_ai(state); toast("Saved."); }),
    setup, el("span", { class: "spacer" }), saveTest), setupLine, report);
  return col;
}

function link(text, url) {
  const a = el("a", { href: "#" }, text);
  a.onclick = e => { e.preventDefault(); NL.api.open_link(url); };
  return a;
}

function switchRow(label, note, value, onChange) {
  const input = el("input", { type: "checkbox", role: "switch" });
  input.checked = value;
  input.onchange = () => onChange(input.checked);
  return el("label", { class: "switch" }, input, el("span", { class: "col", style: "gap:2px" }, el("span", {}, label), note ? el("span", { class: "small muted" }, note) : ""));
}

function modelPicker(s, state, role) {
  const box = el("div", { class: "col" });
  const draw = () => {
    box.replaceChildren();
    const tiles = el("div", { class: "tiles" });
    const options = role === "recall" ? s.presets.filter(p => ["ollama", "lmstudio", "anthropic", "openai", "openrouter", "custom"].includes(p.id)) : s.presets;
    for (const p of options) {
      const on = state[role + "Preset"] === p.id;
      const t = el("button", { type: "button", class: "tile" + (on ? " on" : ""), "aria-pressed": on }, el("b", {}, p.title));
      t.onclick = () => { state[role + "Preset"] = p.id; state[role + "Model"] = ""; state[role + "BaseUrl"] = ""; draw(); };
      tiles.append(t);
    }
    const preset = s.presets.find(p => p.id === state[role + "Preset"]);
    box.append(tiles, el("p", { class: "small muted" }, preset.detail));
    const model = el("input", { type: "text", list: `${role}-models`, placeholder: preset.defaultModel || "Leave empty for the default", value: state[role + "Model"] });
    model.oninput = () => { state[role + "Model"] = model.value; };
    const list = el("datalist", { id: `${role}-models` }, preset.suggestions.map(m => el("option", { value: m })));
    box.append(el("div", { class: "field" }, el("label", {}, "Model"), el("div", {}, model, list)));
    if (preset.id === "custom" || preset.id === "lmstudio") {
      const url = el("input", { type: "url", placeholder: preset.baseUrl || "https://…/v1", value: state[role + "BaseUrl"] });
      url.oninput = () => { state[role + "BaseUrl"] = url.value; };
      box.append(el("div", { class: "field" }, el("label", {}, "Address"), url));
    }
    if (preset.keyVariable) {
      const saved = s.keysSaved[preset.keyVariable];
      const key = el("input", { type: "password", placeholder: saved ? "Saved. Paste a new one to replace it" : preset.keyOptional ? "Optional" : "Paste your key", autocomplete: "off" });
      key.oninput = () => { state.keys[preset.keyVariable] = key.value; };
      const row = el("div", { class: "row" }, key);
      if (saved) row.append(btn("Forget", async () => { s.keysSaved = (await NL.api.forget_key(preset.keyVariable)).keysSaved; draw(); }, "small"));
      box.append(el("div", { class: "field" }, el("label", {}, "Key"), row));
      if (!s.keysPersistent) box.append(el("p", { class: "tiny faint" }, "This PC has no key store NeuralLoop can use, so keys last until NeuralLoop quits."));
    }
    if (preset.id === "hermes" && role === "make") {
      box.append(switchRow("Let Hermes use its tools", "Hermes can act on your PC with its tools, and text in a book could steer it. Only turn this on if you've limited its tools in Hermes.",
        state.hermesTools, v => { state.hermesTools = v; }));
    }
  };
  draw();
  return box;
}

async function voicesPage() {
  const s = await NL.api.ai_settings();
  const voices = [...s.config.voices];
  const known = new Set(s.voices.map(v => v[0]));
  if (!known.has(voices[0])) voices[0] = "af_heart";
  if (!known.has(voices[1])) voices[1] = "am_michael";
  const pick = i => {
    const sel = el("select", { "aria-label": i === 0 ? "Host A" : "Host B" }, s.voices.map(([id, label]) => el("option", { value: id }, label)));
    sel.value = voices[i];
    sel.onchange = () => { voices[i] = sel.value; };
    return sel;
  };
  const quality = el("select", { "aria-label": "Voice quality" }, el("option", { value: "fast" }, "Fast (smaller model, the default)"), el("option", { value: "best" }, "Best (full model, slower)"));
  quality.value = s.config.voiceQuality;
  const length = el("select", { "aria-label": "Podcast length" }, ["auto", "short", "default", "long"].map(v => el("option", { value: v },
    { auto: "Short for short chapters, otherwise the usual", short: "Short", default: "The usual", long: "Long" }[v])));
  length.value = s.config.audioLength;
  return el("div", { class: "col" },
    card("Your podcast hosts", el("p", { class: "small muted" }, "When NotebookLM isn't making the podcast, Kokoro voices it on this PC. Host A also narrates the explainer videos."),
      el("div", { class: "field" }, el("label", {}, "Host A"), pick(0)), el("div", { class: "field" }, el("label", {}, "Host B"), pick(1)),
      el("div", { class: "field" }, el("label", {}, "Quality"), quality), el("div", { class: "field" }, el("label", {}, "Podcast length"), length)),
    el("div", { class: "row" }, el("span", { class: "spacer" }), btn("Save", async () => {
      await NL.api.save_ai({ voices, voiceQuality: quality.value, audioLength: length.value, makePreset: s.makePreset, recallPreset: s.recallPreset,
        makeModel: s.config.make.model, makeBaseUrl: s.config.make.baseUrl, recallModel: s.config.recall.model, recallBaseUrl: s.config.recall.baseUrl });
      toast("Saved. New podcasts use these voices.");
    }, "primary big")));
}

const HOURS = [...Array(24).keys()];
const hourLabel = h => new Date(2000, 0, 1, h).toLocaleTimeString(undefined, { hour: "numeric" });

async function nudgesPage() {
  let { settings: s, moods, sounds } = await NL.api.nudge_settings();
  const save = async changes => { ({ settings: s } = await NL.api.save_nudges(changes)); };
  const col = el("div", { class: "col" });
  const quietStart = el("select", { "aria-label": "Quiet from" }, HOURS.map(h => el("option", { value: h }, hourLabel(h))));
  const quietEnd = el("select", { "aria-label": "Quiet until" }, HOURS.map(h => el("option", { value: h }, hourLabel(h))));
  quietStart.value = s.quietStart; quietEnd.value = s.quietEnd;
  quietStart.onchange = () => save({ quietStart: Number(quietStart.value) });
  quietEnd.onchange = () => save({ quietEnd: Number(quietEnd.value) });
  const paused = el("p", { class: "small muted" }, s.pausedUntil > Date.now() ? `Paused until ${new Date(s.pausedUntil).toLocaleString()}.` : "");
  col.append(card("Notifications",
    switchRow("Notifications from Pip", "", s.enabled, v => save({ enabled: v })),
    switchRow("When my next chapter is ready", "", s.chapterReady, v => save({ chapterReady: v })),
    switchRow("Gentle nudges", "At most one a day, only when something small is worth doing.", s.nudges, v => save({ nudges: v })),
    el("div", { class: "row" }, el("span", {}, "Quiet from"), quietStart, el("span", { class: "muted" }, "until"), quietEnd),
    el("div", { class: "row" }, btn("Send a test nudge", () => NL.api.test_nudge("gentle"), "small"),
      btn("Pause until tomorrow", async () => { await NL.api.pause_until_tomorrow(); go({ kind: "settings", page: "nudges" }); }, "small")), paused));
  const steps = el("div", { class: "col", style: "gap:8px" });
  const drawSteps = () => {
    steps.replaceChildren();
    s.steps.forEach((step, i) => {
      const sound = el("select", { "aria-label": `Step ${i + 1} sound` }, sounds.map(m => el("option", { value: m }, moods[m])));
      sound.value = step.sound;
      sound.onchange = async () => { s.steps[i].sound = sound.value; await save({ steps: s.steps }); };
      const hours = el("input", { type: "text", inputmode: "numeric", value: step.hours, style: "width:60px", "aria-label": `Step ${i + 1} hours` });
      hours.onchange = async () => { s.steps[i].hours = Number(hours.value) || step.hours; await save({ steps: s.steps }); drawSteps(); };
      steps.append(el("div", { class: "row" }, sound, el("span", { class: "muted" }, "after"), hours, el("span", { class: "muted" }, "hours away"),
        btn("Try", () => NL.api.test_nudge(step.sound), "small"),
        btn("Remove", async () => { s.steps.splice(i, 1); await save({ steps: s.steps }); drawSteps(); }, "small link")));
    });
    if (!s.steps.length) steps.append(el("p", { class: "small faint" }, "No steps: Pip only sends the usual nudges."));
  };
  drawSteps();
  const volume = el("input", { type: "range", min: 0, max: 1, step: 0.05, value: s.volume, "aria-label": "Volume" });
  volume.onchange = () => save({ volume: Number(volume.value) });
  const bigPip = el("select", { "aria-label": "How silly nudges arrive" }, el("option", { value: "1" }, "A big Pip on screen, plus a notification"),
    el("option", { value: "0" }, "Just a notification, like the others"));
  bigPip.value = s.bigPip ? "1" : "0";
  bigPip.onchange = () => save({ bigPip: bigPip.value === "1" });
  const repeat = el("input", { type: "text", inputmode: "numeric", value: s.repeatHours || "", placeholder: "off", style: "width:60px", "aria-label": "Repeat hours" });
  repeat.onchange = () => save({ repeatHours: Number(repeat.value) || 0 });
  col.append(card("Silly mode",
    switchRow("Silly sounds and a sad Pip when I've been away", "Only when something's ready for you. Never in quiet hours, never a guilt trip.", s.sillySounds, v => save({ sillySounds: v })),
    el("div", { class: "row" }, el("span", {}, "Arrives as"), bigPip), el("div", { class: "row" }, el("span", {}, "Volume"), volume),
    steps,
    el("div", { class: "row wrap" }, btn("Add a step", async () => { ({ settings: s } = await NL.api.add_silly_step("sadMeow")); drawSteps(); }, "small"),
      btn("Reset to 8, 12, and 24 hours", async () => {
        await save({ steps: [{ sound: "sadViolin", hours: 8 }, { sound: "sadMeow", hours: 12 }, { sound: "shocked", hours: 24 }], repeatHours: 0 });
        go({ kind: "settings", page: "nudges" });
      }, "small link")),
    el("div", { class: "row" }, el("span", {}, "Then repeat the last one every"), repeat, el("span", { class: "muted" }, "hours while I'm away"))));
  return col;
}

window.App = { go, toast, dialog, progressBar, confirmRemove, topbar, switchRow, link, refreshShelf, formatMinutes, cover };
