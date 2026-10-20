// Studio research capture (Phase 0): condition + session metadata, full
// quality readouts, frame review, save to the research library.
import { CoverageMap } from "./coverage-map.js";
import { Scanner, cameraErrorMessage, loadBoards, requestMotionPermission } from "./scanner.js";
import { createStageView } from "./stage-view.js";
import { renderSteer, wireSoundToggle } from "./scan-ui.js";

const TARGET_FRAMES = 60;
const CONDITION_LABELS = {
  nwb: "Non-weight-bearing (neutral)",
  nwb_relaxed: "Non-weight-bearing (relaxed)",
  swb: "Semi-weight-bearing",
  fwb: "Full weight-bearing",
  object: "Object (scanner test)",
  calibration: "Calibration object",
};
const NOT_A_FOOT = ["object", "calibration"];

const $ = (id) => document.getElementById(id);
const views = { setup: $("setup-view"), live: $("live-view"), review: $("review-view") };
function show(name) {
  for (const [k, el] of Object.entries(views)) el.hidden = k !== name;
  window.scrollTo({ top: 0 });
}

let setup = null;
let scanner = null;
let saving = false;
let saved = false;

// For the iPhone app's Done button: is there anything here that closing would lose?
window.footscanCaptureState = () => ({
  uploading: saving,
  unsaved: !saved && (!views.live.hidden || !views.review.hidden) ? (scanner?.frames.length || 0) : 0,
});
let stageView = null;
const isObject = () => NOT_A_FOOT.includes(form.condition.value);

// ---- setup -----------------------------------------------------------------
const form = $("setup-form");
let submitter = "camera";
form.querySelectorAll("button[type=submit]").forEach((b) =>
  b.addEventListener("click", () => (submitter = b.dataset.source)));

function syncSetup() {
  const cond = form.condition.value;
  const loaded = cond === "swb" || cond === "fwb";
  $("load-field").hidden = !loaded;
  $("foot-row").hidden = NOT_A_FOOT.includes(cond);
  $("object-note").hidden = cond !== "object";
  document.querySelectorAll("#checklist [data-cond]").forEach((li) => {
    li.hidden = li.dataset.cond === "nwb" ? cond !== "nwb" : !loaded;
  });
}
form.addEventListener("change", syncSetup);

// Opened from the iPhone app (?condition=swb&foot=right&session=PHOTO&from=app): pre-choose
// what's being scanned, so the person only adds what the app can't know (the scale reading).
{
  const q = new URLSearchParams(location.search);
  const pick = (name, value) => {
    const box = value && form.querySelector(`input[name="${name}"][value="${CSS.escape(value)}"]`);
    if (box) box.checked = true;
  };
  pick("condition", q.get("condition"));
  pick("foot", q.get("foot"));
  if (q.get("from") === "app") $("phone-hint").hidden = true; // already on the phone, inside the app
  const session = q.get("session");
  if (session && /^[A-Za-z0-9_-]{1,20}$/.test(session)) form.session.value = session;
}
syncSetup();

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  setup = {
    foot: isObject() ? null : form.foot.value,
    condition: form.condition.value,
    session: form.session.value.trim(),
    load_kg: form.load_kg.value === "" ? null : Number(form.load_kg.value),
    method: form.method.value,
    notes: form.notes.value.trim(),
  };
  const errors = [];
  if (!setup.condition) errors.push("Choose which condition this scan is.");
  if (!/^[A-Za-z0-9_-]{1,20}$/.test(setup.session)) errors.push("Session: letters, numbers, - or _ only.");
  if ((setup.condition === "swb" || setup.condition === "fwb") && !(setup.load_kg > 0))
    errors.push("Enter the scale reading for a weight-bearing capture.");
  $("setup-errors").textContent = errors.join(" ");
  if (errors.length) return;
  await requestMotionPermission();
  startLive(submitter === "sim");
});

// ---- live ------------------------------------------------------------------
function setChip(id, state, text) {
  const el = $(id);
  el.className = `chip ${state}`;
  el.lastChild.textContent = text;
}

async function startLive(simulated) {
  $("live-title").textContent = setup.foot
    ? `${CONDITION_LABELS[setup.condition]} · ${setup.foot} foot`
    : CONDITION_LABELS[setup.condition];
  $("live-eyebrow").textContent = `Session ${setup.session}`;
  $("sim-ribbon").hidden = !simulated;
  $("btn-start").hidden = false;
  $("btn-pause").hidden = true;
  const map = new CoverageMap($("map"), setup.foot);
  const boards = await loadBoards();
  const needsMat = setup.condition !== "object";

  scanner = new Scanner({
    stage: $("stage"), simulated, targetFrames: TARGET_FRAMES, boards, requireMat: needsMat, foot: setup.foot,
    onFrame: () => {
      $("flash").classList.add("on");
      requestAnimationFrame(() => $("flash").classList.remove("on"));
    },
    onUpdate: (s) => {
      setChip("chip-sharp", s.sharp.ok ? "ok" : "bad", s.sharp.ok ? "Sharp" : "Blurry");
      setChip("chip-exposure", s.exposure.ok ? "ok" : "bad",
        s.exposure.ok ? "Exposure OK" : s.exposure.issue === "overexposed" ? "Too bright" : "Too dark");
      setChip("chip-mat", s.matVisible ? "ok" : needsMat ? "bad" : "idle",
        s.matVisible ? `Mat: ${s.matMarkers} markers` : needsMat ? "Mat not in view" : "No mat (object scan)");
      const VIEW = { mat: "Position: from mat", sensors_aligned: "Position: sensors (mat-aligned)", sensors: "Position: sensors only" };
      setChip("chip-sensor", s.viewSource === "mat" ? "ok" : s.hasView ? "idle" : "bad", VIEW[s.viewSource] || "Position unknown");
      $("frames-label").textContent = `${s.kept} / ${TARGET_FRAMES}`;
      $("frames-bar").style.width = `${Math.min(100, (100 * s.kept) / TARGET_FRAMES)}%`;
      // completeness is null until a kept photo has a known angle: 0% if angles are coming, "no sensor" if not
      $("coverage-label").textContent = s.completeness == null ? (s.hasView ? "0%" : "no sensor") : `${Math.round(100 * s.completeness)}%`;
      $("coverage-bar").style.width = `${s.completeness == null ? 0 : 100 * s.completeness}%`;
      $("stat-kept").textContent = s.kept;
      $("stat-blur").textContent = scanner.rejected.blur;
      $("stat-exposure").textContent = scanner.rejected.exposure;
      $("map-note").textContent = { mat: "measured from mat", sensors_aligned: "sensors, mat-aligned", sensors: "approx. from sensors" }[s.viewSource] || "unavailable";
      map.update({ coverage: scanner.coverage, view: scanner.view, next: s.next, hasSensor: s.hasView, active: scanner.capturing });
      renderSteer(s, scanner);
      $("guidance").textContent = s.guidance.text;
      $("guidance").className = `guidance ${s.guidance.tone}`;
      // Finish only once every angle has photos (not on a photo count: they could all be from one side)
      $("btn-finish").disabled = !s.covered;
      $("btn-finish").textContent = s.covered ? "Finish & review" : "Cover every side first";
      $("btn-finish").className = s.done ? "btn accent" : "btn secondary";
    },
  });
  show("live");
  wireSoundToggle(scanner);
  try {
    await scanner.open();
    stageView ??= createStageView($("stage"), $("capture-controls"),
      { docked: [$("sim-ribbon"), $("guidance")] });
    stageView.full();
  } catch (err) {
    scanner = null;
    show("setup");
    $("setup-errors").textContent = `${cameraErrorMessage(err)} You can still try the simulated camera.`;
  }
}

$("btn-start").addEventListener("click", () => {
  scanner.start();
  $("btn-start").hidden = true;
  $("btn-pause").hidden = false;
  $("btn-pause").textContent = "Pause";
});

$("btn-pause").addEventListener("click", () => {
  scanner.capturing ? scanner.pause() : scanner.resume();
  $("btn-pause").textContent = scanner.capturing ? "Pause" : "Resume";
});

$("btn-cancel").addEventListener("click", () => {
  if (scanner?.frames.length && !confirm(`Discard ${scanner.frames.length} captured frames?`)) return;
  discard();
});

$("btn-finish").addEventListener("click", () => {
  scanner.hold();
  stageView?.inline();
  renderReview();
  show("review");
});


// ---- review + save -----------------------------------------------------------
function renderReview() {
  const kept = scanner.keptFrames();
  const cov = scanner.recount();
  const noSensor = !kept.some((f) => f.view);
  const stat = (label, value, hint = "") =>
    `<div class="card"><div class="hint">${label}</div><div class="mono" style="font-size:1.6rem;font-weight:700">${value}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
  $("review-stats").innerHTML =
    stat("Frames kept", kept.length, `target ${TARGET_FRAMES}`) +
    stat("Angles covered", noSensor ? "—" : `${Math.round(100 * cov.completeness())}%`, noSensor ? "no motion sensors" : "approximate") +
    stat("Rejected", scanner.rejected.blur + scanner.rejected.exposure + scanner.rejected.no_mat,
      `${scanner.rejected.blur} blur · ${scanner.rejected.exposure} exposure · ${scanner.rejected.no_mat} no mat`) +
    stat("With mat", `${kept.filter((f) => f.mat).length}`, scanner.focalHint ? `focal ≈ ${Math.round(scanner.focalHint)} px` : "") +
    stat("Duration", `${Math.round(scanner.elapsedMs / 1000)} s`);

  $("sim-save-note").hidden = !scanner.simulated;
  $("btn-save").disabled = scanner.simulated || kept.length === 0;
  $("upload").hidden = true;

  const thumbs = $("thumbs");
  thumbs.innerHTML = "";
  for (const f of scanner.frames) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `thumb${f.excluded ? " excluded" : ""}`;
    b.setAttribute("aria-pressed", String(f.excluded));
    b.setAttribute("aria-label", `Frame ${f.n}${f.excluded ? ", excluded" : ""}`);
    b.innerHTML = `<img alt="" loading="lazy"><span>#${f.n} · ${(f.relative * 100).toFixed(0)}%</span>`;
    const setSrc = () => (f.url ? (b.firstChild.src = f.url) : setTimeout(setSrc, 100));
    setSrc();
    b.addEventListener("click", () => { f.excluded = !f.excluded; renderReview(); });
    thumbs.append(b);
  }
}

$("btn-more").addEventListener("click", () => {
  show("live");
  scanner.resumeLoop();
  stageView?.full();
});

$("btn-discard").addEventListener("click", () => {
  if (scanner.frames.length && !confirm("Discard this capture?")) return;
  discard();
});

function discard() {
  stageView?.inline();
  scanner?.close();
  scanner?.frames.forEach((f) => f.url && URL.revokeObjectURL(f.url));
  scanner = null;
  show("setup");
}

$("btn-save").addEventListener("click", async () => {
  if (scanner.simulated) return;
  const btns = ["btn-save", "btn-more", "btn-discard"].map($);
  btns.forEach((b) => (b.disabled = true));
  saving = true;
  $("upload").hidden = false;
  await scanner.ready();
  const kept = scanner.keptFrames();
  const setProgress = (i, label) => {
    $("upload-label").textContent = label;
    $("upload-count").textContent = `${i} / ${kept.length}`;
    $("upload-bar").style.width = `${(100 * i) / kept.length}%`;
  };
  try {
    const res = await fetch("/api/captures", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...setup, device: navigator.userAgent }),
    });
    const created = await res.json();
    if (!res.ok) throw new Error(created.error);
    for (let i = 0; i < kept.length; i++) {
      setProgress(i, "Uploading frames…");
      const r = await fetch(`/api/captures/${created.id}/frames/${i + 1}`, {
        method: "PUT", headers: { "Content-Type": "image/jpeg" }, body: kept[i].blob,
      });
      if (!r.ok) throw new Error((await r.json()).error);
    }
    const done = await fetch(`/api/captures/${created.id}/complete`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames: scanner.frameRecords(), summary: scanner.summary() }),
    });
    if (!done.ok) throw new Error((await done.json()).error);
    setProgress(kept.length, "Saved.");
    saved = true;
    scanner.close();
    setTimeout(() => (location.href = `/studio/captures.html#${created.id}`), 600);
  } catch (err) {
    $("upload-label").textContent = `Upload failed: ${err.message}`;
    btns.forEach((b) => (b.disabled = false));
  } finally {
    saving = false;
  }
});
