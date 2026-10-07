// The welcome illustration: the whole idea of footscan in one looping scene.
//
// A foot stands on the printed mat. A phone walks all the way around it,
// taking photos; the ring of angles around the mat fills in as it goes (the
// same coverage idea the real scanner uses). A scan line passes over the
// foot, the toes fade, and the outline becomes an insole with a lattice
// inside, which lifts off the mat with a tick.
//
// It only runs while it is on screen, stops when the page moves on, and with
// "reduce motion" on it is a still picture of the finished insole.
import { animate, inView } from "./motion.js";
import { enabled, POP } from "./fx.js";
import { FOOT_PATH, TOES } from "./layout.js";
import { arcSegment, orbitPoint, segmentAt } from "./scene-math.js";

const W = 320, H = 268, CX = 160, CY = 134;
const ORBIT = { rx: 134, ry: 108 };
const RING = { rx: 147, ry: 121 };
const N = 12;
// The foot drawing is 200 units square; this places it in the middle of the mat.
const FOOT_T = `translate(${CX} ${CY + 4}) scale(0.72) translate(-100 -100)`;

// Like the real mat: markers down both long edges and across the far end of
// each sheet, none along the taped seam in the middle.
function markers(x0, y0, w, h, end) {
  const sq = (x, y) => `<rect x="${x}" y="${y}" width="7" height="7" rx="1"/>`;
  let out = "";
  const ys = end === "top" ? [y0 + 6, y0 + h - 12] : [y0 + 4, y0 + h - 14];
  for (let y = ys[0]; y <= ys[1]; y += 13) out += sq(x0 + 4, y) + sq(x0 + w - 11, y);
  const ey = end === "top" ? y0 + 4 : y0 + h - 11;
  for (const x of [x0 + 26, x0 + 38, x0 + 50, x0 + 62]) out += sq(x, ey);
  return out;
}

export function mountScene(host) {
  const segs = Array.from({ length: N }, (_, i) =>
    `<path class="seg" d="${arcSegment(CX, CY, RING.rx, RING.ry, i, N)}"/>`).join("");
  const toes = TOES.map(([x, y, r]) => `<circle class="toe" cx="${x}" cy="${y}" r="${r}"/>`).join("");
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="A phone circles a foot standing on the printed mat, taking photos from every side; the foot then becomes an insole shaped to it">
    <defs>
      <pattern id="lattice" width="9" height="15.6" patternUnits="userSpaceOnUse" patternTransform="scale(0.9)">
        <path d="M4.5 0 9 2.6v5.2L4.5 10.4 0 7.8V2.6zM4.5 10.4V15.6" fill="none" stroke="var(--brand)" stroke-width="0.9" opacity="0.55"/>
      </pattern>
      <linearGradient id="scanline" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="var(--accent)" stop-opacity="0"/>
        <stop offset="0.5" stop-color="var(--accent)" stop-opacity="0.85"/>
        <stop offset="1" stop-color="var(--accent)" stop-opacity="0"/>
      </linearGradient>
      <clipPath id="footclip"><path d="${FOOT_PATH}" transform="${FOOT_T}"/></clipPath>
      <filter id="lift" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#000" flood-opacity="0.22"/></filter>
    </defs>
    <ellipse class="orbit" cx="${CX}" cy="${CY}" rx="${ORBIT.rx}" ry="${ORBIT.ry}"/>
    <g class="ring">${segs}</g>
    <g class="mat">
      <rect class="sheet" x="${CX - 48}" y="${CY - 86}" width="96" height="86" rx="3"/>
      <rect class="sheet" x="${CX - 48}" y="${CY}" width="96" height="86" rx="3"/>
      <line class="seam" x1="${CX - 48}" y1="${CY}" x2="${CX + 48}" y2="${CY}"/>
      <g class="markers">${markers(CX - 48, CY - 86, 96, 86, "top")}${markers(CX - 48, CY, 96, 86, "bottom")}</g>
    </g>
    <g class="foot" transform="${FOOT_T}"><path class="sole" d="${FOOT_PATH}"/><g class="toes">${toes}</g></g>
    <g clip-path="url(#footclip)"><rect class="scan" x="${CX - 50}" y="${CY - 10}" width="100" height="16" fill="url(#scanline)" opacity="0"/></g>
    <g class="insole" opacity="0"><g transform="${FOOT_T}">
      <path class="insole-fill" d="${FOOT_PATH}" fill="url(#lattice)"/>
      <path class="insole-edge" d="${FOOT_PATH}" pathLength="1"/>
    </g></g>
    <g class="flash-at"><circle class="flash" r="16" opacity="0"/></g>
    <g class="phone"><rect x="-11" y="-19" width="22" height="38" rx="5"/><rect class="screen" x="-8" y="-15" width="16" height="27" rx="2"/><circle class="cam" cx="0" cy="-17" r="1.4"/></g>
    <g transform="translate(${CX + 52} ${CY - 70})"><g class="badge" opacity="0">
      <circle r="15"/><path d="M-6 0.5l4 4 8-9" pathLength="1"/>
    </g></g>
  </svg>`;
  const svg = host.querySelector("svg");
  const $ = (s) => svg.querySelector(s);
  const parts = {
    phone: $(".phone"), flash: $(".flash"), flashAt: $(".flash-at"), segs: [...svg.querySelectorAll(".seg")], scan: $(".scan"),
    sole: $(".sole"), toes: [...svg.querySelectorAll(".toe")], insole: $(".insole"), edge: $(".insole-edge"),
    fill: $(".insole-fill"), badge: $(".badge"), foot: $(".foot"),
  };

  const placePhone = (t) => {
    const p = orbitPoint(CX, CY, ORBIT.rx, ORBIT.ry, t);
    parts.phone.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)}) rotate(${(p.facing + 180).toFixed(1)})`);
    return p;
  };

  if (!enabled()) {
    // Still picture: the finished result, with the phone resting at one side.
    placePhone(0.62);
    parts.segs.forEach((s) => s.classList.add("lit"));
    parts.toes.forEach((t) => (t.style.opacity = "0.25"));
    parts.insole.setAttribute("opacity", "1");
    parts.badge.setAttribute("opacity", "1");
    return () => {};
  }

  let alive = false;
  let running = null;
  const live = new Set();
  const track = (a) => { live.add(a); a.then(() => live.delete(a), () => live.delete(a)); return a; };
  const wait = (s) => new Promise((r) => setTimeout(r, s * 1000));

  async function reset() {
    await Promise.all([
      track(animate(parts.insole, { opacity: 0 }, { duration: 0.45 })),
      track(animate(parts.badge, { opacity: 0, scale: 0.6 }, { duration: 0.3 })),
      track(animate(parts.sole, { opacity: 1 }, { duration: 0.45 })),
      track(animate(parts.toes, { opacity: 1, scale: 1 }, { duration: 0.45 })),
      track(animate(parts.segs, { opacity: 0.18 }, { duration: 0.45 })),
    ]);
    parts.segs.forEach((s) => s.classList.remove("lit"));
  }

  async function orbit() {
    let lastSeg = -1;
    await track(animate(0, 1, {
      duration: 5.2,
      ease: "easeInOut",
      onUpdate: (t) => {
        placePhone(t);
        const seg = segmentAt(t, N);
        if (seg !== lastSeg && t > 0.002) {
          lastSeg = seg;
          snap(t);
          parts.segs[seg].classList.add("lit");
          track(animate(parts.segs[seg], { opacity: [0.35, 1] }, POP));
        }
      },
    }));
  }

  function snap(t) {
    const p = orbitPoint(CX, CY, ORBIT.rx, ORBIT.ry, t);
    parts.flashAt.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
    track(animate(parts.flash, { opacity: [0.9, 0], scale: [0.4, 1.6] }, { duration: 0.45, ease: "easeOut" }));
  }

  async function transform() {
    // scan line: heel to toe, over the foot only
    await track(animate(parts.scan, { opacity: [0, 1, 1, 0], y: [62, 20, -40, -72] }, { duration: 1.1, ease: "easeInOut" }));
    // the foot becomes an insole
    track(animate(parts.toes, { opacity: 0, scale: 0.4 }, { duration: 0.45, delay: (i) => i * 0.05 }));
    track(animate(parts.sole, { opacity: 0.25 }, { duration: 0.6 }));
    parts.insole.setAttribute("opacity", "1");
    track(animate(parts.fill, { opacity: [0, 1] }, { duration: 0.8, delay: 0.25 }));
    await track(animate(parts.edge, { pathLength: [0, 1] }, { duration: 1.0, ease: "easeInOut" }));
    track(animate(parts.insole, { y: [0, -7] }, POP));
    parts.insole.setAttribute("filter", "url(#lift)");
    await track(animate(parts.badge, { opacity: [0, 1], scale: [0.4, 1] }, POP));
    track(animate(parts.badge.querySelector("path"), { pathLength: [0, 1] }, { duration: 0.35 }));
  }

  async function loop() {
    while (alive) {
      await orbit();
      if (!alive) break;
      await transform();
      if (!alive) break;
      await wait(2.2);
      parts.insole.removeAttribute("filter");
      track(animate(parts.insole, { y: 0 }, { duration: 0.3 }));
      await reset();
      await wait(0.5);
    }
  }

  placePhone(0);
  parts.segs.forEach((s) => (s.style.opacity = "0.18"));
  // Run while the picture is visible; stop (and leave it tidy) when it isn't.
  const stopWatching = inView(host, () => {
    alive = true;
    running ??= loop().finally(() => (running = null));
    return () => {
      alive = false;
      for (const a of live) a.stop?.();
    };
  }, { amount: 0.25 });
  return stopWatching;
}

/**
 * The setup page's "how to move the phone" diagram, brought to life: a phone
 * walks round the foot on the left, and climbs low, mid, above on the right.
 */
export function animatePathDiagram(host) {
  if (!enabled()) return () => {};
  const svg = host.querySelector("svg");
  if (!svg || svg.querySelector(".walker")) return () => {};
  const ns = "http://www.w3.org/2000/svg";
  const mk = (cls) => {
    const g = document.createElementNS(ns, "g");
    g.setAttribute("class", `walker ${cls}`);
    g.innerHTML = `<rect x="-6" y="-10" width="12" height="20" rx="2.5"/><circle cx="0" cy="-4" r="2.2"/>`;
    svg.append(g);
    return g;
  };
  const around = mk("around");
  const climb = mk("climb");
  // The static diagram's ellipse (left panel) and the three heights (right panel).
  const E = { cx: 72, cy: 76, rx: 56, ry: 34 };
  const steps = [[176, 100, 60], [180, 66, 35], [216, 38, 0]];
  let stop = false;
  const live = [];
  const go = async () => {
    while (!stop) {
      const a = animate(0, 1, {
        duration: 4.5, ease: "linear",
        onUpdate: (t) => {
          const p = orbitPoint(E.cx, E.cy, E.rx, E.ry, t);
          around.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)}) rotate(${(p.facing + 180).toFixed(1)})`);
          const k = Math.min(2, Math.floor(t * 3));
          const [x, y, r] = steps[k];
          climb.setAttribute("transform", `translate(${x} ${y}) rotate(${r})`);
        },
      });
      live.push(a);
      try { await a; } catch { break; }
    }
  };
  const stopWatching = inView(host, () => {
    stop = false;
    go();
    return () => { stop = true; live.forEach((a) => a.stop?.()); };
  });
  return stopWatching;
}
