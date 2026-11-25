import assert from "node:assert/strict";
import { test } from "node:test";

import { appRows, duration, errorsHtml, notes, size, statusHtml, titleFor } from "../../web/assets/status-page.js";

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

test("the Status page says which 3-D model is being built, escaped, or that none is", () => {
  const st = {
    ...structuredClone(OK), started: "2026-11-25T08:00:00", up_s: 60, python: "3.12", system: "Windows 11",
    sole_scan_preparation: "sole_up-7", search_engines: "kept out (noindex)",
    address: { host: "0.0.0.0", port: 8766, https: true, public: false, phones_can_connect: true, tailscale: [] },
  };
  Object.assign(st.data, { folder: "C:/srv/footscan/data", captures: 3, sole_scans: 1, insoles: 1, shoes_saved: 0, submissions: 0 });
  assert.match(statusHtml(st), /3D model being built<\/dt><dd>none \(one is built at a time\)/);
  assert.match(statusHtml(st), /Newest capture<\/dt><dd class="mono">none yet/);
  st.data.newest_capture = { id: "LIDAR_<x>", created: "2026-11-25T09:00:00" };
  assert.match(statusHtml(st), /href="\/studio\/captures.html#LIDAR_%3Cx%3E">LIDAR_&#60;x&#62;<\/a><br><span class="muted">2026-11-25 09:00:00/);
  st.working = { model_being_built: "captures/<b>" };
  assert.match(statusHtml(st), /3D model being built<\/dt><dd class="mono">captures\/&#60;b&#62;/);
});

test("the tab's title carries how many notes there are, and drops the count once there are none", () => {
  assert.equal(titleFor(2, "Status · Studio"), "(2) Status · Studio");
  assert.equal(titleFor(1, "(2) Status · Studio"), "(1) Status · Studio");
  assert.equal(titleFor(0, "(1) Status · Studio"), "Status · Studio");
  assert.equal(titleFor("!", "(1) Status · Studio"), "(!) Status · Studio");  // couldn't ask the studio
  assert.equal(titleFor(0, "(!) Status · Studio"), "Status · Studio");
});
