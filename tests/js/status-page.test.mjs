import assert from "node:assert/strict";
import { test } from "node:test";

import { appRows, duration, errorsHtml, notes, size } from "../../web/assets/status-page.js";

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

test("an app turned away for a wrong key since it last got in is told to scan the connect code again", () => {
  const reached = { at: "2026-11-25T09:00:00", address: "100.101.1.2", network: "Tailscale", asked: "connection test" };
  const wrong = { at: "2026-11-25T09:30:00", address: "192.168.11.40", network: "home network", asked: "connection test" };
  const st = structuredClone(OK);
  st.app = { reached, wrong_key: wrong, latest: "wrong_key" };
  const n = notes(st);
  assert.equal(n.length, 1);
  assert.match(n[0], /doesn't match .*over home network.*Scan the connect code again/);
  // got in again since (in the same second, too: the order is the studio's, not the clock's)
  st.app = { reached: { ...reached, at: wrong.at }, wrong_key: wrong, latest: "reached" };
  assert.deepEqual(notes(st), []);
  st.app = { reached: null, wrong_key: wrong, latest: "wrong_key" };
  assert.equal(notes(st).length, 1);
});

test("the app's rows say never until it has asked, and escape what they show", () => {
  assert.deepEqual(appRows({}).map((r) => r[1]), ["never", "never"]);
  const [row] = appRows({ reached: { at: "2026-11-25T09:00:00", address: "<b>", network: "Tailscale", asked: "connection test" } });
  assert.match(row[1], /2026-11-25 09:00:00.*connection test, over Tailscale \(&#60;b&#62;\)/);
});

test("unexpected errors are listed escaped, and their count is a note", () => {
  assert.match(errorsHtml([]), /None since the studio started/);
  const e = { at: "2026-11-25T09:00:00", request: "GET /api/captures", error: "RuntimeError: <b>", code: "server.py:12 (route)" };
  const html = errorsHtml([e]);
  assert.match(html, /2026-11-25 09:00:00 · GET \/api\/captures/);
  assert.ok(html.includes("RuntimeError: &#60;b&#62;") && !html.includes("<b>"));
  const st = structuredClone(OK);
  st.recent_errors = [e, e];
  assert.match(notes(st)[0], /^2 requests hit a problem/);
});
