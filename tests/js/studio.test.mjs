import assert from "node:assert/strict";
import { test } from "node:test";

import { answer, ask } from "../../web/assets/studio.js";

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });

test("a JSON answer is read as it is, an error answer's own words included", async () => {
  assert.deepEqual(await answer(json({ id: "x" })), { id: "x" });
  assert.deepEqual(await answer(json({ error: "length_mm must be a number (mm)" }, 400)), { error: "length_mm must be a number (mm)" });
});

test("a login page in place of data says to sign in again, not 'Unexpected token <'", async () => {
  const page = new Response("<!doctype html><title>Sign in</title>", { status: 200, headers: { "Content-Type": "text/html" } });
  assert.match((await answer(page)).error, /sign in/);
});

test("the server's own error page says what was refused", async () => {
  const page = new Response("<html>Bad request</html>", { status: 501, statusText: "Not Implemented", headers: { "Content-Type": "text/html" } });
  assert.match((await answer(page)).error, /refused the request \(501 Not Implemented\)/);
});

test("an answer cut off part-way says so", async () => {
  const cut = new Response('{"made": "2026-', { status: 200, headers: { "Content-Type": "application/json" } });
  assert.match((await answer(cut)).error, /cut off/);
});

test("no connection at all is an answer too, with what to check", async () => {
  const real = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  try {
    const [ok, data] = await ask("/api/captures");
    assert.equal(ok, false);
    assert.match(data.error, /can't reach the studio/);
  } finally {
    globalThis.fetch = real;
  }
});

test("only a JSON answer with a success status counts as ok", async () => {
  const real = globalThis.fetch;
  try {
    globalThis.fetch = async () => json({ error: "not found" }, 404);
    assert.equal((await ask("/api/x"))[0], false);
    globalThis.fetch = async () => new Response("<html></html>", { status: 200, headers: { "Content-Type": "text/html" } });
    assert.equal((await ask("/api/x"))[0], false);
    globalThis.fetch = async () => json({ ok: true });
    assert.deepEqual(await ask("/api/x"), [true, { ok: true }]);
  } finally {
    globalThis.fetch = real;
  }
});
