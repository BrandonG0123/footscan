// The mat check, as a live picture: a ruler with the printed black bar on it.
//
// As the person types the number their ruler showed, the bar grows to that
// length. If it lands on the right mark (10 cm or 4 in) it turns green with a
// tick; if not, the gap to the right mark shows in red, with how far off the
// print is. It turns "measure the bar with a ruler" into something you can
// see, which matters most for the people who find the instruction hardest.
import { animate } from "./motion.js";
import { enabled, POP, shake } from "./fx.js";
import { readCheckBar } from "./mat-check.js";
import { rulerModel } from "./scene-math.js";

const X0 = 14, X1 = 290; // the ruler's 0 mark and its last mark, in SVG units (the unit sits past it)

export function mountRuler(host, input, getBars) {
  host.innerHTML = `<svg viewBox="0 0 320 92" class="ruler" aria-hidden="true">
      <rect class="ruler-body" x="2" y="38" width="316" height="44" rx="6"/>
      <g class="ticks"></g>
      <rect class="printed" x="${X0}" y="16" width="${X1 - X0}" height="12" rx="2" style="transform:scaleX(0)"/>
      <rect class="gap" x="${X0}" y="16" width="0" height="12" rx="2"/>
      <g class="target"><line y1="8" y2="36"/><text y="7" text-anchor="middle"></text></g>
      <g class="ok-at"><g class="ok-tick" opacity="0"><circle r="10"/><path d="M-4.5 0.5l3 3 6-6.5" pathLength="1"/></g></g>
    </svg>
    <p class="ruler-note" aria-live="polite"></p>`;
  const svg = host.querySelector("svg");
  const q = (s) => svg.querySelector(s);
  const note = host.querySelector(".ruler-note");
  let unit = null;

  const scaleX = (v, max) => X0 + ((X1 - X0) * v) / max;

  function drawTicks(m) {
    if (unit === m.unit) return;
    unit = m.unit;
    const g = q(".ticks");
    const per = m.unit === "cm" ? 10 : 8; // millimetres, or eighths of an inch
    let out = "";
    for (let i = 0; i <= m.max * per; i++) {
      const x = scaleX(i / per, m.max).toFixed(2);
      const major = i % per === 0, half = i % (per / 2) === 0;
      const h = major ? 16 : half ? 11 : 7;
      out += `<line x1="${x}" x2="${x}" y1="38" y2="${38 + h}" class="${major ? "major" : ""}"/>`;
      if (major) out += `<text x="${x}" y="76" text-anchor="middle">${i / per}</text>`;
    }
    out += `<text x="312" y="76" text-anchor="end" class="unit">${m.unit === "cm" ? "cm" : "in"}</text>`;
    g.innerHTML = out;
  }

  let last = "";
  function update() {
    const bars = getBars();
    if (!bars) return;
    const value = input.value;
    const check = value === "" ? null : readCheckBar(value, bars);
    const m = rulerModel(value, check, bars);
    drawTicks(m);
    const end = scaleX(m.shown, m.max);
    const tx = scaleX(m.target, m.max);
    const printed = q(".printed"), gap = q(".gap"), target = q(".target"), tick = q(".ok-tick");
    target.setAttribute("transform", `translate(${tx.toFixed(1)} 0)`);
    q(".target text").textContent = `${m.target} ${m.unit === "cm" ? "cm" : "in"}`;
    svg.dataset.status = m.status;

    // The bar is drawn full length and scaled from its left end (transforms
    // animate smoothly everywhere; SVG widths don't in every browser).
    const frac = Math.max(0, end - X0) / (X1 - X0);
    if (enabled()) animate(printed, { scaleX: frac }, POP);
    else printed.style.transform = `scaleX(${frac})`;
    const showGap = m.status === "wrong";
    gap.setAttribute("x", Math.min(end, tx).toFixed(1));
    gap.setAttribute("width", Math.abs(tx - end).toFixed(1));
    if (enabled()) animate(gap, { opacity: showGap ? 1 : 0 }, { duration: 0.25 });
    else gap.style.opacity = showGap ? "1" : "0";

    q(".ok-at").setAttribute("transform", `translate(${tx.toFixed(1)} 22)`);
    if (m.status === "ok" && last !== "ok" && enabled()) {
      animate(tick, { opacity: [0, 1], scale: [0.3, 1] }, POP);
      animate(tick.querySelector("path"), { pathLength: [0, 1] }, { duration: 0.3, delay: 0.1 });
    } else if (m.status !== "ok") {
      tick.setAttribute("opacity", "0");
      tick.style.opacity = "0";
    } else if (!enabled()) {
      tick.style.opacity = "1";
    }
    if (m.status === "wrong" && last !== "wrong") shake(host.querySelector("svg"));
    last = m.status;

    note.className = `ruler-note ${m.status}`;
    note.textContent = {
      empty: "Type the number and the ruler shows you.",
      ok: "Perfect: your mat printed at exactly the right size.",
      unclear: "That doesn't look like either bar. Start the ruler's 0 at the very start of a black bar.",
      wrong: `Your mat printed ${Math.abs(m.pctOff)}% too ${m.pctOff < 0 ? "small" : "big"}. Print it again at 100% ("Actual size").`,
    }[m.status];
  }

  input.addEventListener("input", update);
  return { update };
}
