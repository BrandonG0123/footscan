// Studio: the Submissions list (studio/index.html).
import { STATUS, ask, esc, fmtDate } from "./studio.js";
const $ = (id) => document.getElementById(id);

// The tab shown is kept in the address (?status=archived, ?status=all), so a reload or Back keeps it;
// none (or one that isn't a tab) is New
export function statusFromAddress(search) {
  const s = new URLSearchParams(search).get("status");
  return s === "all" ? "" : s && Object.hasOwn(STATUS, s) ? s : "received";
}
export function addressFor(search, status) {
  const q = new URLSearchParams(search);
  if (status === "received") q.delete("status"); else q.set("status", status || "all");
  const out = q.toString();
  return out ? `?${out}` : "";
}
// An empty tab says so, and how many are in the others, rather than looking as if nothing was ever sent
export function emptyText(status, total) {
  if (!total) return "No submissions yet.";
  return `None ${status ? `marked ${(STATUS[status]?.label || status).toLowerCase()}` : "here"}; ${total} in All.`;
}

let all = [], filter = typeof location === "undefined" ? "received" : statusFromAddress(location.search);

if (typeof document !== "undefined" && document.getElementById("rows")) start();

function start() {
  ask("/api/studio").then(([ok, info]) => {
    $("share").innerHTML = !ok ? `Couldn't ask the studio: ${esc(info.error)}` : info.phones_can_connect
      ? `Send people to <strong class="mono">${esc(info.scan_url)}</strong> (same Wi-Fi). They'll see a certificate warning once.`
      : `Phones can't reach this server yet. Stop it and restart with <span class="mono">footscan serve --host 0.0.0.0 --https</span>.`;
  });

  async function load() {
    const [ok, list] = await ask("/api/submissions");
    if (!ok) { $("rows").innerHTML = `<tr><td colspan="7">Can't load submissions: ${esc(list.error || "the studio refused")}.</td></tr>`; return; }
    all = list;
    for (const b of $("tabs").querySelectorAll("button")) {
      const n = b.dataset.status ? all.filter((s) => s.status === b.dataset.status).length : all.length;
      b.textContent = `${b.textContent.replace(/ \(\d+\)$/, "")} (${n})`;
    }
    render();
  }

  function render() {
    const rows = all.filter((s) => !filter || s.status === filter);
    if (!rows.length) {
      $("rows").innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:36px">${esc(emptyText(filter, all.length))}</td></tr>`;
      return;
    }
    $("rows").innerHTML = rows.map((s) => {
      const scans = Object.values(s.scans);
      const done = scans.filter((x) => x.status === "complete").length;
      const photos = scans.reduce((n, x) => n + (x.frame_files?.length ?? 0), 0);
      const before = (s.flags || []).filter((f) => f.level === "before_wear").length;
      const use = s.survey?.sport || { everyday: "Everyday", on_feet: "On feet all day", sport: "Sport" }[s.survey?.use] || "—";
      const st = STATUS[s.status] || { label: s.status, cls: "" };
      const href = `/studio/submission.html?id=${encodeURIComponent(s.id)}`;
      // data-label: a phone shows each row as a small card, every value under its column's name (index.html's CSS)
      return `<tr data-href="${href}"><td data-label="Name"><a href="${href}">${esc(s.name)}</a></td>
        <td data-label="Sent">${fmtDate(s.submitted || s.created)}</td><td data-label="Scans" class="mono">${done}/${scans.length}</td>
        <td data-label="Photos" class="mono">${photos}</td><td data-label="Use">${esc(use)}</td>
        <td data-label="Flags">${before ? `<span class="badge stop">${before} before wear</span>` : "—"}</td>
        <td data-label="Status"><span class="badge ${st.cls}">${st.label}</span></td></tr>`;
    }).join("");
  }

  $("rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-href]");
    // followed as its link is (which carries the studio key on a phone without the cookie)
    if (tr && !e.target.closest("a")) tr.querySelector("a")?.click();
  });
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    filter = b.dataset.status;
    try { history.replaceState(history.state, "", `${location.pathname}${addressFor(location.search, filter)}${location.hash}`); } catch { /* the address lags */ }
    pressTab();
    render();
  });
  pressTab();
  load();
}

function pressTab() {
  $("tabs").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.status === filter)));
}
