// Customer flow: about you -> survey -> scan plan -> (setup -> scan -> save) per planned scan -> send.
// The survey questions and the scan plan both come from the server
// (src/footscan/survey.py), so this file only renders them.
import { readCheckBar } from "./mat-check.js";
import { Scanner, cameraErrorMessage, loadBoards, requestMotionPermission } from "./scanner.js";
import { createStageView } from "./stage-view.js";
import { renderSteer, wireSoundToggle } from "./scan-ui.js";
import { DIAGRAM_CSS, matDiagram, phonePathDiagram } from "./diagrams.js";
import { unlockAudio } from "./cues.js";
import * as fx from "./fx.js";
import { animatePathDiagram, mountScene } from "./scene.js";
import { assembleMat, heroParallax } from "./interact.js";
import { mountRuler } from "./ruler.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const MIN_FRAMES = 20;
let matTolerance = null;
// ?demo=1 shows a simulated camera for trying the flow on a laptop. Demo mode
// never creates a submission or uploads anything.
const DEMO = new URLSearchParams(location.search).has("demo");

$("map-css").textContent = DIAGRAM_CSS;
$("mat-diagram").innerHTML = matDiagram();
$("path-diagram").innerHTML = phonePathDiagram();
mountScene($("hero-scene"));
heroParallax($("hero-scene"), document.querySelector(".hero-copy"));
animatePathDiagram($("path-diagram"));
fx.updateSteps($("steps"), 0); // first step: you

const flow = {
  name: "", feet: [], acks: {},
  sections: null, sectionIndex: 0, answers: {},
  evaluation: null,       // {flags, plan}
  submission: null,       // {id, upload_token}
  scanIndex: 0,
  results: {},            // scan key -> photo count
  scanner: null,
  stageView: null,
  rescan: false,          // true when following a "please scan again" link
};
const currentScan = () => flow.evaluation.plan[flow.scanIndex];

// Views in the order a person meets them, so moving between them can slide
// the right way: forward comes in from the right, back from the left.
const VIEW_ORDER = ["about", "survey", "stopped", "plan", "setup", "scan", "saving", "send", "done"];
let currentView = "about";

function show(view, step, dir) {
  const from = currentView;
  currentView = view;
  for (const el of document.querySelectorAll("main > .view")) el.hidden = el.id !== `v-${view}`;
  const order = ["about", "survey", "scan", "send"];
  fx.updateSteps($("steps"), order.indexOf(step));
  window.scrollTo({ top: 0 });
  // The camera view is left alone: it starts the scanner straight away.
  if (view === "scan") return;
  const d = dir ?? Math.sign(VIEW_ORDER.indexOf(view) - VIEW_ORDER.indexOf(from));
  fx.enterView($(`v-${view}`), d);
  // Scroll effects re-measure (the page may not scroll at all to tell them).
  document.dispatchEvent(new Event("fx:view"));
}

async function api(path, { method = "POST", json, body, headers = {} } = {}) {
  const h = { ...headers };
  if (flow.submission) h["X-Upload-Token"] = flow.submission.upload_token;
  if (json) h["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, { method, headers: h, body: json ? JSON.stringify(json) : body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || `request failed (${res.status})`), { status: res.status, data });
  return data;
}

// =========================================================================
// 1. About you
// =========================================================================
const ACK_KEYS = ["not_medical_device", "clinician_review", "break_in", "photo_consent"];
let aboutReady = false;
function syncAbout() {
  const f = $("about-form");
  const ticked = ACK_KEYS.filter((k) => f[k].checked).length;
  fx.countTo($("ack-count").querySelector("b"), ticked, { duration: 0.3 });
  $("ack-count").classList.toggle("all", ticked === ACK_KEYS.length);
  const ready = ticked === ACK_KEYS.length && $("name").value.trim() !== "";
  $("btn-about").classList.toggle("ready", ready);
  if (ready && !aboutReady) fx.bounce($("btn-about"), { scale: 1.06 });
  aboutReady = ready;
}
$("about-form").addEventListener("input", syncAbout);
$("about-form").addEventListener("change", syncAbout);
$("about-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  flow.name = $("name").value.trim();
  flow.feet = f.feet.value === "both" ? ["right", "left"] : [f.feet.value];
  flow.acks = Object.fromEntries(
    ["not_medical_device", "clinician_review", "break_in", "photo_consent"].map((k) => [k, f[k].checked]));
  const errors = [];
  if (!flow.name) errors.push("Please type your name.");
  if (!Object.values(flow.acks).every(Boolean)) errors.push("Please tick all four boxes to carry on.");
  $("about-error").textContent = errors.join(" ");
  if (errors.length) {
    if (!flow.name) fx.shake($("name").closest(".field"));
    for (const label of f.querySelectorAll(".ack label")) if (!label.querySelector("input").checked) fx.shake(label);
    return;
  }

  if (!flow.sections) {
    try {
      flow.sections = (await api("/survey", { method: "GET" })).sections;
    } catch (err) {
      $("about-error").textContent = `Couldn't load the questions: ${err.message}`;
      return;
    }
  }
  flow.sectionIndex = 0;
  renderSection();
});

// =========================================================================
// 2. Survey
// =========================================================================
const applies = (q) => Object.entries(q.show_if || {}).every(([k, vals]) => vals.includes(flow.answers[k]));

let lastSection = -1;
function renderSection() {
  const section = flow.sections[flow.sectionIndex];
  const dir = currentView === "survey" ? Math.sign(flow.sectionIndex - lastSection) : undefined;
  lastSection = flow.sectionIndex;
  $("survey-eyebrow").textContent = `Part ${flow.sectionIndex + 1} of ${flow.sections.length}`;
  $("part-dots").innerHTML = flow.sections.map((_, i) =>
    `<span class="${i < flow.sectionIndex ? "done" : i === flow.sectionIndex ? "current" : ""}"></span>`).join("");
  $("survey-title").textContent = section.title;
  $("survey-intro").textContent = section.intro || "";
  $("survey-error").textContent = "";
  $("btn-survey-next").textContent = flow.sectionIndex === flow.sections.length - 1 ? "See my scans" : "Next";

  $("survey-form").innerHTML = section.questions.map((q) => {
    const hint = q.hint ? `<span class="hint">${esc(q.hint)}</span>` : "";
    const a = flow.answers[q.id];
    if (q.type === "single" || q.type === "multi") {
      const type = q.type === "single" ? "radio" : "checkbox";
      const opts = q.options.map(([v, label]) => {
        const checked = q.type === "single" ? a === v : (a || []).includes(v);
        return `<label class="choice"><input type="${type}" name="${q.id}" value="${esc(v)}"${checked ? " checked" : ""}><span>${esc(label)}</span></label>`;
      }).join("");
      return `<fieldset class="q" data-q="${q.id}"><legend>${esc(q.label)}</legend>${hint}<div class="choices">${opts}</div><p class="q-error"></p></fieldset>`;
    }
    if (q.type === "confirm") {
      return `<div class="q" data-q="${q.id}"><label class="confirm"><input type="checkbox" name="${q.id}"${a ? " checked" : ""}><span>${esc(q.label)}</span></label><p class="q-error"></p></div>`;
    }
    const attrs = q.type === "number"
      ? `type="number" inputmode="decimal" min="${q.min}" max="${q.max}" step="0.1"`
      : `type="text" maxlength="${q.max || 200}"`;
    return `<div class="q field" data-q="${q.id}"><label class="q-label" for="q-${q.id}">${esc(q.label)}</label>${hint}
      <input id="q-${q.id}" name="${q.id}" ${attrs} value="${esc(a ?? "")}"><p class="q-error"></p></div>`;
  }).join("");
  syncVisibility();
  show("survey", "survey", dir);
}

function readAnswer(q) {
  const form = $("survey-form");
  if (q.type === "single") return form.querySelector(`input[name="${q.id}"]:checked`)?.value;
  if (q.type === "multi") return [...form.querySelectorAll(`input[name="${q.id}"]:checked`)].map((i) => i.value);
  if (q.type === "confirm") return form.querySelector(`input[name="${q.id}"]`).checked || undefined;
  const v = form.querySelector(`input[name="${q.id}"]`).value.trim();
  return v === "" ? undefined : q.type === "number" ? Number(v) : v;
}

function syncVisibility() {
  for (const q of flow.sections[flow.sectionIndex].questions) {
    flow.answers[q.id] = readAnswer(q);
    const el = $("survey-form").querySelector(`[data-q="${q.id}"]`);
    const wasHidden = el.hidden;
    el.hidden = !applies(q);
    if (el.hidden) delete flow.answers[q.id];
    // A follow-up question that appears because of an answer slides in.
    else if (wasHidden && currentView === "survey") fx.enter([el], { blur: false, distance: 14 });
  }
}

$("survey-form").addEventListener("change", (e) => {
  const q = flow.sections[flow.sectionIndex].questions.find((x) => x.id === e.target.name);
  if (q?.type === "multi") {
    // "None of these" clears the others, and vice versa.
    const boxes = [...$("survey-form").querySelectorAll(`input[name="${q.id}"]`)];
    if (q.exclusive && e.target.checked) {
      for (const b of boxes) if ((e.target.value === q.exclusive) !== (b.value === q.exclusive)) b.checked = false;
    }
    if (q.max_select) {
      const n = boxes.filter((b) => b.checked).length;
      for (const b of boxes) b.disabled = !b.checked && n >= q.max_select;
    }
  }
  const el = e.target.closest(".q");
  el?.classList.remove("invalid");
  if (el) el.querySelector(".q-error").textContent = "";
  syncVisibility();
});

function sectionErrors() {
  const errors = {};
  for (const q of flow.sections[flow.sectionIndex].questions) {
    if (!applies(q)) continue;
    const a = flow.answers[q.id];
    const empty = a === undefined || (Array.isArray(a) && !a.length);
    if (q.required && empty) errors[q.id] = q.type === "confirm" ? "Please tick this to carry on." : "Please answer this one.";
    else if (q.type === "number" && !empty && !(a >= q.min && a <= q.max)) errors[q.id] = `Enter a number between ${q.min} and ${q.max}.`;
  }
  return errors;
}

function showErrors(errors) {
  let first = null;
  for (const el of $("survey-form").querySelectorAll(".q")) {
    const msg = errors[el.dataset.q];
    el.classList.toggle("invalid", !!msg);
    el.querySelector(".q-error").textContent = msg || "";
    if (msg) fx.shake(el);
    if (msg && !first) first = el;
  }
  first?.scrollIntoView({ block: "center", behavior: "smooth" });
}

$("btn-survey-back").addEventListener("click", () => {
  syncVisibility();
  if (flow.sectionIndex === 0) return show("about", "about", -1);
  flow.sectionIndex--;
  renderSection();
});

$("btn-survey-next").addEventListener("click", async () => {
  syncVisibility();
  const errors = sectionErrors();
  showErrors(errors);
  if (Object.keys(errors).length) {
    $("survey-error").textContent = "Please answer the questions marked in red.";
    return;
  }
  if (flow.sectionIndex < flow.sections.length - 1) {
    flow.sectionIndex++;
    return renderSection();
  }
  const btn = $("btn-survey-next");
  btn.disabled = true;
  try {
    const evaluation = await api("/survey/evaluate", { json: { feet: flow.feet, survey: flow.answers } });
    if (evaluation.blocked) return showStopped(evaluation.blocked);
    flow.evaluation = evaluation;
    renderPlan();
  } catch (err) {
    $("survey-error").textContent = err.data?.fields
      ? "Some answers need another look. Go back through the questions."
      : `Something went wrong: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
});

function showStopped(blocked) {
  $("stopped-message").textContent = blocked.message;
  show("stopped", "survey");
}
$("btn-stopped-back").addEventListener("click", () => {
  flow.sectionIndex = 0;
  renderSection();
});

// =========================================================================
// 2c. Scan plan
// =========================================================================
function renderPlan() {
  const { plan, flags } = flow.evaluation;
  const before = flags.filter((f) => f.level === "before_wear" && f.customer);
  $("plan-flags").hidden = !before.length;
  $("plan-flag-list").innerHTML = before.map((f) => `<li>${esc(f.customer)}</li>`).join("");
  $("plan-list").innerHTML = plan.map((p) =>
    `<li><div><p><strong>${esc(p.label)}</strong></p><p class="why">${esc(p.why)}</p></div></li>`).join("");
  const standing = plan.some((p) => p.condition === "fwb");
  $("plan-helper").textContent = standing
    ? "Ask someone to hold the phone for the standing scans. Each scan takes about five minutes."
    : "Each scan takes about five minutes.";
  $("plan-error").textContent = "";
  loadMatBars().then(() => {
    if (DEMO && !$("mat-check").value) $("mat-check").value = "10";
    ruler.update();
  });
  show("plan", "survey");
  popMatDiagram();
}

const ruler = mountRuler($("ruler-view"), $("mat-check"), () => matBars);

// The mat drawing tapes itself together when it scrolls into view (or is tapped).
function popMatDiagram() {
  assembleMat($("mat-diagram"));
}



// ---- Rescan links: /?rescan=<submission>&t=<token> ----------------------------
// The person already answered the questions and agreed to the safety points.
// They only redo the scans the operator asked for, and check the mat again.
async function startRescan(id, token) {
  flow.submission = { id, upload_token: token };
  try {
    const info = await api(`/submissions/${encodeURIComponent(id)}/rescan`, { method: "GET" });
    flow.rescan = true;
    flow.name = info.name;
    flow.evaluation = { plan: info.plan, flags: [] };
    renderPlan();
    $("plan-title").textContent = `Hi ${info.name.split(" ")[0]}, we need a few new photos`;
    $("plan-lede").textContent = info.note
      ? `Here's why: "${info.note}". Only these scans need doing again.`
      : "Only these scans need doing again.";
    $("btn-plan-back").hidden = true;
    document.querySelectorAll("#steps li").forEach((li, i) => (li.className = i < 2 ? "done" : i === 2 ? "current" : ""));
  } catch (err) {
    flow.submission = null;
    $("link-error-text").textContent = err.status === 403 || err.status === 404
      ? "That link has already been used, or it has expired. Ask the person making your insole for a new one."
      : `Couldn't open that link: ${err.message}`;
    $("link-error").hidden = false;
  }
}

const params = new URLSearchParams(location.search);
if (params.get("rescan") && params.get("t")) startRescan(params.get("rescan"), params.get("t"));

$("btn-plan-back").addEventListener("click", () => {
  flow.sectionIndex = flow.sections.length - 1;
  renderSection();
});

// The mat prints two check bars (10 cm and 4 in) so any ruler works. A
// printer's "fit to page" is out by 3-6%, far more than a ruler's error.
let matBars = null;
async function loadMatBars() {
  if (!matBars) {
    const info = await api("/mat", { method: "GET" });
    matBars = info.check_bars;
    matTolerance = info.tolerance_mm;
  }
  return matBars;
}
function checkMatPrint() {
  if (!matBars) return { ok: false, message: "Couldn't load the mat details. Reload the page and try again." };
  return readCheckBar($("mat-check").value, matBars, matTolerance ?? 1.5);
}

$("btn-plan-start").addEventListener("click", async () => {
  const btn = $("btn-plan-start");
  const check = checkMatPrint();
  if (!check.ok) {
    $("plan-error").textContent = check.message;
    $("mat-check").focus();
    fx.shake($("mat-check").closest(".field"));
    return;
  }
  flow.matCheck = { value: Number($("mat-check").value), unit: check.bar.unit };
  if (!DEMO && !flow.submission) {
    btn.disabled = true;
    try {
      const created = await api("/submissions", {
        json: {
          name: flow.name, feet: flow.feet, acknowledgments: flow.acks, survey: flow.answers,
          mat_check_value: flow.matCheck.value, mat_check_unit: flow.matCheck.unit, device: navigator.userAgent,
        },
      });
      flow.submission = created;
      flow.evaluation = { plan: created.plan, flags: created.flags };
    } catch (err) {
      btn.disabled = false;
      if (err.status === 422 && err.data?.blocked) return showStopped(err.data.blocked);
      $("plan-error").textContent = `Couldn't start: ${err.message}`;
      return;
    }
    btn.disabled = false;
  }
  flow.scanIndex = 0;
  openSetup();
});

// =========================================================================
// 3. Set up and scan, once per planned scan
// =========================================================================
const SETUP_STEPS = {
  swb: [
    "<strong>Sit on a chair.</strong> Bend your knee so your lower leg points straight down.",
    "<strong>Put your bare foot flat in the middle of the mat</strong>, heel at the sheet 1 end. Roll trousers up past your ankle.",
    "<strong>Turn the lights on</strong> or open a curtain, so your foot is bright with no dark shadows.",
    "<strong>Ask someone to hold the phone</strong> if you can. It is much easier to reach behind your heel.",
    "<strong>Keep your foot still</strong> the whole time. Only the phone moves.",
  ],
  fwb: [
    "<strong>Stand up straight and barefoot</strong>, with this foot in the middle of the mat, heel at the sheet 1 end.",
    "<strong>Put the same weight on both feet</strong>, feet a little apart, and look straight ahead.",
    "<strong>Someone else holds the phone</strong> for this one, because you need to stand still.",
    "<strong>Turn the lights on</strong> so your foot is bright with no dark shadows.",
  ],
};

function openSetup() {
  const scan = currentScan();
  const total = flow.evaluation.plan.length;
  // A counter only helps when there's more than one scan.
  $("setup-eyebrow").textContent = total > 1 ? `Scan ${flow.scanIndex + 1} of ${total}` : "";
  $("setup-eyebrow").hidden = total <= 1;
  $("setup-title").textContent = `Get ready: ${scan.label.toLowerCase()}`;
  $("setup-steps").innerHTML = (SETUP_STEPS[scan.condition] || SETUP_STEPS.swb).map((t) => `<li><p>${t}</p></li>`).join("");
  $("setup-error").textContent = "";
  $("btn-open").hidden = DEMO;
  $("btn-demo").hidden = !DEMO;
  show("setup", "scan");
}

// Unlock sound on the tap itself: browsers only allow audio to begin from a
// gesture, and scanning now starts by itself a moment later.
$("btn-open").addEventListener("click", () => { unlockAudio(); startScan(false); });
$("btn-demo").addEventListener("click", () => { unlockAudio(); startScan(true); });

// Scanning begins by itself once the mat has been in view for a moment, with
// a short countdown, so there is one button to press instead of two.
const AUTO_START_AFTER_MS = 1200;
const COUNTDOWN_S = 3;
function autoStart(s, scanner) {
  if (scanner.started) return null;
  const now = performance.now();
  if (!s.matVisible) {
    // One missed frame is normal; only start over if the mat is really gone.
    flow.matLostAt ??= now;
    if (flow.matSeenSince == null || now - flow.matLostAt > 900) {
      flow.matSeenSince = null;
      return { text: "Point the phone at the mat so the black squares are in view.", tone: "" };
    }
  } else {
    flow.matLostAt = null;
  }
  flow.matSeenSince ??= now;
  const left = COUNTDOWN_S - Math.floor((now - flow.matSeenSince - AUTO_START_AFTER_MS) / 1000);
  if (now - flow.matSeenSince < AUTO_START_AFTER_MS) return { text: "Got the mat. Hold still…", tone: "" };
  if (left > 0) return { text: `Starting in ${left}…`, tone: "done" };
  beginCapture();
  return null;
}

function beginCapture() {
  if (flow.scanner.started) return;
  flow.scanner.start();
  $("btn-start").hidden = true;
  $("btn-pause").hidden = false;
  $("btn-pause").textContent = "Pause";
}

async function startScan(simulated) {
  await requestMotionPermission();
  const scan = currentScan();
  $("scan-eyebrow").textContent = scan.label;
  $("demo-ribbon").hidden = !simulated;
  flow.matSeenSince = null;
  flow.matLostAt = null;
  flow.doneShown = false;
  const boards = await loadBoards();
  const scanner = new Scanner({
    stage: $("stage"), simulated, boards, requireMat: true, foot: scan.foot,
    onUpdate: (s) => {
      const waiting = autoStart(s, scanner);
      const g = waiting ?? s.guidance;
      fx.setText($("guidance"), g.text);
      $("guidance").className = `guidance ${g.tone}`;
      $("progress-label").textContent = `${Math.round(100 * s.progress)}%`;
      $("progress-bar").style.width = `${100 * s.progress}%`;
      renderSteer(s, scanner);
      $("btn-finish").disabled = s.kept < MIN_FRAMES;
      $("btn-finish").className = s.done ? "btn accent" : "btn secondary";
      // Done: the Finish button says so with a bounce, once.
      if (s.done && !flow.doneShown) { flow.doneShown = true; fx.bounce($("btn-finish"), { scale: 1.08 }); }
    },
  });
  try {
    await scanner.open();
  } catch (err) {
    $("setup-error").textContent = cameraErrorMessage(err);
    return;
  }
  flow.scanner = scanner;
  wireSoundToggle(scanner);
  $("btn-start").hidden = false;
  $("btn-pause").hidden = true;
  $("btn-finish").disabled = true;
  show("scan", "scan");
  // Scanning takes over the screen; the corner button parks it like a video player.
  flow.stageView ??= createStageView($("stage"), $("scan-hud"),
    { docked: [$("demo-ribbon"), $("guidance")] });
  flow.stageView.full();
}

$("btn-start").addEventListener("click", () => beginCapture());

$("btn-pause").addEventListener("click", () => {
  const s = flow.scanner;
  s.capturing ? s.pause() : s.resume();
  $("btn-pause").textContent = s.capturing ? "Pause" : "Resume";
});

$("btn-restart").addEventListener("click", () => {
  if (flow.scanner?.frames.length && !confirm("Delete the photos for this scan and start again?")) return;
  flow.stageView?.inline();
  flow.scanner?.close();
  flow.scanner = null;
  openSetup();
});

$("btn-finish").addEventListener("click", () => saveScan());

async function saveScan() {
  const scanner = flow.scanner;
  scanner.hold();
  flow.stageView?.inline();
  const scan = currentScan();
  $("saving-title").textContent = `Saving: ${scan.label.toLowerCase()}…`;
  $("saving-error").textContent = "";
  $("saving-actions").hidden = true;
  show("saving", "scan");
  const progress = (i, n, label) => {
    $("saving-label").textContent = label;
    $("saving-count").textContent = n ? `${i} / ${n}` : "";
    $("saving-bar").style.width = n ? `${(100 * i) / n}%` : "0";
  };

  try {
    await scanner.ready();
    const kept = scanner.keptFrames();
    const deck = fx.photoDeck($("saving-deck"), kept.map((f) => f.url).filter(Boolean));
    if (!DEMO) {
      const base = `/submissions/${flow.submission.id}/scans/${scan.key}`;
      await api(`${base}/start`);
      for (let i = 0; i < kept.length; i++) {
        progress(i, kept.length, "Uploading photos");
        await api(`${base}/frames/${i + 1}`, { method: "PUT", body: kept[i].blob, headers: { "Content-Type": "image/jpeg" } });
        deck.advance(i + 1);
      }
      await api(`${base}/complete`, {
        json: { frames: scanner.frameRecords(), summary: scanner.summary() },
      });
    } else {
      // Demo: nothing is sent, but show the photos leaving so the flow reads the
      // same (about two and a half seconds however many photos there are).
      const pause = Math.min(30, 2500 / Math.max(1, kept.length));
      for (let i = 0; i < kept.length; i++) {
        progress(i + 1, kept.length, "Demo: nothing is sent");
        deck.advance(i + 1);
        if (fx.enabled()) await new Promise((r) => setTimeout(r, pause));
      }
    }
    deck.done();
    progress(kept.length, kept.length, DEMO ? "Demo: nothing uploaded" : "Saved");
    flow.results[scan.key] = kept.length;
    scanner.close();
    flow.scanner = null;
    flow.scanIndex++;
    setTimeout(() => (flow.scanIndex < flow.evaluation.plan.length ? openSetup() : openSend()), fx.enabled() ? 1100 : 500);
  } catch (err) {
    $("saving-error").textContent = `The photos did not send (${err.message}). Check your Wi-Fi, then tap Try again.`;
    $("saving-actions").hidden = false;
  }
}

$("btn-retry-upload").addEventListener("click", () => saveScan());
$("btn-rescan").addEventListener("click", () => {
  flow.stageView?.inline();
  flow.scanner?.close();
  flow.scanner = null;
  openSetup();
});

// =========================================================================
// 4. Send
// =========================================================================
function openSend() {
  $("foot-rows").innerHTML = flow.evaluation.plan.map((p) =>
    `<div class="card foot-row tilt"><strong>${esc(p.label)}</strong>
      <span class="badge ok"><span class="count" data-n="${flow.results[p.key]}">${flow.results[p.key]}</span> photos</span></div>`).join("");
  for (const c of $("foot-rows").querySelectorAll(".count")) fx.countTo(c, Number(c.dataset.n), { from: 0, duration: 0.9 });
  $("send-error").textContent = DEMO ? "Demo mode: sending is disabled." : "";
  $("btn-send").disabled = DEMO;
  show("send", "send");
}

$("btn-send").addEventListener("click", async () => {
  $("btn-send").disabled = true;
  try {
    await api(`/submissions/${flow.submission.id}/submit`,
      flow.rescan ? { json: { mat_check_value: flow.matCheck.value, mat_check_unit: flow.matCheck.unit } } : {});
  } catch (err) {
    $("send-error").textContent = `Couldn't send: ${err.message}`;
    $("btn-send").disabled = false;
    return;
  }
  $("done-ref").textContent = flow.submission.id.replace(/^sub-/, "");
  flow.submission = null;
  show("done", "send");
  fx.updateSteps($("steps"), 4);
  celebrate();
});

// The finish: the tick draws itself, then confetti from it. Tap it for more.
let lastConfetti = 0;
$("big-check").addEventListener("click", () => {
  if (performance.now() - lastConfetti < 900) return;
  lastConfetti = performance.now();
  fx.bounce($("big-check"), { scale: 1.12 });
  fx.confetti($("big-check"), { count: 50 });
  fx.buzz([8, 40, 8]);
});

function celebrate() {
  lastConfetti = performance.now();
  const check = $("big-check");
  fx.draw(check.querySelector("circle"), { duration: 0.6 });
  fx.draw(check.querySelector("path"), { delay: 0.45, duration: 0.4 });
  setTimeout(() => fx.confetti(check), 700);
}

// Leaving mid-scan: release the camera.
window.addEventListener("pagehide", () => flow.scanner?.close());
