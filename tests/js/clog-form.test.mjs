import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SETTING_NAMES, changeLine, choicesFrom, findingsFrom, letOutText, otherShoe, pairDifferences, pairText, shoeAbove,
  shoeToRecord, understoodLine, valueText, valuesFrom, withPairChoices, withReading, withSuggestion,
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

// ---- what the print-trial pieces showed ----------------------------------------------------------------------
test("a trial record sends which shoe it is about, only the questions answered, and the note without its spaces around", () => {
  assert.deepEqual(findingsFrom({ made: "2026-11-10T19:40:25", answers: { hurt: "no", walls: "press", arch: "", rim: undefined },
    note: "  tight at the heel \n" }),
  { made: "2026-11-10T19:40:25", answers: { hurt: "no", walls: "press" }, note: "tight at the heel" });
  assert.deepEqual(findingsFrom({ answers: {} }), { made: undefined, answers: {}, note: "" });
});

test("a suggested change is said with what the shoe had, what is suggested and every answer it came from", () => {
  assert.equal(changeLine({ setting: "fit", was: "regular", to: "roomy",
    because: ["the toe cap's roof pressed on the toes", "the toe cap pressed on the sides of the toes", "the back half's walls pressed on the foot"] }, OPTIONS),
  "Fit: regular → roomy, because the toe cap's roof pressed on the toes, the toe cap pressed on the sides of the toes and the back half's walls pressed on the foot");
  assert.equal(changeLine({ setting: "cushion", was: "medium", to: "firm", because: ["the firm sole block was the one picked"] }, OPTIONS),
    "Cushioning: medium → firm, because the firm sole block was the one picked");
  assert.equal(changeLine({ setting: "fit", was: "snug", to: "regular" }, OPTIONS), "Fit: snug → regular");
});

test("taking a suggestion changes only the settings it names in the form", () => {
  const form = { style: "vent", fit: "snug", toe: "round", cushion: "medium", sole_mm: "18", length_mm: "260", width_mm: "97" };
  assert.deepEqual(withSuggestion(form, [{ setting: "fit", was: "snug", to: "regular" }, { setting: "cushion", was: "medium", to: "firm" }]),
    { ...form, fit: "regular", cushion: "firm" });
  assert.deepEqual(withSuggestion(form, []), form);
  assert.deepEqual(withSuggestion(form, undefined), form);
});

test("a shoe of the trial record is the shoe on the page only when it is that very shoe, still matching its scan", () => {
  const tried = { made: "2026-11-10T19:40:25" };
  assert.equal(shoeAbove(tried, { made: "2026-11-10T19:40:25" }), true);
  assert.equal(shoeAbove(tried, { made: "2026-11-12T08:00:00" }), false);   // the shoe was made again since
  assert.equal(shoeAbove(tried, { made: "2026-11-10T19:40:25", stale: true }), false);   // its scan changed since
  assert.equal(shoeAbove(tried, { made: "2026-11-10T19:40:25", error: "couldn't" }), false);
  assert.equal(shoeAbove(tried, null), false);
  assert.equal(shoeAbove({}, {}), false);
});

test("the trial form is about the shoe picked, else the shoe on the page, else the newest whose pieces are known", () => {
  const shoes = [{ made: "c", recordable: true }, { made: "b", recordable: true }, { made: "a", recordable: false }];   // newest first
  assert.equal(shoeToRecord(shoes, { made: "b" }, null).made, "b");          // the shoe on the page
  assert.equal(shoeToRecord(shoes, { made: "b" }, "c").made, "c");           // the one the person picked
  assert.equal(shoeToRecord(shoes, { made: "b" }, "a").made, "b");           // a shoe that can't be added to isn't picked
  assert.equal(shoeToRecord(shoes, { made: "z" }, null).made, "c");          // the page's shoe has no pieces: the newest that has
  assert.equal(shoeToRecord(shoes, { made: "b", error: "couldn't" }, null).made, "c");
  assert.equal(shoeToRecord(shoes, null, null).made, "c");
  assert.equal(shoeToRecord([{ made: "a", recordable: false }], { made: "a" }, null), null);
  assert.equal(shoeToRecord([], { made: "a" }, null), null);
  assert.equal(shoeToRecord(undefined, null, null), null);
});

// ---- the other foot's shoe -------------------------------------------------------------------------------------
const shoe = (foot, made, more = {}) => ({ foot, made, choices: {}, made_for: { foot_length_mm: 260, foot_width_mm: 97, length_from: "ruler" }, ...more });

test("the other foot's shoe is the newest one made from the other foot that still matches its scan", () => {
  const mine = { capture_id: "r1", foot: "right", clog: shoe("right", "2026-11-10T10:00:00") };
  const list = [mine,
    { capture_id: "r2", foot: "right", clog: shoe("right", "2026-11-12T10:00:00") },        // this foot's own: not a pair
    { capture_id: "l1", foot: "left", clog: shoe("left", "2026-11-09T10:00:00") },
    { capture_id: "l2", foot: "left", clog: shoe("left", "2026-11-11T10:00:00") },
    { capture_id: "l3", foot: "left", clog: shoe("left", "2026-11-12T10:00:00", { stale: true }) },   // its model changed since
    { capture_id: "l4", foot: "left", clog: { error: "couldn't make a shoe" } },
    { capture_id: "l5", foot: "left" },
    { capture_id: "box", clog: shoe(undefined, "2026-11-13T10:00:00") }];
  assert.equal(otherShoe(list, mine).capture_id, "l2");
  assert.equal(otherShoe(list, list[3]).capture_id, "r2");
  assert.equal(otherShoe([mine], mine), null);
  assert.equal(otherShoe(list, { capture_id: "box" }), null);
});

test("a pair's choices are compared as the shoes were made, a setting left out being the generator's or the style's own", () => {
  const options = { defaults: { style: "vent", fit: "regular", toe: "round", cushion: "medium", sock_mm: 0 },
    styles: [{ key: "vent", sole_mm: 16, openness: 0.28, windows: true }, { key: "stone", sole_mm: 18, openness: 0, windows: false }] };
  assert.deepEqual(pairDifferences({ style: "stone" }, { style: "stone", fit: "regular" }, options), []);
  assert.deepEqual(pairDifferences({ style: "stone", sole_mm: 20 }, { style: "vent", fit: "roomy" }, options),
    ["style", "fit", "sole_mm", "openness"]);
  // a sole or a pattern left empty is the style's own: the same shoe as that number typed in
  assert.deepEqual(pairDifferences({ sole_mm: 16 }, {}, options), []);
  assert.deepEqual(pairDifferences({ sole_mm: "16.0", openness: 0.28 }, { style: "vent" }, options), []);
  assert.deepEqual(pairDifferences({ sole_mm: 20 }, {}, options), ["sole_mm"]);
  assert.deepEqual(pairDifferences({ openness: 0.4 }, {}, options), ["openness"]);
  // a style without windows has no pattern to differ in, whatever was typed
  assert.deepEqual(pairDifferences({ style: "stone", openness: 0.4 }, { style: "stone" }, options), []);
  // each foot's own ruler numbers are not part of what a pair shares
  assert.deepEqual(pairDifferences({ length_mm: 260, width_mm: 97 }, { length_mm: 258, width_mm: 99 }, options), []);
});

test("using the other shoe's choices takes its settings and keeps this foot's own ruler numbers", () => {
  const form = { style: "vent", fit: "snug", toe: "round", cushion: "medium", sole_mm: "", openness_percent: "30", sock_mm: "0",
    length_mm: "260", width_mm: "97", trials: true };
  const got = withPairChoices(form, { style: "stone", fit: "roomy", cushion: "firm", sole_mm: 20, length_mm: 255, width_mm: 99 },
    { style: "vent", fit: "regular", toe: "round", cushion: "medium", sock_mm: 0 });
  assert.deepEqual(got, { style: "stone", fit: "roomy", toe: "round", cushion: "firm", sole_mm: "20", openness_percent: "", sock_mm: "0",
    length_mm: "260", width_mm: "97", trials: true });
  // every setting a pair is compared in is one the button copies (the pattern, by the form's own name for it)
  const copied = withPairChoices(form, { openness: 0.4, sock_mm: 2 }, {});
  assert.equal(copied.openness_percent, "40");
  assert.equal(copied.sock_mm, "2");
});

test("a pair is compared by the feet the two shoes were made for, in the reports' own numbers", () => {
  const right = shoe("right", "a"), left = shoe("left", "b");
  assert.equal(pairText(right, left),
    "This right shoe is made for a foot 260 × 97 mm (length from the ruler), the left one for a foot 260 × 97 mm (length from the ruler): the same length.");
  left.made_for = { foot_length_mm: 246.4, foot_width_mm: 95, length_from: "scan" };
  assert.equal(pairText(right, left),
    "This right shoe is made for a foot 260 × 97 mm (length from the ruler), the left one for a foot 246.4 × 95 mm (length from the scan): "
    + "13.6 mm apart in length. One length is a ruler's and the other a scan's, and the two don't always agree: measure both feet by ruler before printing a pair.");
  right.made_for = { foot_length_mm: 250, foot_width_mm: 96, length_from: "scan" };
  assert.ok(pairText(right, left).endsWith("3.6 mm apart in length."));   // both by their scans: only the difference is said
  // a ruler's length that happens to match a scan's is still a ruler against a scan
  right.made_for = { foot_length_mm: 246.4, foot_width_mm: 96, length_from: "ruler" };
  assert.ok(pairText(right, left).endsWith(": the same length. One length is a ruler's and the other a scan's, and the two don't "
    + "always agree: measure both feet by ruler before printing a pair."));
});
