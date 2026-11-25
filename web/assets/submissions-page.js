// Studio: the Submissions list (studio/index.html).
import { STATUS, ask, esc, fmtDate } from "/assets/studio.js";
const $ = (id) => document.getElementById(id);
let all = [], filter = "received";

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
    $("rows").innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:36px">Nothing here yet.</td></tr>`;
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
    return `<tr data-href="${href}"><td><a href="${href}">${esc(s.name)}</a></td>
      <td>${fmtDate(s.submitted || s.created)}</td><td class="mono">${done}/${scans.length}</td>
      <td class="mono">${photos}</td><td>${esc(use)}</td>
      <td>${before ? `<span class="badge stop">${before} before wear</span>` : "—"}</td>
      <td><span class="badge ${st.cls}">${st.label}</span></td></tr>`;
  }).join("");
}

$("rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-href]");
  if (tr && !e.target.closest("a")) location.href = tr.dataset.href;
});
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  filter = b.dataset.status;
  $("tabs").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  render();
});
load();
