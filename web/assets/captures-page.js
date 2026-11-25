// Studio: the capture library (captures.html): each capture's card, Make insole, saved shoes, comparisons.
import { ask, esc } from "/assets/studio.js";
const $ = (id) => document.getElementById(id);
const KIND_BADGE = { sole_up: `<span class="badge">sole up</span>`, sole_hanging: `<span class="badge">legs flat</span>`,
  impression: `<span class="badge">foam print</span>` };
let all = [];

async function load() {
  // the captures and the saved shoes (one insole outline per shoe model and size; none is fine), together
  const [[ok, captures], [shoesOk, shoes]] = await Promise.all([ask("/api/captures"), ask("/api/shoes")]);
  if (!ok) {
    $("list").innerHTML = `<div class="callout stop"><p>Couldn't load the scans: ${esc(captures.error || "the studio refused")}.
      If the studio isn't running, start it with <span class="mono">footscan serve</span>.</p></div>`;
    return;
  }
  all = captures;
  // not listed (an error): the menu then asks for the default, so the studio applies it or says why
  saved = shoesOk ? shoes : UNLISTED;
  render();
  if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "center" });
}

let saved = { shoes: [], default: null };
const UNLISTED = { shoes: [], default: null, unlisted: true };
const building = new Set();     // captures whose insole is being made now (from this page)
let onlyAttention = false;      // show only the scans whose insole needs making again (or failed)
let remaking = null;            // {done, of} while "Make them all again" runs
let note = "";                  // one line of news for the top of the list (a shoe saved, insoles remade)

// An insole that can't be downloaded until it's made again: it no longer matches what it was made from
// (STALE_MESSAGES on the server says why), or the last attempt failed
const needsAttention = (c) => Boolean(c.insole?.stale || c.insole?.error);
const STALE_SHORT = {
  model: "the 3D model was replaced or rebuilt", shoe: "the shoe it was cut to was saved again or removed",
  prep: "the way sole scans are prepared has changed", outline: "cut to the foot's own outline, from before the generic outline",
};

function renderAttention() {
  const stale = all.filter((c) => c.insole?.stale), failed = all.filter((c) => c.insole?.error);
  const why = {};
  for (const c of stale) why[c.insole.stale_reason] = (why[c.insole.stale_reason] || 0) + 1;
  const n = stale.length + failed.length;
  const parts = [];
  if (note) parts.push(`<div class="callout brand" style="margin-bottom:12px"><p>${esc(note)}</p></div>`);
  if (n || onlyAttention) {
    const reasons = Object.entries(why).map(([k, m]) => `${esc(STALE_SHORT[k] || "it no longer matches")} (${m})`).join("; ");
    parts.push(`<div class="callout warn" style="margin-bottom:16px">
      <p><strong>${n === 0 ? "Every insole is up to date." : `${n} insole${n === 1 ? "" : "s"} can't be downloaded until made again`}</strong>
      ${stale.length ? `<br><span class="hint">${stale.length} out of date: ${reasons}.</span>` : ""}
      ${failed.length ? `<br><span class="hint">${failed.length} failed the last time; the card says why.</span>` : ""}
      ${remaking ? `<br><span class="hint">Making them again: ${remaking.done} of ${remaking.of} done…</span>` : ""}</p>
      <p class="btn-row" style="margin:10px 0 0">
        ${stale.length ? `<button class="btn" type="button" id="remake-all" ${remaking || building.size ? "disabled" : ""}>Make the out-of-date ones again</button>` : ""}
        <button class="btn secondary" type="button" id="only-attention" aria-pressed="${onlyAttention}">${onlyAttention ? "Show every scan" : "Show only these"}</button></p>
      <p class="hint" style="margin:8px 0 0">Each is made again with the outline and length it was made with. One cut to a shoe that is no longer saved is left for you to choose.</p></div>`);
  }
  $("attention").innerHTML = parts.join("");
}

// The search box: every word typed is found somewhere in the capture's name, session or notes (any case)
function matchesWords(c, typed) {
  const hay = [c.capture_id, c.session, c.notes, c.foot && `${c.foot} foot`].filter(Boolean).join(" ").toLowerCase();
  return typed.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

function render() {
  const cond = $("f-cond").value, foot = $("f-foot").value;
  // Phase 0 counts photo scans only: LiDAR imports and object tests are a
  // different method and would muddy the repeatability numbers.
  const complete = all.filter((c) => c.status === "complete" && c.method !== "imported_mesh" && c.measurable !== false);
  $("counts").innerHTML = ["nwb", "nwb_relaxed", "swb", "fwb"].map((k) => {
    const n = complete.filter((c) => c.condition === k && (!foot || c.foot === foot)).length;
    const sessions = new Set(complete.filter((c) => c.condition === k && (!foot || c.foot === foot)).map((c) => c.session)).size;
    const cls = n >= 10 && sessions >= 2 ? "ok" : n ? "warn" : "";
    return `<span class="badge ${cls}">${k}: ${n}/10 · ${sessions} session${sessions === 1 ? "" : "s"}</span>`;
  }).join("");

  renderAttention();
  const words = $("f-text").value;
  const rows = all.filter((c) => (!cond || c.condition === cond) && (!foot || c.foot === foot)
    && (!onlyAttention || needsAttention(c)) && matchesWords(c, words));
  if (!rows.length) {
    $("list").innerHTML = all.length
      ? `<div class="card" style="text-align:center;padding:40px">
      <h3>Nothing matches</h3><p class="muted">${all.length} capture${all.length === 1 ? "" : "s"} in the library, none of them with these filters.</p>
      <button class="btn secondary" type="button" id="clear-filters">Show every capture</button></div>`
      : `<div class="card" style="text-align:center;padding:40px">
      <h3>No captures yet</h3><p class="muted">Real captures you save from the capture page, and scans the iPhone app sends, appear here.</p>
      <a class="btn" href="/studio/capture.html">Make the first capture</a></div>`;
    showThumbs();
    return;
  }
  $("list").innerHTML = rows.map((c) => {
    const s = c.summary || {};
    // a picture of the 3-D model from above (drawn by the studio the first time it's asked for; a few seconds)
    const thumb = c.mesh
      ? `<img class="thumb" data-thumb data-src="/api/captures/${encodeURIComponent(c.capture_id)}/thumb.png" alt="The 3D model of ${esc(c.capture_id)}, seen from above">`
      : c.frame_files?.length
      ? `<img src="/api/captures/${esc(c.capture_id)}/frames/1.jpg" alt="First frame of ${esc(c.capture_id)}" loading="lazy">`
      : `<div class="noimg"></div>`;
    const status = c.status === "complete" ? `<span class="badge ok">complete</span>` : `<span class="badge warn">${esc(c.status)}</span>`;
    // a model sent by the iPhone app or imported: no photos, so no coverage or skin texture to show
    const imported = c.method === "imported_mesh";
    const cov = s.coverage_completeness == null ? "—" : `${Math.round(100 * s.coverage_completeness)}%`;
    return `<article class="card cap" id="${esc(c.capture_id)}">${thumb}<div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:4px">
        <span class="badge brand">${esc(c.condition)}</span>${KIND_BADGE[c.scan_kind] ?? ""}${c.foot ? `<span class="badge">${esc(c.foot)} foot</span>` : c.condition === "calibration" ? `<span class="badge">accuracy study</span>` : c.condition === "shoe_insole" ? `<span class="badge">for Make insole: fit to this shoe</span>` : `<span class="badge warn">not measurable</span>`}${status}</div>
      <h3 class="mono">${esc(c.capture_id)}</h3>
      <dl>
        <div><dt>Session</dt><dd>${esc(c.session)}</dd></div>
        ${c.load_kg == null && imported ? "" : `<div><dt>Load</dt><dd>${c.load_kg == null ? "—" : esc(c.load_kg) + " kg"}</dd></div>`}
        ${c.mesh
          ? `<div><dt>3D model</dt><dd>${c.mesh.extents_mm[0]} × ${c.mesh.extents_mm[1]} × ${c.mesh.extents_mm[2]} mm</dd></div>`
          : `<div><dt>Frames</dt><dd>${c.frame_files?.length ?? 0}</dd></div>`}
        ${imported ? "" : `<div><dt>Coverage</dt><dd>${cov}</dd></div>
        <div><dt>Texture</dt><dd>${esc(c.method)}</dd></div>`}
        <div><dt>Created</dt><dd>${esc(c.created?.replace("T", " "))}</dd></div>
        ${c.device ? `<div><dt>Device</dt><dd>${esc(c.device)}</dd></div>` : ""}
        ${c.accuracy && !c.accuracy.error
          ? `<div><dt>Accuracy</dt><dd>${esc(c.accuracy.median_mm)} mm typical · length ${c.accuracy.length_mm == null ? "—" : (c.accuracy.length_mm > 0 ? "+" : "") + Number(c.accuracy.length_mm).toFixed(2) + " mm"}${c.accuracy.scale_pct == null ? "" : ` · size ${c.accuracy.scale_pct > 0 ? "+" : ""}${Number(c.accuracy.scale_pct).toFixed(1)}%`}</dd></div>` : ""}
      </dl>
      ${c.accuracy?.error ? `<p class="hint" style="margin:8px 0 0;color:var(--warn)">${esc(c.accuracy.error)}</p>` : ""}
      ${c.accuracy && !c.accuracy.error ? `<p class="hint" style="margin:6px 0 0"><a href="/api/captures/${encodeURIComponent(c.capture_id)}/accuracy">Full accuracy report</a></p>` : ""}
      ${notesHtml(c)}
      <p class="btn-row" style="margin:10px 0 0">
        ${(c.status === "complete" && c.frame_files?.length && c.condition !== "object") || (imported && c.mesh)
          ? `<a class="btn secondary" href="/studio/model.html?capture=${encodeURIComponent(c.capture_id)}">3D model</a>` : ""}
        ${c.foot && (c.frame_files?.length || c.mesh)
          ? `<a class="btn secondary" href="/studio/landmarks.html?capture=${encodeURIComponent(c.capture_id)}">Landmarks</a>` : ""}
        ${c.condition === "shoe_insole" && c.mesh
          ? `<button class="btn secondary" type="button" data-save-shoe="${esc(c.capture_id)}" aria-expanded="${Boolean(shoeForms[c.capture_id]?.open)}">Save as a shoe</button>` : ""}
        ${c.foot && (c.frame_files?.length || c.mesh)
          ? `${shoePicker(c)}<span class="shoe-len"><input type="number" inputmode="decimal" min="150" max="360" step="1"
               placeholder="shoe insole, mm" aria-label="Shoe insole length in mm (optional)" data-length-for="${esc(c.capture_id)}"
               value="${c.insole && !c.insole.error ? (c.insole.shoe_length_mm ?? "") : outlineChoice(c) === "generic" ? lastShoeLength() : ""}" style="width:9.5em" ${takesLength(outlineChoice(c)) ? "" : "disabled"}></span>
             <button class="btn secondary" type="button" data-insole="${esc(c.capture_id)}" ${building.has(c.capture_id) ? "disabled" : ""}>${
               building.has(c.capture_id) ? "Making the insole…" : c.insole && !c.insole.error ? "Remake insole" : "Make insole"}</button>
             <a class="btn secondary" href="/studio/clog.html?capture=${encodeURIComponent(c.capture_id)}">${c.clog && !c.clog.error ? "Printed shoe" : "Make printed shoe"}</a>` : ""}</p>
      ${c.condition === "shoe_insole" && c.mesh ? saveShoeForm(c) : ""}
      <div class="insole-out" id="insole-${esc(c.capture_id)}">${c.insole ? insoleHtml(c.capture_id, c.insole) : ""}</div>
      ${clogHtml(c)}
      ${compareHtml(c)}
    </div></article>`;
  }).join("");
  showThumbs();
}

// The insole's outline: a saved shoe's (one outline per shoe model and size, footscan/shoes.py), a scanned
// shoe's insole (recon/shoe.py), the generic insole outline (one shoe insole shape, scaled as a whole to the
// length given, or to the foot's), or the foot's own (optionally lengthened). A length goes with the last two.
// What the menu shows: what was picked on this card since the page loaded, else what the last insole was made
// with (the server records it), else the default saved shoe, else the generic outline. An insole made with
// nothing chosen follows the default (so once a shoe is saved as the default, the menu picks it).
const picked = {};
function outlineChoice(c) {
  if (picked[c.capture_id]) return picked[c.capture_id];
  const ins = c.insole && !c.insole.error ? c.insole : undefined;
  const shoe = ins?.shoe;
  if (shoe?.saved && saved.shoes.some((s) => s.id === shoe.saved)) return `saved:${shoe.saved}`;
  if (shoe?.capture && all.some((s) => s.capture_id === shoe.capture)) return `scan:${shoe.capture}`;
  // the foot's own, chosen: made since outlines were recorded (outline_shape), or without a length. An older
  // insole lengthened for a shoe was the foot's outline only because that was the only way: it's stale, and
  // made again it gets the generic outline at that length
  if (ins && !shoe && ins.outline === "foot" && (ins.outline_shape === "foot" || ins.shoe_length_mm == null)) return "foot";
  if (ins && !shoe && ins.outline === "generic") return "generic";
  // a default that was chosen but can't be read: ask for it anyway, so Make insole says what's wrong with it
  // instead of quietly cutting the insole to another outline
  return saved.default ? `saved:${saved.default}` : saved.default_problem || saved.unlisted ? "" : "generic";
}

const takesLength = (choice) => choice === "generic" || choice === "foot";

// The shoe's insole length last used for an insole made in this browser: offered on cards with no insole yet, so
// it's typed once (the generic outline is then the shoe's size, whatever the scan reads). A card that has an
// insole shows the length that insole was made with (none: sized from the foot), so Remake makes the same one.
// Only a convenience: without it (private window, cleared storage), the box starts empty.
const LENGTH_KEY = "footscan.shoeLengthMm";
const plausibleLength = (v) => { const n = Number(v); return Number.isFinite(n) && n >= 150 && n <= 360; };
function lastShoeLength() {
  try { const v = localStorage.getItem(LENGTH_KEY); return plausibleLength(v) ? v : ""; } catch { return ""; }
}
function rememberShoeLength(len) {
  try { if (plausibleLength(len)) localStorage.setItem(LENGTH_KEY, String(len)); } catch { /* nothing kept */ }
}

function shoePicker(c) {
  const scans = all.filter((s) => s.condition === "shoe_insole" && s.mesh);
  const chosen = outlineChoice(c);
  const opt = (value, label) => `<option value="${esc(value)}" ${value === chosen ? "selected" : ""}>${label}</option>`;
  return `<select data-shoe-for="${esc(c.capture_id)}" aria-label="The insole's outline: a shoe's, the generic insole's, or the foot's own">
    ${saved.default_problem ? opt("", "Outline: the default saved shoe (can't be read)") : ""}
    ${saved.unlisted ? opt("", "Outline: the default saved shoe, if any (the saved shoes couldn't be listed)") : ""}
    ${saved.shoes.map((s) => opt(`saved:${s.id}`, `Outline: ${esc(s.name)}, ${esc(s.size)}${s.id === saved.default ? " (default)" : ""}`)).join("")}
    ${scans.map((s) => opt(`scan:${s.capture_id}`, `Outline: the shoe's insole scanned ${esc(s.created?.slice(0, 16).replace("T", " "))}`)).join("")}
    ${opt("generic", "Outline: a generic insole, the shoe's length")}
    ${opt("foot", "Outline: the foot's own")}</select>`;
}

document.addEventListener("change", (e) => {
  const sel = e.target.closest("[data-shoe-for]");
  if (!sel) return;
  picked[sel.dataset.shoeFor] = sel.value;
  const len = document.querySelector(`[data-length-for="${CSS.escape(sel.dataset.shoeFor)}"]`);
  if (len) {
    len.disabled = !takesLength(sel.value);
    if (!takesLength(sel.value)) len.value = "";
    else if (!len.value && sel.value === "generic") len.value = lastShoeLength();
  }
});

// A capture's notes, changed on its card (the iPhone app's say only how it scanned, not which sock or how the foot
// stood). What is being typed is kept here, like the shoe form, so the list being drawn again doesn't lose it.
const noteEdits = {}; // capture id -> {text, saving, msg}

function notesHtml(c) {
  const id = esc(c.capture_id), ed = noteEdits[c.capture_id];
  if (!ed) {
    return `<p class="hint notes" style="margin:8px 0 0">${c.notes ? esc(c.notes) : ""}
      <button class="linkish" type="button" data-edit-notes="${id}">${c.notes ? "Edit notes" : "Add notes"}</button></p>`;
  }
  return `<form data-notes-form="${id}" style="margin:8px 0 0;display:grid;gap:8px">
    <label class="hint" for="notes-${id}">Notes (the library's search finds them)</label>
    <textarea id="notes-${id}" name="notes" rows="2" maxlength="2000">${esc(ed.text)}</textarea>
    <p class="btn-row" style="margin:0"><button class="btn secondary" type="submit" ${ed.saving ? "disabled" : ""}>Save notes</button>
      <button class="btn secondary" type="button" data-notes-cancel="${id}">Cancel</button>
      <span class="hint" role="status">${esc(ed.msg || "")}</span></p></form>`;
}

document.addEventListener("input", (e) => {
  const f = e.target.closest("[data-notes-form]");
  if (f && noteEdits[f.dataset.notesForm]) noteEdits[f.dataset.notesForm].text = f.elements.notes.value;
});
document.addEventListener("click", (e) => {
  const open = e.target.closest("[data-edit-notes]"), cancel = e.target.closest("[data-notes-cancel]");
  if (open) {
    const id = open.dataset.editNotes;
    noteEdits[id] = { text: all.find((c) => c.capture_id === id)?.notes || "" };
    render();
    document.getElementById(`notes-${id}`)?.focus();
  } else if (cancel) {
    delete noteEdits[cancel.dataset.notesCancel];
    render();
  }
});
document.addEventListener("submit", async (e) => {
  const f = e.target.closest("[data-notes-form]");
  if (!f) return;
  e.preventDefault();
  const id = f.dataset.notesForm, ed = noteEdits[id];
  ed.saving = true; ed.msg = "Saving…"; render();
  const [ok, out] = await ask(`/api/captures/${encodeURIComponent(id)}/notes`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notes: ed.text }),
  });
  if (!ok) { ed.saving = false; ed.msg = `Couldn't save: ${out.error}`; render(); return; }
  delete noteEdits[id];
  const c = all.find((x) => x.capture_id === id);  // the list as it is now (it may have been loaded again)
  if (c) c.notes = out.notes;
  render();
});

// Save a shoe's-insole scan as a saved shoe: its outline, kept for that shoe model and size. A small form on the
// card (not the browser's prompt boxes, which a phone shows one at a time over the page)
// What is open and typed in each card's form, kept here so the list being drawn again (an insole finishing on
// another card) doesn't close it or lose what was typed
const shoeForms = {}; // capture id -> {open, name, size, default, msg, saving}

function saveShoeForm(c) {
  const id = esc(c.capture_id);
  const f = shoeForms[c.capture_id] || {};
  return `<form class="card" data-save-shoe-form="${id}" ${f.open ? "" : "hidden"} style="margin-top:10px;padding:12px;display:grid;gap:10px">
    <div class="field"><label for="shoe-name-${id}">Which shoe is this insole from?</label>
      <input id="shoe-name-${id}" name="name" type="text" maxlength="60" required placeholder="e.g. ASICS Gel Resolution X" value="${esc(f.name)}"></div>
    <div class="field"><label for="shoe-size-${id}">Which size?</label>
      <input id="shoe-size-${id}" name="size" type="text" maxlength="24" required placeholder="e.g. US men's 9.5" value="${esc(f.size)}"></div>
    <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" name="default" style="width:auto" ${f.default ? "checked" : ""}>
      Make it the default: new insoles take this shoe's outline unless another is chosen</label>
    <p class="btn-row" style="margin:0"><button class="btn" type="submit" ${f.saving ? "disabled" : ""}>Save the shoe</button>
      <button class="btn secondary" type="button" data-save-shoe-cancel>Cancel</button></p>
    <p class="hint" role="status" style="margin:0">${esc(f.msg)}</p></form>`;
}

function shoeFormState(form) {
  const id = form.dataset.saveShoeForm;
  return (shoeForms[id] = { ...shoeForms[id], name: form.elements.name.value, size: form.elements.size.value,
    default: form.elements.default.checked });
}
document.addEventListener("input", (e) => { const f = e.target.closest("[data-save-shoe-form]"); if (f) shoeFormState(f); });
document.addEventListener("change", (e) => { const f = e.target.closest("[data-save-shoe-form]"); if (f) shoeFormState(f); });

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-save-shoe], [data-save-shoe-cancel]");
  if (!btn) return;
  const form = btn.dataset.saveShoe
    ? document.querySelector(`[data-save-shoe-form="${CSS.escape(btn.dataset.saveShoe)}"]`) : btn.closest("form");
  if (!form) return;
  form.hidden = !form.hidden;
  shoeFormState(form).open = !form.hidden;
  const opener = document.querySelector(`[data-save-shoe="${CSS.escape(form.dataset.saveShoeForm)}"]`);
  opener?.setAttribute("aria-expanded", String(!form.hidden));
  if (!form.hidden) form.elements.name.focus();
});

document.addEventListener("submit", async (e) => {
  const form = e.target.closest("[data-save-shoe-form]");
  if (!form) return;
  e.preventDefault();
  const id = form.dataset.saveShoeForm;
  const f = shoeFormState(form);
  // the message and the button through the state, so a redraw meanwhile shows them too
  const say = (msg, saving = false) => {
    Object.assign(f, { msg, saving });
    const now = document.querySelector(`[data-save-shoe-form="${CSS.escape(id)}"]`);
    if (now) { now.querySelector("[role=status]").textContent = msg; now.querySelector("button[type=submit]").disabled = saving; }
  };
  const name = f.name.trim(), size = f.size.trim();
  if (!name || !size) return say("Say which shoe and which size.");
  say("Reading the insole's outline…", true);
  const [ok, out] = await ask("/api/shoes", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ capture: id, name, size, default: f.default }) });
  if (!ok) return say(`Couldn't save the shoe: ${out.error || "the studio refused"}`);
  delete shoeForms[id];
  note = `Saved: ${out.name}, ${out.size} (${out.length_mm} × ${out.width_mm} mm)${f.default ? ", the default for new insoles" : ""}.`;
  await load(); // the captures too: insoles cut to an earlier save of this shoe are stale now
});

// Repeatability: compare this scan with another of the same foot (recon/compare.py)
function compareHtml(c) {
  if (!c.foot || !(c.mesh || c.status === "complete")) return "";
  const others = all.filter((o) => o.capture_id !== c.capture_id && o.foot === c.foot && (o.mesh || o.status === "complete"));
  if (!others.length) return "";
  return `<p class="btn-row" style="margin:8px 0 0">
    <select data-compare-with="${esc(c.capture_id)}" aria-label="Another scan of the same foot to compare with">
      ${others.map((o) => `<option value="${esc(o.capture_id)}">${esc(o.capture_id)}${o.scan_kind ? ` · ${esc(o.scan_kind)}` : ""}</option>`).join("")}
    </select>
    <button class="btn secondary" type="button" data-compare="${esc(c.capture_id)}">Compare scans</button></p>
    <p class="hint" id="compare-${esc(c.capture_id)}" style="margin:6px 0 0"></p>`;
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-compare]");
  if (!btn) return;
  const a = btn.dataset.compare;
  const b = document.querySelector(`[data-compare-with="${CSS.escape(a)}"]`)?.value;
  const out = document.getElementById(`compare-${a}`);
  btn.disabled = true;
  out.textContent = "Comparing the two scans…";
  const [ok, res] = await ask("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ a, b }) });
  out.textContent = ok && !res.error
    ? `${res.verdict} (95% within ${res.p95_mm} mm; average difference ${res.bias_mm} mm; ${res.points} points)`
    : `Couldn't compare: ${res.error || "the studio refused"}`;
  btn.disabled = false;
});

// The printed shoe (a clog) made from this capture (its own page makes it and shows it): one line here, so the
// library says there is one and whether it still matches the scan. "Printed", because a shoe on this page is
// otherwise a bought shoe an insole is cut to fit. Not a medical device; walking and casual wear only.
function clogHtml(c) {
  const r = c.clog;
  if (!r || r.error) return "";
  const page = `/studio/clog.html?capture=${encodeURIComponent(c.capture_id)}`;
  if (r.stale) return `<p class="hint" style="color:var(--warn);margin:8px 0 0">The 3D model has changed since this capture's printed
    shoe was made, so it no longer matches. <a href="${page}">Make it again</a>.</p>`;
  return `<p class="hint" style="margin:8px 0 0"><strong>Printed shoe</strong> (clog, ${esc(r.style)}, ${esc(r.length_mm)} × ${esc(r.width_mm)} mm,
    untested design, walking and casual wear only): <a href="${page}">open it</a>.</p>`;
}

// First-fit insole: not a medical device; no posting; walking-only until a clinician signs the sheet.
function insoleHtml(id, r) {
  if (r.error) return `<p class="hint" style="color:var(--warn);margin:8px 0 0">${esc(r.error)}</p>`;
  if (r.stale) return `<p class="hint" style="color:var(--warn);margin:8px 0 0">${esc(r.stale_message || "This insole no longer matches what it was made from.")}
    Press Remake insole to make it again.</p>`;
  const base = `/api/captures/${encodeURIComponent(id)}/insole/`;
  const warn = (r.warnings || []).map((w) => `<li>${esc(w.charAt(0).toUpperCase() + w.slice(1))}</li>`).join("");
  return `<div class="card" style="margin-top:10px;padding:12px">
    <strong>First-fit insole</strong> <span class="badge">${esc(r.foot)} foot</span> <span class="badge">no posting</span>
    <p class="hint" style="margin:6px 0">${r.length_mm} × ${r.width_mm} mm, ${r.height_mm} mm tall · highest arch fill ${r.max_fill_mm} mm${r.foot_max_fill_mm > r.max_fill_mm + 0.5
        ? ` (${r.foot_max_fill_mm} mm under the foot, past the outline's edge)` : ""} ·
      sole seen ${Math.round(100 * r.sole.seen)}% (arch ${Math.round(100 * r.sole.seen_under_arch)}%) · bed: ${esc(r.bed.how)}</p>
    ${r.generic?.fit ? `<p class="hint" style="margin:0 0 6px">Outline: a generic insole, the same shape for every foot, ${esc(r.generic.length_mm)} mm
      ${r.shoe_length_mm ? "(the shoe's length)" : "(sized from the scanned foot: enter the shoe's insole length to make it the shoe's size)"},
      ${esc(r.generic.fit.room_past_toes_mm)} mm past the toes${r.generic.fit.overhang.max_mm > 1
        ? `; the foot is over its edge by up to ${esc(r.generic.fit.overhang.max_mm)} mm at the ${esc(r.generic.fit.overhang.where)}` : "; the foot is inside it all round"}.</p>`
    : !r.shoe ? `<p class="hint" style="margin:0 0 6px">Outline: the foot's own${r.shoe_length_mm ? `, lengthened to the shoe's ${esc(r.shoe_length_mm)} mm` : " (no shoe chosen)"}: trim it to the shoe's stock insole.</p>` : ""}
    ${r.shoe?.fit ? `<p class="hint" style="margin:0 0 6px">Outline: ${r.shoe.name ? esc(r.shoe.name) : "the shoe's own insole"} (${esc(r.shoe.fit.shoe_length_mm)} mm),
      ${esc(r.shoe.fit.room_past_toes_mm)} mm past the toes${r.shoe.fit.overhang.max_mm > 1
        ? `; the foot is over its edge by up to ${esc(r.shoe.fit.overhang.max_mm)} mm at the ${esc(r.shoe.fit.overhang.where)}` : "; the foot is inside it all round"}.</p>` : ""}
    ${warn ? `<ul class="checklist" style="margin:6px 0;color:var(--warn)">${warn}</ul>` : ""}
    <p class="btn-row" style="margin:8px 0 0">
      <a class="btn" href="${base}insole.3mf">3MF for Bambu Studio</a>
      <a class="btn secondary" href="/studio/insole.html?capture=${encodeURIComponent(id)}">3D preview</a>
      <a class="btn secondary" href="${base}summary.html" target="_blank" rel="noopener">Summary sheet</a>
      <a class="btn secondary" href="${base}print-notes.txt" target="_blank" rel="noopener">Print notes</a>
      <a class="btn secondary" href="${base}insole.stl">STL</a></p>
    <p class="hint" style="margin:8px 0 0">Not a medical device. Walking-only break-in; no sport until a clinician has signed the summary sheet.</p>
  </div>`;
}

// The request for an insole with this outline choice (the menu's value) and shoe's insole length (mm, or "")
function insoleRequest(c, pick, len) {
  // the outline: a shoe's (saved, or a scanned insole), fitted round the foot; or the generic insole outline
  // or the foot's own, each with the shoe's insole length if given (the generic one is scaled to it as a
  // whole; the foot's own is lengthened at the front, the foot-shaped part unchanged)
  const id = c.capture_id;
  const length = len ? { length_mm: Number(len) } : {};
  return pick?.startsWith("saved:") ? { saved_shoe: pick.slice(6) }
    : pick?.startsWith("scan:") ? { shoe: pick.slice(5) }
    : pick === "foot" ? { foot_outline: true, ...length }
    // the generic outline only because nothing else was chosen (no default saved shoe): don't say generic, so
    // the insole follows a default shoe saved later; chosen on purpose (now or for the last insole): say so
    : pick === "generic" ? { ...length, ...(picked[id] === "generic" || c.insole?.outline === "generic"
      ? { generic: true } : {}) } : {};
}

// Make (or remake) one capture's insole; its card shows the result. The button counts the seconds meanwhile.
async function makeInsole(c, pick, len) {
  const id = c.capture_id;
  building.add(id);
  const t0 = Date.now();
  const button = () => document.querySelector(`[data-insole="${CSS.escape(id)}"]`);
  const tick = () => { const b = button(); if (b) { b.disabled = true; b.textContent = `Making the insole… ${Math.round((Date.now() - t0) / 1000)} s`; } };
  tick();
  const timer = setInterval(tick, 1000);
  const [ok, out] = await ask(`/api/captures/${encodeURIComponent(id)}/insole`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(insoleRequest(c, pick, len)),
  });
  clearInterval(timer);
  building.delete(id);
  // remembered only once an insole was made with it (a refused length isn't offered again)
  if (ok && !out.error && len && takesLength(pick ?? "generic")) rememberShoeLength(len);
  // Keep the result with the capture, then redraw from that, so filtering (even
  // mid-build) neither loses it nor brings back an older one. The list may have been loaded again meanwhile (a
  // shoe saved): the result goes on the capture as it is now listed.
  const now = all.find((x) => x.capture_id === id) || c;
  now.insole = ok ? out : { error: `Couldn't make it: ${out.error || "the studio refused"}` };
  render();
  return !now.insole.error;
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-insole]");
  if (!btn) return;
  const id = btn.dataset.insole;
  const capture = all.find((c) => c.capture_id === id);
  if (!capture || building.has(id)) return;
  const len = document.querySelector(`[data-length-for="${CSS.escape(id)}"]`)?.value.trim();
  const pick = document.querySelector(`[data-shoe-for="${CSS.escape(id)}"]`)?.value;
  note = "";
  await makeInsole(capture, pick, len);
});

// The outline an out-of-date insole is made again with: the one it was made with, from its own record. A shoe it
// was cut to that is no longer there (or the saved shoes couldn't be listed) gives null: that insole is left for
// a person to choose, never quietly cut to another shoe. One made with the default outline, or the foot's own
// before the generic outline was the default, takes what its card's menu shows.
function remakeChoice(c) {
  const shoe = c.insole?.shoe;
  if (shoe?.saved) return saved.shoes.some((s) => s.id === shoe.saved) ? `saved:${shoe.saved}` : null;
  if (shoe?.capture) return all.some((s) => s.capture_id === shoe.capture && s.mesh) ? `scan:${shoe.capture}` : null;
  return outlineChoice(c);
}

// Every out-of-date insole made again, one at a time (each takes the studio a few seconds and the whole
// computer's attention), each with the outline and length it was made with
document.addEventListener("click", async (e) => {
  if (e.target.closest("#only-attention")) { onlyAttention = !onlyAttention; render(); return; }
  if (e.target.closest("#clear-filters")) {
    $("f-cond").value = ""; $("f-foot").value = ""; $("f-text").value = ""; onlyAttention = false; refilter(); return;
  }
  if (!e.target.closest("#remake-all") || remaking) return;
  const stale = all.filter((c) => c.insole?.stale && !building.has(c.capture_id));
  const todo = stale.map((c) => [c, remakeChoice(c)]).filter(([, pick]) => pick !== null);
  const skipped = stale.length - todo.length;
  remaking = { done: 0, of: todo.length };
  note = "";
  render();
  let failed = 0;
  for (const [c, pick] of todo) {
    const len = takesLength(pick) ? String(c.insole?.shoe_length_mm ?? "") : "";
    if (!(await makeInsole(c, pick, len))) failed += 1;
    remaking.done += 1;
    render();
  }
  remaking = null;
  const made = todo.length - failed;
  note = `Made ${made} insole${made === 1 ? "" : "s"} again.`
    + (failed ? ` ${failed} couldn't be made (the card says why).` : "")
    + (skipped ? ` ${skipped} left as ${skipped === 1 ? "it was" : "they were"}: the shoe ${skipped === 1 ? "it was" : "they were"} cut to`
      + " is no longer saved (or the saved shoes couldn't be listed); choose an outline on the card and press Remake insole." : "");
  render();
});

// The pictures of the models (thumb.png), asked for two at a time, newest first: the studio draws each the first
// time (a second or so), and a library of 30 new scans asking at once would fill every connection the browser
// keeps to the studio, so Make insole would wait behind them. One already fetched is shown at once.
const thumbs = new Map(); // src -> "queued" | "loading" | "done" | "failed"
let thumbsLoading = 0;
const THUMBS_AT_ONCE = 2;

function plainBox(img) { // a model the studio couldn't draw: the plain box, as before pictures
  const box = document.createElement("div");
  box.className = "noimg";
  box.style.cssText = "display:grid;place-items:center;font-weight:700;color:var(--brand)";
  box.textContent = "3D";
  img.replaceWith(box);
}

function showThumbs() {
  for (const img of document.querySelectorAll("img[data-thumb]:not([src])")) {
    const state = thumbs.get(img.dataset.src);
    if (state === "done") img.src = img.dataset.src;
    else if (state === "failed") plainBox(img);
    else if (!state) thumbs.set(img.dataset.src, "queued");
  }
  while (thumbsLoading < THUMBS_AT_ONCE) {
    const next = [...thumbs].find(([, state]) => state === "queued");
    if (!next) return;
    const src = next[0];
    thumbs.set(src, "loading");
    thumbsLoading += 1;
    const probe = new Image();
    const settle = (state) => { thumbs.set(src, state); thumbsLoading -= 1; showThumbs(); };
    probe.addEventListener("load", () => settle("done"));
    probe.addEventListener("error", () => settle("failed"));
    probe.src = src;
  }
}

// The filters live in the page's address (?q=…&condition=…&foot=…), so a reload, or Back from a capture's
// pages, comes back to the same list, and a filtered list can be bookmarked
const FILTERS = [["q", "f-text"], ["condition", "f-cond"], ["foot", "f-foot"]];
function filtersFromAddress() {
  const q = new URLSearchParams(location.search);
  for (const [name, id] of FILTERS) {
    const v = q.get(name);
    // a menu takes only one of its own choices: anything else in the address is left out
    if (v != null && ($(id).tagName !== "SELECT" || [...$(id).options].some((o) => o.value === v))) $(id).value = v;
  }
}
function filtersToAddress() {
  const q = new URLSearchParams(location.search);
  for (const [name, id] of FILTERS) { if ($(id).value) q.set(name, $(id).value); else q.delete(name); }
  const search = q.toString();
  history.replaceState(history.state, "", `${location.pathname}${search ? `?${search}` : ""}${location.hash}`);
}
const refilter = () => { filtersToAddress(); render(); };
$("f-cond").addEventListener("change", refilter);
$("f-foot").addEventListener("change", refilter);
$("f-text").addEventListener("input", refilter);
// "/" jumps to the search box (as on many sites), unless something is being typed already
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]")) return;
  e.preventDefault();
  $("f-text").focus();
});
filtersFromAddress();
load();
