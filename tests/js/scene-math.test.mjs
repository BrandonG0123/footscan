// The animated illustrations' geometry, and what the live ruler says.
import test from "node:test";
import assert from "node:assert/strict";
import { arcSegment, orbitPoint, rulerModel, segmentAt } from "../../web/assets/scene-math.js";
import { readCheckBar } from "../../web/assets/mat-check.js";

const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const BARS = [
  { unit: "cm", value: 10, length_mm: 100 },
  { unit: "in", value: 4, length_mm: 101.6 },
];

test("the orbit starts at the bottom and goes clockwise: bottom, left, top, right", () => {
  const p = (t) => orbitPoint(0, 0, 10, 5, t);
  close(p(0).x, 0); close(p(0).y, 5);       // bottom (screen y points down)
  close(p(0.25).x, -10); close(p(0.25).y, 0); // left
  close(p(0.5).x, 0); close(p(0.5).y, -5);   // top
  close(p(0.75).x, 10);                       // right
});

test("the phone always faces the middle", () => {
  close(orbitPoint(0, 0, 10, 5, 0).facing, 0);       // at the bottom: point up
  close(orbitPoint(0, 0, 10, 5, 0.5).facing, 180);   // at the top: point down
  close(orbitPoint(0, 0, 10, 5, 0.25).facing, 90);   // on the left: point right
});

test("segments split the turn evenly and wrap around", () => {
  assert.equal(segmentAt(0, 12), 0);
  assert.equal(segmentAt(0.999, 12), 11);
  assert.equal(segmentAt(1.04, 12), 0);
  assert.equal(segmentAt(-0.01, 12), 11);
  assert.match(arcSegment(0, 0, 10, 5, 0, 12), /^M[-\d.]+ [-\d.]+ A10 5 0 0 1 [-\d.]+ [-\d.]+$/);
});

test("ruler: a correct print, a shrunk print, and nonsense", () => {
  const m = (v) => rulerModel(v, v === "" ? null : readCheckBar(v, BARS), BARS);
  assert.deepEqual(m(""), { unit: "cm", max: 12, target: 10, shown: 0, pctOff: null, status: "empty" });
  assert.equal(m("10").status, "ok");
  assert.equal(m("4").unit, "in");
  assert.equal(m("4").status, "ok");
  const shrunk = m("9.4"); // "fit to page" on Letter shrinks about 6%
  assert.equal(shrunk.status, "wrong");
  assert.equal(shrunk.pctOff, -6);
  assert.equal(shrunk.shown, 9.4);
  assert.equal(m("25").status, "unclear");
  assert.equal(m("25").shown, 12); // clamped to the ruler's end
});
