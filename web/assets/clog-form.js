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
