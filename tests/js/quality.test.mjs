import assert from "node:assert/strict";
import { test } from "node:test";

import {
  Coverage, SharpnessJudge, cellFor, coveredEnough, exposureStats, judgeExposure,
  laplacianVariance, nextMissing, shouldCapture, viewFromOrientation,
} from "../../web/assets/quality.js";

function checkerboard(w, h, size) {
  const g = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
    g[y * w + x] = ((Math.floor(x / size) + Math.floor(y / size)) % 2) * 200 + 25;
  return g;
}

function boxBlur(g, w, h, r) {
  const out = new Float32Array(g.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let s = 0, n = 0;
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
      const yy = y + dy, xx = x + dx;
      if (yy >= 0 && yy < h && xx >= 0 && xx < w) { s += g[yy * w + xx]; n++; }
    }
    out[y * w + x] = s / n;
  }
  return out;
}

test("laplacian variance: flat is zero, blur reduces it", () => {
  const w = 64, h = 64;
  assert.equal(laplacianVariance(new Float32Array(w * h).fill(120), w, h), 0);
  const sharp = checkerboard(w, h, 4);
  const blurred = boxBlur(sharp, w, h, 2);
  assert.ok(laplacianVariance(blurred, w, h) < 0.2 * laplacianVariance(sharp, w, h));
});

test("exposure judgement", () => {
  assert.equal(judgeExposure(exposureStats(new Float32Array(100).fill(128))).ok, true);
  assert.equal(judgeExposure(exposureStats(new Float32Array(100).fill(255))).issue, "overexposed");
  assert.equal(judgeExposure(exposureStats(new Float32Array(100).fill(3))).issue, "underexposed");
});

test("sharpness judge is relative to recent frames", () => {
  const j = new SharpnessJudge();
  for (let i = 0; i < 20; i++) j.judge(1000);
  assert.equal(j.judge(900).ok, true);
  assert.equal(j.judge(300).ok, false);
  assert.match(j.judge(5).message, /can.t see any detail/);
});

test("orientation to view and cells", () => {
  assert.deepEqual(viewFromOrientation({ alpha: 30, beta: 90 }, 10), { azimuth: 20, elevation: 0 });
  assert.equal(viewFromOrientation({ alpha: 5, beta: 0 }, 10).azimuth, 355);
  assert.equal(cellFor({ azimuth: 0, elevation: 10 }), "low-0");
  assert.equal(cellFor({ azimuth: 359, elevation: 40 }), "mid-11");
  assert.equal(cellFor({ azimuth: 100, elevation: 80 }), "top");
});

test("coverage completeness and next missing", () => {
  const c = new Coverage({ perSideCell: 1, topCell: 1 });
  assert.equal(c.completeness(), 0);
  for (const cell of c.counts.keys()) c.add(cell);
  assert.equal(c.completeness(), 1);
  assert.equal(nextMissing(c, { azimuth: 0, elevation: 10 }), null);
  c.remove("mid-3");
  assert.equal(nextMissing(c, { azimuth: 0, elevation: 10 }), "mid-3");
});

test("capture policy", () => {
  const c = new Coverage();
  const base = { sharpOk: true, exposureOk: true, now: 1000, lastCaptureAt: 0, cell: "low-0", coverage: c };
  assert.equal(shouldCapture(base), true);
  assert.equal(shouldCapture({ ...base, sharpOk: false }), false);
  assert.equal(shouldCapture({ ...base, lastCaptureAt: 700 }), false);
  for (let i = 0; i < 6; i++) c.add("low-0");
  assert.equal(shouldCapture(base), false);
});

// Guard for a real bug: the Foot and Session inputs shared one row, so hiding
// the foot for object scans hid the session box too.
test("research capture hides only the foot field for object scans", async () => {
  const { readFileSync } = await import("node:fs");
  const html = readFileSync(new URL("../../web/studio/capture.html", import.meta.url), "utf8");
  const footRow = html.slice(html.indexOf('id="foot-row"'));
  const block = footRow.slice(0, footRow.indexOf("</div>"));
  assert.ok(!block.includes('id="session"'), "session input must not sit inside the hidden foot field");
  assert.ok(html.includes('id="session"'), "session input still exists");
});

test("directions suit what is being scanned", async () => {
  const { describeCell } = await import("../../web/assets/quality.js");
  // a foot has a heel and an inner/outer side
  assert.match(describeCell("low-0", "right"), /behind the heel/);
  assert.match(describeCell("mid-3", "right"), /outer side of the foot/);
  assert.match(describeCell("mid-3", "left"), /inner side of the foot/);
  // anything else must not: no heel on a hand or a shoe
  for (const cell of ["low-0", "mid-3", "low-6", "mid-9", "top"]) {
    const text = describeCell(cell, null);
    assert.ok(!/heel|toes|foot/.test(text), `object wording leaked foot terms: ${text}`);
  }
  assert.match(describeCell("low-0", null), /back where you started/);
  assert.match(describeCell("low-6", null), /far side/);
});

test("steering points the right way around the subject", async () => {
  const { steerTo, targetView } = await import("../../web/assets/quality.js");
  const at = (azimuth, elevation) => ({ azimuth, elevation });

  // increasing azimuth is the camera's own right, so a cell ahead of us is "right"
  assert.equal(steerTo(at(0, 12), "low-3").turn, "right");
  assert.equal(steerTo(at(180, 12), "low-3").turn, "left");
  // and it takes the short way round the circle
  assert.equal(steerTo(at(350, 12), "low-0").turn, "right");
  assert.equal(steerTo(at(10, 12), "low-11").turn, "left");

  // height
  assert.equal(steerTo(at(15, 12), "mid-0").tilt, "up");
  assert.equal(steerTo(at(15, 42), "low-0").tilt, "down");
  assert.equal(steerTo(at(15, 12), "top").tilt, "up");

  // close enough: hold still
  const here = targetView("mid-4");
  const arrived = steerTo(at(here.azimuth, here.elevation), "mid-4");
  assert.equal(arrived.arrived, true);
  assert.match(arrived.text, /Hold it there/);

  // the arrow angle: 0 is up the screen, 90 is right
  assert.ok(Math.abs(steerTo(at(0, 12), "low-3").angle - 90) < 1, "pure right turn points right");
  assert.ok(Math.abs(steerTo(at(15, 12), "top").angle) < 1, "pure lift points up");
  assert.ok(steerTo(at(15, 42), "low-0").angle === 180, "pure drop points down");
});

test("bridging: a big turn since the last kept photo is kept soon, even in a full cell", async () => {
  const { shouldCapture, viewAngle, Coverage } = await import("../../web/assets/quality.js");
  const coverage = new Coverage();
  for (let i = 0; i < 6; i++) coverage.add("mid-0");
  const base = { sharpOk: true, exposureOk: true, lastCaptureAt: 1000, cell: "mid-0", coverage };
  const last = { azimuth: 0, elevation: 40 };
  // small turn, full cell: no
  assert.equal(shouldCapture({ ...base, now: 2000, view: { azimuth: 3, elevation: 40 }, lastView: last }), false);
  // big turn: yes after 250 ms, even though the cell is full and 600 ms hasn't passed
  assert.equal(shouldCapture({ ...base, now: 1300, view: { azimuth: 12, elevation: 40 }, lastView: last }), true);
  assert.equal(shouldCapture({ ...base, now: 1100, view: { azimuth: 12, elevation: 40 }, lastView: last }), false);
  // never a blurry one
  assert.equal(shouldCapture({ ...base, sharpOk: false, now: 1300, view: { azimuth: 30, elevation: 40 }, lastView: last }), false);
  assert.ok(Math.abs(viewAngle({ azimuth: 0, elevation: 0 }, { azimuth: 90, elevation: 0 }) - 90) < 1e-9);
  assert.ok(Math.abs(viewAngle({ azimuth: 0, elevation: 90 }, { azimuth: 123, elevation: 90 })) < 1e-6);
});

test("turning speed is measured over the last moments", async () => {
  const { angularSpeed } = await import("../../web/assets/quality.js");
  const samples = [0, 100, 200, 300, 400, 500].map((t) => ({ t, view: { azimuth: t / 10, elevation: 0 } })); // 100 deg/s
  assert.ok(Math.abs(angularSpeed(samples, 500) - 100) < 1);
  assert.equal(angularSpeed([{ t: 0, view: { azimuth: 0, elevation: 0 } }], 0), 0);
});

test("finishing needs every angle, not a photo count", () => {
  // plenty of photos, but not every angle: no
  assert.equal(coveredEnough({ hasView: true, completeness: 0.6, kept: 90, targetFrames: 60 }), false);
  // every angle covered, even with fewer photos than the target: yes
  assert.equal(coveredEnough({ hasView: true, completeness: 1, kept: 40, targetFrames: 60 }), true);
  // no motion sensors: the angles can't be known, so the full target is needed
  assert.equal(coveredEnough({ hasView: false, completeness: null, kept: 59, targetFrames: 60 }), false);
  assert.equal(coveredEnough({ hasView: false, completeness: null, kept: 60, targetFrames: 60 }), true);
  assert.equal(coveredEnough({ hasView: true, completeness: 1, kept: 0, targetFrames: 60 }), false);
});

test("a lap from one side never completes the coverage", () => {
  const cov = new Coverage();
  for (let i = 0; i < 80; i++) cov.add(cellFor({ azimuth: 10 + (i % 20), elevation: 45 }));
  assert.ok(cov.completeness() < 1);
  assert.equal(coveredEnough({ hasView: true, completeness: cov.completeness(), kept: 80, targetFrames: 60 }), false);
});
