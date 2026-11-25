// Studio: the Status page. Every value comes from GET /api/studio/status; nothing is changed from here.
import { ask, esc } from "./studio.js";

const $ = (id) => document.getElementById(id);

export function size(bytes) {
  if (bytes == null) return "—";
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(gb >= 100 ? 0 : 1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
}

export function duration(s) {
  if (s == null) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}

// What on this page needs the owner's attention, in plain words (each from the status the studio gave)
export function notes(st) {
  const out = [];
  const disk = st.data.disk;
  if (disk.error) out.push(`The studio couldn't read its disk's free space: ${disk.error}.`);
  else if (disk.low) out.push(`The disk is nearly full (${size(disk.free_bytes)} free). The studio refuses photos once under 5 GB would be left.`);
  if (st.data.insoles_out_of_date) out.push(`${st.data.insoles_out_of_date} insole${st.data.insoles_out_of_date === 1 ? "" : "s"} can't be downloaded until made again: the library lists them, with a button to make them all again.`);
  if (st.claude.check_scans && !st.claude.api_key_set) out.push("Claude's look at sole scans is on, but no ANTHROPIC_API_KEY is set for the studio, so unless another sign-in is found every scan is kept without a look.");
  if (st.claude.describe_shoes && !st.claude.api_key_set) out.push("Reading a shoe's description with Claude is on, but no ANTHROPIC_API_KEY is set for the studio.");
  const app = st.app || {};
  if (app.wrong_key && app.latest === "wrong_key") out.push(`The iPhone app last asked with a studio key that doesn't match (${app.wrong_key.at.replace("T", " ")}, over ${app.wrong_key.network}): it was paired before this studio's key changed, or reinstalled. Scan the connect code again on Import a 3D scan.`);
  if (st.recent_errors?.length) out.push(`${st.recent_errors.length} request${st.recent_errors.length === 1 ? "" : "s"} hit a problem the studio didn't expect since it started: listed under Unexpected errors below.`);
  if (!st.checkout) out.push("This copy of footscan isn't a git checkout (or its .git folder can't be read), so the code's version can't be shown.");
  return out;
}

function facts(rows) {
  return `<dl class="facts">${rows.map(([k, v, mono]) => `<div><dt>${esc(k)}</dt><dd${mono ? ' class="mono"' : ""}>${v}</dd></div>`).join("")}</dl>`;
}

// The app's latest request let in, and its latest turned away for a wrong key: when, which way, what for
export function appRows(app) {
  const seen = (e) => (e ? `${esc(e.at.replace("T", " "))}<br><span class="muted">${esc(e.asked)}, over ${esc(e.network)} (${esc(e.address)})</span>` : "never");
  return [["Last reached the studio", seen(app.reached)], ["Last turned away (wrong key)", seen(app.wrong_key)]];
}

// Requests the studio answered "a problem it didn't expect" (500), the newest first: what was asked, what went
// wrong and where in the code, for a bug report. The full tracebacks are in the studio's log.
export function errorsHtml(errors) {
  if (!errors.length) return `<p class="muted" style="margin:0">None since the studio started.</p>`;
  return `<ul class="errors-list">${errors.map((e) => `<li><span class="mono">${esc(e.at.replace("T", " "))} · ${esc(e.request)}</span><br>
    ${esc(e.error)}<br><span class="hint mono">${esc(e.code)}</span></li>`).join("")}</ul>
    <p class="hint" style="margin:8px 0 0">The studio's log has the full detail of each.</p>`;
}

export function statusHtml(st) {
  const a = st.address, d = st.data, disk = d.disk;
  const on = (b) => (b ? "on" : "off");
  return `
    <section class="card"><h2>Code</h2>${facts([
      ["Version (commit)", st.checkout ? esc(st.checkout.commit) : "unknown", true],
      ["Branch", st.checkout?.branch ? esc(st.checkout.branch) : "—", true],
      ["Running since", esc(st.started.replace("T", " ")), true],
      ["Up for", esc(duration(st.up_s))],
      ["Python", esc(st.python), true],
      ["Computer", esc(st.system)],
      ["Sole scans prepared as", esc(st.sole_scan_preparation)],
    ])}</section>
    <section class="card"><h2>Address</h2>${facts([
      ["Listening on", `${esc(a.host)}:${esc(a.port)}`, true],
      ["HTTPS", a.https ? "yes" : "no"],
      ["Phones can connect", a.phones_can_connect ? "yes" : "no (start with --host 0.0.0.0 --https)"],
      ["Tailscale", a.tailscale.length ? a.tailscale.map(esc).join("<br>") : "—", true],
      ["Public mode", a.public ? "yes: only the studio key opens it" : "no"],
      ["Search engines", esc(st.search_engines)],
    ])}</section>
    <section class="card"><h2>iPhone app</h2>${facts(appRows(st.app || {}))}
      <p class="hint" style="margin:12px 0 0">Since the studio started. "Test the connection" in the app shows here as a
        connection test; nothing here means the phone's requests aren't reaching this computer at all.</p></section>
    <section class="card"><h2>Unexpected errors</h2>${errorsHtml(st.recent_errors || [])}</section>
    <section class="card"><h2>Data</h2>${facts([
      ["Folder", esc(d.folder), true],
      ["Disk free", disk.error ? "couldn't be read" : `${esc(size(disk.free_bytes))} of ${esc(size(disk.total_bytes))}`],
      ["Captures", esc(d.captures)],
      ["Sole scans", esc(d.sole_scans)],
      ["Insoles", `${esc(d.insoles)}${d.insoles_out_of_date ? ` (<a href="/studio/captures.html?attention=1">${esc(d.insoles_out_of_date)} out of date</a>)` : ""}${d.insoles_failed ? ` (${esc(d.insoles_failed)} failed)` : ""}`],
      ["3D model being built", st.working?.model_being_built ? esc(st.working.model_being_built) : "none (one is built at a time)", !!st.working?.model_being_built],
      ["Saved shoes", esc(d.shoes_saved)],
      ["Submissions", esc(d.submissions)],
    ])}</section>
    <section class="card"><h2>Claude</h2>${facts([
      ["Looks at each sole scan", `${on(st.claude.check_scans)}${st.claude.check_scans ? "" : " (start with --check-scans-with-claude)"}`],
      ["Reads a shoe's description", `${on(st.claude.describe_shoes)}${st.claude.describe_shoes ? "" : " (start with --describe-with-claude)"}`],
      ["API key set", st.claude.api_key_set ? "yes" : "no"],
    ])}</section>`;
}

let asking = false;
async function load() {
  if (asking) return;
  asking = true;
  $("refresh").disabled = true;
  const [ok, st] = await ask("/api/studio/status");
  asking = false;
  $("refresh").disabled = false;
  $("updated").textContent = `Asked at ${new Date().toLocaleTimeString()}; asked again every ${AGAIN_S} s while this page is open.`;
  if (!ok) {
    show($("notes"), "");  // the last answer's notes aren't current any more
    $("root").innerHTML = `<div class="callout stop"><p>Couldn't ask the studio: ${esc(st.error || "it refused")}.</p></div>`;
    return;
  }
  const n = notes(st);
  show($("notes"), n.length ? `<div class="callout warn" style="margin:16px 0"><ul class="checklist" style="margin:0">${n.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "");
  $("root").innerHTML = statusHtml(st);
}

// The notes are read out as they change (aria-live): rewritten only when they do, not on every ask
function show(el, html) {
  if (el.dataset.shown !== html) { el.innerHTML = html; el.dataset.shown = html; }
}

// Asked again on its own while the page is in view, so "Test the connection" pressed on the phone shows up here
// within a few seconds (not while the tab is hidden: nothing to see, and nothing asked for nothing)
const AGAIN_S = 10;
if (typeof document !== "undefined" && document.getElementById("root")) {
  $("refresh").addEventListener("click", load);
  load();
  setInterval(() => { if (document.visibilityState === "visible") load(); }, AGAIN_S * 1000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
}
