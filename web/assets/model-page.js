// Studio: build a capture's 3D model (Phase 2) and read the results.
// Everything numeric on this page comes from the reconstruction's report;
// nothing is estimated or filled in here.
import { ask, esc } from "./studio.js";

const $ = (id) => document.getElementById(id);
const q = new URLSearchParams(location.search);
const capture = q.get("capture");
const submission = q.get("submission");
const scanKey = q.get("scan");
const base = capture
  ? `/api/captures/${encodeURIComponent(capture)}`
  : `/api/submissions/${encodeURIComponent(submission)}/scans/${encodeURIComponent(scanKey)}`;
const api = `${base}/recon`;

const STAGES = [
  ["cameras", "Placing the photos"],
  ["scale", "Millimetres from the mat"],
  ["depth", "Depth for every pixel"],
  ["surface", "Building the surface"],
  ["accuracy", "Accuracy study"],
  ["foot frame", "Foot frame"],
];
const CALIPERS = [
  ["length", "Overall length", 150], ["width", "Overall width", 70], ["base", "Base thickness", 10],
  ["dome_apex", "Dome top height", 30], ["terrace_high", "High terrace height", 35], ["terrace_low", "Low terrace height", 22],
];
const mm = (v, d = 2) => (v == null ? "—" : `${Number(v).toFixed(d)} mm`);
const signed = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`);

let meta = null;
let timer = null;

async function init() {
  if (capture) {
    $("back").innerHTML = `Research capture <a class="mono" href="/studio/captures.html#${esc(capture)}">${esc(capture)}</a>`;
    const [ok, one] = await ask(base);  // this capture alone, not the whole library
    meta = ok ? one : {};
    $("title").textContent = meta.condition === "calibration" ? "Calibration object" :
      meta.foot ? `${meta.foot} foot · ${meta.condition}` : `${meta.condition || "Capture"}`;
    if (meta.method === "imported_mesh") return importedCard(meta);  // nothing to build: it came as a model
  } else {
    $("back").innerHTML = `Submission <a class="mono" href="/studio/submission.html?id=${esc(submission)}">${esc(submission)}</a> · scan ${esc(scanKey)}`;
    meta = { condition: scanKey?.split("-")[1] };
    $("title").textContent = `Scan ${scanKey}`;
  }
  refresh();
}

async function refresh() {
  clearTimeout(timer);
  const [, s, status] = await ask(api);
  if (s.error && s.state === undefined) {
    // Unreachable, or the studio's own trouble (5xx): shown, and asked again in a while (weak Wi-Fi drops a
    // request now and then while a model builds). A refusal (no such capture, not the studio's operator) won't
    // change by asking again: shown once.
    const again = status === 0 || status >= 500;
    $("root").innerHTML = `<div class="callout stop"><p>Couldn't ask the studio about this model: ${esc(s.error)}.
      ${again ? "Asking again in a few seconds…" : ""}</p></div>`;
    if (again) timer = setTimeout(refresh, 5000);
    return;
  }
  render(s);
  if (s.state === "running") timer = setTimeout(refresh, 2000);
}

async function build() {
  const btn = $("btn-build");
  if (btn) btn.disabled = true;
  const [ok, body] = await ask(api, { method: "POST" });
  if (!ok) {
    $("build-error").textContent = body.error || "Couldn't start.";
    if (btn) btn.disabled = false;
    return;
  }
  refresh();
}

function stepsHtml(stage, state) {
  const isCal = meta?.condition === "calibration";
  const isStandingFoot = ["swb", "fwb"].includes(meta?.condition);
  const list = STAGES.filter(([k]) => (k !== "accuracy" || isCal) && (k !== "foot frame" || isStandingFoot));
  const at = list.findIndex(([k]) => k === stage);
  return `<ol class="steps">${list.map(([k, label], i) => {
    const cls = state === "done" || (at >= 0 && i < at) ? "done" : i === at && state === "running" ? "now" : "";
    return `<li class="${cls}">${esc(label)}</li>`;
  }).join("")}</ol>`;
}

function buildCard(s) {
  const running = s.state === "running";
  const label = s.state === "none" ? "Build 3D model" : "Rebuild";
  const intro = s.state === "none"
    ? `<p class="muted" style="margin:0">Turns the photos into a surface in millimetres. It runs on this computer and takes several minutes; the page updates as it goes.</p>`
    : "";
  return `<section class="card">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
      <div><h2 style="margin:0;font-size:1.2rem">${running ? "Building…" : s.state === "done" ? "Model built" : s.state === "failed" ? "Build failed" : "Not built yet"}</h2>
        ${running ? `<p class="hint" style="margin:4px 0 0">${s.elapsed_s ?? 0} s so far</p>` : s.seconds ? `<p class="hint" style="margin:4px 0 0">took ${Math.round(s.seconds)} s</p>` : ""}</div>
      ${running ? "" : `<button class="btn ${s.state === "done" ? "secondary" : ""}" id="btn-build">${label}</button>`}
    </div>
    ${intro}
    ${s.state !== "none" ? stepsHtml(s.stage, s.state) : ""}
    <p class="errors" id="build-error" role="alert"></p>
    ${s.state === "failed" ? `<div class="callout stop"><p><strong>${esc(s.error || "Failed")}</strong></p></div>
      ${s.log_tail ? `<details style="margin-top:10px"><summary>Log</summary><pre class="log">${esc(s.log_tail)}</pre></details>` : ""}` : ""}
  </section>`;
}

function warningsCard(s) {
  if (!s.warnings?.length) return "";
  return `<div class="callout warn" style="margin:0 0 16px"><p><strong>Read before trusting these numbers</strong></p>
    <ul style="margin:6px 0 0;padding-left:20px">${s.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
}

function qualityCard(s) {
  const sc = s.scale || {};
  return `<section class="card"><h2 style="margin:0;font-size:1.2rem">How well it went together</h2>
    <dl class="big">
      <div><dt>Photos placed</dt><dd>${s.sfm?.registered ?? "—"} / ${s.photos ?? "—"}</dd></div>
      <div><dt>Camera fit</dt><dd>${s.sfm?.mean_reprojection_error_px ?? "—"} px<small>average reprojection error</small></dd></div>
      <div><dt>Mat corner fit</dt><dd>${mm(sc.residual_rms_mm)}<small>RMS over ${sc.corners_located ?? "—"} corners</small></dd></div>
      <div><dt>Sheets agree on scale</dt><dd>${sc.sheet_scale_disagreement_pct == null ? "—" : sc.sheet_scale_disagreement_pct.toFixed(3) + " %"}<small>${sc.sheet_scale_disagreement_mm_per_250mm == null ? esc(sc.note || "") : `= ${sc.sheet_scale_disagreement_mm_per_250mm} mm over a 250 mm foot`}</small></dd></div>
      <div><dt>Mat flatness</dt><dd>${mm(sc.mat_flatness_rms_mm)}<small>corner heights, RMS</small></dd></div>
      <div><dt>Surface</dt><dd>${s.mesh?.final_faces?.toLocaleString() ?? "—"}<small>triangles, ${s.mesh?.surface_area_cm2 ?? "—"} cm²</small></dd></div>
    </dl>
    <p class="hint" style="margin:12px 0 0">The sheets are scaled separately, so their disagreement is an independent check on the scale. "Mat corner fit" is per-corner noise, most of which averages out of the scale.</p>
  </section>`;
}

function accuracyCard(s) {
  const a = s.accuracy;
  if (!a) return "";
  const d = a.surface_deviation, b = a.before_smoothing;
  const synthetic = s.synthetic ? `<div class="callout warn" style="margin:12px 0 0"><p><strong>Synthetic capture.</strong> These photos were rendered by the test suite. The numbers test the code, not a phone.</p></div>` : "";
  const rows = a.dimensions.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.model_mm}</td>
      <td>${r.caliper_mm ?? "—"}</td><td>${r.scan_mm ?? "—"}</td>
      <td>${signed(r.scan_minus_reference_mm, 3)}${r.scan_minus_reference_mm == null ? "" : ` <span class="hint">vs ${esc(r.reference)}</span>`}</td></tr>`).join("");
  return `<section class="card"><h2 style="margin:0;font-size:1.2rem">Accuracy: scan vs. the calibration object</h2>
    ${synthetic}
    <dl class="big">
      <div><dt>Median deviation</dt><dd>${mm(d.median_mm)}<small>typical distance from the true surface</small></dd></div>
      <div><dt>95th percentile</dt><dd>${mm(d.p95_mm)}<small>19 in 20 points are closer than this</small></dd></div>
      <div><dt>Signed mean</dt><dd>${signed(d.signed_mean_mm)} mm<small>+ = scan too big, − = too small</small></dd></div>
      <div><dt>Coverage</dt><dd>${(100 * a.completeness.within_1mm).toFixed(1)} %<small>of the surface within 1 mm of the scan</small></dd></div>
    </dl>
    ${b ? `<p class="hint" style="margin:10px 0 0">Before smoothing: median ${mm(b.median_mm)}, 95th percentile ${mm(b.p95_mm)}, signed mean ${signed(b.signed_mean_mm)} mm.</p>` : ""}
    <h3 style="margin:18px 0 0;font-size:1rem">Caliper dimensions</h3>
    <div class="table-scroll"><table class="dims"><thead><tr><th>Dimension</th><th>Model</th><th>Calipers</th><th>Scan</th><th>Scan − reference</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="hint" style="margin:10px 0 0">The surface numbers come after lining the scan up with the model (rotation and shift only, never scaling), which flatters them slightly. The dimensions don't depend on that alignment.</p>
  </section>`;
}

function calipersCard(s) {
  if (meta?.condition !== "calibration") return "";
  const have = s.calipers || {};
  return `<section class="card"><h2 style="margin:0;font-size:1.2rem">Your caliper readings</h2>
    <p class="muted" style="margin:6px 0 0">Measure the printed object (see the Project page for how). With these, the dimensions are compared with the real print instead of the model, so printer error isn't counted as scan error.</p>
    <form id="caliper-form"><div class="calipers">${CALIPERS.map(([k, label, nominal]) => `
      <div class="field"><label for="c-${k}">${esc(label)} <span class="hint">model ${nominal}</span></label>
        <input id="c-${k}" name="${k}" type="number" inputmode="decimal" step="0.01" min="1" max="300" value="${have[k] ?? ""}"></div>`).join("")}
    </div><div class="btn-row"><button class="btn secondary" type="submit">Save readings</button></div>
    <p class="hint" id="caliper-msg" role="status" style="margin:8px 0 0"></p></form>
  </section>`;
}

function profileSvg(profile) {
  if (!profile?.length) return "";
  const W = 640, H = 170, pad = 30;
  const xs = profile.map((p) => p.x_mm), ys = profile.map((p) => p.height_mm);
  const xmax = Math.max(...xs), ymax = Math.max(10, ...ys);
  const X = (x) => pad + (x / xmax) * (W - 2 * pad);
  const Y = (y) => H - pad - (y / ymax) * (H - 2 * pad);
  const line = profile.map((p, i) => `${i ? "L" : "M"}${X(p.x_mm).toFixed(1)},${Y(p.height_mm).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Height of the underside of the inner foot from heel to toe, up to ${ymax.toFixed(1)} millimetres">
    <line x1="${pad}" y1="${Y(0)}" x2="${W - pad}" y2="${Y(0)}" stroke="currentColor" stroke-opacity="0.3"/>
    <path d="${line}" fill="none" stroke="var(--brand)" stroke-width="2.5"/>
    <text x="${pad}" y="${H - 8}" font-size="11" fill="currentColor" opacity="0.6">heel</text>
    <text x="${W - pad}" y="${H - 8}" font-size="11" text-anchor="end" fill="currentColor" opacity="0.6">toes (${Math.round(xmax)} mm)</text>
    <text x="${pad - 6}" y="${Y(ymax) + 4}" font-size="11" text-anchor="end" fill="currentColor" opacity="0.6">${ymax.toFixed(0)}</text>
    <text x="${pad - 6}" y="${Y(0) + 4}" font-size="11" text-anchor="end" fill="currentColor" opacity="0.6">0</text></svg>`;
}

function footCard(s) {
  const p = s.plantar;
  if (!p) return "";
  if (p.skipped) return `<section class="card"><h2 style="margin:0;font-size:1.2rem">Foot frame</h2><p class="muted">${esc(p.skipped)}</p></section>`;
  const hi = p.highest_medial_point;
  return `<section class="card"><h2 style="margin:0;font-size:1.2rem">Underside of the foot <span class="badge warn">provisional frame</span></h2>
    <p class="muted" style="margin:6px 0 0">Oriented from the mat and the footprint's outline. Landmarks (Phase 3) replace this frame, so treat these as a first look, not measurements.</p>
    <dl class="big">
      <div><dt>Footprint length</dt><dd>${mm(p.footprint_length_mm, 1)}</dd></div>
      <div><dt>Footprint width</dt><dd>${mm(p.footprint_width_mm, 1)}</dd></div>
      <div><dt>Highest inner underside</dt><dd>${hi ? mm(hi.height_mm, 1) : "—"}<small>${hi ? `${hi.x_mm} mm from the heel` : ""}</small></dd></div>
    </dl>
    <div class="profile" style="margin-top:14px"><p class="hint" style="margin:0 0 4px">Inner (medial) underside height, heel to toe</p>${profileSvg(s.medial_profile)}</div>
  </section>`;
}

function landmarksCard(s) {
  const isFoot = capture ? !!meta?.foot : true;
  if (!isFoot) return "";
  const href = `/studio/landmarks.html?${capture ? `capture=${encodeURIComponent(capture)}` : `submission=${encodeURIComponent(submission)}&scan=${encodeURIComponent(scanKey)}`}`;
  return `<section class="card"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
    <div><h2 style="margin:0;font-size:1.2rem">Landmarks</h2><p class="muted" style="margin:4px 0 0">Click the skin markers on the model to get the measurements.</p></div>
    <a class="btn" href="${href}">Open landmarks</a></div></section>`;
}

function filesCard(s) {
  if (!s.files?.length) return "";
  const NAMES = { "mesh.ply": "Surface (final)", "mesh_raw.ply": "Surface (before smoothing)", "mesh_foot.ply": "Surface in foot frame",
    "plantar.ply": "Underside only", "points.ply": "Point cloud", "report.json": "Full report", "accuracy.json": "Accuracy details", "plantar.json": "Foot frame details" };
  return `<section class="card"><h2 style="margin:0 0 10px;font-size:1.2rem">Files</h2>
    <div class="files">${s.files.map((f) => `<a class="btn secondary" href="${api}/${f}">${esc(NAMES[f] || f)}</a>`).join("")}</div>
    <p class="hint" style="margin:10px 0 0">Millimetres. PLY opens in MeshLab, Blender, or most slicers.</p></section>`;
}

// A scan that arrived as a 3-D model (the iPhone app, or Import a 3D scan) has no photos to build from: what the
// studio read from it, and where to go next, instead of a Build button the studio would refuse.
function importedCard(c) {
  const m = c.mesh;
  const id = encodeURIComponent(capture);
  if (!m) {
    $("root").innerHTML = `<section class="card"><h2 style="margin:0;font-size:1.2rem">No model yet</h2>
      <p class="muted" style="margin:8px 0 0">This capture was started for a 3-D model that hasn't arrived. Send it again from the
      iPhone app, or use <a href="/studio/import.html">Import a 3D scan</a>.</p></section>`;
    return;
  }
  const units = m.units_detected === "m" ? "metres" : m.units_detected === "cm" ? "centimetres" : "millimetres";
  $("root").innerHTML = `<section class="card"><h2 style="margin:0;font-size:1.2rem">Arrived as a 3-D model</h2>
    <p class="muted" style="margin:8px 0 0">It came from the iPhone app or an imported file, so there are no photos to
      build from: the model as sent is what the studio uses. ${c.foot ? "Landmarks and Make insole work from it." : ""}</p>
    <dl class="big">
      <div><dt>Size</dt><dd>${m.extents_mm.map((v) => esc(v)).join(" × ")} mm<small>longest side first</small></dd></div>
      <div><dt>Surface</dt><dd>${Number(m.faces).toLocaleString()} faces<small>${m.watertight ? "closed" : "open"}, ${Number(m.vertices).toLocaleString()} points</small></dd></div>
      <div><dt>Units in the file</dt><dd>${esc(units)}<small>scaled by ${esc(m.scale_to_mm)} to mm</small></dd></div>
    </dl>
    <p class="btn-row" style="margin:14px 0 0">
      <a class="btn secondary" href="/api/captures/${id}/mesh.ply" download>Download the model (PLY, mm)</a>
      ${c.foot ? `<a class="btn secondary" href="/studio/landmarks.html?capture=${id}">Landmarks</a>` : ""}
      <a class="btn secondary" href="/studio/captures.html#${esc(capture)}">Its card in the library</a>
    </p></section>${c.condition === "calibration" ? `<div id="imported-accuracy"></div>` : ""}`;
  if (c.condition === "calibration") importedAccuracy(c);
}

// An imported calibration object: what the studio measured against the object's true shape, and the caliper
// readings that make the comparison with the real print (re-scored at once: an imported model needs no build)
async function importedAccuracy(c) {
  const [, s] = await ask(api);  // the saved caliper readings come with the build's status
  const a = c.accuracy;
  const signedMm = (v) => (v == null ? "not measured" : `${signed(v)} mm`);
  const figures = !a ? `<p class="muted" style="margin:8px 0 0">Not measured yet.</p>`
    : a.error ? `<div class="callout warn" style="margin:10px 0 0"><p>${esc(a.error)}</p></div>`
    : `<p class="hint" style="margin:6px 0 0">Lengths compared with the ${a.reference === "calipers" ? "caliper readings of the print" : "object's design (add caliper readings for a fairer comparison)"}.</p>
      <dl class="big">
        <div><dt>Surface, typical error</dt><dd>${esc(a.median_mm)} mm</dd></div>
        <div><dt>Surface, worst 5%</dt><dd>${esc(a.p95_mm)} mm</dd></div>
        <div><dt>Length</dt><dd>${esc(signedMm(a.length_mm))}</dd></div>
        <div><dt>Width</dt><dd>${esc(signedMm(a.width_mm))}</dd></div>
        <div><dt>Dome top height</dt><dd>${esc(signedMm(a.dome_apex_mm))}</dd></div>
      </dl>
      ${(a.warnings || []).length ? `<ul class="checklist" style="margin:10px 0 0;color:var(--warn)">${a.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <p class="hint" style="margin:8px 0 0"><a href="${base}/accuracy">Full accuracy report</a></p>`;
  $("imported-accuracy").innerHTML = `<section class="card"><h2 style="margin:0;font-size:1.2rem">Against the object's true shape</h2>${figures}</section>`
    + calipersCard(s && !s.error ? s : {});
  $("caliper-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    $("caliper-msg").textContent = "Re-scoring…";
    const [ok, out] = await ask(`${base}/calipers`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!ok) { $("caliper-msg").textContent = out.error || "Couldn't save."; return; }
    c.accuracy = out.accuracy;
    await importedAccuracy(c);
    $("caliper-msg").textContent = "Saved. The figures above now use your readings.";
  });
}

function render(s) {
  $("root").innerHTML = buildCard(s) + (s.state === "done" ? warningsCard(s) + accuracyCard(s) + calipersCard(s) +
    landmarksCard(s) + footCard(s) + qualityCard(s) + filesCard(s) : calipersCard(s));
  $("btn-build")?.addEventListener("click", build);
  $("caliper-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    const [ok, out] = await ask(`${base}/calipers`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!ok) { $("caliper-msg").textContent = out.error || "Couldn't save."; return; }
    $("caliper-msg").textContent = out.updating ? "Saved. Updating the comparison…" : "Saved. Build the model to compare against them.";
    if (out.updating) setTimeout(refresh, 800);
  });
}

init();
