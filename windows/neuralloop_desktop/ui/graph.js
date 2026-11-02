// The concept graph and the growing book map (GraphLayout.swift and GraphExplorer.swift): a small seeded force
// layout, then an SVG explorer: tap an idea, follow its connections, take the guided tour, rebuild it from memory,
// or ask how two ideas are connected. Ideas on the book map never move once placed.
"use strict";

const GraphLayout = (() => {
  const GOLDEN = 2.39996, RING = 420, CUTOFF = 900;

  function sproutPoint(k, center = { x: 0, y: 0 }) {
    if (k <= 0) return { ...center };
    const angle = k * GOLDEN, radius = RING * Math.sqrt(k);
    return { x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle) };
  }

  function shortestPath(from, to, edges) {
    if (from === to) return [from];
    const next = new Map();
    for (const e of edges) {
      if (!next.has(e.source)) next.set(e.source, []);
      if (!next.has(e.target)) next.set(e.target, []);
      next.get(e.source).push(e.target); next.get(e.target).push(e.source);
    }
    const previous = new Map([[from, from]]);
    const queue = [from];
    for (let head = 0; head < queue.length; head++) {
      const at = queue[head];
      for (const n of next.get(at) || []) {
        if (previous.has(n)) continue;
        previous.set(n, at);
        if (n === to) {
          const path = [to];
          let step = to;
          while (step !== from) { step = previous.get(step); path.push(step); }
          return path.reverse();
        }
        queue.push(n);
      }
    }
    return null;
  }

  function jitter(id) {  // a small, stable offset per id (FNV-1a), so ideas sharing an anchor start apart
    let h = 0x811c9dc5;
    for (let i = 0; i < id.length; i++) { h ^= id.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return [((h & 0xffff) / 65535 - 0.5) * 40, (((h >>> 16) & 0xffff) / 65535 - 0.5) * 40];
  }

  function iterationsFor(n) { return n <= 100 ? 300 : Math.max(60, Math.floor(300 * 10000 / (n * n))); }

  function layout(ids, edges, anchors, fixed = {}, radius = {}) {
    ids = [...new Set(ids)];
    if (!ids.length) return {};
    const iterations = iterationsFor(ids.length);
    const index = new Map(ids.map((id, i) => [id, i]));
    const pos = ids.map(id => {
      if (fixed[id]) return { ...fixed[id] };
      const a = anchors[id] || { x: 0, y: 0 }, [dx, dy] = jitter(id);
      return { x: a.x + dx, y: a.y + dy };
    });
    const vel = ids.map(() => ({ x: 0, y: 0 }));
    const links = edges.map(e => [index.get(e.source), index.get(e.target)]).filter(([a, b]) => a != null && b != null && a !== b);
    const size = ids.map(id => radius[id] || 14);
    let alpha = 1;
    const cooling = Math.min(0.985, Math.pow(0.02, 1 / Math.max(iterations, 1)));
    for (let it = 0; it < iterations; it++) {
      const force = ids.map(() => ({ x: 0, y: 0 }));
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          let dx = pos[j].x - pos[i].x, dy = pos[j].y - pos[i].y, d2 = dx * dx + dy * dy;
          if (d2 > CUTOFF * CUTOFF) continue;
          if (d2 < 0.01) { dx = 0.1 * (j - i); dy = 0.1; d2 = dx * dx + dy * dy; }
          const d = Math.sqrt(d2);
          let push = 9000 / d2;
          const touching = size[i] + size[j] + 70;
          if (d < touching) push += (touching - d) * 0.5;
          force[i].x -= push * dx / d; force[i].y -= push * dy / d;
          force[j].x += push * dx / d; force[j].y += push * dy / d;
        }
      }
      for (const [a, b] of links) {
        const dx = pos[b].x - pos[a].x, dy = pos[b].y - pos[a].y, d = Math.max(Math.hypot(dx, dy), 0.01);
        const pull = (d - 140) * 0.05;
        force[a].x += pull * dx / d; force[a].y += pull * dy / d;
        force[b].x -= pull * dx / d; force[b].y -= pull * dy / d;
      }
      for (let i = 0; i < ids.length; i++) {
        if (fixed[ids[i]]) continue;
        const a = anchors[ids[i]] || { x: 0, y: 0 };
        force[i].x += (a.x - pos[i].x) * 0.03; force[i].y += (a.y - pos[i].y) * 0.03;
        vel[i].x = (vel[i].x + force[i].x * alpha) * 0.6; vel[i].y = (vel[i].y + force[i].y * alpha) * 0.6;
        pos[i].x += Math.max(-30, Math.min(30, vel[i].x)); pos[i].y += Math.max(-30, Math.min(30, vel[i].y));
      }
      alpha = Math.max(0.02, alpha * cooling);
    }
    return Object.fromEntries(ids.map((id, i) => [id, pos[i]]));
  }

  return { sproutPoint, shortestPath, layout };
})();

const PALETTE = ["var(--accent)", "var(--mint)", "var(--sky)", "var(--rose)", "var(--violet)", "var(--gold)"];
const paletteColor = i => PALETTE[((i % PALETTE.length) + PALETTE.length) % PALETTE.length];
const ARROW_TYPES = new Set(["builds_on", "depends_on", "exemplifies", "categorized_under"]);
const SVGNS = "http://www.w3.org/2000/svg";
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

class GraphExplorer {
  /** options: {colorBy: "layer"|"chapter", chapterOrder, chapterTitles, saved, fresh, onPlaced, onOpenChapter} */
  constructor(root, graph, options = {}) {
    this.root = root; this.graph = graph; this.o = Object.assign({ colorBy: "layer", chapterOrder: [], chapterTitles: {},
      saved: {}, fresh: [], onPlaced: null, onOpenChapter: null }, options);
    this.positions = {}; this.anchors = {}; this.sprouted = new Set();
    this.selected = null; this.detail = "learn"; this.query = ""; this.hiddenGroups = new Set(); this.hiddenKinds = new Set();
    this.tour = -1; this.memory = false; this.revealed = new Set(); this.path = null; this.pathNote = "";
    this.scale = 1; this.pan = { x: 0, y: 0 };
    this.byId = new Map(graph.nodes.map(n => [n.id, n]));
    this.groups = this.o.colorBy === "chapter" ? this.o.chapterOrder.map(String)
      : [...new Set(graph.nodes.map(n => n.layerName || n.layer || "Ideas"))];
    this.build();
    setTimeout(() => this.layOut(), 10);
  }

  groupKey(n) { return this.o.colorBy === "layer" ? (n.layerName || n.layer || "Ideas") : String(n.chapter || 0); }
  groupLabel(k) { return this.o.colorBy === "chapter" ? (this.o.chapterTitles[k] || `Chapter ${k}`) : k; }
  color(n) { return paletteColor(Math.max(0, this.groups.indexOf(this.groupKey(n)))); }
  radius(n) { return n.complexity === "complex" ? 20 : n.complexity === "moderate" ? 16 : 12; }
  visible() { return this.graph.nodes.filter(n => !this.hiddenGroups.has(this.groupKey(n)) && !this.hiddenKinds.has(n.type || "concept")); }

  lit() {
    if (this.path) return new Set(this.path);
    if (this.tour >= 0 && this.tour < this.graph.tour.length) return new Set(this.graph.tour[this.tour].nodeIds);
    if (this.selected && !this.memory) {
      const around = new Set([this.selected]);
      for (const e of this.graph.edges) if (e.source === this.selected || e.target === this.selected) { around.add(e.source); around.add(e.target); }
      return around;
    }
    const q = this.query.trim().toLowerCase();
    if (!q) return null;
    return new Set(this.graph.nodes.filter(n => `${n.name} ${n.summary || ""}`.toLowerCase().includes(q)).map(n => n.id));
  }

  build() {
    const r = this.root;
    r.innerHTML = "";
    const controls = el("div", { class: "row wrap" });
    const detail = el("div", { class: "segmented", role: "group", "aria-label": "Detail" });
    for (const [key, label] of [["overview", "Overview"], ["learn", "Learn"], ["deep", "Deep dive"]]) {
      const b = el("button", { type: "button", class: key === this.detail ? "on" : "" }, label);
      b.onclick = () => { this.detail = key; [...detail.children].forEach(c => c.classList.toggle("on", c === b)); this.drawPanel(); };
      detail.append(b);
    }
    const find = el("input", { type: "text", placeholder: "Find an idea", "aria-label": "Find an idea", style: "max-width:200px" });
    find.oninput = () => { this.query = find.value; this.draw(); };
    const show = el("select", { "aria-label": "Show" });
    show.append(el("option", { value: "" }, "Show everything"));
    for (const k of this.groups) show.append(el("option", { value: "g:" + k }, "Only " + this.groupLabel(k)));
    for (const [k, label] of [["concept", "Only concepts"], ["claim", "Only claims"], ["topic", "Only topics"]]) show.append(el("option", { value: "k:" + k }, label));
    show.onchange = () => {
      this.hiddenGroups = new Set(); this.hiddenKinds = new Set();
      const v = show.value;
      if (v.startsWith("g:")) this.groups.forEach(g => { if (g !== v.slice(2)) this.hiddenGroups.add(g); });
      if (v.startsWith("k:")) ["concept", "claim", "topic"].forEach(k => { if (k !== v.slice(2)) this.hiddenKinds.add(k); });
      this.draw();
    };
    controls.append(detail, find, show, el("span", { class: "spacer" }));
    if (this.graph.tour.length) {
      const tour = el("button", { class: "btn small", type: "button" }, "🚶 Guided tour");
      tour.onclick = () => { this.tour = 0; this.selected = null; this.path = null; this.memory = false; this.update(); };
      controls.append(tour);
    }
    const memory = el("button", { class: "btn small", type: "button", title: "Hide the names and rebuild the map from memory" }, "🧠 From memory");
    memory.onclick = () => {
      this.memory = !this.memory; this.selected = null; this.tour = -1; this.path = null; this.revealed = new Set();
      memory.textContent = this.memory ? "🧠 Show names" : "🧠 From memory"; this.update();
    };
    controls.append(memory);

    const wrap = el("div", { class: "graph-wrap" });
    this.canvas = el("div", { class: "graph" });
    this.svg = document.createElementNS(SVGNS, "svg");
    this.svg.setAttribute("role", "group");
    this.svg.setAttribute("aria-label", "Concept graph");
    this.edgesLayer = document.createElementNS(SVGNS, "g");
    this.nodesLayer = document.createElementNS(SVGNS, "g");
    this.svg.append(this.edgesLayer, this.nodesLayer);
    this.arranging = el("div", { class: "arranging" }, el("span", { class: "row" }, el("span", { class: "spinner" }), "Arranging the ideas…"));
    const zoom = el("div", { class: "zoom" });
    for (const [label, act] of [["+", () => this.zoomBy(1.25)], ["−", () => this.zoomBy(1 / 1.25)], ["⤢", () => this.fit()]]) {
      const b = el("button", { type: "button", "aria-label": label === "⤢" ? "Fit the whole map" : label === "+" ? "Zoom in" : "Zoom out" }, label);
      b.onclick = act; zoom.append(b);
    }
    this.canvas.append(this.svg, this.arranging, zoom);
    this.panel = el("div", { class: "side" });
    wrap.append(this.canvas, this.panel);
    r.append(controls, wrap);
    this.gestures();
    this.drawPanel();
  }

  gestures() {
    let start = null;
    this.svg.addEventListener("pointerdown", e => {
      if (e.target.closest(".node")) return;
      start = { x: e.clientX, y: e.clientY, pan: { ...this.pan }, moved: false };
      this.svg.setPointerCapture(e.pointerId); this.svg.classList.add("dragging");
    });
    this.svg.addEventListener("pointermove", e => {
      if (!start) return;
      const dx = e.clientX - start.x, dy = e.clientY - start.y;
      if (Math.hypot(dx, dy) > 4) start.moved = true;
      this.pan = { x: start.pan.x + dx, y: start.pan.y + dy }; this.draw();
    });
    this.svg.addEventListener("pointerup", () => {
      if (start && !start.moved) { this.selected = null; this.path = null; this.update(); }
      start = null; this.svg.classList.remove("dragging");
    });
    this.svg.addEventListener("wheel", e => { e.preventDefault(); this.zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1); }, { passive: false });
  }

  zoomBy(k) { this.scale = Math.min(3, Math.max(0.25, this.scale * k)); this.draw(); }

  layOut() {
    const order = this.o.chapterOrder;
    const anchors = {}, radius = {};
    for (const n of this.graph.nodes) {
      const k = this.o.colorBy === "chapter" ? Math.max(0, order.indexOf(n.chapter || 0)) : 0;
      anchors[n.id] = GraphLayout.sproutPoint(k);
      radius[n.id] = this.radius(n);
    }
    const fixed = {};
    for (const [id, p] of Object.entries(this.o.saved || {})) if (this.byId.has(id) && p.length === 2) fixed[id] = { x: p[0], y: p[1] };
    this.positions = GraphLayout.layout(this.graph.nodes.map(n => n.id), this.graph.edges, anchors, fixed, radius);
    this.anchors = anchors;
    const fresh = new Set(this.o.fresh || []);
    this.sprouted = new Set(this.graph.nodes.map(n => n.chapter).filter(c => c != null && !fresh.has(c)));
    const placed = {};
    for (const [id, p] of Object.entries(this.positions)) if (!fixed[id]) placed[id] = [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10];
    if (Object.keys(placed).length && this.o.onPlaced) this.o.onPlaced(placed);
    this.arranging.remove();
    this.fit();
    if (fresh.size) this.grow(order.filter(n => fresh.has(n)));
  }

  grow(chapters) {
    if (reduceMotion()) { chapters.forEach(n => this.sprouted.add(n)); this.draw(); return; }
    chapters.forEach((n, i) => setTimeout(() => { this.sprouted.add(n); this.draw(); }, 350 + i * 700));
  }

  replay() { this.sprouted = new Set(); this.draw(); this.grow(this.o.chapterOrder); }

  fit() {
    const pts = Object.values(this.positions);
    if (!pts.length) return;
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(maxX - minX + 160, 300), h = Math.max(maxY - minY + 120, 300);
    this.scale = Math.min(1.3, Math.max(0.25, Math.min((rect.width || 640) / w, (rect.height || 520) / h)));
    this.pan = { x: -((minX + maxX) / 2) * this.scale, y: -((minY + maxY) / 2) * this.scale };
    this.draw();
  }

  screen(id) {
    let p = this.positions[id];
    if (!p) return null;
    const n = this.byId.get(id);
    if (n && n.chapter != null && !this.sprouted.has(n.chapter) && this.anchors[id]) p = this.anchors[id];
    const rect = this.canvas.getBoundingClientRect();
    return { x: (rect.width || 640) / 2 + this.pan.x + p.x * this.scale, y: (rect.height || 520) / 2 + this.pan.y + p.y * this.scale };
  }

  update() { this.draw(); this.drawPanel(); }

  draw() {
    if (!Object.keys(this.positions).length) return;
    const shown = new Set(this.visible().map(n => n.id));
    const lit = this.lit();
    this.edgesLayer.innerHTML = ""; this.nodesLayer.innerHTML = "";
    for (const e of this.graph.edges) {
      if (!shown.has(e.source) || !shown.has(e.target)) continue;
      const a = this.screen(e.source), b = this.screen(e.target);
      if (!a || !b) continue;
      const on = !lit || (lit.has(e.source) && lit.has(e.target));
      const type = e.type || "related";
      const line = svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: type === "contradicts" ? "var(--rose)" : "var(--ink3)",
        "stroke-opacity": on ? 0.7 : 0.15, "stroke-width": on ? 1.6 : 1, "stroke-linecap": "round",
        "stroke-dasharray": type === "similar_to" ? "6 5" : type === "contradicts" ? "2 4" : "" });
      this.edgesLayer.append(line);
      if (ARROW_TYPES.has(type)) {
        const angle = Math.atan2(b.y - a.y, b.x - a.x);
        const tip = { x: b.x - Math.cos(angle) * 16, y: b.y - Math.sin(angle) * 16 };
        const d = `M${tip.x - Math.cos(angle - 0.45) * 8},${tip.y - Math.sin(angle - 0.45) * 8} L${tip.x},${tip.y} L${tip.x - Math.cos(angle + 0.45) * 8},${tip.y - Math.sin(angle + 0.45) * 8}`;
        this.edgesLayer.append(svgEl("path", { d, fill: "none", stroke: "var(--ink3)", "stroke-opacity": on ? 0.8 : 0.15, "stroke-width": 1.6 }));
      }
    }
    for (const n of this.visible()) {
      const at = this.screen(n.id);
      if (!at) continue;
      const growing = n.chapter != null && !this.sprouted.has(n.chapter);
      const r = this.radius(n) * Math.min(Math.max(this.scale, 0.7), 1.3);
      const g = svgEl("g", { class: "node", transform: `translate(${at.x},${at.y}) scale(${growing ? 0.1 : 1})`, tabindex: 0, role: "button",
        opacity: growing ? 0 : (lit && !lit.has(n.id) ? 0.25 : 1),
        "aria-label": this.memory && !this.revealed.has(n.id) ? "Hidden idea" : n.name });
      g.style.transition = reduceMotion() ? "" : "transform .9s cubic-bezier(.3,1.5,.5,1), opacity .5s";
      const color = this.color(n);
      if (n.type === "claim") g.append(svgEl("rect", { x: -r * .7, y: -r * .7, width: r * 1.4, height: r * 1.4, fill: color, transform: "rotate(45)" }));
      else if (n.type === "topic") g.append(svgEl("rect", { x: -r, y: -r, width: r * 2, height: r * 2, rx: 6, fill: color }));
      else g.append(svgEl("circle", { r, fill: color }));
      if (this.selected === n.id) g.append(svgEl("circle", { r: r + 5, fill: "none", stroke: "var(--ink)", "stroke-width": 2.5 }));
      const label = this.memory && !this.revealed.has(n.id) ? "?" : (n.name.length > 24 ? n.name.slice(0, 22) + "…" : n.name);
      const t = svgEl("text", { y: r + 13, "text-anchor": "middle" }); t.textContent = label; g.append(t);
      const choose = () => this.tap(n);
      g.addEventListener("click", choose);
      g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } });
      this.nodesLayer.append(g);
    }
  }

  tap(n) {
    if (this.memory) { this.selected = n.id; this.update(); return; }
    this.selected = this.selected === n.id ? null : n.id; this.path = null; this.tour = -1; this.update();
  }

  drawPanel() {
    const p = this.panel; p.innerHTML = "";
    const node = this.selected && this.byId.get(this.selected);
    if (this.tour >= 0 && this.tour < this.graph.tour.length) {
      const step = this.graph.tour[this.tour], last = this.tour === this.graph.tour.length - 1;
      p.append(el("div", { class: "caps", style: "color:var(--accent)" }, `Tour ${this.tour + 1} of ${this.graph.tour.length}`),
        el("h4", {}, step.title), step.description ? el("p", { class: "small" }, step.description) : "");
      const row = el("div", { class: "row" });
      const back = btn("Back", () => { this.tour--; this.update(); }, "small"); back.disabled = this.tour === 0;
      row.append(back, btn(last ? "Finish" : "Next", () => { this.tour = last ? -1 : this.tour + 1; this.update(); }, "small primary"),
        btn("Exit", () => { this.tour = -1; this.update(); }, "small"));
      p.append(row, pip(last ? "proud" : "read", 80));
    } else if (this.memory) {
      const left = this.graph.nodes.length - this.revealed.size;
      p.append(el("h4", {}, "Rebuild from memory"),
        el("p", { class: "small muted" }, "The names are hidden. Tap an idea, say what it is, then reveal it."));
      if (node) {
        if (this.revealed.has(node.id)) p.append(el("h4", {}, node.name), node.summary ? el("p", { class: "small" }, node.summary) : "");
        else p.append(btn("Reveal", () => {
          this.revealed.add(node.id);
          if (this.revealed.size === this.graph.nodes.length) { this.memory = false; this.selected = null; }
          this.update();
        }, "primary"));
      }
      p.append(el("p", { class: "tiny faint" }, left === 0 ? "Map rebuilt from memory!" : `${left} left`));
    } else if (node) {
      const links = this.graph.edges.filter(e => e.source === node.id || e.target === node.id);
      p.append(el("div", { class: "caps", style: `color:${this.color(node)}` }, this.groupLabel(this.groupKey(node))), el("h4", {}, node.name));
      if (node.summary) p.append(el("p", { class: "small" }, node.summary));
      if (this.detail !== "overview" && node.detail) p.append(el("p", { class: "small muted" }, node.detail));
      if (links.length) {
        p.append(el("b", { class: "small" }, "Connections"));
        const list = el("div", { class: "col", style: "gap:6px;max-height:180px;overflow-y:auto" });
        for (const link of links) {
          const out = link.source === node.id, other = this.byId.get(out ? link.target : link.source);
          if (!other) continue;
          let note = (link.type || "related").replaceAll("_", " ");
          if (this.detail === "deep" && link.description) note += ": " + link.description;
          if (other.chapter != null && other.chapter !== node.chapter) note += ` · chapter ${other.chapter}`;
          const b = el("button", { class: "link-row", type: "button" }, el("div", {}, `${out ? "→" : "←"} ${other.name}`), el("div", { class: "tiny faint" }, note));
          b.onclick = () => { this.selected = other.id; this.update(); };
          list.append(b);
        }
        p.append(list);
      }
      const row = el("div", { class: "row" });
      if (node.chapter != null && this.o.onOpenChapter) row.append(btn(`Open chapter ${node.chapter}`, () => this.o.onOpenChapter(node.chapter), "small"));
      row.append(btn("Clear", () => { this.selected = null; this.update(); }, "small"));
      p.append(row);
    } else {
      p.append(el("h4", {}, "Tap an idea to learn about it"),
        el("p", { class: "small muted" }, "Arrows show what builds on what. Dashed lines join the same idea across chapters; pink dotted lines are disagreements."));
      this.groups.slice(0, 8).forEach((k, i) => p.append(el("div", { class: "row small" },
        el("i", { style: `width:9px;height:9px;border-radius:50%;background:${paletteColor(i)};display:inline-block` }), this.groupLabel(k))));
    }
    p.append(el("hr", { style: "border:0;border-top:1px solid var(--line);width:100%;margin:2px 0" }));
    const details = el("details", {});
    details.append(el("summary", { class: "small" }, "How are two ideas connected?"));
    const sorted = [...this.graph.nodes].sort((a, b) => a.name.localeCompare(b.name));
    const pick = label => {
      const s = el("select", { "aria-label": label, style: "width:100%" });
      s.append(el("option", { value: "" }, "Pick an idea"));
      sorted.forEach(n => s.append(el("option", { value: n.id }, n.name)));
      return s;
    };
    const from = pick("From"), to = pick("To"), note = el("p", { class: "tiny muted" }, this.pathNote);
    const go = btn("Show path", () => {
      if (!from.value || !to.value) return;
      const found = GraphLayout.shortestPath(from.value, to.value, this.graph.edges);
      if (found) { this.path = found; this.selected = null; this.tour = -1; this.pathNote = found.map(id => this.byId.get(id)?.name).join(" → "); }
      else { this.path = null; this.pathNote = "These two ideas aren't connected yet."; }
      this.update();
    }, "small");
    details.append(el("div", { class: "col", style: "gap:6px;margin-top:6px" }, from, to, go, note));
    if (this.pathNote) details.open = true;
    p.append(details);
  }
}

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== "" && v != null && v !== false) node.setAttribute(k, v === true ? "" : v);
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== "") node.append(kid instanceof Node ? kid : String(kid));
  return node;
}
function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== "" && v != null) node.setAttribute(k, v);
  return node;
}
function btn(label, onclick, kind = "") {
  const b = el("button", { class: "btn " + kind, type: "button" }, label);
  b.onclick = onclick;
  return b;
}
function pip(pose, size) {
  const holder = el("div", { class: "pip", style: `width:${size}px`, "aria-hidden": "true" });
  holder.innerHTML = (window.PIP && (window.PIP[pose] || window.PIP.read)) || "";
  return holder;
}
