// Studio, Make shoe: choose a clog's settings (or have a description read into them), make it from this
// capture's sole scan, and look at it in 3-D, whole or cut open to see the footbed built into its floor.
// Below the shoe: the other foot's shoe, for making a pair alike, and what this shoe's print-trial pieces
// showed, kept with the scan, with the changes to the choices the studio's fixed rules suggest from it.
// Every number shown comes from the shoe's own report; the lists and limits come from the generator
// (/api/footwear/options). Not a medical device: walking and casual wear only, never sport, and nothing from
// this design has been printed or worn yet (the page says so in the generator's own words).
import { MeshViewer } from "./mesh-viewer.js";
import { parseViewerBin } from "./viewer-math.js";
import {
  SETTING_NAMES, changeLine, choicesFrom, findingsFrom, letOutText, otherShoe, pairDifferences, pairText, shoeAbove,
  shoeToRecord, understoodLine, valuesFrom, withPairChoices, withReading, withSuggestion,
} from "./clog-form.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const id = new URLSearchParams(location.search).get("capture");
const base = `/api/captures/${encodeURIComponent(id || "")}/clog`;

let options, capture, captures, clog, viewer;
let fit = null;                         // what the trial pieces showed: { questions, records, max_note }
const meshes = {};                      // "whole" and "open", fetched when first shown
const state = { open: false };

const WHERE_WORDS_GO = {
  keywords: "Read on this computer, by looking for known words. Nothing is sent anywhere.",
  claude: "Read by Claude: the words you type here, and nothing else (no scan, no measurements), are sent to Anthropic. "
    + "A description that says the shoe is for a foot condition or for sport is not sent, and not read.",
};

// ---- the form ---------------------------------------------------------------------------------------
function segmented(name, items, label) {
  return `<fieldset><legend>${label}</legend><div class="segmented" role="radiogroup" aria-label="${label}">
    ${items.map((k) => `<label><input type="radio" name="${name}" value="${esc(k)}"> ${esc(k)}</label>`).join("")}</div>
    <p class="hint" id="${name}-hint" style="margin:6px 0 0"></p></fieldset>`;
}

function formHtml() {
  const lim = options.limits;
  return `
  <div class="callout warn"><p><strong>Not a medical device.</strong> A clog for walking and casual wear only, not for
    tennis, running or any other sport. ${esc(options.untested)}</p></div>
  <section class="card section">
    <h2 style="margin-top:0">Describe it <span class="hint">(optional)</span></h2>
    <p class="hint" style="margin:0 0 10px">Say what you would like in your own words. It is read into the choices below,
      which you can then change. ${esc(WHERE_WORDS_GO[options.described_by] ?? "")}</p>
    <textarea id="words" maxlength="1000" aria-label="Describe the shoe you would like"
      placeholder="For example: airy and roomy, with a thick sole, for thick socks"></textarea>
    <p class="btn-row" style="margin:10px 0 0"><button class="btn secondary" type="button" id="read">Read my description</button></p>
    <div class="read" id="reading"></div>
  </section>
  <section class="card section">
    <h2 style="margin-top:0">Choose</h2>
    <fieldset style="margin-top:0"><legend>Style</legend><div class="choices">
      ${options.styles.map((s) => `<label class="choice"><input type="radio" name="style" value="${esc(s.key)}">
        <strong>${esc(s.label)}</strong><span class="hint">${esc(s.about)} (${esc(s.sole_mm)} mm under the ball of the foot)</span></label>`).join("")}
    </div></fieldset>
    <div class="form-grid">
      ${segmented("fit", options.fits.map((f) => f.key), "Fit")}
      ${segmented("toe", options.toes, "Toe")}
      ${segmented("cushion", options.cushions.map((c) => c.key), "Cushioning")}
    </div>
    <div class="form-grid">
      <div class="field"><label for="sole_mm">Sole thickness, mm</label>
        <input type="number" id="sole_mm" inputmode="decimal" min="${lim.sole_mm[0]}" max="${lim.sole_mm[1]}" step="1">
        <span class="hint">Under the ball of the foot. Empty: the style's own.</span></div>
      <div class="field"><label for="openness_percent">Pattern open, %</label>
        <input type="number" id="openness_percent" inputmode="decimal" min="${100 * lim.openness[0]}" max="${100 * lim.openness[1]}" step="1">
        <span class="hint" id="openness-hint">How much of the patterned area is window. Empty: the style's own.</span></div>
      <div class="field"><label for="sock_mm">Thicker sock, mm</label>
        <input type="number" id="sock_mm" inputmode="decimal" min="${lim.sock_mm[0]}" max="${lim.sock_mm[1]}" step="0.5">
        <span class="hint">Extra room for a sock thicker than the one the foot was measured in.</span></div>
    </div>
    <fieldset><legend>The foot, by ruler, standing</legend>
      <div class="form-grid" style="margin-top:0">
        <div class="field"><label for="length_mm">Length, mm</label>
          <input type="number" id="length_mm" inputmode="decimal" min="${lim.length_mm[0]}" max="${lim.length_mm[1]}" step="1">
          <span class="hint">Heel to the longest toe.</span></div>
        <div class="field"><label for="width_mm">Width, mm</label>
          <input type="number" id="width_mm" inputmode="decimal" min="1" step="1">
          <span class="hint">Across the ball of the foot.</span></div>
      </div>
      <p class="hint" style="margin:8px 0 0">Empty: the sole scan's own size. With a ruler's length the shoe is sized by the
        ruler, and its sheet says how the scan compares.</p></fieldset>
    <ul class="checklist" style="margin-top:18px"><li><label><input type="checkbox" id="trials">
      <span>Also cut the print-trial pieces: small parts of this shoe to print before a whole one. They are not shoes.</span></label></li></ul>
    <p class="btn-row" style="margin:18px 0 0"><button class="btn" type="button" id="make">Make shoe</button></p>
    <p class="hint" id="making" style="margin:10px 0 0" role="status"></p>
  </section>
  <div id="result" class="section"></div>
  <div id="pair" class="section"></div>
  <div id="fit" class="section"></div>`;
}

const FIELDS = ["sole_mm", "openness_percent", "sock_mm", "length_mm", "width_mm"];
const RADIOS = ["style", "fit", "toe", "cushion"];

function readForm() {
  const values = { trials: $("trials").checked };
  for (const k of RADIOS) values[k] = document.querySelector(`input[name="${k}"]:checked`)?.value ?? "";
  // (a field that is switched off, the pattern's openness on a style with no windows, is not a choice)
  for (const k of FIELDS) values[k] = $(k).disabled ? "" : $(k).value.trim();
  return values;
}

function writeForm(values) {
  for (const k of RADIOS) {
    const radio = [...document.querySelectorAll(`input[name="${k}"]`)].find((r) => r.value === values[k]);
    if (radio) radio.checked = true;
  }
  for (const k of FIELDS) $(k).value = values[k] ?? "";
  hints();
}

// What the chosen style, fit and cushioning come to, from the generator's own tables.
function hints() {
  const v = readForm();
  const style = options.styles.find((s) => s.key === v.style);
  const fit = options.fits.find((f) => f.key === v.fit);
  const cushion = options.cushions.find((c) => c.key === v.cushion);
  $("sole_mm").placeholder = style ? `${style.sole_mm} (${style.label})` : "";
  $("openness_percent").disabled = !!style && !style.windows;
  $("openness_percent").placeholder = style?.windows ? `${Math.round(1000 * style.openness) / 10} (${style.label})` : "";
  $("openness-hint").textContent = style && !style.windows
    ? `${style.label} has no windows, so there is nothing to open.`
    : "How much of the patterned area is window. Empty: the style's own.";
  $("fit-hint").textContent = fit
    ? `${fit.toe_room_mm} mm past the longest toe, ${fit.width_mm} mm added across the ball.` : "";
  $("cushion-hint").textContent = cushion ? `${cushion.infill_percent}% infill suggested (untested).` : "";
  $("toe-hint").textContent = "The shape of the front.";
}

// ---- a description read into the form -------------------------------------------------------------------
async function readDescription() {
  const text = $("words").value.trim();
  const out = $("reading");
  if (!text) {
    out.innerHTML = `<p class="hint">Write a few words about the shoe first.</p>`;
    return;
  }
  $("read").disabled = true;
  out.innerHTML = `<p class="hint">Reading…</p>`;
  try {
    const r = await fetch("/api/footwear/describe", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    });
    const res = await r.json();
    if (!r.ok) throw new Error(res.error || r.status);
    writeForm(withReading(readForm(), res.settings));
    const understood = res.understood.map((u) => `<li>${esc(understoodLine(u, options))}</li>`).join("");
    const notes = res.notes.map((n) => `<li>${esc(n)}</li>`).join("");
    out.innerHTML = `
      <p class="hint" style="margin:0">${res.not_read ? "Not read into the choices:"
        : res.read_by === "claude" ? "Read by Claude." : "Read on this computer, by looking for known words."}
        ${understood ? "The choices below now say:" : ""}</p>
      ${understood ? `<ul>${understood}</ul>` : ""}
      ${notes ? `<ul style="color:var(--warn)">${notes}</ul>` : ""}
      <p class="hint" style="margin:6px 0 0">${res.not_read ? "The choices below are as they were."
        : "Nothing is made until you press Make shoe: check the choices first."}</p>`;
  } catch (err) {
    out.innerHTML = `<p class="hint" style="color:var(--warn)">Couldn't read it: ${esc(err.message)}</p>`;
  } finally {
    $("read").disabled = false;
  }
}

// ---- the shoe ---------------------------------------------------------------------------------------------
async function make() {
  const btn = $("make");
  const says = $("making");
  btn.disabled = true;
  says.style.color = "";
  says.textContent = "Making the shoe…";
  try {
    const r = await fetch(base, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(choicesFrom(readForm())),
    });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || r.status);
    clog = out;     // the shoe, or why it couldn't be made (an earlier one is then gone from the studio too)
    capture.clog = clog;
  } catch (err) {
    // refused before anything was made (a choice the generator doesn't have), or the studio wasn't reached:
    // whatever shoe is on the page still stands
    says.style.color = "var(--warn)";
    says.textContent = `Couldn't make it: ${err.message}`;
    return;
  } finally {
    btn.disabled = false;
  }
  says.textContent = "";
  await showResult();
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  showPair();
  fitPicked = null;   // a new shoe is the one the trial form opens on (an earlier one can still be picked there)
  await showFit();
}

const file = (name) => `${base}/${name}?v=${encodeURIComponent(clog.made || "")}`;

function trialsHtml(t) {
  if (!t) return "";
  if (t.error) return `<h3>Print-trial pieces</h3><p class="hint" style="color:var(--warn)">${esc(t.error)} The shoe itself was made.</p>`;
  return `<h3 style="margin-bottom:6px">Print-trial pieces</h3>
    <div class="callout warn" style="padding:12px 14px"><p style="margin:0"><strong>${esc(t.warning)}</strong></p></div>
    <p class="hint" style="margin:10px 0 0">Print these before the whole shoe, in this order. The sheet says how to print each and what to look at.</p>
    <ol class="pieces">${t.pieces.map((p) => `<li><span><strong>${esc(p.title ?? p.piece)}</strong>
      <span class="hint">${esc(p.length_mm)} × ${esc(p.width_mm)} × ${esc(p.height_mm)} mm</span></span>
      <a class="btn secondary" href="${file(`clog-trial-${encodeURIComponent(p.piece)}.3mf`)}">3MF</a></li>`).join("")}</ol>
    ${(t.left_out || []).map((line) => `<p class="hint" style="color:var(--warn);margin:8px 0 0">${esc(line)}</p>`).join("")}
    <p class="btn-row" style="margin:12px 0 0">
      <a class="btn secondary" href="${file("clog-trials.txt")}">The trials' sheet</a>
      <a class="btn secondary" href="${file("clog-trials.png")}" target="_blank" rel="noopener">Picture of the pieces</a></p>`;
}

function resultHtml() {
  const r = clog;
  if (!r) return "";
  if (r.error) return `<div class="callout stop"><p>${esc(r.error)}</p></div>`;
  if (r.stale) {
    return `<div class="callout warn"><p>The 3D model has changed since this shoe was made, so its footbed no longer
      matches. Press Make shoe to make it again.</p></div>`;
  }
  const style = options.styles.find((s) => s.key === r.style);
  const fb = r.footbed;
  const letOut = fb ? letOutText(fb.let_out) : "";
  const warn = (r.warnings || []).map((w) => `<li>${esc(w)}</li>`).join("");
  return `<section class="card">
    <h2 style="margin-top:0">${esc(r.foot === "left" ? "Left" : "Right")} clog · ${esc(style?.label ?? r.style)}
      <span class="badge warn">untested design</span></h2>
    <div class="stage" id="stage"><canvas id="canvas" aria-label="3-D view of the shoe; drag to turn, scroll or pinch to zoom"></canvas></div>
    <div class="views" id="views">
      <label><input type="checkbox" id="open"> Cut it open</label>
    </div>
    <p class="hint-key">Drag to turn, scroll or pinch to zoom, two fingers or right-drag to slide. Cut open, the outer half
      is taken away along the middle of the heel, so the footbed built into the floor shows; the coloured face is the cut.</p>
    <dl class="big">
      <div><dt>Outside, length × width × height</dt><dd>${esc(r.length_mm)} × ${esc(r.width_mm)} × ${esc(r.height_mm)} mm</dd></div>
      <div><dt>Inside, length × width</dt><dd>${esc(r.inside.length_mm)} × ${esc(r.inside.width_mm)} mm</dd></div>
      <div><dt>Made for a foot</dt><dd>${esc(r.made_for.foot_length_mm)} × ${esc(r.made_for.foot_width_mm)} mm</dd>
        <span class="hint">length from the ${esc(r.made_for.length_from)}, width from the ${esc(r.made_for.width_from)}</span></div>
      <div><dt>Sole, under ball / heel</dt><dd>${esc(r.sole.under_ball_mm)} / ${esc(r.sole.under_heel_mm)} mm</dd></div>
      <div><dt>Footbed's highest fill</dt><dd>${fb ? `${esc(fb.max_fill_mm)} mm` : "flat"}</dd></div>
      <div><dt>On the printer's bed</dt><dd style="font-size:0.9rem">${esc(r.bed.fits ? r.bed.how : "does not fit")}</dd></div>
    </dl>
    ${fb ? `<p class="hint" style="margin:12px 0 0">The upper is a standard shape in this foot's size; the footbed follows the
      scanned sole${letOut ? `, and ${esc(letOut)}` : ""}.</p>` : ""}
    ${warn ? `<ul class="checklist" style="margin:12px 0 0;color:var(--warn)">${warn}</ul>` : ""}
    <p class="btn-row" style="margin:14px 0 0">
      <a class="btn" href="${file("clog.3mf")}">3MF for Bambu Studio</a>
      <a class="btn secondary" href="${file("summary.html")}" target="_blank" rel="noopener">Summary sheet</a>
      <a class="btn secondary" href="${file("print-notes.txt")}">Print notes</a>
      <a class="btn secondary" href="${file("clog-views.png")}" target="_blank" rel="noopener">Pictures</a>
      <a class="btn secondary" href="${file("clog.stl")}">STL</a></p>
    ${trialsHtml(r.trials)}
    <p class="hint" style="margin:14px 0 0">Not a medical device. Walking and casual wear only, not sport; break-in as on the
      summary sheet. ${esc(r.untested)}</p>
  </section>`;
}

// The shoe's frame: x forward from the back of the shoe, y toward the foot's left, z up.
function views() {
  const inner = clog.foot === "right" ? 1 : -1;
  return [
    ["Front and side", [0.75, -inner * 0.8, 0.5]],
    ["Outer side", [0, -inner, 0.12]],
    ["Into the cut", [0.12, -inner, 0.4]],
    ["From above", [0, 0, 1]],
    ["From behind", [-1, -inner * 0.45, 0.3]],
    ["Inner side", [0, inner, 0.12]],
    ["Underneath", [0.2, -inner * 0.3, -1]],
  ];
}

// Each preview is fetched once (the promise is kept, so a second ask while the first is on its way waits for
// it); one that failed is asked for again next time.
function mesh(which) {
  if (!meshes[which]) {
    const asked = (async () => {
      const r = await fetch(file(which === "open" ? "clog-preview-open.bin" : "clog-preview.bin"));
      if (!r.ok) throw new Error(r.status === 409 ? "this shoe no longer matches its scan: make it again" : `the 3-D preview (${r.status})`);
      return parseViewerBin(await r.arrayBuffer());
    })();
    meshes[which] = asked;
    asked.catch(() => { if (meshes[which] === asked) delete meshes[which]; });
  }
  return meshes[which];
}

function noViewer(why) {
  // no 3-D here (an old browser, or the preview couldn't be fetched): the generator's own pictures instead
  $("stage").innerHTML = `<img src="${file("clog-views.png")}" alt="The shoe from six sides">`;
  $("views").innerHTML = `<span class="hint">${esc(why)} These are the shoe's pictures instead.</span>`;
}

async function showResult() {
  for (const k of Object.keys(meshes)) delete meshes[k];
  state.open = false;
  viewer = null;
  $("result").innerHTML = resultHtml();
  $("make").textContent = clog && !clog.error ? "Make it again" : "Make shoe";
  if (!clog || clog.error || clog.stale) return;
  try {
    viewer = new MeshViewer($("canvas"));
  } catch (err) {
    return noViewer(err.message);
  }
  try {
    viewer.setBasis({ east: [0, -1, 0], north: [1, 0, 0], up: [0, 0, 1] });
    viewer.load(await mesh("whole"));
  } catch (err) {
    return noViewer(`Couldn't show the 3-D preview: ${err.message}.`);
  }
  viewer.lookFrom(views()[0][1]);
  $("views").insertAdjacentHTML("beforeend",
    views().map(([label], i) => `<button class="btn secondary" type="button" data-view="${i}">${label}</button>`).join(""));
  $("views").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) viewer.lookFrom(views()[Number(b.dataset.view)][1]);
  });
  const shown = viewer;
  $("open").addEventListener("change", async (e) => {
    const open = state.open = e.target.checked;
    let data;
    try {
      data = await mesh(open ? "open" : "whole");
    } catch (err) {
      if (viewer !== shown || state.open !== open) return;
      e.target.checked = state.open = false;
      $("views").insertAdjacentHTML("beforeend", `<span class="hint" style="color:var(--warn)">${esc(err.message)}</span>`);
      return;
    }
    // while it was on its way the box may have been changed back, or another shoe made: then this isn't wanted
    if (viewer !== shown || state.open !== open) return;
    viewer.load(data, { keepView: true });
    if (open) viewer.lookFrom(views()[2][1]);
  });
}

// ---- the other foot's shoe ------------------------------------------------------------------------------------
const when = (stamp) => String(stamp || "").replace("T", " ").slice(0, 16);
const styleLabel = (key) => options.styles.find((s) => s.key === key)?.label ?? key;

// A pair is two shoes, each made from its own foot's scan. Where the other foot has a shoe, say how the two
// compare (in their reports' own numbers) and offer its choices for this form; each foot keeps its own ruler numbers.
function showPair() {
  const other = otherShoe(captures, capture);
  if (!other) {
    $("pair").innerHTML = "";
    return;
  }
  const o = other.clog;
  const mine = clog && !clog.error && !clog.stale ? clog : null;
  const differ = mine ? pairDifferences(mine.choices, o.choices, options) : [];
  $("pair").innerHTML = `<section class="card">
    <h2 style="margin-top:0">The ${esc(o.foot)} foot's shoe</h2>
    <p style="margin:0">A ${esc(styleLabel(o.style))} clog was made for the ${esc(o.foot)} foot on ${esc(when(o.made))}, from that foot's own
      scan (<a class="mono" href="/studio/clog.html?capture=${encodeURIComponent(other.capture_id)}">${esc(other.capture_id)}</a>).
      A pair is two shoes, each made from its own foot's scan.</p>
    ${mine ? `<p style="margin:10px 0 0">${esc(pairText(mine, o))}</p>
      <p class="hint" style="margin:6px 0 0">${differ.length
    ? `The two were made to different choices: ${esc(differ.map((k) => (SETTING_NAMES[k] ?? k).toLowerCase()).join(", "))}.`
    : "Both were made to the same choices."}</p>` : ""}
    <p class="btn-row" style="margin:12px 0 0"><button class="btn secondary" type="button" data-pair="use">Use the ${esc(o.foot)} shoe's choices</button></p>
    <p class="hint" id="pair-says" style="margin:8px 0 0" role="status"></p>
  </section>`;
}

function usePairChoices() {
  const other = otherShoe(captures, capture);
  if (!other) return;
  writeForm(withPairChoices(readForm(), other.clog.choices, options.defaults));
  $("pair-says").textContent = `The choices above are now the ${other.clog.foot} shoe's, with this foot's own ruler numbers. `
    + "Nothing is made until you press Make shoe.";
}

// ---- what the print-trial pieces showed -------------------------------------------------------------------------
// The studio sends the shoes whose trial pieces were cut here, each with its questions, the records about it and
// what those say together for its choices (footwear_fit.py). A record is about the shoe its pieces were cut
// from, which may have been made again since: the form asks which.
let fitPicked = null;     // the shoe the form is about, where the person picked one (when it was made)

// A shoe of the record by what tells it from the one made before or after it: when, and the fit and cushioning
// it was made to (the two choices a record can suggest changing).
function shoeName(s) {
  const c = { ...options.defaults, ...(s.choices || {}) };
  return `${styleLabel(s.style)} shoe made ${when(s.made)}, ${c.fit} fit, ${c.cushion} cushioning`;
}

function shoeHtml(s) {
  const above = shoeAbove(s, clog);
  const g = s.suggestion;
  const changes = g.changes.map((c) => `<li>${esc(changeLine(c, options))}</li>`).join("");
  // (once something hurt, why nothing is suggested is said once, with the stop rule above the shoes)
  const notes = g.notes.filter((n) => n !== fit.stop?.nothing).map((n) => `<li>${esc(n)}</li>`).join("");
  const records = s.records.map((r) => `<p class="hint" style="margin:10px 0 0">Recorded ${esc(when(r.recorded))}</p>
    <ul>${r.said.map((w) => `<li>${w.piece_title ? `<span class="hint">${esc(w.piece_title)}:</span> ` : ""}${esc(w.ask)}
      <strong>${esc(w.answer)}</strong></li>`).join("")}</ul>
    ${r.note ? `<p style="margin:6px 0 0">Note: “${esc(r.note)}”</p>` : ""}`).join("");
  return `<div class="record">
    <p style="margin:0"><strong>The ${esc(shoeName(s))}</strong>
      <span class="hint">${above ? "(the shoe above)" : "(not the shoe above: it has been made again since, or its scan has changed)"}</span></p>
    ${records}
    ${changes ? `<p style="margin:12px 0 0">Suggested for its choices, from everything recorded about this shoe <span class="hint">(by
      fixed rules that are judgments, untested; nothing is changed until you do it)</span>:</p><ul>${changes}</ul>` : ""}
    ${notes ? `<ul style="color:var(--warn)">${notes}</ul>` : ""}
    ${above && changes ? `<p class="btn-row" style="margin:10px 0 0">
      <button class="btn secondary" type="button" data-fit="take" data-made="${esc(s.made)}">Put these into the choices</button></p>
      <p class="hint" id="fit-took" style="margin:8px 0 0" role="status"></p>` : ""}
  </div>`;
}

function questionsHtml(shoe) {
  const groups = [];
  for (const q of shoe.questions) {
    const title = q.piece_title ?? "Any of the pieces";
    if (groups.at(-1)?.title !== title) groups.push({ title, questions: [] });
    groups.at(-1).questions.push(q);
  }
  return groups.map((g) => `<h4 style="margin:18px 0 0">${esc(g.title)}</h4>
    ${g.questions.map((q) => `<fieldset style="margin-top:10px"><legend style="font-weight:500">${esc(q.ask)}</legend>
      <div class="answers">${q.answers.map((a) => `<label><input type="radio" name="fit-${esc(q.key)}" value="${esc(a.key)}">
        ${esc(a.label)}</label>`).join("")}</div></fieldset>`).join("")}`).join("");
}

function fitFormHtml() {
  const open = fit.shoes.filter((s) => s.recordable);
  const shoe = shoeToRecord(fit.shoes, clog, fitPicked);
  if (!shoe) {
    return clog && !clog.error ? `<p class="hint" style="margin:14px 0 0;color:var(--warn)">This shoe has no print-trial pieces (it was made
      without them, or they couldn't be cut), so there is nothing to print and record. Tick “Also cut the print-trial pieces”
      and make it again to get them.</p>` : "";
  }
  const which = open.length > 1
    ? `<div class="field" style="margin-top:12px"><label for="fit-shoe">Which shoe were these pieces cut from?</label>
      <select id="fit-shoe">${open.map((s) => `<option value="${esc(s.made)}"${s.made === shoe.made ? " selected" : ""}>The ${esc(shoeName(s))}${
    shoeAbove(s, clog) ? " (the shoe above)" : ""}</option>`).join("")}</select>
      <p class="hint" style="margin:6px 0 0">The pieces' own sheet and data file were written when their shoe was made.</p></div>`
    : `<p style="margin:10px 0 0">About the pieces cut from the ${esc(shoeName(shoe))}${shoeAbove(shoe, clog) ? " (the shoe above)" : ""}.</p>`;
  return `<h3 style="margin:20px 0 0">Record what they showed</h3>
    <p class="hint" style="margin:4px 0 0">Answer for the pieces you have printed and leave the rest: what is recorded about one shoe is
      read together. Whether anything hurt is asked every time.</p>
    ${which}
    <div id="fit-questions">${questionsHtml(shoe)}</div>
    <div class="field" style="margin-top:16px"><label for="fit-note">A note <span class="hint">(optional; kept as written, not read into anything)</span></label>
      <textarea id="fit-note" maxlength="${esc(fit.max_note)}"></textarea></div>
    <p class="btn-row" style="margin:14px 0 0"><button class="btn" type="button" data-fit="keep">Keep this record</button></p>
    <p class="hint" id="fit-says" style="margin:10px 0 0" role="status"></p>`;
}

function renderFit() {
  const stop = fit.stop;
  $("fit").innerHTML = `<section class="card">
    <h2 style="margin-top:0">What the trial pieces showed</h2>
    <p class="hint" style="margin:0">Print a shoe's trial pieces, try them as their sheet says (seated: they are not shoes), and
      record here what you found. It is kept with this scan. The sole block you pick, and a piece that pressed or stood off the
      foot, can suggest a change to that shoe's choices. The footbed is never changed to how it felt, and nothing is suggested
      for this foot's shoes once anything hurt.</p>
    ${stop ? `<div class="callout stop" style="margin:14px 0 0;padding:12px 14px"><p style="margin:0"><strong>${esc(stop.words)}</strong></p>
      <p style="margin:8px 0 0">${esc(stop.nothing)} <span class="hint">(Recorded ${esc(when(stop.recorded))}.)</span></p></div>` : ""}
    ${fit.shoes.filter((s) => s.records.length).map(shoeHtml).join("")}
    ${fitFormHtml()}
  </section>`;
}

async function showFit() {
  const has = clog && !clog.error;
  try {
    const r = await fetch(`${base}/fit`);
    if (!r.ok) throw new Error(`the trial record (${r.status})`);
    fit = await r.json();
  } catch (err) {
    fit = null;
    $("fit").innerHTML = has ? `<p class="hint" style="color:var(--warn)">Couldn't load what the trial pieces showed: ${esc(err.message)}.</p>` : "";
    return;
  }
  if (!has && !fit.shoes.length) {      // no shoe yet, and none was ever made here with trial pieces: nothing to show
    $("fit").innerHTML = "";
    return;
  }
  renderFit();
}

// Another shoe picked in the form: its own pieces' questions (Stone has no swatch), nothing answered yet.
function pickFitShoe(made) {
  fitPicked = made;
  const shoe = shoeToRecord(fit.shoes, clog, fitPicked);
  if (shoe) $("fit-questions").innerHTML = questionsHtml(shoe);
}

async function keepRecord(btn) {
  const says = $("fit-says");
  const shoe = shoeToRecord(fit.shoes, clog, fitPicked);
  if (!shoe) return;
  const answers = {};
  for (const q of shoe.questions) answers[q.key] = document.querySelector(`input[name="fit-${q.key}"]:checked`)?.value ?? "";
  const findings = findingsFrom({ made: shoe.made, answers, note: $("fit-note").value });
  says.style.color = "var(--warn)";
  if (!findings.answers.hurt) {
    says.textContent = "Say whether anything hurt, rubbed or left a mark (the last question): every record has that answer.";
    return;
  }
  btn.disabled = true;
  try {
    const r = await fetch(`${base}/fit`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(findings),
    });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || r.status);
    fit = out;
  } catch (err) {
    says.textContent = `Couldn't keep it: ${err.message}`;
    btn.disabled = false;
    return;
  }
  renderFit();
  $("fit").scrollIntoView({ behavior: "smooth", block: "start" });
}

function takeSuggestion(made) {
  const shoe = fit.shoes.find((s) => s.made === made);
  if (!shoe?.suggestion || !shoeAbove(shoe, clog)) return;
  writeForm(withSuggestion(readForm(), shoe.suggestion.changes));
  $("fit-took").textContent = "The choices above now say so. Nothing is made until you press Make shoe.";
}

async function init() {
  if (!id) {
    $("root").innerHTML = `<p class="muted">No capture given. Open this page from the
      <a href="/studio/captures.html">research library</a>.</p>`;
    return;
  }
  $("back").innerHTML = `Research capture <a class="mono" href="/studio/captures.html#${esc(id)}">${esc(id)}</a>`;
  try {
    const [opts, list] = await Promise.all([
      fetch("/api/footwear/options").then((r) => { if (!r.ok) throw new Error(`the shoe's settings (${r.status})`); return r.json(); }),
      fetch("/api/captures").then((r) => { if (!r.ok) throw new Error(`the library (${r.status})`); return r.json(); }),
    ]);
    options = opts;
    captures = list;
    capture = list.find((c) => c.capture_id === id);
  } catch (err) {
    $("root").innerHTML = `<div class="callout stop"><p>Can't reach the footscan server: ${esc(err.message)}.</p></div>`;
    return;
  }
  if (!capture) {
    $("root").innerHTML = `<p class="hint" style="color:var(--warn)">No such capture in the library.</p>`;
    return;
  }
  if (!capture.foot) {
    $("root").innerHTML = `<p class="hint" style="color:var(--warn)">A shoe needs a foot capture (left or right); this one isn't.</p>`;
    return;
  }
  clog = capture.clog || null;
  $("title").textContent = `Make a printed shoe for the ${capture.foot} foot`;
  $("root").innerHTML = formHtml();
  // the form opens as it was left when this shoe was made, else at the generator's defaults
  writeForm(valuesFrom(clog && !clog.error ? clog.choices : null, options.defaults));
  $("trials").checked = !!(clog && clog.trials);
  $("root").addEventListener("change", (e) => { if (e.target.matches('input[type="radio"]')) hints(); });
  $("read").addEventListener("click", readDescription);
  $("make").addEventListener("click", make);
  $("pair").addEventListener("click", (e) => { if (e.target.closest('[data-pair="use"]')) usePairChoices(); });
  $("fit").addEventListener("click", (e) => {
    const b = e.target.closest("[data-fit]");
    if (b?.dataset.fit === "keep") keepRecord(b);
    if (b?.dataset.fit === "take") takeSuggestion(b.dataset.made);
  });
  $("fit").addEventListener("change", (e) => { if (e.target.id === "fit-shoe") pickFitShoe(e.target.value); });
  showPair();
  await Promise.all([showResult(), showFit()]);
}

init();
