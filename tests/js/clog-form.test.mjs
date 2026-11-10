import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SETTING_NAMES, choicesFrom, letOutText, understoodLine, valueText, valuesFrom, withReading,
} from "../../web/assets/clog-form.js";

// As /api/footwear/options sends them (the generator's own tables): the page knows no style's name itself.
const OPTIONS = {
  styles: [{ key: "vent", label: "Vent" }, { key: "stream", label: "Stream" }, { key: "stone", label: "Stone" }],
};
const EMPTY = {
  style: "", fit: "", toe: "", cushion: "", sole_mm: "", sock_mm: "", length_mm: "", width_mm: "", openness_percent: "",
};

test("an empty field is left out of the request, so the generator's own default stands", () => {
  assert.deepEqual(choicesFrom(EMPTY), { trials: false });
  assert.deepEqual(choicesFrom({ ...EMPTY, sole_mm: "  ", length_mm: null, width_mm: undefined }), { trials: false });
});

test("the form's fields are sent as the settings the studio checks: names as they are, numbers as numbers", () => {
  const sent = choicesFrom({
    style: "stone", fit: "roomy", toe: "square", cushion: "soft",
    sole_mm: "24", sock_mm: "1.5", length_mm: "260", width_mm: "97", openness_percent: "", trials: true,
  });
  assert.deepEqual(sent, {
    style: "stone", fit: "roomy", toe: "square", cushion: "soft",
    sole_mm: 24, sock_mm: 1.5, length_mm: 260, width_mm: 97, trials: true,
  });
});

test("a thinner sock of 0 mm is a choice, not an empty field", () => {
  assert.equal(choicesFrom({ ...EMPTY, sock_mm: "0" }).sock_mm, 0);
  assert.equal(choicesFrom({ ...EMPTY, sock_mm: 0 }).sock_mm, 0);
});

test("the form shows how open the pattern is in percent; the generator takes a share", () => {
  assert.equal(choicesFrom({ ...EMPTY, openness_percent: "38" }).openness, 0.38);
  assert.equal(choicesFrom({ ...EMPTY, openness_percent: "26.4" }).openness, 0.264);
  assert.equal(choicesFrom({ ...EMPTY, openness_percent: "0" }).openness, 0);
  assert.equal(valuesFrom({ openness: 0.38 }).openness_percent, "38");
  assert.equal(valuesFrom({ openness: 0.264 }).openness_percent, "26.4");
  assert.equal(valuesFrom({}).openness_percent, "");
});

test("trial pieces are asked for only by the box being ticked", () => {
  assert.equal(choicesFrom({ ...EMPTY, trials: true }).trials, true);
  for (const v of [false, undefined, "true", 1, "on"]) assert.equal(choicesFrom({ ...EMPTY, trials: v }).trials, false);
});

test("a shoe's kept choices fill the form again, over the generator's defaults, and send back the same", () => {
  const kept = { style: "stream", fit: "snug", sole_mm: 18, openness: 0.3, length_mm: 260, width_mm: 97 };
  const defaults = { style: "vent", fit: "regular", toe: "round", cushion: "medium" };
  const values = valuesFrom(kept, defaults);
  assert.deepEqual(values, {
    style: "stream", fit: "snug", toe: "round", cushion: "medium",
    sole_mm: "18", sock_mm: "", length_mm: "260", width_mm: "97", openness_percent: "30",
  });
  assert.deepEqual(choicesFrom(values), { ...defaults, ...kept, trials: false });
  assert.deepEqual(valuesFrom(null, defaults), {
    ...EMPTY, style: "vent", fit: "regular", toe: "round", cushion: "medium",
  });
});

test("a description's reading changes only the settings it speaks to", () => {
  const before = {
    style: "stone", fit: "regular", toe: "round", cushion: "medium",
    sole_mm: "", sock_mm: "", length_mm: "260", width_mm: "97", openness_percent: "20",
  };
  const after = withReading(before, { style: "vent", fit: "roomy", sole_mm: 24, sock_mm: 1.5 });
  assert.deepEqual(after, {
    ...before, style: "vent", fit: "roomy", sole_mm: "24", sock_mm: "1.5",
  });
  assert.deepEqual(withReading(before, {}), before); // nothing read: nothing moved, the ruler numbers included
  assert.equal(withReading(before, { openness: 0.38 }).openness_percent, "38");
  assert.equal(before.style, "stone"); // the values handed in are not changed in place
});

test("a setting's value is said in the form's own words", () => {
  assert.equal(valueText("style", "stream", OPTIONS), "Stream");
  assert.equal(valueText("style", "new-one", OPTIONS), "new-one"); // a style the page wasn't told of: its key
  assert.equal(valueText("style", "vent", undefined), "vent");
  assert.equal(valueText("openness", 0.38, OPTIONS), "38% open");
  assert.equal(valueText("sole_mm", 24, OPTIONS), "24 mm");
  assert.equal(valueText("sock_mm", 1.5, OPTIONS), "1.5 mm");
  assert.equal(valueText("fit", "roomy", OPTIONS), "roomy");
});

test("what was read from a description is shown with the person's own words and says when it is a judgment", () => {
  assert.equal(
    understoodLine({ setting: "fit", value: "roomy", words: ["roomy"], judgment: null }, OPTIONS),
    "Fit: roomy, from “roomy”",
  );
  assert.equal(
    understoodLine({ setting: "sole_mm", value: 24, words: ["thick sole", "chunky"],
      judgment: "“thick” was taken as 24 mm" }, OPTIONS),
    "Sole thickness: 24 mm, from “thick sole”, “chunky” (“thick” was taken as 24 mm; change it below if you know better)",
  );
  assert.equal(understoodLine({ setting: "style", value: "stone", words: [] }, OPTIONS), "Style: Stone");
  for (const name of ["style", "fit", "toe", "cushion", "sole_mm", "openness", "sock_mm"]) assert.ok(SETTING_NAMES[name], name);
});

test("a wall let out for this foot is said with where, measured from the back of the shoe", () => {
  const letOut = {
    inner: { max_mm: 16.9, stretches: [{ from_mm: 10.4, to_mm: 187.4, max_mm: 16.9 }] },
    outer: { max_mm: 0.4, stretches: [] },
  };
  assert.equal(letOutText(letOut), "the inner wall is let out by up to 16.9 mm for this foot (10 to 187 mm from the back)");
  const both = {
    inner: { max_mm: 9.3, stretches: [{ from_mm: 15.4, to_mm: 192.4 }] },
    outer: { max_mm: 8.1, stretches: [{ from_mm: 15.4, to_mm: 169.4 }, { from_mm: 191.4, to_mm: 224.4 }] },
  };
  assert.equal(
    letOutText(both),
    "the inner wall is let out by up to 9.3 mm for this foot (15 to 192 mm from the back); "
    + "the outer wall is let out by up to 8.1 mm for this foot (15 to 169 mm from the back and 191 to 224 mm from the back)",
  );
});

test("a shoe with no wall let out by a millimetre says nothing about it", () => {
  assert.equal(letOutText({ inner: { max_mm: 0.6 }, outer: { max_mm: 0 } }), "");
  assert.equal(letOutText({}), "");
  assert.equal(letOutText(null), "");
  assert.equal(letOutText(undefined), "");
});
