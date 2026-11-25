// The break-in tracker page (care.html): moved out of the page so the site's CSP can forbid inline script.
// Schedule mirrors docs/SAFETY.md. Keep them in sync.
const SCHEDULE = [
  [1, 1, "1 h"], [2, 3, "2 h"], [4, 5, "3 h"], [6, 7, "4 h"], [8, 10, "6 h"], [11, 14, "All day"],
];
const targetFor = (d) => SCHEDULE.find(([a, b]) => d >= a && d <= b);
const hoursCap = (label) => (label === "All day" ? 16 : parseFloat(label));
const SKIN = [
  ["", "Choose one…"],
  ["clear", "All fine"],
  ["faded", "A red mark that went away"],
  ["persistent", "A red mark that stayed"],
  ["blister", "A blister or hot spot"],
  ["numb", "Numb or tingly"],
];
const STOP_SKIN = new Set(["blister", "numb"]);
const KEY = "footscan.breakin.v1";
const $ = (id) => document.getElementById(id);

const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {} };
let state = Object.assign({ revision: "", start: "", days: {}, stopped: null, reviews: [] }, load());

function dayNumber() {
  if (!state.start) return null;
  const ms = new Date().setHours(0, 0, 0, 0) - new Date(state.start + "T00:00").getTime();
  return Math.floor(ms / 86400000) + 1;
}

function evaluateStop() {
  for (let d = 1; d <= 14; d++) {
    const e = state.days[d];
    if (!e) continue;
    if (e.pain === "yes") return `Day ${d}: something hurt.`;
    if (STOP_SKIN.has(e.skin)) return `Day ${d}: ${SKIN.find(([v]) => v === e.skin)[1].toLowerCase()}.`;
    if (e.skin === "persistent" && state.days[d + 1]?.skin === "persistent")
      return `Day ${d} and day ${d + 1}: a red mark was still there the next day.`;
  }
  return null;
}

function render() {
  $("revision").value = state.revision;
  $("start").value = state.start;
  const reason = state.stopped ?? evaluateStop();
  if (reason && !state.stopped) { state.stopped = reason; save(); }
  $("stop").hidden = !state.stopped;
  $("stop-reason").textContent = state.stopped || "";
  // A stop can only be cleared through the review step, never by resetting.
  $("btn-reset").disabled = !!state.stopped;
  $("btn-reset").title = state.stopped ? "See a doctor first, then use the button above" : "";

  const today = dayNumber();
  const html = [];
  for (let d = 1; d <= 14; d++) {
    const [, , label] = targetFor(d);
    const e = state.days[d] || {};
    const future = today != null && d > today;
    const locked = !!state.stopped || future;
    const over = e.hours != null && e.hours !== "" && Number(e.hours) > hoursCap(label);
    const persistentOnce = e.skin === "persistent";
    html.push(`<div class="card day${d === today ? " today" : ""}${locked ? " locked" : ""}">
      <div><div class="num">Day ${d}${d === today ? ' <span class="badge brand">today</span>' : ""}</div>
        <div class="target">target ${label}</div><div class="hint">walking only</div></div>
      <div class="inputs">
        <div class="field"><label for="h${d}">Hours worn</label>
          <input id="h${d}" data-day="${d}" data-k="hours" type="number" min="0" max="24" step="0.25" inputmode="decimal" value="${e.hours ?? ""}" ${locked ? "disabled" : ""}></div>
        <div class="field skin"><label for="s${d}">How did your feet look?</label>
          <select id="s${d}" data-day="${d}" data-k="skin" ${locked ? "disabled" : ""}>${SKIN.map(([v, t]) =>
            `<option value="${v}"${e.skin === v ? " selected" : ""}>${t}</option>`).join("")}</select></div>
        <div class="field"><label for="p${d}">Did anything hurt?</label>
          <select id="p${d}" data-day="${d}" data-k="pain" ${locked ? "disabled" : ""}>
            <option value=""${!e.pain ? " selected" : ""}>—</option>
            <option value="no"${e.pain === "no" ? " selected" : ""}>No</option>
            <option value="yes"${e.pain === "yes" ? " selected" : ""}>Yes</option></select></div>
        ${over ? `<p class="flag" style="color:var(--warn)">That is more than today's plan. Going faster can hurt.</p>` : ""}
        ${persistentOnce && !state.stopped ? `<p class="flag" style="color:var(--warn)">Leave the insole out until the red mark is gone. If it is still there tomorrow, stop and see a doctor.</p>` : ""}
      </div></div>`);
  }
  $("days").innerHTML = html.join("");
  renderRamp(today);
}

// The plan at a glance, drawn from the same SCHEDULE as the day list.
function renderRamp(today) {
  const caps = SCHEDULE.map(([a, b, label]) =>
    `<span class="ramp-cap" style="grid-column:${a} / ${b + 1}">${label}</span>`).join("");
  const bars = [];
  for (let d = 1; d <= 14; d++) {
    const [, , label] = targetFor(d);
    const logged = state.days[d]?.hours != null && state.days[d].hours !== "";
    const cls = [d === today ? "today" : "", logged ? "logged" : ""].join(" ");
    bars.push(`<button type="button" class="ramp-day ${cls}" data-day="${d}" style="grid-column:${d}"
      aria-label="Day ${d}: up to ${label === "All day" ? "all day" : label.replace(" h", " hours")}${d === today ? ", today" : ""}. Go to day ${d}.">
      <span class="bar" style="height:${(100 * hoursCap(label)) / 16}%"></span><span class="ramp-num">${d}</span></button>`);
  }
  $("ramp").innerHTML = caps + bars.join("");
  $("ramp").classList.toggle("stopped", !!state.stopped);
}

$("ramp").addEventListener("click", (e) => {
  const btn = e.target.closest(".ramp-day");
  if (!btn) return;
  const card = $(`h${btn.dataset.day}`)?.closest(".day");
  if (!card) return;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  card.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "center" });
  card.classList.remove("flash");
  void card.offsetWidth; // restart the highlight if it's tapped twice
  card.classList.add("flash");
});

$("days").addEventListener("change", (ev) => {
  const el = ev.target;
  if (!el.dataset.day) return;
  const d = el.dataset.day;
  state.days[d] = { ...(state.days[d] || {}), [el.dataset.k]: el.value };
  save(); render();
});
$("revision").addEventListener("input", (e) => { state.revision = e.target.value; save(); });
$("start").addEventListener("change", (e) => { state.start = e.target.value; save(); render(); });
$("btn-reset").addEventListener("click", () => {
  if (state.stopped) return;
  if (!confirm("Clear all entries?")) return;
  state = { revision: "", start: "", days: {}, stopped: null, reviews: state.reviews };
  save(); render();
});

const syncResume = () => ($("btn-resume").disabled = !($("reviewed-ack").checked && $("reviewer").value.trim()));
$("reviewer").addEventListener("input", syncResume);
$("reviewed-ack").addEventListener("change", syncResume);
$("btn-resume").addEventListener("click", () => {
  state.reviews.push({ at: new Date().toISOString(), by: $("reviewer").value.trim(), reason: state.stopped });
  // Resuming starts the protocol again from day 1: the flagged entries stay in the review log.
  state = { ...state, days: {}, start: "", stopped: null };
  save(); render();
});

render();
import("/assets/interact.js").then(({ growBars }) => growBars($("ramp")));
