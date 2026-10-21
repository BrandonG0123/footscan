// Geometry for the landmark viewer, kept free of WebGL so it can be tested in Node.
//
// Conventions: 4x4 matrices are Float64Array(16) in column-major order (as
// WebGL expects). The orbit camera circles a target point: "yaw" turns
// around the up axis, "pitch" tilts above or below the horizon, "distance"
// is how far away it sits.

export function mat4Multiply(a, b) {
  const o = new Float64Array(16);
  for (let c = 0; c < 4; c++)
    for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
  return o;
}

export function perspective(fovyRad, aspect, near, far) {
  const f = 1 / Math.tan(fovyRad / 2);
  const o = new Float64Array(16);
  o[0] = f / aspect;
  o[5] = f;
  o[10] = (far + near) / (near - far);
  o[11] = -1;
  o[14] = (2 * far * near) / (near - far);
  return o;
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
export const vec = { sub, dot, cross, norm };

/** View matrix for a camera at eye looking at target with the given up direction. */
export function lookAt(eye, target, up) {
  const z = norm(sub(eye, target)); // camera looks down -z
  let x = cross(up, z);
  if (Math.hypot(...x) < 1e-9) x = cross([0, 1, 0], z);
  x = norm(x);
  const y = cross(z, x);
  return new Float64Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -dot(x, eye), -dot(y, eye), -dot(z, eye), 1,
  ]);
}

/**
 * Where an orbit camera sits. ``basis`` gives the scene's axes: right-handed
 * {east, north, up}; yaw 0 looks from +east toward the target.
 */
export function orbitEye(cam, basis) {
  const { east, north, up } = basis;
  const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw);
  const dir = [0, 1, 2].map((i) => cp * cy * east[i] + cp * sy * north[i] + sp * up[i]);
  return [0, 1, 2].map((i) => cam.target[i] + cam.distance * dir[i]);
}

/** Yaw and pitch that look from a direction (unit vector from target toward the eye). */
export function anglesFor(direction, basis) {
  const d = norm(direction);
  const e = dot(d, basis.east), n = dot(d, basis.north), u = dot(d, basis.up);
  return { yaw: Math.atan2(n, e), pitch: Math.asin(Math.max(-1, Math.min(1, u))) };
}

/**
 * Ray through a pixel. px, py in CSS pixels from the canvas's top-left.
 * Returns {origin, dir} in world coordinates.
 */
export function pixelRay(px, py, width, height, eye, target, up, fovyRad) {
  const z = norm(sub(eye, target));
  const x = norm(cross(up, z));
  const y = cross(z, x);
  const t = Math.tan(fovyRad / 2);
  const nx = ((2 * px) / width - 1) * t * (width / height);
  const ny = (1 - (2 * py) / height) * t;
  const dir = norm([0, 1, 2].map((i) => nx * x[i] + ny * y[i] - z[i]));
  return { origin: eye, dir };
}

/**
 * Nearest triangle hit by a ray (Möller–Trumbore). Brute force over every
 * triangle: a few milliseconds for a few hundred thousand, which is fine for
 * one click. Returns {t, point, face} or null.
 */
export function intersectMesh(positions, indices, origin, dir) {
  let best = Infinity, face = -1;
  const [ox, oy, oz] = origin, [dx, dy, dz] = dir;
  for (let f = 0; f < indices.length; f += 3) {
    const a = indices[f] * 3, b = indices[f + 1] * 3, c = indices[f + 2] * 3;
    const ax = positions[a], ay = positions[a + 1], az = positions[a + 2];
    const e1x = positions[b] - ax, e1y = positions[b + 1] - ay, e1z = positions[b + 2] - az;
    const e2x = positions[c] - ax, e2y = positions[c + 1] - ay, e2z = positions[c + 2] - az;
    const px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
    const det = e1x * px + e1y * py + e1z * pz;
    if (det > -1e-12 && det < 1e-12) continue; // ray parallel to the triangle
    const inv = 1 / det;
    const tx = ox - ax, ty = oy - ay, tz = oz - az;
    const u = (tx * px + ty * py + tz * pz) * inv;
    if (u < 0 || u > 1) continue;
    const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
    const v = (dx * qx + dy * qy + dz * qz) * inv;
    if (v < 0 || u + v > 1) continue;
    const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
    if (t > 1e-9 && t < best) { best = t; face = f / 3; }
  }
  if (face < 0) return null;
  return { t: best, face, point: [ox + best * dx, oy + best * dy, oz + best * dz] };
}

/** World point -> CSS pixel (x, y) and whether it's in front of the camera. */
export function projectToScreen(p, viewProj, width, height) {
  const m = viewProj;
  const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
  const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
  const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
  if (w <= 0) return null;
  return [((x / w + 1) / 2) * width, ((1 - y / w) / 2) * height];
}

/** Area-weighted vertex normals (each face adds its un-normalised normal to its corners). */
export function vertexNormals(positions, indices) {
  const n = new Float32Array(positions.length);
  for (let f = 0; f < indices.length; f += 3) {
    const a = indices[f] * 3, b = indices[f + 1] * 3, c = indices[f + 2] * 3;
    const e1 = [positions[b] - positions[a], positions[b + 1] - positions[a + 1], positions[b + 2] - positions[a + 2]];
    const e2 = [positions[c] - positions[a], positions[c + 1] - positions[a + 1], positions[c + 2] - positions[a + 2]];
    const fn = cross(e1, e2);
    for (const i of [a, b, c]) { n[i] += fn[0]; n[i + 1] += fn[1]; n[i + 2] += fn[2]; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
    n[i] /= l; n[i + 1] /= l; n[i + 2] /= l;
  }
  return n;
}

export function bounds(positions) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3)
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], positions[i + k]);
      hi[k] = Math.max(hi[k], positions[i + k]);
    }
  return { lo, hi, center: lo.map((v, k) => (v + hi[k]) / 2), size: Math.max(...hi.map((v, k) => v - lo[k])) };
}

/** Parse viewer.bin (see src/footscan/recon/viewer_data.py). */
export function parseViewerBin(buffer) {
  const head = new Uint8Array(buffer, 0, 4);
  if (String.fromCharCode(...head) !== "FSV1") throw new Error("not a footscan model file");
  const dv = new DataView(buffer);
  const nv = dv.getUint32(4, true), nf = dv.getUint32(8, true), flags = dv.getUint32(12, true);
  let off = 16;
  const positions = new Float32Array(buffer, off, nv * 3);
  off += nv * 12;
  let colors = null;
  if (flags & 1) {
    colors = new Uint8Array(buffer, off, nv * 3);
    off += nv * 3 + ((4 - ((nv * 3) % 4)) % 4);
  }
  const indices = new Uint32Array(buffer, off, nf * 3);
  return { positions, colors, indices };
}

/** Closest point on triangle abc to p (Ericson, Real-Time Collision Detection, 5.1.5). */
export function closestPointOnTriangle(p, a, b, c) {
  const ab = sub(b, a), ac = sub(c, a), ap = sub(p, a);
  const d1 = dot(ab, ap), d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return a;
  const bp = sub(p, b), d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return b;
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) { const v = d1 / (d1 - d3); return a.map((x, i) => x + v * ab[i]); }
  const cp = sub(p, c), d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return c;
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) { const w = d2 / (d2 - d6); return a.map((x, i) => x + w * ac[i]); }
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
    const w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    return b.map((x, i) => x + w * (c[i] - x));
  }
  const denom = 1 / (va + vb + vc), v = vb * denom, w = vc * denom;
  return a.map((x, i) => x + ab[i] * v + ac[i] * w);
}

/**
 * Snap a click to the centre of the coloured sticker under it.
 *
 * Look at the surface within ``radius`` mm of the click. The skin colour is
 * the median colour of a ring just outside that (``radius`` to 1.8 x radius).
 * Vertices whose colour differs from the skin by more than ``minDiff``
 * (0-255 RGB distance) are sticker. The landmark is their centre, carried
 * back onto the surface: the closest point on any triangle touching the
 * sticker (the centre of a curved patch sits slightly inside it). Returns
 * {point, snapped, count}; snapped is false (and point the click) when
 * there's no clear sticker there.
 */
export function snapToSticker(positions, colors, click, { radius = 6, minDiff = 60, minCount = 5, indices = null } = {}) {
  if (!colors) return { point: click, snapped: false, count: 0 };
  const inner = [], ring = [];
  const r2 = radius * radius, R2 = (1.8 * radius) ** 2;
  for (let i = 0; i < positions.length; i += 3) {
    const dx = positions[i] - click[0], dy = positions[i + 1] - click[1], dz = positions[i + 2] - click[2];
    const d2 = dx * dx + dy * dy + dz * dz;
    if (d2 <= r2) inner.push(i);
    else if (d2 <= R2) ring.push(i);
  }
  if (ring.length < 5 || inner.length < minCount) return { point: click, snapped: false, count: 0 };
  const median = (arr) => { const s = [...arr].sort((a, b) => a - b); return s[s.length >> 1]; };
  const skin = [0, 1, 2].map((k) => median(ring.map((i) => colors[i + k])));
  const marker = inner.filter((i) => Math.hypot(colors[i] - skin[0], colors[i + 1] - skin[1], colors[i + 2] - skin[2]) > minDiff);
  if (marker.length < minCount) return { point: click, snapped: false, count: marker.length };
  const c = [0, 1, 2].map((k) => marker.reduce((s, i) => s + positions[i + k], 0) / marker.length);
  const vert = (i) => [positions[i], positions[i + 1], positions[i + 2]];
  let best = null, bd = Infinity;
  const consider = (q) => {
    const d = (q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2 + (q[2] - c[2]) ** 2;
    if (d < bd) { bd = d; best = q; }
  };
  if (indices) {
    const inMarker = new Set(marker.map((i) => i / 3));
    for (let f = 0; f < indices.length; f += 3) {
      if (!inMarker.has(indices[f]) && !inMarker.has(indices[f + 1]) && !inMarker.has(indices[f + 2])) continue;
      consider(closestPointOnTriangle(c, vert(indices[f] * 3), vert(indices[f + 1] * 3), vert(indices[f + 2] * 3)));
    }
  }
  if (!best) for (const i of marker) consider(vert(i));
  return { point: best, snapped: true, count: marker.length };
}

/**
 * Two meshes as one ({positions, colors, indices} each, colours as uint8 RGB), the second moved
 * up by ``lift`` (mm, along z): for showing a scanned sole lifted off the insole made from it.
 * A mesh without colours gets light grey.
 */
export function mergeMeshes(a, b, lift = 0) {
  const na = a.positions.length / 3, nb = b.positions.length / 3;
  const positions = new Float32Array((na + nb) * 3);
  positions.set(a.positions, 0);
  for (let i = 0; i < nb; i++) {
    positions[(na + i) * 3] = b.positions[i * 3];
    positions[(na + i) * 3 + 1] = b.positions[i * 3 + 1];
    positions[(na + i) * 3 + 2] = b.positions[i * 3 + 2] + lift;
  }
  const colors = new Uint8Array((na + nb) * 3).fill(200);
  if (a.colors) colors.set(a.colors, 0);
  if (b.colors) colors.set(b.colors, na * 3);
  const indices = new Uint32Array(a.indices.length + b.indices.length);
  indices.set(a.indices, 0);
  for (let i = 0; i < b.indices.length; i++) indices[a.indices.length + i] = b.indices[i] + na;
  return { positions, colors, indices };
}
