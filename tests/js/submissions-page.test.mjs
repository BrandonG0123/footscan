import assert from "node:assert/strict";
import { test } from "node:test";

import { addressFor, emptyText, statusFromAddress } from "../../web/assets/submissions-page.js";

test("the submissions tab comes from the address, and New when it names none or no tab", () => {
  assert.equal(statusFromAddress(""), "received");
  assert.equal(statusFromAddress("?status=archived"), "archived");
  assert.equal(statusFromAddress("?status=all"), "");
  assert.equal(statusFromAddress("?status=nonsense"), "received");
  assert.equal(statusFromAddress("?status=__proto__"), "received");
});

test("the tab is written to the address, keeping anything else there (the studio key)", () => {
  assert.equal(addressFor("?key=k", "archived"), "?key=k&status=archived");
  assert.equal(addressFor("?key=k&status=archived", "received"), "?key=k");
  assert.equal(addressFor("", ""), "?status=all");
  assert.equal(addressFor("?status=all", "received"), "");
  for (const s of ["received", "archived", "", "needs_rescan"]) assert.equal(statusFromAddress(addressFor("", s)), s);
});

test("an empty tab says how many are in the others, not that nothing was ever sent", () => {
  assert.equal(emptyText("received", 0), "No submissions yet.");
  assert.equal(emptyText("needs_rescan", 4), "None marked waiting for rescan; 4 in All.");
  assert.equal(emptyText("", 0), "No submissions yet.");
});
