// Studio: the Project page's coverage-map illustration (project.html).
import { footSvg } from "/assets/layout.js";
// Illustrative only: a fixed decorative pattern, not data from any capture.
const svg = document.getElementById("hero-map");
const cx = 100, cy = 100, rings = [[46, 70], [70, 94]];
const pattern = [
  [1, 1, 1, 0.5, 0, 0, 0.5, 1, 1, 1, 1, 1],
  [1, 1, 0.5, 0, 0, 0, 0, 0.5, 1, 1, 1, 1],
];
const pt = (r, deg) => [cx + r * Math.sin(deg * Math.PI / 180), cy + r * Math.cos(deg * Math.PI / 180)];
let out = "";
rings.forEach(([r1, r2], b) => {
  for (let i = 0; i < 12; i++) {
    const a1 = i * 30, a2 = a1 + 30;
    const [x1, y1] = pt(r2, a1), [x2, y2] = pt(r2, a2), [x3, y3] = pt(r1, a2), [x4, y4] = pt(r1, a1);
    const f = pattern[b][i];
    const fill = f ? `color-mix(in srgb, var(--brand) ${20 + 70 * f}%, var(--surface-2))` : "var(--surface-2)";
    out += `<path class="cov-cell" fill="${fill}" d="M${x1} ${y1}A${r2} ${r2} 0 0 0 ${x2} ${y2}L${x3} ${y3}A${r1} ${r1} 0 0 1 ${x4} ${y4}Z"/>`;
  }
});
out += `<circle cx="100" cy="100" r="45" fill="color-mix(in srgb, var(--accent) 55%, var(--surface))"/>`;
out += `<g transform="translate(70 70) scale(0.3)">${footSvg({ cls: "hero-foot" })}</g>`;
svg.innerHTML = out;
