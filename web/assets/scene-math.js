// Geometry for the animated illustrations, kept separate so it can be tested
// in Node without a browser.

/**
 * A point on an ellipse at parameter t (0..1 = one full turn, starting at
 * the bottom and going clockwise on screen), and the direction from that
 * point to the centre in degrees (0 = pointing up), for turning a phone so
 * its camera faces the middle.
 */
export function orbitPoint(cx, cy, rx, ry, t) {
  const a = Math.PI / 2 + t * 2 * Math.PI; // screen y points down: pi/2 is the bottom
  const x = cx + rx * Math.cos(a);
  const y = cy + ry * Math.sin(a);
  const facing = (Math.atan2(cx - x, -(cy - y)) * 180) / Math.PI;
  return { x, y, facing };
}

/** Which of n equal segments around the orbit t falls in. */
export function segmentAt(t, n) {
  const f = ((t % 1) + 1) % 1;
  return Math.min(n - 1, Math.floor(f * n));
}

/** SVG path for segment i of n around an ellipse, as an arc (with a small gap either side). */
export function arcSegment(cx, cy, rx, ry, i, n, gap = 0.012) {
  const p0 = orbitPoint(cx, cy, rx, ry, i / n + gap);
  const p1 = orbitPoint(cx, cy, rx, ry, (i + 1) / n - gap);
  const f = (v) => v.toFixed(2);
  return `M${f(p0.x)} ${f(p0.y)} A${rx} ${ry} 0 0 1 ${f(p1.x)} ${f(p1.y)}`;
}

/**
 * The ruler check, as a picture: what the person's number means.
 *
 * check: the result of readCheckBar (mat-check.js). Returns the ruler's
 * unit and length, where the printed bar should end, where it actually
 * ended, and how far off the print is, for drawing and for the words under it.
 */
export function rulerModel(value, check, bars) {
  const v = Number(value);
  const has = value !== "" && value != null && Number.isFinite(v) && v > 0;
  // Which ruler to draw: the bar the reading was matched to, else the
  // nearest by size, else centimetres.
  const bar = check?.bar ?? (has
    ? bars.reduce((b, x) => (Math.abs(v - x.value) / x.value < Math.abs(v - b.value) / b.value ? x : b))
    : bars.find((b) => b.unit === "cm") ?? bars[0]);
  const max = bar.unit === "cm" ? 12 : 5;
  const shown = has ? Math.min(Math.max(v, 0), max) : 0;
  const pctOff = has ? Math.round(((v - bar.value) / bar.value) * 1000) / 10 : null;
  const status = !has ? "empty" : check?.ok ? "ok" : check?.reason === "unclear" ? "unclear" : "wrong";
  return { unit: bar.unit, max, target: bar.value, shown, pctOff, status };
}
