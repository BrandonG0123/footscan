// The welcome illustration: the whole idea of footscan in one scene, which
// you can also play with.
//
// A foot stands on the printed mat. A phone walks all the way around it,
// taking photos; the ring of angles around the mat fills in as it goes (the
// same coverage idea the real scanner uses). A scan line passes over the
// foot, the toes fade, and the outline becomes an insole with a lattice
// inside, which lifts off the mat with a tick.
//
// Touch it (or drag with a mouse, or use the arrow keys) and the phone is
// yours: walk it round the foot and each side you pass lights up. Light all
// twelve and the foot turns into the insole, which is exactly what a real
// scan needs. Leave it alone for a few seconds and it goes back to playing by
// itself. A vertical swipe still scrolls the page.
//
// The scene is in two layers, the ring and phone behind and the mat and foot
// in front, which drift apart a little as the mouse moves (or, on phones that
// allow it without asking, as the phone tilts), so it reads as having depth.
//
// It only runs while it is on screen, and with "reduce motion" on it is a
// still picture of the finished insole.
import { animate, inView } from "./motion.js";
import { enabled, POP, SOFT } from "./fx.js";
import { FOOT_PATH, TOES } from "./layout.js";
import { arcSegment, orbitParam, orbitPoint, segmentAt, segmentsSwept, shortestDelta } from "./scene-math.js";

const W = 320, H = 268, CX = 160, CY = 134;
const ORBIT = { rx: 134, ry: 108 };
const RING = { rx: 147, ry: 121 };
const N = 12;
// The foot drawing is 200 units square; this places it in the middle of the mat.
const FOOT_T = `translate(${CX} ${CY + 4}) scale(0.72) translate(-100 -100)`;
const IDLE_MS = 6000;       // hands off this long: it plays by itself again
const DONE_HOLD_MS = 3500;  // after you finish the circle, admire the insole this long
const DRAG_START_PX = 6;    // a touch has to move this far to count as a drag

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

const HINT_INVITE = "Drag the phone round the foot";

export function mountScene(host) {
  const segs = Array.from({ length: N }, (_, i) =>
    `<path class="seg" d="${arcSegment(CX, CY, RING.rx, RING.ry, i, N)}"/>`).join("");
  const toes = TOES.map(([x, y, r]) => `<circle class="toe" cx="${x}" cy="${y}" r="${r}"/>`).join("");
  const label = "A phone circles a foot standing on the printed mat, taking photos from every side; the foot then becomes an insole shaped to it";
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">
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
    <g class="layer-far">
      <ellipse class="orbit" cx="${CX}" cy="${CY}" rx="${ORBIT.rx}" ry="${ORBIT.ry}"/>
      <g class="ring">${segs}</g>
    </g>
    <g class="layer-near">
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
      <g transform="translate(${CX + 52} ${CY - 70})"><g class="badge" opacity="0">
        <circle r="15"/><path d="M-6 0.5l4 4 8-9" pathLength="1"/>
      </g></g>
    </g>
    <g class="layer-far2">
      <g class="flash-at"><circle class="flash" r="16" opacity="0"/></g>
      <g class="phone-at"><g class="phone"><rect x="-11" y="-19" width="22" height="38" rx="5"/><rect class="screen" x="-8" y="-15" width="16" height="27" rx="2"/><circle class="cam" cx="0" cy="-17" r="1.4"/></g></g>
    </g>
  </svg>
  <span class="phone-grip" aria-hidden="true"></span>
  <p class="scene-hint" aria-hidden="true"><span class="scene-hint-icon"></span><span class="scene-hint-text"></span></p>`;
  const svg = host.querySelector("svg");
  const $ = (s) => host.querySelector(s);
  const parts = {
    phoneAt: $(".phone-at"), phone: $(".phone"), flash: $(".flash"), flashAt: $(".flash-at"),
    segs: [...svg.querySelectorAll(".seg")], scan: $(".scan"),
    sole: $(".sole"), toes: [...svg.querySelectorAll(".toe")], insole: $(".insole"), edge: $(".insole-edge"),
    fill: $(".insole-fill"), badge: $(".badge"), foot: $(".foot"),
    far: [$(".layer-far"), $(".layer-far2")], near: $(".layer-near"),
    hint: $(".scene-hint"), hintText: $(".scene-hint-text"), grip: $(".phone-grip"),
  };
  // The grip is an invisible, finger-sized handle over the phone (HTML, so it
  // can refuse to scroll the page): grab the phone itself and drag it any way.
  let scale = 1;
  const measure = () => (scale = svg.clientWidth / W || 1);
  new ResizeObserver(measure).observe(svg);

  let phoneT = 0;
  const placePhone = (t) => {
    phoneT = ((t % 1) + 1) % 1;
    const p = orbitPoint(CX, CY, ORBIT.rx, ORBIT.ry, phoneT);
    parts.phoneAt.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)}) rotate(${(p.facing + 180).toFixed(1)})`);
    parts.grip.style.transform = `translate(${(p.x * scale).toFixed(1)}px, ${(p.y * scale).toFixed(1)}px)`;
    return p;
  };

  if (!enabled()) {
    // Still picture: the finished result, with the phone resting at one side.
    placePhone(0.62);
    parts.segs.forEach((s) => s.classList.add("lit"));
    parts.toes.forEach((t) => (t.style.opacity = "0.25"));
    parts.insole.setAttribute("opacity", "1");
    parts.badge.setAttribute("opacity", "1");
    parts.hint.hidden = true;
    return () => {};
  }

  // ---- bookkeeping: every running animation is tracked so a hand on the
  // scene (or scrolling away) can stop the lot at once. `gen` counts those
  // interruptions; a sequence that sees it change stops where it is.
  let gen = 0;
  let alive = false;
  let mode = "auto"; // "auto": playing by itself; "user": you're driving; "done": you finished
  const live = new Set();
  const track = (a) => { live.add(a); a.then(() => live.delete(a), () => live.delete(a)); return a; };
  let signal = makeSignal();
  function makeSignal() { let fire; const p = new Promise((r) => (fire = r)); return { p, fire }; }
  // Wait for something, unless interrupted first.
  const step = (p) => Promise.race([p, signal.p]);
  const wait = (s) => new Promise((r) => setTimeout(r, s * 1000));
  function interrupt() {
    gen++;
    signal.fire();
    signal = makeSignal();
    for (const a of live) a.stop?.();
    live.clear();
  }

  // ---- the pieces of the story, used by both the autoplay and you
  function reset(d = 0.45) {
    parts.segs.forEach((s) => s.classList.remove("lit"));
    parts.insole.removeAttribute("filter");
    return Promise.all([
      track(animate(parts.insole, { opacity: 0, y: 0 }, { duration: d })),
      track(animate(parts.badge, { opacity: 0, scale: 0.6 }, { duration: d * 0.7 })),
      track(animate(parts.sole, { opacity: 1 }, { duration: d })),
      track(animate(parts.toes, { opacity: 1, scale: 1 }, { duration: d })),
      track(animate(parts.segs, { opacity: 0.18 }, { duration: d })),
      track(animate(parts.scan, { opacity: 0 }, { duration: 0.1 })),
    ]);
  }

  function snapAt(t) {
    const p = orbitPoint(CX, CY, ORBIT.rx, ORBIT.ry, t);
    parts.flashAt.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
    track(animate(parts.flash, { opacity: [0.9, 0], scale: [0.4, 1.6] }, { duration: 0.45, ease: "easeOut" }));
  }

  function light(seg) {
    const el = parts.segs[seg];
    if (el.classList.contains("lit")) return false;
    el.classList.add("lit");
    track(animate(el, { opacity: [0.35, 1], strokeWidth: [11, 7] }, POP));
    return true;
  }

  async function transform() {
    // scan line: heel to toe, over the foot only
    await track(animate(parts.scan, { opacity: [0, 1, 1, 0], y: [62, 20, -40, -72] }, { duration: 1.1, ease: "easeInOut" }));
    // the foot becomes an insole
    track(animate(parts.toes, { opacity: 0, scale: 0.4 }, { duration: 0.45, delay: (i) => i * 0.05 }));
    track(animate(parts.sole, { opacity: 0.25 }, { duration: 0.6 }));
    // (reset() faded it out with an inline style, which outranks the attribute)
    parts.insole.setAttribute("opacity", "1");
    parts.insole.style.opacity = "1";
    track(animate(parts.fill, { opacity: [0, 1] }, { duration: 0.8, delay: 0.25 }));
    await track(animate(parts.edge, { pathLength: [0, 1] }, { duration: 1.0, ease: "easeInOut" }));
    track(animate(parts.insole, { y: [0, -7] }, POP));
    parts.insole.setAttribute("filter", "url(#lift)");
    await track(animate(parts.badge, { opacity: [0, 1], scale: [0.4, 1] }, POP));
    track(animate(parts.badge.querySelector("path"), { pathLength: [0, 1] }, { duration: 0.35 }));
  }

  // ---- playing by itself
  async function orbitOnce() {
    let lastSeg = -1;
    const from = phoneT;
    await track(animate(0, 1, {
      duration: 5.2,
      ease: "easeInOut",
      onUpdate: (k) => {
        const t = from + k;
        placePhone(t);
        const seg = segmentAt(t, N);
        if (seg !== lastSeg && k > 0.002) {
          lastSeg = seg;
          snapAt(t);
          light(seg);
        }
      },
    }));
  }

  async function autoplay(my) {
    await step(reset());
    while (my === gen) {
      await step(orbitOnce()); if (my !== gen) return;
      await step(transform()); if (my !== gen) return;
      await step(wait(2.2)); if (my !== gen) return;
      await step(reset()); if (my !== gen) return;
      await step(wait(0.5));
    }
  }

  function startAuto() {
    interrupt();
    mode = "auto";
    hint(HINT_INVITE, "invite");
    if (alive) autoplay(gen);
  }

  // ---- you driving
  let idleTimer = null;
  const armIdle = (ms = IDLE_MS) => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { if (mode !== "auto") startAuto(); }, ms);
  };

  function takeOver() {
    clearTimeout(idleTimer);
    if (mode === "user") return;
    interrupt();
    mode = "user";
    reset(0.25);
    hint(countText(), "count");
  }

  const litCount = () => parts.segs.filter((s) => s.classList.contains("lit")).length;
  const countText = () => `${litCount()} of ${N} sides`;

  function buzz(pattern) {
    try { navigator.vibrate?.(pattern); } catch { /* not allowed here: fine */ }
  }

  // Move the phone by `delta` of a turn, lighting every side it passes.
  function walk(delta) {
    const swept = segmentsSwept(phoneT, delta, N);
    placePhone(phoneT + delta);
    let fresh = 0;
    for (const s of swept) if (light(s)) { fresh++; snapAt((s + 0.5) / N); }
    if (!fresh) return;
    buzz(6);
    const n = litCount();
    hint(countText(), "count");
    if (n === N) finish();
  }

  let glide = null;
  // Go to an orbit position: straight there while dragging, or a quick glide
  // round the ring for a tap or a key press (lighting the sides on the way).
  function goTo(t, { smooth }) {
    glide?.stop();
    const d = shortestDelta(phoneT, t);
    if (!smooth || Math.abs(d) < 0.02) { walk(d); return; }
    let done = 0;
    glide = track(animate(0, 1, {
      duration: 0.25 + Math.abs(d) * 0.8, ease: "easeOut",
      onUpdate: (k) => { if (mode !== "user") return; walk(d * k - done); done = d * k; },
    }));
  }

  async function finish() {
    mode = "done";
    glide?.stop();
    clearTimeout(idleTimer);
    buzz([12, 50, 18]);
    hint("That's a whole scan: every side", "done");
    const my = gen;
    await step(transform());
    if (my !== gen) return;
    armIdle(DONE_HOLD_MS);
  }

  // ---- pointer: drag along the ring, tap to jump, a vertical swipe still scrolls
  // From the screen to the drawing's own units, via the picture's on-screen
  // box (which already includes the scroll parallax's move and shrink).
  function toOrbit(e) {
    const r = svg.getBoundingClientRect();
    if (!r.width) return null;
    const p = { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
    const nx = (p.x - CX) / ORBIT.rx, ny = (p.y - CY) / ORBIT.ry;
    return { t: orbitParam(CX, CY, ORBIT.rx, ORBIT.ry, p.x, p.y), r: Math.hypot(nx, ny) };
  }

  let press = null;
  const inScene = (el) => el === parts.grip || svg.contains(el);
  host.addEventListener("pointerdown", (e) => {
    if (e.button > 0 || !inScene(e.target)) return;
    const grip = e.target === parts.grip;
    press = { id: e.pointerId, x: e.clientX, y: e.clientY, dragging: false, grip };
    if (e.pointerType === "mouse" || grip) host.setPointerCapture?.(e.pointerId);
  });
  host.addEventListener("pointermove", (e) => {
    if (!press || e.pointerId !== press.id || mode === "done") return;
    if (!press.dragging) {
      const dx = Math.abs(e.clientX - press.x), dy = Math.abs(e.clientY - press.y);
      if (Math.hypot(dx, dy) < DRAG_START_PX) return;
      // A finger that sets off up or down is scrolling the page, not steering
      // (unless it is holding the phone itself).
      if (e.pointerType !== "mouse" && !press.grip && dy > dx) { press = null; return; }
      press.dragging = true;
      takeOver();
      host.classList.add("dragging");
    }
    const o = toOrbit(e);
    if (o && o.r > 0.25) goTo(o.t, { smooth: false });
  });
  const release = (e, cancelled) => {
    if (!press || e.pointerId !== press.id) return;
    const wasTap = !press.dragging && !cancelled;
    press = null;
    host.classList.remove("dragging");
    if (wasTap) {
      const o = toOrbit(e);
      if (o && o.r < 0.45) wiggleFoot();
      else if (o && mode !== "done") { takeOver(); goTo(o.t, { smooth: true }); }
    }
    if (mode === "user") armIdle();
  };
  host.addEventListener("pointerup", (e) => release(e, false));
  // The browser took the touch for scrolling (a vertical swipe): leave the scene be.
  host.addEventListener("pointercancel", (e) => release(e, true));

  // A tap on the foot: the toes wiggle. Just because.
  function wiggleFoot() {
    if (parts.insole.getAttribute("opacity") === "1" && mode !== "auto") return;
    animate(parts.toes, { y: [0, -5, 0, -2, 0] }, { duration: 0.6, delay: (i) => i * 0.05, ease: "easeOut" });
    buzz(8);
  }

  // ---- keyboard: the scene is focusable; arrows walk the phone a side at a time
  svg.setAttribute("tabindex", "0");
  svg.setAttribute("aria-label", `${label}. Press the left and right arrow keys to walk the phone round the foot yourself.`);
  svg.addEventListener("keydown", (e) => {
    const dir = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!dir || mode === "done") return;
    e.preventDefault();
    takeOver();
    goTo(phoneT + dir / N, { smooth: true });
    armIdle();
  });

  // ---- the hint under the picture
  let hintMode = "";
  function hint(text, kind) {
    const changed = kind !== hintMode;
    hintMode = kind;
    parts.hint.dataset.kind = kind;
    if (parts.hintText.textContent === text) return;
    parts.hintText.textContent = text;
    if (changed) animate(parts.hint, { opacity: [0, 1], y: [6, 0] }, SOFT);
    else if (kind === "count") animate(parts.hintText, { scale: [1.12, 1] }, POP);
  }

  // ---- depth: the two layers drift apart with the mouse, or the phone's tilt
  const shift = (fx, fy) => {
    for (const el of parts.far) animate(el, { x: fx * -5, y: fy * -4 }, SOFT);
    animate(parts.near, { x: fx * 4, y: fy * 3 }, SOFT);
  };
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  addEventListener("pointermove", (e) => {
    if (!alive || !fine.matches || e.pointerType !== "mouse") return;
    const r = host.getBoundingClientRect();
    shift(Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width * 0.8))),
          Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height * 0.8))));
  }, { passive: true });
  // iPhones only report tilt after a permission prompt, which a welcome page
  // has no business showing; Android and others report it freely.
  if (!fine.matches && typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission !== "function") {
    let base = null, last = 0;
    addEventListener("deviceorientation", (e) => {
      if (!alive || e.beta == null || e.gamma == null) return;
      const now = performance.now();
      if (now - last < 50) return;
      last = now;
      base ??= { b: e.beta, g: e.gamma };
      // drift the resting angle slowly, so holding the phone a new way becomes "level"
      base.b += (e.beta - base.b) * 0.01;
      base.g += (e.gamma - base.g) * 0.01;
      const c = (v) => Math.max(-1, Math.min(1, v / 18));
      shift(c(e.gamma - base.g), c(e.beta - base.b));
    });
  }

  placePhone(0);
  parts.segs.forEach((s) => (s.style.opacity = "0.18"));
  hint(HINT_INVITE, "invite");
  // Run while the picture is visible; stop (and leave it tidy) when it isn't.
  const stopWatching = inView(host, () => {
    alive = true;
    if (mode === "auto") autoplay(gen);
    return () => {
      alive = false;
      clearTimeout(idleTimer);
      interrupt();
      mode = "auto";
      hint(HINT_INVITE, "invite");
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
