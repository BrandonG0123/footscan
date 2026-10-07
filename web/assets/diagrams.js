// Simple diagrams for the scanning instructions. Plain SVG, theme colours, no
// text smaller than the body copy: a picture explains "walk around the foot,
// low then high" far faster than a paragraph does.
import { footSvg } from "./layout.js";

const SQ = (x, y, s = 9) =>
  `<rect x="${x}" y="${y}" width="${s}" height="${s}" rx="1" fill="var(--ink)"/>`;

/** Two taped sheets seen from above, with a foot in the middle. */
export function matDiagram() {
  const edge = (y0, y1) => {
    let out = "";
    for (let y = y0 + 6; y < y1 - 10; y += 16) out += SQ(8, y) + SQ(103, y);
    return out;
  };
  // Grouped by sheet so the drawing can tape itself together (interact.js).
  return `<svg viewBox="0 0 120 204" role="img" aria-label="Two printed sheets taped end to end, with a foot standing in the middle">
    <g class="mat-sheet sheet-1">
      <rect x="4" y="96" width="112" height="90" rx="2" fill="var(--surface)" stroke="var(--line)"/>
      ${edge(96, 186)}${SQ(30, 172)}${SQ(52, 172)}${SQ(74, 172)}
      <text x="60" y="166" text-anchor="middle" font-size="6.5" fill="var(--muted)">sheet 1 · heel</text>
    </g>
    <g class="mat-sheet sheet-2">
      <rect x="4" y="4" width="112" height="90" rx="2" fill="var(--surface)" stroke="var(--line)"/>
      ${edge(4, 94)}${SQ(30, 8)}${SQ(52, 8)}${SQ(74, 8)}
      <text x="60" y="32" text-anchor="middle" font-size="6.5" fill="var(--muted)">sheet 2 · toes</text>
    </g>
    <g class="mat-foot-at"><g transform="translate(11.5 48) scale(0.48)">${footSvg({ cls: "mat-foot" })}</g></g>
    <line class="mat-seam" x1="4" y1="95" x2="116" y2="95" stroke="var(--brand)" stroke-width="1.5" stroke-dasharray="4 3"/>
    <g class="mat-legend">
      <line x1="30" y1="196" x2="48" y2="196" stroke="var(--brand)" stroke-width="1.5" stroke-dasharray="4 3"/>
      <text x="53" y="198" font-size="6.5" fill="var(--brand)">tape the sheets here</text>
    </g>
  </svg>`;
}

/** How to move the phone: around the foot, and at three heights. */
export function phonePathDiagram() {
  const phone = (x, y, r) =>
    `<g transform="translate(${x} ${y}) rotate(${r})"><rect x="-5" y="-8" width="10" height="16" rx="2"
      fill="var(--surface)" stroke="var(--ink)" stroke-width="1.2"/><circle cx="0" cy="-3" r="2" fill="var(--ink)"/></g>`;
  return `<svg viewBox="0 0 300 132" role="img" aria-label="Walk the phone all the way around the foot: first low down, then higher, then from above">
    <g>
      <text x="72" y="14" text-anchor="middle" font-size="10" fill="var(--muted)">Go all the way around</text>
      <ellipse cx="72" cy="76" rx="56" ry="34" fill="none" stroke="var(--brand)" stroke-width="2" stroke-dasharray="5 4"/>
      <g transform="translate(57 52) scale(0.15)">${footSvg({ cls: "mat-foot" })}</g>
      ${phone(16, 76, -90)}${phone(128, 76, 90)}${phone(72, 42, 0)}
      <path d="M104 104 q14 -6 18 -18" fill="none" stroke="var(--brand)" stroke-width="2" marker-end="url(#ar)"/>
    </g>
    <g transform="translate(160 0)">
      <text x="70" y="14" text-anchor="middle" font-size="10" fill="var(--muted)">Low, then higher, then above</text>
      <line x1="6" y1="110" x2="112" y2="110" stroke="var(--line)" stroke-width="2"/>
      <g transform="translate(48 98) scale(0.1)">${footSvg({ cls: "mat-foot" })}</g>
      ${phone(16, 100, 60)}${phone(20, 66, 35)}${phone(56, 38, 0)}
      <text x="116" y="104" font-size="9" fill="var(--muted)">low</text>
      <text x="116" y="70" font-size="9" fill="var(--muted)">mid</text>
      <text x="72" y="36" font-size="9" fill="var(--muted)">above</text>
    </g>
    <defs><marker id="ar" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
      <path d="M0 0 L6 3 L0 6 z" fill="var(--brand)"/></marker></defs>
  </svg>`;
}

export const DIAGRAM_CSS = `
  .diagram { background: var(--surface-2); border-radius: var(--radius); padding: 14px; }
  .diagram svg { width: 100%; height: auto; display: block; }
  .mat-foot { fill: var(--brand-soft); stroke: var(--brand); stroke-width: 3; }
`;
