// Studio: Import a 3D scan (import.html), the iPhone app's connect code, and the calibration object's accuracy.
import { ask, esc, sendWithProgress } from "/assets/studio.js";
const $ = (id) => document.getElementById(id);
let file = null;
const MAX_MODEL_BYTES = 150 * 1024 * 1024; // the studio's own limit (server.MAX_MESH_BYTES): refused before it's sent

// "condition:kind" for the scans that show the sole (sole up, foam print); plain condition otherwise
const NOT_A_FOOT = new Set(["object", "calibration", "shoe_insole"]);
const choice = () => { const [cond, kind] = $("condition").value.split(":"); return { cond, kind: kind || "foot" }; };

function sync() {
  const { cond: c, kind } = choice();
  $("foot-field").hidden = NOT_A_FOOT.has(c);
  $("up-field").hidden = c !== "calibration" && c !== "shoe_insole";
  $("load-field").hidden = (c !== "swb" && c !== "fwb") || kind === "impression";
}
$("condition").addEventListener("change", sync);
sync();

function pick(f) {
  file = f;
  $("drop-title").textContent = f ? f.name : "Choose a 3D file";
  $("drop-hint").textContent = f ? `${(f.size / 1048576).toFixed(1)} MB` : "OBJ, PLY, STL, GLB or OFF · up to 150 MB";
}
$("file").addEventListener("change", (e) => pick(e.target.files[0]));
const drop = $("drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); pick(e.dataTransfer.files[0]); });

// The connect code for the iPhone app: footscan-capture://connect?url=…&key=…&fp=…[&alt=…]
$("btn-pair").addEventListener("click", async () => {
  if (!$("pair").hidden) {
    $("pair").hidden = true; $("pair-msg").textContent = ""; // the note goes with the code
    $("btn-pair").textContent = "Show the connect code"; return;
  }
  $("pair-msg").textContent = "";
  try {
    const [ok, p] = await ask("/api/studio/pairing");
    if (!ok) throw new Error(p.error || "couldn't ask the studio");
    if (!p.available) { $("pair-msg").textContent = p.reason; return; }
    const q = new URLSearchParams({ url: p.url, key: p.key });
    if (p.fingerprint) q.set("fp", p.fingerprint);
    for (const alt of p.alt_urls || []) q.append("alt", alt);  // e.g. its Tailscale address, for away from home
    const code = qrcode(0, "M");
    code.addData(`footscan-capture://connect?${q}`);
    code.make();
    $("pair-qr").innerHTML = code.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
    $("pair").hidden = false;
    $("pair-msg").textContent = p.note || ""; // a public studio: which builds of the app can use it
    $("btn-pair").textContent = "Hide the code";
  } catch (err) {
    $("pair-msg").textContent = `Couldn't make the code: ${err.message}`;
  }
});

const CALIPERS = [
  ["length", "Overall length", 150], ["width", "Overall width", 70], ["base", "Base thickness", 10],
  ["dome_apex", "Dome top height", 30], ["terrace_high", "High terrace height", 35], ["terrace_low", "Low terrace height", 22],
];
$("calipers").innerHTML = CALIPERS.map(([k, label, nominal]) => `
  <div class="field"><label for="c-${k}">${esc(label)} <span class="hint">model ${nominal}</span></label>
    <input id="c-${k}" name="${k}" type="number" inputmode="decimal" step="0.01" min="1" max="300"></div>`).join("");
let importedId = null;
$("caliper-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  $("caliper-msg").textContent = "Re-scoring…";
  const [ok, out] = await ask(`/api/captures/${encodeURIComponent(importedId)}/calipers`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!ok) { $("caliper-msg").textContent = out.error || "Couldn't save."; return; }
  showAccuracy(out.accuracy, importedId);
  $("caliper-msg").textContent = "Saved. The numbers above now use your readings.";
});

// What the scan measured against the object's true shape (imported calibration object only).
function showAccuracy(a, id) {
  importedId = id;
  $("acc").hidden = !a;
  $("caliper-form").hidden = !a || !!a.error;
  if (!a) return;
  if (a.error) {
    $("acc-ref").textContent = "";
    $("acc-facts").innerHTML = "";
    $("acc-warn").innerHTML = `<li>${esc(a.error)}</li>`;
    $("acc-json").parentElement.hidden = true;
    return;
  }
  const mm = (v) => (v == null ? "not measured" : `${v > 0 ? "+" : ""}${Number(v).toFixed(2)} mm`);
  $("acc-ref").textContent = `Lengths compared with the ${a.reference === "calipers" ? "caliper readings of the print" : "object's design (add caliper readings for a fairer comparison)"}. ${a.floor.charAt(0).toUpperCase()}${a.floor.slice(1)}.`;
  $("acc-facts").innerHTML = [
    ["Surface, typical error", `${a.median_mm} mm`], ["Surface, worst 5%", `${a.p95_mm} mm`],
    ["Too big (+) or small (−) on average", mm(a.signed_mean_mm)], ["Object captured within 1 mm", `${Math.round(100 * a.within_1mm)}%`],
    ["Length", mm(a.length_mm)], ["Width", mm(a.width_mm)], ["Dome top height", mm(a.dome_apex_mm)],
  ].map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");
  $("acc-warn").innerHTML = (a.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
  $("acc-json").href = `/api/captures/${encodeURIComponent(id)}/accuracy`;
  $("acc-json").parentElement.hidden = false;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ext = file?.name.split(".").pop().toLowerCase();
  const { cond, kind } = choice();
  const errors = [];
  if (!file) errors.push("Choose a 3D file first.");
  else if (!["obj", "ply", "stl", "glb", "gltf", "off"].includes(ext)) errors.push("That file type can't be read. Export as OBJ or PLY.");
  else if (file.size > MAX_MODEL_BYTES) errors.push(`That file is ${(file.size / 1048576).toFixed(0)} MB; the studio takes up to 150 MB. Export it with fewer faces (a lower detail level) and try again.`);
  else if (!file.size) errors.push("That file is empty.");
  if ((cond === "swb" || cond === "fwb") && kind === "foot" && !$("load").value) errors.push("Enter the scale reading for a loaded scan.");
  $("errors").textContent = errors.join(" ");
  $("retake").hidden = true;
  if (errors.length) return;

  const btn = $("btn-import");
  btn.disabled = true;
  btn.textContent = cond === "calibration" ? "Importing and measuring…" : "Importing…";
  try {
    const [made, created] = await ask("/api/captures", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        condition: cond, foot: NOT_A_FOOT.has(cond) ? null : $("foot").value, session: $("session").value.trim(),
        load_kg: kind === "impression" ? null : $("load").value || null, method: "imported_mesh", notes: $("notes").value,
        ...(NOT_A_FOOT.has(cond) ? {} : { scan_kind: kind }),
      }),
    });
    if (!made) throw new Error(created.error);
    // how much has gone up, then what the studio is doing with it (a sole scan is checked on arrival)
    btn.textContent = "Sending the model…";
    const [sent, data] = await sendWithProgress(`/api/captures/${created.id}/mesh?ext=${ext}&up=${$("up").value}`, {
      method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file,
    }, (part) => { btn.textContent = `Sending the model… ${Math.round(100 * part)}%`; },
    () => { btn.textContent = cond === "calibration" ? "Measuring it against the object…" : "The studio is reading and checking it…"; });
    if (!sent) throw Object.assign(new Error(data.error), { retake: data.retake });
    const m = data.mesh;
    $("facts").innerHTML = [
      ["Length", `${m.extents_mm[0]} mm`], ["Width", `${m.extents_mm[1]} mm`], ["Height", `${m.extents_mm[2]} mm`],
      ["Vertices", m.vertices.toLocaleString()], ["Faces", m.faces.toLocaleString()], ["Closed surface", m.watertight ? "yes" : "no"],
    ].map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");
    $("units-note").textContent = `The file looked like it was in ${m.units_detected === "m" ? "metres" : m.units_detected === "cm" ? "centimetres" : "millimetres"}, `
      + `so it was scaled by ${m.scale_to_mm} to millimetres. `
      + (cond === "calibration" ? "The calibration object is 150 × 70 mm." : "A foot is usually 220–320 mm long: if the length above is far off, the units guess was wrong.");
    showAccuracy(data.accuracy, created.id);
    $("to-library").href = `/studio/captures.html#${created.id}`;
    $("result").hidden = false;
    $("result").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    $("errors").textContent = `Import failed: ${err.message}`;
    // a sole scan refused for a missing part: what to change on the next scan, step by step
    $("retake").hidden = !err.retake?.length;
    $("retake").innerHTML = (err.retake || []).map(a => `<h3>${esc(a.title)}. Next time:</h3>`
      + `<ol>${a.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol>`).join("");
  } finally {
    btn.disabled = false;
    btn.textContent = "Import";
  }
});

$("import-another").addEventListener("click", () => location.reload());
