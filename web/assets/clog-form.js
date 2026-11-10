// Studio, Make shoe: the form's own arithmetic, apart from the page so it can be tested
// (tests/js/clog-form.test.mjs). What is sent to the studio for the form's values, how a description's
// reading is laid over the form, and the words for each choice. The lists and limits themselves come from
// the studio (/api/footwear/options, the generator's own tables): nothing here knows a style's name.

export const SETTING_NAMES = {
  style: "Style", fit: "Fit", toe: "Toe", cushion: "Cushioning", sole_mm: "Sole thickness",
  openness: "How open the pattern is", sock_mm: "Room for a thicker sock",
};

const NUMBERS = ["sole_mm", "sock_mm", "length_mm", "width_mm"];
const NAMES = ["style", "fit", "toe", "cushion"];

const filled = (v) => v !== undefined && v !== null && String(v).trim() !== "";

/**
 * The Make shoe request for the form's values. An empty field is left out, so the generator's own default
 * stands (the style's sole, the scan's size). The form shows openness in percent; the generator takes a share.
 */
export function choicesFrom(values) {
  const body = {};
  for (const k of NAMES) if (filled(values[k])) body[k] = values[k];
  for (const k of NUMBERS) if (filled(values[k])) body[k] = Number(values[k]);
  if (filled(values.openness_percent)) body.openness = Math.round(Number(values.openness_percent) * 10) / 1000;
  body.trials = values.trials === true;
  return body;
}

/** The form's values for choices as the studio keeps them with a shoe (the other way round from choicesFrom). */
export function valuesFrom(choices, defaults = {}) {
  const c = { ...defaults, ...(choices || {}) };
  const values = {};
  for (const k of [...NAMES, ...NUMBERS]) values[k] = filled(c[k]) ? String(c[k]) : "";
  values.openness_percent = filled(c.openness) ? String(Math.round(Number(c.openness) * 1000) / 10) : "";
  return values;
}

/**
 * A description's reading laid over the form: only the settings it speaks to change; every other field keeps
 * what the person had there.
 */
export function withReading(values, settings) {
  const read = valuesFrom(settings);
  const out = { ...values };
  for (const [k, v] of Object.entries(read)) if (v !== "") out[k] = v;
  return out;
}

/** A setting's value in words: a style by its label, a thickness in mm, openness in percent. */
export function valueText(setting, value, options) {
  if (setting === "style") return options?.styles?.find((s) => s.key === value)?.label ?? String(value);
  if (setting === "openness") return `${Math.round(Number(value) * 1000) / 10}% open`;
  if (setting === "sole_mm" || setting === "sock_mm") return `${Number(value)} mm`;
  return String(value);
}

/** One line for what a reader took from a description: the setting, its value, and the words it was read from. */
export function understoodLine(u, options) {
  const from = (u.words || []).length ? `, from ${u.words.map((w) => `“${w}”`).join(", ")}` : "";
  const judged = u.judgment ? ` (${u.judgment}; change it below if you know better)` : "";
  return `${SETTING_NAMES[u.setting] ?? u.setting}: ${valueText(u.setting, u.value, options)}${from}${judged}`;
}

/** Where a wall was let out for this foot, in words (nothing when no wall was let out by a millimetre or more). */
export function letOutText(letOut) {
  const sides = Object.entries(letOut || {}).filter(([, v]) => v.max_mm >= 1);
  if (!sides.length) return "";
  return sides.map(([side, v]) => {
    const where = (v.stretches || []).map((s) => `${Math.round(s.from_mm)} to ${Math.round(s.to_mm)} mm from the back`).join(" and ");
    return `the ${side} wall is let out by up to ${v.max_mm} mm for this foot${where ? ` (${where})` : ""}`;
  }).join("; ");
}

// ---- what the print-trial pieces showed (the questions and the rules are the studio's: footwear_fit.py) ----

/**
 * The record to keep for the trial form's values: which shoe the pieces were cut from (when it was made),
 * {question: answer picked} with the unanswered questions left out (a piece not printed yet), and the
 * person's note.
 */
export function findingsFrom(values) {
  const answers = {};
  for (const [k, v] of Object.entries(values.answers || {})) if (filled(v)) answers[k] = v;
  return { made: values.made, answers, note: String(values.note ?? "").trim() };
}

/** One suggested change in words: the setting, what the shoe had, what is suggested, and the answers it came from. */
export function changeLine(change, options) {
  const name = SETTING_NAMES[change.setting] ?? change.setting;
  const why = change.because || [];
  const because = why.length ? `, because ${why.length > 1 ? `${why.slice(0, -1).join(", ")} and ${why.at(-1)}` : why[0]}` : "";
  return `${name}: ${valueText(change.setting, change.was, options)} → ${valueText(change.setting, change.to, options)}${because}`;
}

/** A record's suggested changes laid over the form: only those settings change, like a description's reading. */
export function withSuggestion(values, changes) {
  const out = { ...values };
  for (const c of changes || []) out[c.setting] = String(c.to);
  return out;
}

/**
 * Is this shoe of the trial record the one now on the page: made then, and still matching its scan? Only then
 * can what its pieces showed be put into the form as a change to "the shoe above".
 */
export function shoeAbove(shoe, clog) {
  return !!clog && !clog.error && !clog.stale && !!shoe?.made && shoe.made === clog.made;
}

/**
 * Which shoe the trial form is about: the one picked if a record can still be added about it, else the shoe
 * on the page, else the most recently made one that can be recorded about (``shoes`` is newest first). Null
 * where there is none: no shoe was made here with its trial pieces.
 */
export function shoeToRecord(shoes, clog, picked) {
  const open = (shoes || []).filter((s) => s.recordable);
  return open.find((s) => s.made === picked) ?? open.find((s) => !!clog && !clog.error && s.made === clog.made) ?? open[0] ?? null;
}

// ---- the other foot's shoe: a pair is two shoes, each made from its own foot's scan -------------------------

/**
 * The other foot's shoe in the library: the most recently made one that still matches its scan, or null.
 * ``captures``: the studio's list; ``capture``: the one this page is for.
 */
export function otherShoe(captures, capture) {
  const other = capture.foot === "left" ? "right" : capture.foot === "right" ? "left" : null;
  const made = (captures || []).filter((c) => c.foot === other && c.clog && !c.clog.error && !c.clog.stale);
  made.sort((a, b) => String(b.clog.made).localeCompare(String(a.clog.made)));
  return made[0] ?? null;
}

const PAIRED = [...NAMES, "sole_mm", "openness", "sock_mm"];   // a pair shares these; each foot keeps its own ruler numbers
const FORM_KEY = { openness: "openness_percent" };              // the one the form names differently (it shows a percent)

/**
 * A shoe's choices with nothing left out, as the generator fills them: its defaults, then the style's own sole
 * and pattern where those were left empty. A style without windows has no pattern to be more or less open.
 */
function inFull(choices, options) {
  const c = { ...(options.defaults || {}), ...(choices || {}) };
  const style = (options.styles || []).find((s) => s.key === c.style) || {};
  if (!filled(c.sole_mm)) c.sole_mm = style.sole_mm;
  c.openness = style.windows === false ? "" : filled(c.openness) ? c.openness : style.openness;
  return c;
}

/**
 * The settings in which the other shoe differs from this one. Compared as made, not as typed: a sole left
 * empty is the style's own, so it is the same as that number typed in. ``options``: the studio's (defaults, styles).
 */
export function pairDifferences(choices, otherChoices, options = {}) {
  const mine = inFull(choices, options), theirs = inFull(otherChoices, options);
  const said = (v) => (!filled(v) ? "" : Number.isNaN(Number(v)) ? String(v) : String(Number(v)));
  return PAIRED.filter((k) => said(mine[k]) !== said(theirs[k]));
}

/**
 * The form with the other shoe's choices, so the pair is made alike: style, fit, toe, cushioning, sole,
 * pattern and sock. The foot's ruler length and width stay as they are here: they are this foot's.
 */
export function withPairChoices(values, otherChoices, defaults = {}) {
  const theirs = valuesFrom(otherChoices, defaults);
  const out = { ...values };
  for (const k of PAIRED) out[FORM_KEY[k] ?? k] = theirs[FORM_KEY[k] ?? k];
  return out;
}

/** How the two shoes of a pair compare, in the reports' own numbers: the feet they were made for, and how far apart. */
export function pairText(mine, other) {
  const a = mine.made_for, b = other.made_for;
  const apart = Math.round(Math.abs(a.foot_length_mm - b.foot_length_mm) * 10) / 10;
  const foot = (shoe) => `${shoe.made_for.foot_length_mm} × ${shoe.made_for.foot_width_mm} mm (length from the ${shoe.made_for.length_from})`;
  const said = `This ${mine.foot} shoe is made for a foot ${foot(mine)}, the ${other.foot} one for a foot ${foot(other)}`;
  // said whether or not the two numbers match: a scan has read a foot short that a ruler read longer
  const mixed = a.length_from !== b.length_from
    ? " One length is a ruler's and the other a scan's, and the two don't always agree: measure both feet by ruler before printing a pair."
    : "";
  return `${said}: ${apart < 0.05 ? "the same length" : `${apart} mm apart in length`}.${mixed}`;
}
