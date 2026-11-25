// Studio: click landmarks on a scan's 3-D model, save them as a pick, see the measurements.
import { MeshViewer } from "./mesh-viewer.js";
import { ask, esc } from "./studio.js";
import { parseViewerBin, snapToSticker, vec } from "./viewer-math.js";

const $ = (id) => document.getElementById(id);
const q = new URLSearchParams(location.search);
const capture = q.get("capture"), submission = q.get("submission"), scanKey = q.get("scan");
const base = capture
  ? `/api/captures/${encodeURIComponent(capture)}`
  : `/api/submissions/${encodeURIComponent(submission)}/scans/${encodeURIComponent(scanKey)}`;

// Distinct, colour-blind-friendly-ish dot colours (Okabe-Ito plus a few).
const PALETTE = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#999999",
  "#7F3C8D", "#11A579", "#3969AC", "#F2B701", "#E73F74", "#80BA5A", "#E68310", "#008695"];
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const LABELS = {
  foot_length_mm: ["Foot length", "mm"], truncated_foot_length_mm: ["Truncated foot length", "mm"],
  dorsal_height_50_mm: ["Dorsal height at 50 %", "mm"], ahi: ["Arch height index", ""],
  navicular_height_mm: ["Navicular height", "mm"], navicular_height_norm: ["Navicular height ÷ truncated length", ""],
  rearfoot_angle_deg: ["Rearfoot angle", "°"], calcaneal_angle_deg: ["Calcaneal angle", "°"],
  forefoot_rearfoot_angle_deg: ["Forefoot–rearfoot angle", "°"],
};

let info = null;      // {foot, condition, spec, picks, provisional_frame}
let viewer = null;
let current = 1;      // pick number being edited
let points = {};      // landmark key -> [x, y, z] for the current pick
let snapped = {};     // landmark key -> true if placed on a sticker's centre
let active = null;    // landmark key waiting for a click
let dirty = false;

async function init() {
  $("back").innerHTML = capture
    ? `Research capture <a class="mono" href="/studio/captures.html#${esc(capture)}">${esc(capture)}</a> · <a href="/studio/model.html?capture=${encodeURIComponent(capture)}">3D model</a>`
    : `Submission <a class="mono" href="/studio/submission.html?id=${esc(submission)}">${esc(submission)}</a> · scan ${esc(scanKey)}`;
  const [ok, got] = await ask(`${base}/picks`);
  info = got;
  if (!ok) return showMsg(esc(info.error || "Couldn't load this scan."));
  $("title").textContent = `Landmarks · ${info.foot} foot · ${info.condition}`;
  if (!info.has_model) {
    return showMsg(`No 3-D model yet. <a href="/studio/model.html?${capture ? `capture=${encodeURIComponent(capture)}` : `submission=${encodeURIComponent(submission)}&scan=${encodeURIComponent(scanKey)}`}">Build it first</a>.`);
  }
  try {
    viewer = new MeshViewer($("canvas"), { onPick: place, onChange: drawLabels });
    window.footscanViewer = viewer; // for debugging from the browser console
  } catch (e) {
    return showMsg(esc(e.message));
  }
  const buf = await fetch(`${base}/viewer.bin`).then((x) => x.arrayBuffer());
  viewer.load(parseViewerBin(buf));
  $("btn-color").hidden = !viewer.hasColor;
  $("btn-upright").hidden = info.in_mat_frame;  // reconstructions are already upright (mat frame)
  $("snap").checked = viewer.hasColor;
  $("snap").disabled = !viewer.hasColor;
  $("msg").hidden = true;
  $("toolbar").hidden = false;
  current = info.picks.length ? info.picks[info.picks.length - 1].pick : 1;
  selectPick(current);
}

function showMsg(html) {
  $("msg").hidden = false;
  $("msg").innerHTML = `<p>${html}</p>`;
}

// ---- foot directions for the view buttons -----------------------------------
// From the clicked landmarks when there are enough, else the reconstruction's
// provisional frame, else plain axes.
function footAxes() {
  const p = points;
  let up = info.provisional_frame?.up || viewer.basis.up;
  if (p.floor_a && p.floor_b && p.floor_c) {
    // imported scan: the clicked floor says which way is up (toward the ankles)
    up = vec.norm(vec.cross(vec.sub(p.floor_b, p.floor_a), vec.sub(p.floor_c, p.floor_a)));
    const ank = p.malleolus_medial || p.malleolus_lateral || p.navicular_tuberosity;
    if (ank && vec.dot(vec.sub(ank, p.floor_a), up) < 0) up = up.map((v) => -v);
  }
  if (p.mtpj1_medial && p.mtpj5_lateral && (p.malleolus_medial || p.malleolus_lateral)) {
    const fore = vec.sub(p.mtpj1_medial, vec.sub(p.mtpj1_medial, p.mtpj5_lateral).map((v) => v / 2));
    const malls = [p.malleolus_medial, p.malleolus_lateral].filter(Boolean);
    const ank = [0, 1, 2].map((i) => malls.reduce((s, m) => s + m[i], 0) / malls.length);
    let a = vec.sub(fore, ank);
    a = vec.norm(vec.sub(a, up.map((u) => u * vec.dot(a, up))));
    const left = vec.cross(up, a);
    return { anterior: a, medial: info.foot === "right" ? left : left.map((v) => -v), up };
  }
  if (info.provisional_frame) return info.provisional_frame;
  return null;
}

function viewDirection(name) {
  const f = footAxes();
  const up = f?.up || [0, 0, 1];
  if (name === "top") return up;
  if (name === "plantar") return up.map((v) => -v);
  if (!f) return null;
  if (name === "medial") return vec.norm(vec.sub(f.medial, up.map((v) => -0.35 * v)));
  if (name === "lateral") return vec.norm(vec.sub(f.medial.map((v) => -v), up.map((v) => -0.35 * v)));
  if (name === "posterior") return vec.norm(vec.sub(f.anterior.map((v) => -v), up.map((v) => -0.25 * v)));
  return null;
}

// Imported scans can arrive lying on their side (many apps export y-up).
// Cycle the viewer's "up" through the six axis directions until it looks right.
const UPS = [[0, 0, 1], [0, 1, 0], [0, -1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, -1]];
let upIndex = 0;
function setUp(up) {
  const east = Math.abs(up[0]) > 0.9 ? [0, 1, 0] : [1, 0, 0];
  const e = vec.norm(vec.sub(east, up.map((u) => u * vec.dot(east, up))));
  viewer.setBasis({ east: e, north: vec.cross(up, e), up });
}
function cycleUp() {
  upIndex = (upIndex + 1) % UPS.length;
  setUp(UPS[upIndex]);
  viewer.home();
}

function turnTo(name) {
  if (name === "home") return viewer.home();
  if (name === "upright") return cycleUp();
  const d = viewDirection(name);
  if (!d) return;
  // Frame the whole foot from that side; zoom in from there if needed.
  viewer.cam.target = viewer.bounds.center.slice();
  viewer.cam.distance = viewer.bounds.size * 1.5;
  viewer.lookFrom(d);
}

document.querySelectorAll("#toolbar [data-view]").forEach((b) => b.addEventListener("click", () => turnTo(b.dataset.view)));
$("btn-color").addEventListener("click", (e) => {
  viewer.useColor = !viewer.useColor;
  e.target.setAttribute("aria-pressed", String(viewer.useColor));
  viewer.draw();
});

// ---- picks ---------------------------------------------------------------------
function pickRecord(n) {
  return info.picks.find((p) => p.pick === n);
}

function selectPick(n) {
  if (dirty && !confirm("Leave this pick without saving?")) return;
  current = n;
  const rec = pickRecord(n);
  // A stale pick was clicked on an older model: its points don't sit on this
  // surface, so it is re-picked from scratch rather than patched.
  points = rec && !rec.stale ? structuredClone(rec.landmarks) : {};
  snapped = rec?.snapped && !rec.stale ? { ...rec.snapped } : {};
  dirty = false;
  active = info.spec.find((l) => !points[l.key] && !l.optional)?.key ?? null;
  renderPicks();
  renderList();
  renderResults(rec);
  updateMarkers();
  if (active && $("auto-turn").checked) turnTo(info.spec.find((l) => l.key === active).view);
}

function renderPicks() {
  const nums = info.picks.map((p) => p.pick);
  if (!nums.includes(current)) nums.push(current);
  const next = Math.max(0, ...nums) + 1;
  $("picks").innerHTML = nums.sort((a, b) => a - b).map((n) =>
    `<button data-pick="${n}" aria-pressed="${n === current}">Pick ${n}${pickRecord(n)?.stale ? " ⚠" : ""}</button>`).join("") +
    `<button data-pick="${next}" title="Pick again without seeing earlier picks">+ New pick</button>`;
  $("picks").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    const n = +b.dataset.pick;
    if (n === next) $("show-others").checked = false; // a re-pick is blind
    selectPick(n);
  }));
  const rec = pickRecord(current);
  $("pick-note").textContent = rec?.stale
    ? "This pick was clicked on an older version of the model (it was rebuilt since). Re-pick it."
    : rec ? `Saved ${rec.picked_at.replace("T", " ")}.` : "Not saved yet.";
}

function renderList() {
  $("lm-list").innerHTML = info.spec.map((l, i) => {
    const done = !!points[l.key];
    const color = PALETTE[i % PALETTE.length];
    return `<li data-key="${l.key}" class="${done ? "done" : ""} ${active === l.key ? "active" : ""}">
      <span class="dot" style="${done ? `background:${color}` : ""}"></span>
      <span class="name">${esc(l.label)}${l.optional ? ` <span class="hint">(optional)</span>` : ""}${done && snapped[l.key] ? ` <span class="hint" title="placed on the sticker's centre">· on sticker</span>` : ""}
        ${active === l.key ? `<span class="where">${esc(l.where)}</span>` : ""}</span>
      ${done ? `<button data-clear="${l.key}" aria-label="Clear ${esc(l.label)}">clear</button>` : "<span></span>"}</li>`;
  }).join("");
  $("lm-list").querySelectorAll("li").forEach((li) => li.addEventListener("click", (e) => {
    if (e.target.dataset.clear) {
      delete points[e.target.dataset.clear];
      delete snapped[e.target.dataset.clear];
      dirty = true;
      active = e.target.dataset.clear;
    } else active = li.dataset.key;
    renderList();
    updateMarkers();
    if ($("auto-turn").checked && active) turnTo(info.spec.find((l) => l.key === active).view);
  }));
  const l = info.spec.find((x) => x.key === active);
  $("prompt").hidden = !l;
  if (l) $("prompt").innerHTML = `<strong>Click: ${esc(l.label)}</strong><br>${esc(l.where)}`;
  $("btn-save").disabled = !Object.keys(points).length || !dirty;
}

function place(point) {
  if (!active) return;
  let s = { point, snapped: false };
  if ($("snap").checked) s = snapToSticker(viewer.positions, viewer.colors, point, { indices: viewer.indices });
  points[active] = s.point.map((v) => +v.toFixed(3));
  snapped[active] = s.snapped;
  $("snap-note").textContent = $("snap").checked
    ? (s.snapped ? "Snapped to the sticker's centre." : "No sticker found there: placed where you clicked.") : "";
  dirty = true;
  // next landmark still to do, after this one
  const order = info.spec.map((l) => l.key);
  const from = order.indexOf(active);
  active = [...order.slice(from + 1), ...order.slice(0, from)]
    .find((k) => !points[k] && !info.spec.find((l) => l.key === k).optional) ?? null;
  renderList();
  updateMarkers();
  if (active && $("auto-turn").checked) turnTo(info.spec.find((l) => l.key === active).view);
}

function updateMarkers() {
  const marks = info.spec.map((l, i) => points[l.key] && ({
    position: points[l.key], color: rgb(PALETTE[i % PALETTE.length]), label: l.label, key: l.key }))
    .filter(Boolean);
  if ($("show-others").checked) {
    for (const rec of info.picks) {
      if (rec.pick === current) continue;
      for (const [k, p] of Object.entries(rec.landmarks)) marks.push({ position: p, color: [0.55, 0.55, 0.55], label: `${k} (pick ${rec.pick})`, other: true });
    }
  }
  viewer?.setMarkers(marks);
}
$("show-others").addEventListener("change", updateMarkers);

function drawLabels() {
  if (!viewer) return;
  $("labels").innerHTML = viewer.markers.filter((m) => !m.other && m.visible).map((m) => {
    const s = viewer.toScreen(m.position);
    return s ? `<span style="left:${s[0]}px;top:${s[1]}px">${esc(m.label)}</span>` : "";
  }).join("");
}

// ---- save + results ------------------------------------------------------------
$("btn-save").addEventListener("click", async () => {
  $("btn-save").disabled = true;
  $("save-error").textContent = "";
  const [ok, rec] = await ask(`${base}/picks/${current}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ landmarks: points, snapped, mesh_sha256: info.mesh_sha256 }),
  });
  if (!ok) {
    $("save-error").textContent = rec.error || "Couldn't save.";
    $("btn-save").disabled = false;
    return;
  }
  info.picks = info.picks.filter((p) => p.pick !== current).concat(rec).sort((a, b) => a.pick - b.pick);
  dirty = false;
  renderPicks();
  renderList();
  renderResults(rec);
});

function fmt(k, v) {
  if (v == null) return "—";
  const [, unit] = LABELS[k] || ["", ""];
  return unit === "°" ? `${v.toFixed(1)}°` : unit === "mm" ? `${v.toFixed(1)} mm` : v.toFixed(3);
}

function renderResults(rec) {
  const box = $("results");
  if (!rec) { box.hidden = true; return; }
  box.hidden = false;
  const rows = Object.entries(rec.measures || {}).map(([k, v]) =>
    `<tr><td>${esc(LABELS[k]?.[0] || k)}</td><td>${fmt(k, v)}</td></tr>`).join("");
  box.innerHTML = `<h2 style="margin:0 0 8px;font-size:1.1rem">Measurements · pick ${rec.pick}</h2>
    ${rec.warnings?.length ? `<div class="callout warn" style="margin:0 0 10px"><ul style="margin:0;padding-left:18px">${rec.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    <table class="meas"><tbody>${rows}</tbody></table>
    <p class="hint" style="margin:10px 0 0">${rec.heel_posterior_auto ? "Back of the heel was found from the surface. " : ""}One pick is one measurement; repeatability needs several captures and re-picks (Phase 0 protocol).</p>`;
}

window.addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });
init();
