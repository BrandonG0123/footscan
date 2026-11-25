import assert from "node:assert/strict";
import { test } from "node:test";

import { duration, notes, size } from "../../web/assets/status-page.js";

const OK = {
  checkout: { commit: "36cc2ef", branch: "main" },
  data: { disk: { free_bytes: 200 * 1024 ** 3, total_bytes: 900 * 1024 ** 3, low: false }, insoles_out_of_date: 0 },
  claude: { check_scans: false, describe_shoes: false, api_key_set: false },
};

test("sizes and times read as a person says them", () => {
  assert.equal(size(200 * 1024 ** 3), "200 GB");
  assert.equal(size(5.5 * 1024 ** 3), "5.5 GB");
  assert.equal(size(300 * 1024 ** 2), "300 MB");
  assert.equal(duration(90), "1 min");
  assert.equal(duration(3 * 3600 + 120), "3 h 2 min");
  assert.equal(duration(2 * 86400 + 5 * 3600), "2 d 5 h");
});

test("a healthy studio has nothing to say", () => {
  assert.deepEqual(notes(OK), []);
});

test("a nearly full disk, insoles to make again and Claude on without a key are each said", () => {
  const st = structuredClone(OK);
  st.data.disk.low = true;
  st.data.insoles_out_of_date = 2;
  st.claude = { check_scans: true, describe_shoes: false, api_key_set: false };
  const n = notes(st);
  assert.equal(n.length, 3);
  assert.match(n[0], /nearly full/);
  assert.match(n[1], /^2 insoles can't be downloaded/);
  assert.match(n[2], /no ANTHROPIC_API_KEY/);
});
