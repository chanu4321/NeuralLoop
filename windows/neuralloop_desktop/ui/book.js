// A book (BookView.swift, Steps.swift, StudyViews.swift): chapters in order, each chapter's five-step loop, and the
// book map. Steps tick themselves off from what you really did (playing, reading, answering, remaking, reviewing);
// "I've done this step" stays as the manual way.
"use strict";

const STAGES = ["prime", "read", "recall", "map", "space"];
const STAGE_ICONS = { prime: "🎧", read: "📖", recall: "💬", map: "🗺️", space: "🃏" };
const ITEMS = { study: "The reading guide", graph: "The concept map", quiz: "The quiz", cards: "Flashcards", mindmap: "The mind map", audio: "The podcast", video: "The video" };

const BookScreen = (() => {
  let data = null, id = null, chapterN = null, stage = null, mapView = false, cleanup = [], earnedTimer = null;

  const api = () => NL.api;
  const fileUrl = rel => `${NL.base}/book/${id}/${rel.split("/").map(encodeURIComponent).join("/")}`;
  const chapter = n => data.book.chapters.find(c => c.n === n);
  const state = n => data.chapters.find(c => c.n === n);
  const clean = text => plainMath(text || "");

  async function open(bookId, n, review = false) {
    id = bookId;
    data = await api().book(bookId);
    if (!data) return gone();
    data.wantReview = review;
    const wanted = n ?? data.last?.n ?? data.book.chapters[0]?.n ?? null;
    chapterN = wanted; stage = null; mapView = false;
    draw();
  }

  function close() {
    stopAll();
    if (id) api().close_book(id);
    id = null; data = null;
  }

  function stopAll() { cleanup.forEach(fn => { try { fn(); } catch { /* already gone */ } }); cleanup = []; }

  async function reload() {
    if (!id) return;
    const fresh = await api().book(id);
    if (!fresh) return gone();
    data = fresh;
  }

  /** The shelf changed (a new item made, a run started or ended): catch up without losing your place. */
  async function shelfChanged() {
    if (!id || document.querySelector(".chapter-body textarea:focus, .chapter-body input:focus")) return;
    const before = JSON.stringify(data?.book.chapters.map(c => c.status));
    await reload();
    const after = JSON.stringify(data?.book.chapters.map(c => c.status));
    if (before !== after) draw(true);
    else drawSidebar();
  }

  function gone() {
    app().replaceChildren(el("div", { class: "empty-state" }, pip("read", 140), el("h2", {}, "This book is no longer on your shelf"),
      el("p", { class: "muted" }, "It was removed. Everything else is right where you left it."),
      btn("Back to your shelf", () => App.go({ kind: "library" }), "primary")));
  }

  // Layout.

  function draw(keepStage = false) {
    stopAll();
    const book = data.book;
    const more = btn([icon("more"), "More"], moreMenu, "small");
    const mapBtn = btn(mapView ? "Chapters" : "🗺️ Book map", () => { mapView = !mapView; draw(); }, "small");
    mapBtn.title = "Your map of the book grows with every chapter you map";
    const extras = [mapBtn];
    if (!data.preparing) extras.push(btn("Prepare more", async () => { await api().prepare_more(id); App.toast("Pip is preparing podcasts and videos for every chapter."); }, "small"));
    extras.push(more);
    const top = App.topbar(book.title, () => App.go({ kind: "library" }), ...extras);
    const sidebar = el("nav", { class: "chapters", "aria-label": "Chapters" });
    const main = el("main", { class: "chapter-main", id: "main" });
    app().replaceChildren(top, el("div", { class: "book-page" }, sidebar, main));
    drawSidebar();
    if (mapView) return bookMap(main);
    const c = chapterN != null && chapter(chapterN);
    if (!c) {
      main.append(el("div", { class: "empty-state" }, pip(data.book.chapters.length ? "read" : "study", 160),
        el("h3", { class: "muted" }, data.book.chapters.length ? "Pick a chapter to start its loop." : "Pip is splitting the book into chapters…")));
      return;
    }
    if (!state(c.n).unlocked) return locked(main, c);
    chapterView(main, c, keepStage);
  }

  function drawSidebar() {
    const nav = document.querySelector(".chapters");
    if (!nav || !data) return;
    nav.replaceChildren(el("div", { class: "caps", style: "padding:6px 10px" }, "Chapters"));
    for (const c of data.book.chapters) {
      const s = state(c.n);
      const item = el("button", { type: "button", class: "chapter-item" + (c.n === chapterN && !mapView ? " on" : ""), "aria-current": c.n === chapterN ? "true" : "" },
        el("span", { class: "n" }, c.n), el("span", { class: "grow" }, el("div", { class: "small" }, c.title), el("div", { class: "tiny faint" }, caption(c, s))),
        !s.unlocked ? icon("lock") : s.closed ? el("span", { class: "ok", "aria-label": "Loop closed" }, "✓") : "");
      item.disabled = !s.unlocked;
      item.onclick = () => { chapterN = c.n; mapView = false; stage = null; draw(); };
      nav.append(item);
    }
  }

  function caption(c, s) {
    if (!s.unlocked) return "Opens when the chapter before is done";
    if (c.status.study === "skipped") return "Pip will prepare it when you get close";
    if (c.status.study !== "done") return c.status.study === "working" ? "Pip is preparing it…" : "Waiting its turn";
    if (s.next) return "Next: " + data.labels[s.next];
    return "Loop closed";
  }

  async function moreMenu() {
    const problem = await api().problem(id);
    const buttons = [{ label: "Show in folder", value: "folder" }, { label: "Remove book…", value: "remove", kind: "danger" }];
    if (problem) buttons.unshift({ label: "What happened with the last run?", value: "problem" });
    buttons.push({ label: "Close", value: "close", kind: "primary" });
    const answer = await App.dialog(data.book.title, "More for this book", buttons);
    if (answer === "folder") api().show_in_folder(id);
    if (answer === "problem") App.dialog(problem.card, problem.detail);
    if (answer === "remove") App.confirmRemove(id, data.book.title);
  }

  function locked(main, c) {
    const index = data.book.chapters.findIndex(x => x.n === c.n);
    const previous = data.book.chapters[index - 1];
    main.append(el("div", { class: "empty-state" }, pip("nap", 150), el("h2", {}, `“${c.title}” is waiting for you`),
      el("p", { class: "muted", style: "max-width:440px" }, `It opens when you finish the loop for “${previous?.title || "the chapter before"}”. One chapter at a time is how it sticks.`),
      state(c.n).ahead ? el("p", { class: "small faint", style: "max-width:440px" }, "Pip will prepare it when you get close, so your allowance goes to the chapters you're about to study.") : ""));
  }

  // One chapter.

  function chapterView(main, c, keepStage) {
    const s = state(c.n);
    if (!stage || !keepStage) {
      stage = data.last && data.last.n === c.n && STAGES.includes(data.last.stage) ? data.last.stage : (s.next || "prime");
      if (data.wantReview) { stage = "space"; data.wantReview = false; }
    }
    api().remember(id, c.n, stage);
    const steps = el("div", { class: "steps", role: "tablist", "aria-label": "Steps" });
    for (const st of STAGES) {
      const done = s.steps[st];
      const b = el("button", { type: "button", role: "tab", "aria-selected": st === stage, class: "step" + (st === stage ? " on" : "") + (done ? " done" : ""),
        "aria-label": done ? `${data.labels[st]}, done` : data.labels[st] }, el("span", { "aria-hidden": "true" }, done ? "✓" : STAGE_ICONS[st]), el("span", {}, data.labels[st]));
      b.onclick = () => { stage = st; stopAll(); chapterView(main, c, true); };
      steps.append(b);
    }
    const body = el("div", { class: "chapter-body" });
    main.replaceChildren(el("div", { class: "chapter-head" }, el("h1", { style: "font-size:28px" }, c.title), steps), body);
    const finish = btn([icon("check"), "I've done this step"], async () => {
      const result = await api().complete(id, c.n, stage);
      await reload();
      if (result.closed) return loopClosed(c);
      const next = state(c.n).next;
      if (next) stage = next;
      draw(true);
    }, "primary");
    finish.disabled = !!s.steps[stage];
    const content = el("div", { class: "col", style: "gap:20px" });
    body.append(content, el("div", { style: "margin-top:10px" }, finish));
    ({ prime: listenStep, read: readStep, recall: recallStep, map: mapStep, space: rememberStep })[stage](content, c);
  }

  /** A step that ticked itself off: "Nicely done", or the loop-closed hug. */
  async function earned(result, c) {
    if (!result) return;
    await reload();
    drawSidebar();
    document.querySelectorAll(".step").forEach((b, i) => { if (state(c.n).steps[STAGES[i]]) b.classList.add("done"); });
    if (result.closed) return loopClosed(c);
    const main = document.querySelector(".chapter-main");
    main.querySelector(".toast-earned")?.remove();
    const next = state(c.n).next;
    const box = el("div", { class: "toast-earned", role: "status" }, pip("hop", 64),
      el("div", { class: "col grow", style: "gap:4px" }, el("h4", {}, "Nicely done!"),
        el("p", { class: "small muted" }, `You finished ${result.label}, so Pip ticked it off for you.`)));
    if (next && next !== stage) box.append(btn(`On to ${data.labels[next]}`, () => { stage = next; box.remove(); chapterView(main, c, true); }, "primary"));
    box.append(btn("✕", () => box.remove(), "link"));
    main.append(box);
    clearTimeout(earnedTimer);
    earnedTimer = setTimeout(() => box.remove(), 8000);
  }

  function loopClosed(c) {
    const overlay = el("div", { class: "overlay" }, el("div", { class: "card" }, pip("hug", 200), el("h1", {}, "Loop closed!"),
      el("p", { class: "muted" }, "The next chapter is open. Pip is proud of you."),
      btn("Keep going", () => {
        overlay.remove();
        const index = data.book.chapters.findIndex(x => x.n === c.n);
        const next = data.book.chapters[index + 1];
        if (next) { chapterN = next.n; stage = null; }
        draw();
      }, "primary big")));
    document.body.append(overlay);
    overlay.querySelector("button").focus();
  }

  function stepProgress(fraction, text, detail) {
    return el("div", { class: "progress-row" }, el("b", { class: "small" }, text), App.progressBar(Math.min(1, fraction)), el("span", { class: "tiny faint" }, detail));
  }

  function notReady(what, item, c) {
    const status = c.status[item];
    const live = data.activity;
    const making = live && live.items.find(x => x.n === c.n && x.item === item);
    const queued = live && live.queue.find(x => x.n === c.n && x.item === item);
    const col = el("div", { class: "col grow", style: "gap:6px" });
    if (making) {
      col.append(el("div", { class: "row" }, el("h4", { class: "grow" }, what), making.percent ? el("b", { style: "color:var(--accent)" }, making.percent) : ""),
        el("p", { class: "small muted" }, making.step || "Pip is making it right now"), App.progressBar(making.fraction, making.slow),
        el("div", { class: "row small" }, making.detail, making.by ? el("span", { class: "pill", style: "background:var(--accent-soft);color:var(--accent)" },
          making.by === "NotebookLM" ? "NotebookLM" : "On your PC · " + making.by) : ""));
    } else {
      const title = status === "working" ? `${what}: Pip is making it right now.` : status === "skipped" ? `${what}: Pip will prepare this when you get close.`
        : status === "failed" ? `${what} needs another try.` : status === "waiting_quota" ? `${what} is waiting for NotebookLM.`
        : queued ? `${what} is in line: Pip is making the items ahead of it.` : `${what} is on Pip's list. It starts when Pip's next run does.`;
      col.append(el("h4", {}, title));
      if (queued && status !== "done" && status !== "skipped") col.append(el("span", { class: "small", style: "color:var(--accent)" }, queued.place));
      let detail = c.notes[item] || "";
      if (status === "waiting_quota" && !/didn't answer/i.test(detail)) {
        const u = data.usage;
        detail = u && u.known && u.fiveHour
          ? `NotebookLM has ${Math.round(u.fiveHour.remaining)}% of its five-hour allowance left; a podcast or video uses about 44%. It resets at ${new Date(u.fiveHour.resetsAt).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}, and Pip will try again then. Or make it with your own AI right now.`
          : "NotebookLM is at its limit for now. Pip will try again when it resets.";
      }
      if (detail) col.append(el("p", { class: "small muted" }, detail));
      if (status === "waiting_quota" || status === "failed") {
        const b = btn("⚡ Make it with my AI now", async () => { await api().make_with_my_ai(id); App.toast("Pip is making it with your AI."); }, "primary");
        b.disabled = data.preparing;
        col.append(b);
        if (data.preparing) col.append(el("p", { class: "tiny muted" }, "Pip is preparing this book right now. You can make it with your AI once that's done."));
      }
    }
    return el("div", { class: "card sunk row top", style: "gap:16px" }, pip(status === "working" || making ? "study" : "nap", 90), col);
  }

  // Listen & watch.

  function listenStep(body, c) {
    const s = state(c.n);
    const lengths = { audio: 0, video: 0 };
    const listened = el("div");
    const drawListened = () => {
      if (s.steps.prime || !(c.audio || c.video)) return listened.replaceChildren();
      const w = data.watch[String(c.n)] || { audio: [], video: [] };
      const share = (spans, len) => len > 0 ? Math.min(1, spans.reduce((t, [a, b]) => t + Math.max(0, Math.min(b, len) - Math.max(a, 0)), 0) / len) : 0;
      const heard = c.audio ? share(w.audio, lengths.audio) : null, seen = c.video ? share(w.video, lengths.video) : null;
      const parts = [heard != null ? `Heard ${Math.floor(heard * 100)}% of the podcast` : null, seen != null ? `watched ${Math.floor(seen * 100)}% of the video` : null].filter(Boolean).join(" · ");
      listened.replaceChildren(stepProgress(Math.max(heard || 0, seen || 0) / 0.85, parts.charAt(0).toUpperCase() + parts.slice(1),
        "This step ticks itself off once you've heard or watched most of one (85%). Skipping ahead doesn't count."));
    };
    body.append(listened, el("h3", {}, "Watch"));
    if (c.video) {
      const video = el("video", { class: "media", controls: true, preload: "metadata", src: fileUrl(c.video) });
      track(video, c, "video", len => { lengths.video = len; drawListened(); });
      body.append(video);
    } else body.append(notReady("The video", "video", c));
    body.append(el("h3", {}, "Listen"));
    if (c.audio) {
      body.append(podcast(id, c.n, fileUrl(c.audio), false, c.transcript, len => { lengths.audio = len; drawListened(); }));
      if (c.explainer && !c.video) body.append(el("p", { class: "small muted" }, "The explainer video is still being made."));
    } else body.append(notReady("The podcast", "audio", c));
    drawListened();
  }

  /** Reports believable stretches of playback (seeks and > 2x are left out in Python too). */
  function track(media, c, kind, onLength) {
    let last = null;
    const send = () => {
      if (media.paused || media.seeking) { last = null; return; }
      const now = performance.now(), t = media.currentTime;
      if (last) {
        const wall = (now - last.wall) / 1000;
        if (wall > 0.4) {
          api().record_play(id, c.n, kind, last.t, t, media.playbackRate, wall, media.duration || 0).then(r => { if (r) earned(r, c); });
          last = { t, wall: now };
        }
      } else last = { t, wall: now };
    };
    media.addEventListener("timeupdate", send);
    media.addEventListener("seeking", () => { last = null; });
    media.addEventListener("pause", () => { last = null; });
    media.addEventListener("loadedmetadata", () => onLength && onLength(media.duration || 0));
    cleanup.push(() => media.pause());
  }

  /** Play/pause, where you are, and a bar to jump around; with a transcript when Pip's own voices made it. */
  function podcast(bookId, n, url, compact = false, transcriptPath = null, onLength = null) {
    const audio = el("audio", { preload: "metadata", src: url });
    const play = el("button", { class: "play", type: "button", "aria-label": "Play" }, "▶");
    const bar = el("input", { type: "range", min: 0, max: 1000, value: 0, "aria-label": "Position" });
    const time = el("span", { class: "tiny faint", style: "min-width:84px;text-align:right" }, "0:00");
    const speed = el("select", { "aria-label": "Speed", class: "small" }, ["0.8", "1", "1.25", "1.5", "1.75", "2"].map(r => el("option", { value: r }, r + "×")));
    speed.value = "1";
    speed.onchange = () => { audio.playbackRate = Number(speed.value); };
    play.onclick = () => { audio.paused ? audio.play() : audio.pause(); };
    audio.onplay = () => { play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause"); };
    audio.onpause = () => { play.textContent = "▶"; play.setAttribute("aria-label", "Play"); };
    const mmss = s => isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00";
    audio.ontimeupdate = () => {
      if (audio.duration) bar.value = Math.round(audio.currentTime / audio.duration * 1000);
      time.textContent = `${mmss(audio.currentTime)} / ${mmss(audio.duration)}`;
      lines?.forEach((b, i) => b.classList.toggle("now", audio.currentTime >= b.dataset.start && (i + 1 >= lines.length || audio.currentTime < lines[i + 1].dataset.start)));
    };
    bar.oninput = () => { if (audio.duration) audio.currentTime = bar.value / 1000 * audio.duration; };
    audio.addEventListener("loadedmetadata", () => { time.textContent = `0:00 / ${mmss(audio.duration)}`; });
    const holder = el("div", { class: "col", style: "gap:10px" });
    const fake = { n };
    if (bookId === id) track(audio, chapter(n) || fake, "audio", onLength);
    else {
      // From the shelf or the panel: still counts toward that book's Listen step.
      let last = null;
      audio.addEventListener("timeupdate", () => {
        if (audio.paused || audio.seeking) { last = null; return; }
        const now = performance.now();
        if (last && (now - last.wall) / 1000 > 0.4) { NL.api.record_play(bookId, n, "audio", last.t, audio.currentTime, audio.playbackRate, (now - last.wall) / 1000, audio.duration || 0); last = { t: audio.currentTime, wall: now }; }
        else if (!last) last = { t: audio.currentTime, wall: now };
      });
      audio.addEventListener("seeking", () => { last = null; });
    }
    holder.append(el("div", { class: "player" }, play, bar, time, compact ? "" : speed, audio));
    let lines = null;
    if (transcriptPath && !compact) {
      const box = el("div", { class: "transcript", "aria-label": "Transcript" });
      holder.append(box);
      const load = async () => {
        const t = await NL.api.transcript(bookId, transcriptPath);
        lines = t.lines.map(line => {
          const b = el("button", { type: "button", "data-start": line.start || 0 }, el("b", { class: "small" }, line.speaker === "A" ? "Host A  " : "Host B  "), line.text);
          b.onclick = () => { audio.currentTime = line.start || 0; audio.play(); };
          return b;
        });
        box.replaceChildren(...lines);
        if (!t.complete) { const timer = setTimeout(load, 5000); cleanup.push(() => clearTimeout(timer)); }
      };
      load();
    }
    return holder;
  }

  // Read.

  async function readStep(body, c) {
    const s = state(c.n);
    const plan = await api().reading_plan(id, c.n);
    if (!plan) return;
    const soFar = el("div");
    const drawSoFar = p => {
      if (s.steps.read) return soFar.replaceChildren();
      const unit = plan.kind === "pdf" ? (p.total === 1 ? "page" : "pages") : (p.total === 1 ? "section" : "sections");
      soFar.replaceChildren(stepProgress(p.fraction, `Read ${Math.floor(p.fraction * 100)}% · ${p.counted} of ${p.total} ${unit}`,
        p.fraction >= 0.85 && !p.reachedLast ? "Nearly there: this step ticks itself off once you reach the end."
          : "Pages count as you read them, at your own pace. This step ticks itself off at 85% and the last page."));
    };
    drawSoFar(plan.done);
    body.append(soFar);
    if (c.guide.length) {
      body.append(el("div", { class: "card sunk col", style: "gap:8px" }, el("h4", {}, "Your reading plan"),
        c.guide.map(g => el("div", { class: "row top small" }, levelPill(g.level), el("span", {}, el("b", {}, g.section), "  ", el("span", { class: "muted" }, g.why))))));
    }
    const pages = [];
    if (plan.kind === "pdf") {
      const holder = el("div", { class: "reader" });
      for (let i = 0; i < plan.pages; i++) {
        const img = el("img", { class: "pdf-page", loading: "lazy", alt: `Page ${i + 1}`, src: `${NL.base}/page/${id}/${plan.file}/${i}.png` });
        holder.append(img); pages.push(img);
      }
      body.append(holder);
    } else {
      const reader = el("article", { class: "reader" });
      plan.sections.forEach(section => {
        const div = el("section", {});
        section.forEach(i => div.append(block(plan.blocks[i], c)));
        reader.append(div); pages.push(div);
      });
      reader.addEventListener("click", e => {
        const a = e.target.closest("a[data-href]");
        if (a) { e.preventDefault(); NL.api.open_link(a.dataset.href); }
      });
      body.append(reader);
    }
    if (s.steps.read || !plan.needs.length) return;
    const scroller = document.querySelector(".chapter-main");
    let last = performance.now();
    const timer = setInterval(async () => {
      const now = performance.now(), seconds = (now - last) / 1000;
      last = now;
      const view = scroller.getBoundingClientRect();
      const visible = pages.map((p, i) => [i, p.getBoundingClientRect()]).filter(([, r]) => {
        const height = r.bottom - r.top, shown = Math.min(r.bottom, view.bottom) - Math.max(r.top, view.top);
        return height > 0 && shown > 0 && (shown >= 0.4 * height || shown >= 0.4 * (view.bottom - view.top));
      }).map(([i]) => i);
      const earning = NL.focused && !document.hidden && Date.now() - NL.lastInput <= 90000;
      const result = await api().credit_reading(id, c.n, visible, seconds, plan.needs, earning);
      if (result) { clearInterval(timer); soFar.replaceChildren(); return earned(result, c); }
      if (earning && visible.length) {
        const fresh = await api().reading_plan(id, c.n);
        if (fresh) drawSoFar(fresh.done);
      }
    }, 1000);
    cleanup.push(() => clearInterval(timer));
  }

  function levelPill(level) {
    const [label, cls] = level === "deep" ? ["Deep read", "level-deep"] : level === "skim" ? ["Skim", "level-skim"] : ["Read", "level-normal"];
    return el("span", { class: "pill " + cls }, label);
  }

  /** One block of chapter Markdown: a figure, a heading (with its reading-plan label), a caption, a list, code, or a paragraph. */
  function block(text, c) {
    let m;
    if ((m = text.match(/^!\[([^\]]*)\]\((img\/[\w.-]+)\)$/))) {
      return el("figure", {}, el("img", { src: fileUrl("chapters/" + m[2]), alt: m[1] }));
    }
    if ((m = text.match(/^(#{1,3})\s+(.*)$/))) {
      const title = m[2], low = title.toLowerCase();
      const g = c.guide.find(g => low.includes(g.section.toLowerCase()) || g.section.toLowerCase().includes(low));
      return el(m[1].length === 1 ? "h2" : "h3", {}, inline(title), g ? levelPill(g.level) : "");
    }
    if (text.startsWith("```")) return el("pre", {}, el("code", {}, text.replace(/^```[^\n]*\n?/, "").replace(/```$/, "")));
    if (text.startsWith("*") && text.endsWith("*") && !text.startsWith("**")) return el("p", { class: "caption" }, inline(text.replace(/^\*+|\*+$/g, "")));
    const lines = text.split("\n");
    if (lines.every(l => /^\s*([-*+]|\d+[.)])\s+/.test(l))) {
      const ordered = /^\s*\d/.test(lines[0]);
      return el(ordered ? "ol" : "ul", {}, lines.map(l => el("li", {}, inline(l.replace(/^\s*([-*+]|\d+[.)])\s+/, "")))));
    }
    return el("p", {}, inline(text));
  }

  /** **bold**, *emphasis*, `code`, and [links](https://…), safely (built as elements, never as HTML). */
  function inline(text) {
    const frag = document.createDocumentFragment();
    const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
    let at = 0, m;
    text = clean(text);
    while ((m = re.exec(text))) {
      if (m.index > at) frag.append(text.slice(at, m.index));
      const t = m[0];
      if (t.startsWith("**")) frag.append(el("strong", {}, t.slice(2, -2)));
      else if (t.startsWith("`")) frag.append(el("code", {}, t.slice(1, -1)));
      else if (t.startsWith("[")) {
        const [, label, href] = t.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        frag.append(/^https?:\/\//i.test(href) ? el("a", { href: "#", "data-href": href }, label) : label);
      } else frag.append(el("em", {}, t.slice(1, -1)));
      at = m.index + t.length;
    }
    if (at < text.length) frag.append(text.slice(at));
    return frag;
  }

  // Recall.

  function recallStep(body, c) {
    const s = state(c.n);
    let showQuiz = false, index = 0;
    if (!s.steps.recall && (c.recall.length || c.quiz.length)) {
      const total = c.quiz.length, answered = Math.min(s.quiz.i, total);
      body.append(stepProgress(total ? answered / total : 0, total ? `Quiz: ${answered} of ${total} answered` : "Answer one question in your own words",
        !c.recall.length ? "This step ticks itself off when you finish the quiz."
          : total ? "This step ticks itself off when Pip checks an answer in your own words, or when you finish the quiz." : "This step ticks itself off when Pip checks your answer."));
    }
    const holder = el("div", { class: "col", style: "gap:16px" });
    const drawMode = () => {
      holder.replaceChildren();
      if (c.quiz.length) {
        const seg = el("div", { class: "segmented", role: "group", "aria-label": "Recall" });
        for (const [quiz, label] of [[false, "In your own words"], [true, "Quiz"]]) {
          const b = el("button", { type: "button", class: showQuiz === quiz ? "on" : "" }, label);
          b.onclick = () => { showQuiz = quiz; drawMode(); };
          seg.append(b);
        }
        holder.append(seg);
      }
      holder.append(showQuiz ? quizView(c) : ownWords());
    };
    const ownWords = () => {
      if (!c.recall.length) return notReady("Recall questions", "study", c);
      const prompt = c.recall[Math.min(index, c.recall.length - 1)];
      const answer = el("textarea", { "aria-label": "Your answer, in your own words" });
      const result = el("div");
      const check = btn("Check my answer", async () => {
        check.disabled = true; check.textContent = "Pip is checking…";
        const asked = index;
        const r = await api().check_recall(id, c.n, index, answer.value);
        check.disabled = false; check.textContent = "Check my answer";
        if (asked !== index) return;
        result.replaceChildren(el("div", { class: "card sunk col", style: "gap:8px" },
          prompt.keyPoints.map((k, i) => el("div", { class: "row top small", style: `color:var(${r.covered[i] ? "--mint" : "--ink3"})` }, r.covered[i] ? "✓" : "○", el("span", { style: "color:var(--ink)" }, k))),
          el("p", { class: "small" }, r.feedback), r.by ? el("p", { class: "tiny faint" }, `Checked by ${r.by}`) : ""));
        if (!(index + 1 < c.recall.length) && c.quiz.length) row.append(btn("On to the quiz", () => { showQuiz = true; drawMode(); }));
        if (r.earned) earned(r.earned, c);
      }, "primary");
      answer.oninput = () => { check.disabled = !answer.value.trim(); };
      check.disabled = true;
      const row = el("div", { class: "row" }, check);
      if (index + 1 < c.recall.length) row.append(btn("Next question", () => { index++; drawMode(); }));
      return el("div", { class: "col", style: "gap:14px" }, el("span", { class: "small faint" }, `Question ${index + 1} of ${c.recall.length}`),
        el("h3", {}, clean(prompt.prompt)), el("p", { class: "small muted" }, "No peeking. Pulling it out of your head is the whole trick."), answer, row, result);
    };
    drawMode();
    body.append(holder);
  }

  function quizView(c) {
    const holder = el("div");
    let picked = null, hint = false;
    const draw = () => {
      const q = state(c.n).quiz, total = c.quiz.length;
      holder.replaceChildren();
      if (q.i >= total) {
        const right = q.results.filter(Boolean).length, great = total > 0 && right >= Math.ceil(total * 0.8);
        holder.append(el("div", { class: "col center", style: "align-items:center;padding:20px 0" }, pip(great ? "proud" : "hug", 140), el("h2", {}, `${right} of ${total} right`),
          el("p", { class: "muted" }, great ? "Wonderful! That chapter's really sinking in." : "Nice work. The ones that slipped by are great flashcard material."),
          btn("Try again", async () => { await api().set_quiz(id, c.n, 0, []); await reload(); picked = null; draw(); })));
        return;
      }
      const question = c.quiz[q.i];
      const bars = el("div", { class: "qbar" }, [...Array(total).keys()].map(i => el("i", { class: i < q.i ? (q.results[i] ? "ok" : "no") : i === q.i ? "now" : "" })));
      const options = question.options.map((option, i) => {
        const answered = picked !== null, right = i === question.a, chosen = i === picked;
        const b = el("button", { type: "button", class: "option" + (answered && right ? " right" : answered && chosen ? " wrong" : "") },
          el("span", { class: "letter" }, "ABCDEF"[Math.min(i, 5)]),
          el("span", { class: "col grow", style: "gap:4px" }, el("span", {}, clean(option)),
            answered && (right || chosen) && question.why[i] ? el("span", { class: "small muted" }, clean(question.why[i])) : ""));
        b.disabled = answered;
        b.onclick = async () => {
          picked = i;
          const results = [...q.results];
          while (results.length <= q.i) results.push(false);
          results[q.i] = right;
          const r = await api().set_quiz(id, c.n, q.i, results);
          await reload(); draw();
          if (r) earned(r, c);
        };
        return b;
      });
      const actions = el("div", { class: "row" });
      if (question.hint && !hint && picked === null) actions.append(btn("Show a hint", () => { hint = true; draw(); }));
      actions.append(el("span", { class: "spacer" }));
      if (picked !== null) actions.append(btn(q.i + 1 >= total ? "See my score" : "Next question", async () => {
        const r = await api().set_quiz(id, c.n, q.i + 1, q.results);
        picked = null; hint = false; await reload(); draw();
        if (r) earned(r, c);
      }, "primary"));
      const bubble = picked === null ? "Take your time. Guessing and checking is how memory grows." : picked === question.a ? "Yes! Exactly right." : "Close! The right one is highlighted.";
      holder.append(el("div", { class: "row top", style: "gap:20px" },
        el("div", { class: "col grow", style: "gap:12px" }, bars, el("span", { class: "small faint" }, `Question ${q.i + 1} of ${total}`), el("h3", {}, clean(question.q)),
          ...options, actions, hint ? el("p", { class: "small card", style: "background:var(--butter-soft);padding:10px" }, "💡 " + clean(question.hint)) : ""),
        el("div", { class: "col", style: "width:150px;align-items:center;gap:6px" }, el("p", { class: "small card center", style: "padding:10px" }, bubble),
          pip(picked !== null && picked === question.a ? "hop" : "read", 110))));
    };
    draw();
    return holder;
  }

  // Map.

  function mapStep(body, c) {
    const chapterGraph = graphFor(c);
    const modes = [...(c.mindmap ? ["remake", "mind"] : []), ...(chapterGraph.nodes.length ? ["concepts"] : [])];
    if (!modes.length) return body.append(notReady("The mind map", "mindmap", c));
    let mode = c.mindmap ? (state(c.n).steps.map ? "mind" : "remake") : "concepts";
    const holder = el("div", { class: "col", style: "gap:14px" });
    const drawMode = () => {
      const seg = el("div", { class: "segmented", role: "group", "aria-label": "Map view" });
      for (const m of modes) {
        const b = el("button", { type: "button", class: m === mode ? "on" : "" }, { remake: "Remake from memory", mind: "Mind map", concepts: "Concept graph" }[m]);
        b.onclick = () => { mode = m; drawMode(); };
        seg.append(b);
      }
      const view = mode === "remake" ? remakeView(c, () => { mode = "mind"; drawMode(); }) : mode === "mind" ? mindMap(c.mindmap) : graphView(chapterGraph, {});
      holder.replaceChildren(seg, view);
    };
    drawMode();
    body.append(holder);
  }

  function graphFor(c) {
    const ids = new Set();
    const nodes = data.book.graph.nodes.filter(n => n.chapter === c.n);
    nodes.forEach(n => ids.add(n.id));
    const edges = data.book.graph.edges.filter(e => ids.has(e.source) && ids.has(e.target));
    const tour = (c.graph?.tour || []).map(t => ({ ...t, nodeIds: t.nodeIds.map(x => `c${c.n}:${x}`).filter(x => ids.has(x)) })).filter(t => t.nodeIds.length);
    return { nodes, edges, tour };
  }

  function graphView(graph, options) {
    const holder = el("div");
    new GraphExplorer(holder, graph, options);
    return holder;
  }

  function mindMap(root) {
    const palette = ["--accent", "--mint", "--sky", "--rose", "--violet", "--gold"];
    const node = (n, depth, color) => {
      const wrap = el("div", { class: "mnode" });
      const open = { v: depth < 1 };
      const chip = el(n.children.length ? "button" : "div", { class: "mchip" + (depth === 0 ? " root" : ""), style: `--c:var(${color})`, tabindex: 0 }, el("span", {}, n.name));
      if (n.children.length) {
        const mark = el("span", { style: `color:var(${color})`, "aria-hidden": "true" }, open.v ? "⊖" : "⊕");
        chip.append(mark);
        chip.setAttribute("aria-expanded", open.v);
        chip.onclick = () => { open.v = !open.v; mark.textContent = open.v ? "⊖" : "⊕"; chip.setAttribute("aria-expanded", open.v); kids.hidden = !open.v; link.hidden = !open.v; };
      }
      const link = el("i", { class: "mlink", style: `--c:var(${color})` });
      const kids = el("div", { class: "mkids", style: `--c:var(${color})` }, n.children.map((child, i) => {
        const childColor = depth === 0 ? palette[i % palette.length] : color;
        return el("div", { class: "row", style: "gap:0" }, el("i", { class: "mlink", style: `--c:var(${childColor});width:14px` }), node(child, depth + 1, childColor));
      }));
      link.hidden = kids.hidden = !open.v || !n.children.length;
      wrap.append(chip, link, kids);
      return wrap;
    };
    return el("div", { class: "mind" }, el("p", { class: "tiny faint", style: "margin-bottom:8px" }, "Click a branch to fold or unfold it"), node(root, 0, "--accent"));
  }

  function remakeView(c, seeMap) {
    const map = c.mindmap;
    const guess = el("textarea", { "aria-label": "Your map, from memory", placeholder: "Foundations\n- key terms\nIn practice\n- failure modes" });
    guess.value = state(c.n).remake.guess || "";
    let draft;
    guess.oninput = () => { clearTimeout(draft); draft = setTimeout(() => api().remake_draft(id, c.n, guess.value), 1000); };
    cleanup.push(() => { clearTimeout(draft); api().remake_draft(id, c.n, guess.value); });
    const note = el("span", { class: "small muted" });
    const result = el("div");
    const compare = btn("Compare with the real map", async () => {
      if (!guess.value.trim()) { note.textContent = "Write at least one branch first"; return; }
      note.textContent = "";
      const r = await api().check_remake(id, c.n, guess.value);
      const good = r.percent >= 70;
      result.replaceChildren(el("div", { class: "row top", style: "gap:18px" },
        el("div", { class: "col grow", style: "gap:6px" }, el("b", { class: "small" }, "The real map"), el("span", { class: "tiny faint" }, "Green means you remembered it"),
          r.rows.map(row => el("div", { class: "card", style: `padding:8px;background:var(${row.remembered ? "--mint-soft" : "--sunk"})` },
            el("div", { class: "small" }, (row.remembered ? "✓ " : "") + row.name),
            row.children.map(child => el("div", { class: "tiny muted" }, `${child.remembered ? "✓" : "·"} ${child.name}`))))),
        el("div", { class: "col grow", style: "gap:8px" }, el("b", { class: "small" }, "Your version"),
          r.lines.map(line => el("div", { class: "small card", style: "padding:6px;background:var(--sunk)" }, line)),
          el("div", { class: "row" }, el("h1", {}, `${r.percent}%`), el("span", { class: "small muted" }, "remembered" + (r.best > r.percent ? ` · best ${r.best}%` : ""))),
          el("p", { class: "small muted" }, good ? "Brilliant. You can sketch this chapter from memory." : "Look at the grey branches, then try again tomorrow. It gets easier every time."),
          el("div", { class: "row" }, btn("See the full map", seeMap, "primary"), btn("Try again", () => { guess.value = ""; result.replaceChildren(); })),
          pip(good ? "proud" : "hug", 90))));
      if (r.earned) earned(r.earned, c);
    }, "primary");
    return el("div", { class: "col", style: "gap:12px" }, el("h3", {}, "Remake the map from memory"),
      el("p", { class: "small muted" }, `Before you look: write the main branches of “${map.name}” as you remember them, one per line. Add sub-ideas under a branch by starting the line with a dash.`),
      guess, el("div", { class: "row" }, compare, note), result);
  }

  // Remember.

  async function rememberStep(body, c) {
    if (!c.cards.length) return body.append(notReady("Flashcards", "cards", c));
    const holder = el("div", { class: "col", style: "align-items:center;gap:18px" });
    body.append(holder);
    const draw = async () => {
      const due = await api().due_cards(id, c.n);
      const s = state(c.n);
      holder.replaceChildren();
      if (!s.steps.space) holder.append(stepProgress(s.cardsSeen / Math.max(1, c.cards.length), `Reviewed ${s.cardsSeen} of ${c.cards.length} card${c.cards.length === 1 ? "" : "s"}`,
        "This step ticks itself off once you've seen every card once."));
      if (!due.length) {
        holder.append(pip("proud", 150), el("h3", {}, "All caught up for this chapter."),
          el("p", { class: "muted" }, "Pip will bring cards back right before you'd forget them."));
        return;
      }
      const card = due[0];
      let flipped = false;
      const face = el("button", { type: "button", class: "flash", "aria-live": "polite" }, card.front);
      const rate = el("div", { class: "row" });
      const hintText = el("p", { class: "small muted" }, "Say the answer in your head, then click the card.");
      face.onclick = () => {
        flipped = !flipped;
        face.textContent = flipped ? card.back : card.front;
        face.classList.toggle("back", flipped);
        rate.hidden = !flipped; hintText.hidden = flipped;
        if (flipped) rate.querySelector("button")?.focus();
      };
      for (const [rating, label] of [["again", "Again"], ["hard", "Hard"], ["good", "Good"], ["easy", "Easy"]]) {
        rate.append(btn(label, async () => {
          const r = await api().review(id, card.id, rating);
          await reload();
          if (r) earned(r, c);
          draw();
        }, "big"));
      }
      rate.hidden = true;
      holder.append(el("span", { class: "small faint" }, `${due.length} card${due.length === 1 ? "" : "s"} to go`), face, hintText, rate);
      face.focus();
    };
    draw();
  }

  // The book map.

  function bookMap(main) {
    const chapters = data.book.chapters;
    const ideas = {};
    for (const n of data.book.graph.nodes) if (n.chapter != null) ideas[n.chapter] = (ideas[n.chapter] || 0) + 1;
    const earnedChapters = chapters.filter(c => state(c.n).steps.map && ideas[c.n]).map(c => c.n);
    const col = el("div", { class: "chapter-body", style: "max-width:none" }, el("h1", { style: "font-size:28px" }, "Book map"),
      el("p", { class: "muted" }, "Your map of the book grows with every chapter you map. Dashed lines join the same idea across chapters; pink dotted lines show disagreements."));
    const strip = el("div", { class: "growth" });
    chapters.forEach(c => {
      const k = earnedChapters.indexOf(c.n);
      if (k >= 0) strip.append(el("span", {}, el("i", { style: `display:inline-block;width:9px;height:9px;border-radius:50%;background:${paletteColor(k)};margin-right:6px` }), `🌱 Chapter ${c.n} · ${ideas[c.n]} ideas`));
      else strip.append(el("span", { class: "later" }, `${state(c.n).unlocked ? "🌰" : "🔒"} Chapter ${c.n}`));
    });
    col.append(strip);
    if (!earnedChapters.length) {
      const first = chapters.find(c => !state(c.n).steps.map) || chapters[0];
      col.append(el("div", { class: "card sunk col", style: "align-items:center;padding:20px" }, pip("play", 130), el("h3", {}, "Your map is a tiny seed"),
        first ? el("p", { class: "muted center", style: "max-width:460px" }, `Finish chapter ${first.n}'s Map step and its ideas will sprout here. Every chapter after that makes the map bigger.`) : "",
        first ? btn(`Go to chapter ${first.n}`, () => { chapterN = first.n; mapView = false; stage = "map"; draw(true); }, "primary") : ""));
    } else {
      const ids = new Set(data.book.graph.nodes.filter(n => earnedChapters.includes(n.chapter)).map(n => n.id));
      const graph = { nodes: data.book.graph.nodes.filter(n => ids.has(n.id)), edges: data.book.graph.edges.filter(e => ids.has(e.source) && ids.has(e.target)),
        tour: data.book.graph.tour.map(t => ({ ...t, nodeIds: t.nodeIds.filter(x => ids.has(x)) })).filter(t => t.nodeIds.length) };
      const seen = new Set(data.mapSeen);
      const fresh = earnedChapters.filter(n => !seen.has(n));
      const holder = el("div");
      const explorer = new GraphExplorer(holder, graph, { colorBy: "chapter", chapterOrder: earnedChapters,
        chapterTitles: Object.fromEntries(chapters.map(c => [String(c.n), c.title])), saved: data.mapPos, fresh,
        onPlaced: placed => api().place_on_map(id, placed, earnedChapters),
        onOpenChapter: n => { chapterN = n; mapView = false; stage = null; draw(); } });
      if (fresh.length) api().place_on_map(id, {}, earnedChapters);
      if (earnedChapters.length > 1) strip.append(btn("▶ Replay growth", () => explorer.replay(), "small"));
      col.append(holder);
    }
    main.replaceChildren(col);
  }

  return { open, close, shelfChanged, podcast };
})();

window.BookScreen = BookScreen;

/** Models sometimes write math as LaTeX ("$M \times N$"): shown as plain text (PlainMath). */
function plainMath(text) {
  if (!text.includes("$") && !text.includes("\\")) return text;
  const symbols = [["\\times", "×"], ["\\cdot", "·"], ["\\rightarrow", "→"], ["\\to", "→"], ["\\leftarrow", "←"], ["\\leq", "≤"], ["\\le", "≤"],
    ["\\geq", "≥"], ["\\ge", "≥"], ["\\neq", "≠"], ["\\approx", "≈"], ["\\infty", "∞"], ["\\pm", "±"], ["\\{", "{"], ["\\}", "}"], ["\\%", "%"], ["\\,", " "]];
  for (const [latex, symbol] of symbols) text = text.split(latex).join(symbol);
  text = text.replace(/\$\$?([^\s$](?:[^$]*[^\s$])?)\$\$?/g, "$1");
  return text.replace(/\\(?:text|mathrm|mathbf)\{([^}]*)\}/g, "$1");
}
