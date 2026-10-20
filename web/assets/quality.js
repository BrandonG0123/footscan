// Frame quality and coverage logic for the capture page.
// Pure functions, no DOM, so they run under `node --test` too.
//
// Every threshold here is a starting guess. They get tuned against what
// actually reconstructs well in Phase 2, not against how the UI feels.

/** RGBA pixel array -> luma (Rec. 601 weights), one value per pixel. */
export function toGray(rgba, w, h) {
  const g = new Float32Array(w * h);
  for (let i = 0, p = 0; i < g.length; i++, p += 4) {
    g[i] = 0.299 * rgba[p] + 0.587 * rgba[p + 1] + 0.114 * rgba[p + 2];
  }
  return g;
}

/**
 * Sharpness = variance of the Laplacian.
 *
 * The Laplacian (4*centre - up - down - left - right) is a second derivative:
 * it is large at edges and fine texture and near zero on smooth gradients.
 * Blur removes fine texture, so the Laplacian response flattens and its
 * variance drops. The absolute value depends on the scene (a speckle sock
 * scores far higher than bare skin), which is why SharpnessJudge compares
 * each frame against recent frames rather than a fixed number.
 */
export function laplacianVariance(gray, w, h) {
  let sum = 0, sumSq = 0, n = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const l = 4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - w] - gray[i + w];
      sum += l; sumSq += l * l; n++;
    }
  }
  if (!n) return 0;
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

export function exposureStats(gray) {
  let sum = 0, hi = 0, lo = 0;
  for (const v of gray) {
    sum += v;
    if (v >= 250) hi++;
    if (v <= 8) lo++;
  }
  const n = gray.length || 1;
  return { mean: sum / n, clippedHigh: hi / n, clippedLow: lo / n };
}

export function judgeExposure({ mean, clippedHigh, clippedLow }) {
  if (clippedHigh > 0.05) return { ok: false, issue: "overexposed", message: "Too bright. Move out of direct sunlight or away from the lamp." };
  if (mean > 215) return { ok: false, issue: "overexposed", message: "Too bright. Move somewhere with softer light." };
  if (clippedLow > 0.25 || mean < 50) return { ok: false, issue: "underexposed", message: "Too dark. Turn on more lights." };
  return { ok: true, issue: null, message: "Exposure OK" };
}

export class SharpnessJudge {
  constructor({ window = 40, ratio = 0.55, absoluteMin = 15 } = {}) {
    Object.assign(this, { window, ratio, absoluteMin });
    this.recent = [];
  }

  /** Score relative to the 90th percentile of recent frames. */
  judge(score) {
    this.recent.push(score);
    if (this.recent.length > this.window) this.recent.shift();
    const sorted = [...this.recent].sort((a, b) => a - b);
    const p90 = sorted[Math.floor(0.9 * (sorted.length - 1))];
    const relative = p90 > 0 ? score / p90 : 0;
    const warmingUp = this.recent.length < 8;
    const ok = score >= this.absoluteMin && (warmingUp || relative >= this.ratio);
    return {
      ok, relative, warmingUp,
      message: ok ? "Sharp" : score < this.absoluteMin
        ? "The camera can't see any detail. Point it at the object and wait for it to focus."
        : "Blurry. Move slower and hold steady.",
    };
  }
}

// ---- coverage ------------------------------------------------------------
//
// Viewing positions around the foot, seen from above: 12 azimuth sectors x
// 2 side bands (low, mid) + 1 overhead cell. Azimuth 0 is where the capture
// started (the protocol says start behind the heel) and increases
// counter-clockwise seen from above.
//
// Until the marker board is detected in each frame, position comes from the
// phone's motion sensors, which drift. Treat the map as guidance, not a
// measurement.

export const AZ_SECTORS = 12;
export const BANDS = [
  { key: "low", label: "low", min: 0, max: 25 },
  { key: "mid", label: "mid", min: 25, max: 60 },
  { key: "top", label: "overhead", min: 60, max: 91 },
];

export function wrap360(deg) {
  return ((deg % 360) + 360) % 360;
}

/**
 * DeviceOrientation -> approximate camera position around the foot.
 * beta is front/back tilt: 90 = phone upright (rear camera looks level),
 * 0 = phone flat (rear camera looks straight down). So camera elevation
 * above the floor is about 90 - |beta|.
 */
export function viewFromOrientation({ alpha, beta }, alpha0) {
  return {
    azimuth: wrap360(alpha - alpha0),
    elevation: Math.max(0, Math.min(90, 90 - Math.abs(beta))),
  };
}

export function cellFor({ azimuth, elevation }) {
  const band = BANDS.findIndex((b) => elevation >= b.min && elevation < b.max);
  if (BANDS[band].key === "top") return "top";
  return `${BANDS[band].key}-${Math.floor(wrap360(azimuth) / (360 / AZ_SECTORS)) % AZ_SECTORS}`;
}

/**
 * May the scan finish? Only once every angle has its photos, never on a
 * photo count alone: twenty photos can all come from one side. Without
 * motion sensors the angles can't be known, so the full frame target stands
 * in for them.
 */
export function coveredEnough({ hasView, completeness, kept, targetFrames }) {
  if (kept === 0) return false;
  return hasView ? completeness >= 1 : kept >= targetFrames;
}

export class Coverage {
  constructor({ perSideCell = 2, topCell = 4 } = {}) {
    this.perSideCell = perSideCell;
    this.topCell = topCell;
    this.counts = new Map();
    for (const b of ["low", "mid"]) for (let i = 0; i < AZ_SECTORS; i++) this.counts.set(`${b}-${i}`, 0);
    this.counts.set("top", 0);
  }

  target(cell) {
    return cell === "top" ? this.topCell : this.perSideCell;
  }

  add(cell) {
    this.counts.set(cell, (this.counts.get(cell) || 0) + 1);
  }

  remove(cell) {
    this.counts.set(cell, Math.max(0, (this.counts.get(cell) || 0) - 1));
  }

  fill(cell) {
    return Math.min(1, this.counts.get(cell) / this.target(cell));
  }

  /** Fraction of the total required frames that are present. */
  completeness() {
    let have = 0, need = 0;
    for (const cell of this.counts.keys()) {
      const t = this.target(cell);
      have += Math.min(t, this.counts.get(cell));
      need += t;
    }
    return have / need;
  }

  missing() {
    return [...this.counts.keys()].filter((c) => this.counts.get(c) < this.target(c));
  }
}

/**
 * Where to stand, in words a child can follow. Azimuth 0 is where scanning
 * started and grows counter-clockwise seen from above, which passes a foot's
 * outer side first, so the names match the labels on the coverage map.
 *
 * `foot` is "left"/"right" for a foot, or null when it's any other object:
 * "behind the heel" is meaningless when you're scanning a hand or a shoe.
 */
export function describeCell(cell, foot = "right") {
  const object = foot !== "left" && foot !== "right";
  if (cell === "top") return object ? "right above it, looking down" : "right above the foot, looking down";
  const [band, idx] = cell.split("-");
  const az = (Number(idx) + 0.5) * (360 / AZ_SECTORS);
  const height = band === "low" ? "down low" : "a bit higher up";
  if (object) {
    const where = az < 30 || az >= 330 ? "back where you started"
      : az < 150 ? "a quarter of the way around from the start"
        : az < 210 ? "the far side, opposite where you started"
          : "three quarters of the way around";
    return `${where}, ${height}`;
  }
  const [first, second] = foot === "right" ? ["outer", "inner"] : ["inner", "outer"];
  const where = az < 30 || az >= 330 ? "behind the heel"
    : az < 150 ? `by the ${first} side of the foot`
      : az < 210 ? "in front of the toes"
        : `by the ${second} side of the foot`;
  return `${where}, ${height}`;
}

/** Where a cell sits: the middle of its wedge and of its height band. */
export function targetView(cell) {
  if (cell === "top") return { azimuth: null, elevation: 78 };
  const [band, idx] = cell.split("-");
  return {
    azimuth: (Number(idx) + 0.5) * (360 / AZ_SECTORS),
    elevation: band === "low" ? 12 : 42,
  };
}

/**
 * Which way to move the phone to reach a cell: an arrow, not a sentence.
 *
 * Geometry: the camera points inward at the subject, so stepping around it in
 * the direction of increasing azimuth moves the camera to its own right.
 * (Camera position P = (sin a, -cos a); dP/da = (cos a, sin a), which is the
 * camera's right vector.) So a positive azimuth difference means "go right",
 * and a positive elevation difference means "lift it higher".
 *
 * Returns the screen rotation for an up-pointing arrow, plus plain words.
 */
export function steerTo(view, cell, { azTolerance = 14, elTolerance = 9 } = {}) {
  if (!view || !cell) return { arrived: false, angle: null, turn: "none", tilt: "none", text: "" };
  const target = targetView(cell);
  const dAz = target.azimuth == null ? 0 : ((target.azimuth - view.azimuth + 540) % 360) - 180;
  const dEl = target.elevation - view.elevation;
  const turn = Math.abs(dAz) < azTolerance ? "none" : dAz > 0 ? "right" : "left";
  const tilt = Math.abs(dEl) < elTolerance ? "none" : dEl > 0 ? "up" : "down";
  if (turn === "none" && tilt === "none") {
    return { arrived: true, angle: null, turn, tilt, dAz, dEl, text: "Hold it there" };
  }
  // Arrow: 0 degrees points up the screen, 90 points right.
  const vx = Math.max(-1, Math.min(1, dAz / 45));
  const vy = Math.max(-1, Math.min(1, dEl / 25));
  const angle = (Math.atan2(vx, vy) * 180) / Math.PI;
  const words = [];
  if (turn !== "none") words.push(`go ${turn}`);
  if (tilt !== "none") words.push(tilt === "up" ? "higher" : "lower");
  const text = words.join(", ").replace(/^./, (c) => c.toUpperCase());
  return { arrived: false, angle, turn, tilt, dAz, dEl, text };
}

/** Nearest under-covered cell to where the camera is now. */
export function nextMissing(coverage, view) {
  const missing = coverage.missing();
  if (!missing.length) return null;
  const here = view ? cellFor(view) : null;
  if (here && missing.includes(here)) return here;
  if (!view) return missing[0];
  const dist = (cell) => {
    if (cell === "top") return Math.max(0, 60 - view.elevation) * 2;
    const [band, idx] = cell.split("-");
    const centre = (Number(idx) + 0.5) * (360 / AZ_SECTORS);
    const d = Math.abs(((centre - view.azimuth + 540) % 360) - 180);
    const bandCentre = band === "low" ? 12 : 42;
    return d + Math.abs(bandCentre - view.elevation);
  };
  return missing.sort((a, b) => dist(a) - dist(b))[0];
}

/** Angle in degrees between two viewing directions given as {azimuth, elevation}. */
export function viewAngle(a, b) {
  const r = Math.PI / 180;
  const v = (x) => [Math.cos(x.elevation * r) * Math.cos(x.azimuth * r), Math.cos(x.elevation * r) * Math.sin(x.azimuth * r), Math.sin(x.elevation * r)];
  const p = v(a), q = v(b);
  const d = Math.max(-1, Math.min(1, p[0] * q[0] + p[1] * q[1] + p[2] * q[2]));
  return Math.acos(d) / r;
}

/**
 * How fast the view is turning, degrees per second, from recent
 * {t (ms), view} samples (the last ``windowMs``).
 */
export function angularSpeed(samples, now, windowMs = 600) {
  const recent = samples.filter((s) => s.view && now - s.t <= windowMs);
  if (recent.length < 2) return 0;
  let deg = 0;
  for (let i = 1; i < recent.length; i++) deg += viewAngle(recent[i - 1].view, recent[i].view);
  const dt = (recent[recent.length - 1].t - recent[0].t) / 1000;
  return dt > 0 ? deg / dt : 0;
}

/**
 * Decide whether to keep the current frame.
 *
 * Keeps frames that are sharp and well exposed, at most one per minInterval,
 * and stops piling frames into a cell that is already well covered.
 *
 * Bridging: if the view has turned ``bridgeDeg`` or more since the last kept
 * photo, keep one now (after only ``bridgeIntervalMs``), even in a full cell.
 * The 3-D reconstruction links photos through what neighbouring photos have
 * in common; on a real capture, gaps of 25-47 degrees between kept photos
 * split it into pieces that couldn't be joined.
 */
export function shouldCapture({ sharpOk, exposureOk, now, lastCaptureAt, cell, coverage, maxPerCell = 6, minIntervalMs = 600,
  view = null, lastView = null, bridgeDeg = 8, bridgeIntervalMs = 250 }) {
  if (!sharpOk || !exposureOk) return false;
  if (view && lastView && viewAngle(view, lastView) >= bridgeDeg && now - lastCaptureAt >= bridgeIntervalMs) return true;
  if (now - lastCaptureAt < minIntervalMs) return false;
  if (cell && coverage.counts.get(cell) >= maxPerCell) return false;
  return true;
}
