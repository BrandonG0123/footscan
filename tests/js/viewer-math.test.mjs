// Landmark viewer geometry: camera, picking rays, triangle hits, file parsing.
import test from "node:test";
import assert from "node:assert/strict";
import {
  anglesFor, bounds, intersectMesh, lookAt, mat4Multiply, mergeMeshes, orbitEye, parseViewerBin, perspective,
  pixelRay, projectToScreen, vertexNormals,
} from "../../web/assets/viewer-math.js";

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const BASIS = { east: [1, 0, 0], north: [0, 1, 0], up: [0, 0, 1] };

// A 10 x 10 mm square at z = 5, two triangles.
const square = { positions: new Float32Array([0, 0, 5, 10, 0, 5, 10, 10, 5, 0, 10, 5]), indices: new Uint32Array([0, 1, 2, 0, 2, 3]) };

test("a ray straight down hits the square at the right point", () => {
  const hit = intersectMesh(square.positions, square.indices, [3, 7, 50], [0, 0, -1]);
  assert.ok(hit);
  close(hit.t, 45);
  assert.deepEqual(hit.point.map((v) => +v.toFixed(9)), [3, 7, 5]);
});

test("rays that miss, or point away, hit nothing", () => {
  assert.equal(intersectMesh(square.positions, square.indices, [30, 7, 50], [0, 0, -1]), null);
  assert.equal(intersectMesh(square.positions, square.indices, [3, 7, 50], [0, 0, 1]), null);
});

test("the nearest of two surfaces wins", () => {
  const two = {
    positions: new Float32Array([...square.positions, 0, 0, 1, 10, 0, 1, 10, 10, 1]),
    indices: new Uint32Array([...square.indices, 4, 5, 6]),
  };
  close(intersectMesh(two.positions, two.indices, [8, 2, 50], [0, 0, -1]).point[2], 5);
  close(intersectMesh(two.positions, two.indices, [8, 2, -50], [0, 0, 1]).point[2], 1);
});

test("the ray through the centre pixel points at the target, and projects back there", () => {
  const cam = { target: [5, 5, 5], yaw: 0.7, pitch: 0.4, distance: 200 };
  const eye = orbitEye(cam, BASIS);
  close(Math.hypot(eye[0] - 5, eye[1] - 5, eye[2] - 5), 200);
  const fov = Math.PI / 4;
  const ray = pixelRay(400, 300, 800, 600, eye, cam.target, BASIS.up, fov);
  const toTarget = [0, 1, 2].map((i) => (cam.target[i] - eye[i]) / 200);
  for (let i = 0; i < 3; i++) close(ray.dir[i], toTarget[i]);
  // clicking a pixel and projecting the hit point lands on the same pixel
  const r2 = pixelRay(430, 260, 800, 600, eye, cam.target, BASIS.up, fov);
  const big = { positions: new Float32Array([-500, -500, 5, 500, -500, 5, 500, 500, 5, -500, 500, 5]), indices: square.indices };
  const hit = intersectMesh(big.positions, big.indices, r2.origin, r2.dir);
  assert.ok(hit);
  const vp = mat4Multiply(perspective(fov, 800 / 600, 1, 5000), lookAt(eye, cam.target, BASIS.up));
  const [x, y] = projectToScreen(hit.point, vp, 800, 600);
  close(x, 430, 1e-3);
  close(y, 260, 1e-3);
});

test("anglesFor is the inverse of orbitEye", () => {
  const cam = { target: [0, 0, 0], yaw: -2.1, pitch: -0.6, distance: 1 };
  const eye = orbitEye(cam, BASIS);
  const a = anglesFor(eye, BASIS);
  close(a.yaw, cam.yaw);
  close(a.pitch, cam.pitch);
});

test("vertex normals of the square point up; bounds are right", () => {
  const n = vertexNormals(square.positions, square.indices);
  for (let i = 0; i < 4; i++) close(n[i * 3 + 2], 1);
  const b = bounds(square.positions);
  assert.deepEqual(b.lo, [0, 0, 5]);
  assert.deepEqual(b.center, [5, 5, 5]);
});

test("viewer.bin parses, with and without colours", () => {
  for (const withColor of [true, false]) {
    const nv = 3, nf = 1;
    const pad = withColor ? (4 - ((nv * 3) % 4)) % 4 : 0;
    const buf = new ArrayBuffer(16 + nv * 12 + (withColor ? nv * 3 + pad : 0) + nf * 12);
    const dv = new DataView(buf);
    [70, 83, 86, 49].forEach((c, i) => dv.setUint8(i, c));
    dv.setUint32(4, nv, true); dv.setUint32(8, nf, true); dv.setUint32(12, withColor ? 1 : 0, true);
    new Float32Array(buf, 16, 9).set([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    let off = 16 + 36;
    if (withColor) { new Uint8Array(buf, off, 9).set([255, 0, 0, 0, 255, 0, 0, 0, 255]); off += 9 + pad; }
    new Uint32Array(buf, off, 3).set([0, 1, 2]);
    const m = parseViewerBin(buf);
    assert.deepEqual([...m.indices], [0, 1, 2]);
    assert.equal(m.positions[3], 1);
    assert.equal(m.colors?.[4] ?? null, withColor ? 255 : null);
  }
});

test("a click near a sticker snaps to its centre; plain skin doesn't snap", async () => {
  const { snapToSticker } = await import("../../web/assets/viewer-math.js");
  // a flat 40 x 40 mm patch, 0.5 mm grid, skin-coloured, with an 8 mm green dot centred at (12, 20)
  const pos = [], col = [];
  for (let x = 0; x <= 40; x += 0.5)
    for (let y = 0; y <= 40; y += 0.5) {
      pos.push(x, y, 0);
      col.push(...(Math.hypot(x - 12, y - 20) <= 4 ? [40, 170, 90] : [224, 178, 148]));
    }
  const P = new Float32Array(pos), C = new Uint8Array(col);
  const s = snapToSticker(P, C, [13.6, 21.1, 0]);
  assert.ok(s.snapped);
  close(s.point[0], 12, 0.26);
  close(s.point[1], 20, 0.26);
  const plain = snapToSticker(P, C, [32, 8, 0]);
  assert.equal(plain.snapped, false);
  assert.deepEqual(plain.point, [32, 8, 0]);
});

test("snapping lands on the surface at the sticker's centre, between vertices", async () => {
  const { snapToSticker } = await import("../../web/assets/viewer-math.js");
  // coarse 2 mm grid; the dot's centre (13, 21) is not a vertex
  const pos = [], col = [], idx = [];
  const n = 21;
  for (let j = 0; j < n; j++)
    for (let i = 0; i < n; i++) {
      const x = 2 * i, y = 2 * j;
      pos.push(x, y, 0);
      col.push(...(Math.hypot(x - 13, y - 21) <= 4.2 ? [40, 170, 90] : [224, 178, 148]));
    }
  for (let j = 0; j < n - 1; j++)
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i;
      idx.push(a, a + 1, a + n + 1, a, a + n + 1, a + n);
    }
  const s = snapToSticker(new Float32Array(pos), new Uint8Array(col), [15, 23, 0], { indices: new Uint32Array(idx) });
  assert.ok(s.snapped);
  close(s.point[0], 13, 0.05);
  close(s.point[1], 21, 0.05);
  close(s.point[2], 0, 1e-9);
});

test("two meshes merge into one, the second lifted, its triangles pointing at its own points", () => {
  const tri = (z, c) => ({ positions: new Float32Array([0, 0, z, 1, 0, z, 0, 1, z]), colors: new Uint8Array([c, c, c, c, c, c, c, c, c]), indices: new Uint32Array([0, 1, 2]) });
  const m = mergeMeshes(tri(0, 10), tri(5, 20), 7);
  assert.equal(m.positions.length, 18);
  assert.deepEqual([...m.positions.slice(9)], [0, 0, 12, 1, 0, 12, 0, 1, 12]);
  assert.deepEqual([...m.indices], [0, 1, 2, 3, 4, 5]);
  assert.deepEqual([...m.colors.slice(0, 3)], [10, 10, 10]);
  assert.deepEqual([...m.colors.slice(9, 12)], [20, 20, 20]);
  const plain = mergeMeshes(tri(0, 10), { ...tri(0, 0), colors: null }, 0);
  assert.deepEqual([...plain.colors.slice(9, 12)], [200, 200, 200]);
});
