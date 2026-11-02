"use strict";
// Silly mode's big Pip: zooms in, plays the sound, and shrinks away when it ends. Clicking it opens the library.
if (window.PIP_CSS) { const s = document.createElement("style"); s.textContent = window.PIP_CSS; document.head.append(s); }
let hideTimer = null, audio = null;
function hide() {
  const big = document.getElementById("big");
  big.classList.remove("in");
  if (audio) { audio.pause(); audio = null; }
  setTimeout(() => window.pywebview && window.pywebview.api.hide_big_pip(), 350);
}
window.BigPip = {
  show(nudge) {
    const big = document.getElementById("big");
    const pose = nudge.mood === "shocked" ? "shocked" : "sad";
    const emoji = [...nudge.title][0];
    const words = nudge.title.slice(emoji.length).trim();
    big.innerHTML = "";
    const e = document.createElement("div"); e.className = "emoji"; e.textContent = emoji;
    const p = document.createElement("div"); p.className = "pip"; p.style.width = "220px"; p.innerHTML = (window.PIP || {})[pose] || "";
    const b = document.createElement("div"); b.className = "bubble"; b.textContent = words;
    const small = document.createElement("small"); small.textContent = nudge.body; b.append(small);
    big.append(e, p, b);
    requestAnimationFrame(() => big.classList.add("in"));
    clearTimeout(hideTimer);
    audio = new Audio(nudge.sound);
    audio.volume = Math.max(0, Math.min(1, nudge.volume ?? 0.8));
    audio.onended = () => { hideTimer = setTimeout(hide, 600); };
    audio.play().catch(() => { hideTimer = setTimeout(hide, 6000); });
    hideTimer = setTimeout(hide, 20000);  // a sound that never ends never keeps Pip up
  },
};
document.getElementById("big").onclick = () => { hide(); window.pywebview && window.pywebview.api.show_main(null); };
