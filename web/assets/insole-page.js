// Studio: the first-fit insole in 3-D, coloured by how much it fills under the foot, with the
// scanned sole it was made from. Every number here comes from the insole's own report.
// Not a medical device: first fit, no posting, walking-only until a clinician signs the sheet.
import { MeshViewer } from "./mesh-viewer.js";
import { mergeMeshes, parseViewerBin } from "./viewer-math.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const capture = new URLSearchParams(location.search).get("capture");
const base = `/api/captures/${encodeURIComponent(capture || "")}/insole/`;
// The same stops as insole.FILL_RAMP (light where flat, deep teal at the 20 mm arch cap).
const RAMP = "linear-gradient(90deg, rgb(237,230,214), rgb(95,194,182), rgb(14,79,74))";

let viewer, insoleMesh, soleMesh, report;
const state = { sole: true, lift: 15 };

async function bin(name) {
  const r = await fetch(base + name);
  if (!r.ok) throw new Error(r.status === 409 ? "this insole no longer matches its scan: make it again" : `${name}: ${r.status}`);
  return parseViewerBin(await r.arrayBuffer());
}

function show(keepView) {
  const mesh = state.sole && soleMesh ? mergeMeshes(insoleMesh, soleMesh, state.lift) : insoleMesh;
  viewer.load(mesh, { keepView });
}

function views() {
  // the insole's frame: x forward from the heel, y toward the foot's left, z up
  const inner = report.foot === "right" ? 1 : -1;
  return [
    ["Inner side", [0, inner, 0.12]],  // the arch: the sole's curve above the insole's
    ["From above", [0, 0, 1]],
    ["Outer side", [0, -inner, 0.25]],
    ["From the heel", [-1, 0, 0.35]],
    ["Underneath", [0, 0, -1]],
  ];
}

async function init() {
  if (!capture) {
    $("root").innerHTML = `<p class="muted">No capture given.</p>`;
    return;
  }
  $("back").innerHTML = `Research capture <a class="mono" href="/studio/captures.html#${esc(capture)}">${esc(capture)}</a>`;
  try {
    report = await fetch(base + "insole.json").then((r) => {
      if (!r.ok) throw new Error(r.status === 409 ? "this insole no longer matches its scan: make it again" : `no insole yet (${r.status})`);
      return r.json();
    });
    insoleMesh = await bin("preview-insole.bin");
    soleMesh = await bin("preview-sole.bin").catch(() => null);
  } catch (err) {
    $("root").innerHTML = `<p class="hint" style="color:var(--warn)">Couldn't show it: ${esc(err.message)}.
      Make the insole from the <a href="/studio/captures.html#${esc(capture)}">research library</a> first.</p>`;
    return;
  }
  $("title").textContent = `${report.foot === "left" ? "Left" : "Right"} first-fit insole`;
  const warn = (report.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
  $("root").innerHTML = `
    <section class="card">
      <div class="stage"><canvas id="canvas" aria-label="3-D view of the insole; drag to turn, scroll or pinch to zoom"></canvas></div>
      <div class="views" id="views"></div>
      <div class="controls">
        <label><input type="checkbox" id="sole" ${soleMesh ? "checked" : "disabled"}> Show the scanned sole</label>
        <label>Lift the sole <input type="range" id="lift" min="0" max="40" step="1" value="${state.lift}" ${soleMesh ? "" : "disabled"}>
          <output id="lift-out" class="mono">${state.lift} mm</output></label>
      </div>
      <p class="hint-key">Drag to turn, scroll or pinch to zoom, two fingers or right-drag to slide. The sole is the
        scan as the insole was made from it: the insole's top sits ${report.params?.relief_mm ?? 1} mm below it. For the
        fill colours alone, look from above with the sole hidden.</p>
      <div class="legend">
        <div class="bar" style="background:${RAMP}"></div>
        <div class="ticks"><span>no fill</span><span>10 mm</span><span>20 mm (the arch cap)</span></div>
        <p class="hint-key" style="margin-top:4px">Colour: how high the insole's top rises above its base, to meet the sole.</p>
      </div>
      <dl class="big">
        <div><dt>Length × width</dt><dd>${report.length_mm} × ${report.width_mm} mm</dd></div>
        <div><dt>Highest fill</dt><dd>${report.max_fill_mm} mm</dd></div>
        <div><dt>Sole seen</dt><dd>${Math.round(100 * report.sole.seen)}%</dd></div>
        <div><dt>On the bed</dt><dd>${esc(report.bed_fit.how)}</dd></div>
      </dl>
      ${warn ? `<ul class="checklist" style="margin:12px 0 0;color:var(--warn)">${warn}</ul>` : ""}
      <p class="btn-row" style="margin:14px 0 0">
        <a class="btn" href="${base}insole.3mf">3MF for Bambu Studio</a>
        <a class="btn secondary" href="${base}summary.html" target="_blank" rel="noopener">Summary sheet</a></p>
      <p class="hint" style="margin:10px 0 0">Not a medical device. First fit, no posting. Walking-only break-in;
        no sport until a podiatrist or athletic trainer has signed the summary sheet.</p>
    </section>`;
  try {
    viewer = new MeshViewer($("canvas"));
  } catch (err) {
    $("canvas").replaceWith(Object.assign(document.createElement("p"), { className: "hint", textContent: err.message }));
    return;
  }
  // Seen from above, toes up the screen and (for either foot) as you'd look down at it: the
  // insole's x (heel to toe) is "north", its -y (the foot's right) "east".
  viewer.setBasis({ east: [0, -1, 0], north: [1, 0, 0], up: [0, 0, 1] });
  show(false);
  viewer.lookFrom(views()[0][1]);
  $("views").innerHTML = views().map(([label], i) => `<button class="btn secondary" data-view="${i}">${label}</button>`).join("");
  $("views").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) viewer.lookFrom(views()[Number(b.dataset.view)][1]);
  });
  $("sole").addEventListener("change", (e) => {
    state.sole = e.target.checked;
    $("lift").disabled = !state.sole;
    show(true);
  });
  $("lift").addEventListener("input", (e) => {
    state.lift = Number(e.target.value);
    $("lift-out").textContent = `${state.lift} mm`;
    show(true);
  });
}

init();
