// Motion effects for the customer pages: how things arrive, how they answer a
// tap, and a few moments of celebration.
//
// Rules every effect here follows:
// - Decoration only. Content is never hidden waiting for an animation: an
//   element is only made transparent by the same call that animates it back,
//   and its inline styles are cleared when it finishes.
// - "Reduce motion" (the system setting) turns everything off.
// - Nothing animates the camera stage or anything containing it: a transform
//   on an ancestor would turn the fullscreen camera's position: fixed into
//   position: absolute, and the scanner needs every frame it can get.
import { animate, available, inView, scroll, stagger } from "./motion.js";

const reducedQuery = matchMedia("(prefers-reduced-motion: reduce)");
const fineQuery = matchMedia("(hover: hover) and (pointer: fine)");
export const enabled = () => available && !reducedQuery.matches;
const fine = () => fineQuery.matches;

// Springs: "settle" for things arriving, "pop" for answers to a tap.
export const SETTLE = { type: "spring", visualDuration: 0.55, bounce: 0.18 };
export const POP = { type: "spring", visualDuration: 0.3, bounce: 0.5 };
const SOFT = { type: "spring", visualDuration: 0.4, bounce: 0.1 };

const NO_TOUCH = "#v-scan, .stage";
const touchesStage = (el) => !!el.closest(NO_TOUCH) || !!el.querySelector?.(".stage");

function clear(el, props = ["opacity", "transform", "filter"]) {
  for (const p of props) el.style.removeProperty(p);
}

async function settle(anim, els, props) {
  try { await anim; } catch { /* interrupted: still clean up */ }
  for (const el of els) clear(el, props);
}

// =========================================================================
// Arriving
// =========================================================================

/**
 * Bring blocks in: up (or across, by direction) and into focus, one after
 * another. dir: 1 = going forward (from the right), -1 = back, 0 = up.
 */
export function enter(targets, { dir = 0, delay = 0, each = 0.055, distance = 26, blur = true } = {}) {
  if (!enabled()) return;
  const els = [...targets].filter((el) => el && !el.hidden && el.offsetParent !== null && !touchesStage(el));
  if (!els.length) return;
  for (const el of els) el.style.opacity = "0";
  const from = dir ? { x: [dir * distance, 0] } : { y: [distance * 0.7, 0] };
  const anim = animate(els, {
    opacity: [0, 1],
    ...from,
    ...(blur ? { filter: ["blur(6px)", "blur(0px)"] } : {}),
  }, { ...SETTLE, delay: stagger(each, { startDelay: delay }), filter: { duration: 0.35 } });
  settle(anim, els);
}

/** A whole view arriving: its blocks in order, then lists inside it. */
export function enterView(view, dir = 0) {
  if (!enabled() || !view || touchesStage(view)) return;
  const blocks = [...view.children].filter((el) => !el.matches(".action-bar"));
  enter(blocks, { dir, each: 0.06 });
  for (const list of view.querySelectorAll(".stagger")) {
    enter(list.children, { delay: 0.18, each: 0.07, blur: false, distance: 18 });
  }
  const bar = view.querySelector(":scope > .action-bar");
  if (bar) enter([bar], { delay: 0.28, blur: false, distance: 18 });
}

/** Blocks further down a long page come in as they scroll into view. */
export function revealOnScroll(selector) {
  if (!enabled()) return;
  for (const el of document.querySelectorAll(selector)) {
    if (touchesStage(el) || el.getBoundingClientRect().top < innerHeight * 0.92) continue;
    el.style.opacity = "0";
    inView(el, () => {
      const anim = animate(el, { opacity: [0, 1], y: [28, 0] }, SETTLE);
      settle(anim, [el]);
    }, { amount: 0.12 });
  }
}

/** The soft wash behind the top of the page drifts up as the page scrolls. */
export function parallaxGlow() {
  const glow = document.querySelector(".page-glow");
  if (!enabled() || !glow) return;
  scroll(animate(glow, { y: [0, -140], opacity: [0.55, 0.15] }, { ease: "linear" }));
}

// =========================================================================
// Answering a touch
// =========================================================================
const PRESSABLE = ".btn, .choice, .ack label, .confirm, .segmented label, .foot-row, .stage-btn";

/**
 * Everything you can tap gives way under your finger (a quick spring down
 * and back) and sends a ripple out from exactly where you touched.
 */
export function initPress() {
  if (!available) return;
  document.addEventListener("pointerdown", (e) => {
    const el = e.target.closest(PRESSABLE);
    if (!el || !enabled() || el.matches(":disabled, [aria-disabled='true']")) return;
    animate(el, { scale: 0.965 }, POP);
    ripple(el, e.clientX, e.clientY);
    const up = () => {
      const a = animate(el, { scale: 1 }, POP);
      settle(a, [el], ["transform"]);
      removeEventListener("pointerup", up);
      removeEventListener("pointercancel", up);
    };
    addEventListener("pointerup", up);
    addEventListener("pointercancel", up);
  });
}

function ripple(el, x, y) {
  const r = el.getBoundingClientRect();
  const size = Math.hypot(r.width, r.height) * 2;
  const dot = document.createElement("span");
  dot.className = "ripple";
  dot.setAttribute("aria-hidden", "true");
  Object.assign(dot.style, { width: `${size}px`, height: `${size}px`, left: `${x - r.left - size / 2}px`, top: `${y - r.top - size / 2}px` });
  el.append(dot);
  animate(dot, { scale: [0, 1], opacity: [0.32, 0] }, { duration: 0.6, ease: "easeOut" }).then(() => dot.remove(), () => dot.remove());
}

/** Cards that lean toward the mouse, a few degrees, on computers with a mouse. */
export function initTilt(selector = ".tilt") {
  if (!available) return;
  document.addEventListener("pointermove", (e) => {
    if (!enabled() || !fine()) return;
    const el = e.target.closest(selector);
    if (!el || touchesStage(el)) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el._tilting = true;
    animate(el, { rotateY: px * 5, rotateX: -py * 4, transformPerspective: 900 }, SOFT);
  });
  document.addEventListener("pointerout", (e) => {
    const el = e.target.closest?.(selector);
    if (!el || !el._tilting || el.contains(e.relatedTarget)) return;
    el._tilting = false;
    settle(animate(el, { rotateY: 0, rotateX: 0 }, SOFT), [el], ["transform"]);
  });
}

/** Primary buttons drift a few pixels toward the cursor, as if magnetic. */
export function initMagnetic(selector = ".btn.magnetic") {
  if (!available) return;
  document.addEventListener("pointermove", (e) => {
    if (!enabled() || !fine()) return;
    for (const el of document.querySelectorAll(selector)) {
      if (el.disabled || el.offsetParent === null) continue;
      const r = el.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height / 2);
      const near = Math.abs(dx) < r.width / 2 + 40 && Math.abs(dy) < r.height / 2 + 40;
      if (near) {
        el._magnet = true;
        animate(el, { x: dx * 0.12, y: dy * 0.18 }, SOFT);
      } else if (el._magnet) {
        el._magnet = false;
        settle(animate(el, { x: 0, y: 0 }, SOFT), [el], ["transform"]);
      }
    }
  });
}

// =========================================================================
// Controls
// =========================================================================

/**
 * A segmented control (radio buttons styled as a pill row) gets a single pill
 * that slides to the chosen option instead of jumping. Without motion, the
 * stylesheet's own "checked" colour still shows the choice.
 */
export function initSegmented(group) {
  if (!available || !group || group.querySelector(".seg-pill")) return;
  const pill = document.createElement("span");
  pill.className = "seg-pill";
  pill.setAttribute("aria-hidden", "true");
  group.prepend(pill);
  group.classList.add("has-pill");
  const place = (instant) => {
    const label = group.querySelector("input:checked")?.closest("label");
    if (!label) return;
    const to = { x: label.offsetLeft, width: label.offsetWidth };
    if (instant || !enabled()) {
      pill.style.transform = `translateX(${to.x}px)`;
      pill.style.width = `${to.width}px`;
    } else {
      animate(pill, { x: to.x, width: to.width }, POP);
    }
  };
  group.addEventListener("change", () => place(false));
  requestAnimationFrame(() => place(true));
  addEventListener("resize", () => place(true));
}

/** A tick box that was just ticked: the box pops and the tick draws itself. */
export function popTick(input) {
  if (!enabled()) return;
  const box = input.closest("label")?.querySelector(".tick");
  if (!box) return;
  animate(box, { scale: [0.7, 1] }, POP);
  const path = box.querySelector("path");
  if (path && input.checked) animate(path, { pathLength: [0, 1] }, { duration: 0.32, ease: "easeOut" });
}

/** A gentle "no" for something that needs fixing. */
export function shake(el) {
  if (!enabled() || !el || touchesStage(el)) return;
  settle(animate(el, { x: [0, -9, 8, -6, 4, 0] }, { duration: 0.42, ease: "easeOut" }), [el], ["transform"]);
}

/** One celebratory bounce, e.g. a button that has just become available. */
export function bounce(el, { scale = 1.05 } = {}) {
  if (!enabled() || !el) return;
  settle(animate(el, { scale: [1, scale, 1] }, { duration: 0.5, ease: "easeOut" }), [el], ["transform"]);
}

/** Count a number up (or down) to its new value. */
export function countTo(el, to, { from, format = (v) => String(Math.round(v)), duration = 0.6 } = {}) {
  if (!el) return;
  const start = from ?? (Number(el.dataset.value) || 0);
  el.dataset.value = String(to);
  if (!enabled() || start === to) { el.textContent = format(to); return; }
  animate(start, to, { duration, ease: "easeOut", onUpdate: (v) => (el.textContent = format(v)) });
}

/** Swap a line of text with a short fade, only when it actually changes. */
export function setText(el, text) {
  if (!el || el.textContent === text) return;
  el.textContent = text;
  if (enabled()) animate(el, { opacity: [0.35, 1] }, { duration: 0.22 });
}

// =========================================================================
// Progress across the steps
// =========================================================================

/** The step bar fills in with a spring as you move forward. */
export function updateSteps(list, at) {
  list.querySelectorAll("li").forEach((li, i) => {
    const state = i < at ? "done" : i === at ? "current" : "";
    const was = li.className;
    li.className = state;
    li.toggleAttribute("aria-current", i === at);
    const fill = li.querySelector(".fill");
    if (!fill) return;
    const filled = !!state;
    const wasFilled = was === "done" || was === "current";
    if (enabled() && filled !== wasFilled) {
      animate(fill, { scaleX: filled ? [0, 1] : [1, 0] }, { ...SETTLE, delay: filled ? 0.08 * Math.max(0, i - at + 1) : 0 })
        .then(() => fill.style.removeProperty("transform"), () => {});
    }
  });
}

// =========================================================================
// Celebrations
// =========================================================================
const CONFETTI = ["var(--brand)", "var(--accent)", "var(--ok)", "#ff9f43", "#5fa8ff", "#ff6b9a"];

/** Confetti from a point on the screen (the big tick on the last page). */
export function confetti(originEl, { count = 80 } = {}) {
  if (!enabled()) return;
  const r = originEl?.getBoundingClientRect() ?? { left: innerWidth / 2, top: innerHeight / 3, width: 0, height: 0 };
  const ox = r.left + r.width / 2, oy = r.top + r.height / 2;
  const layer = document.createElement("div");
  layer.className = "confetti-layer";
  layer.setAttribute("aria-hidden", "true");
  document.body.append(layer);
  const pieces = [];
  for (let i = 0; i < count; i++) {
    const p = document.createElement("i");
    const w = 6 + Math.random() * 6;
    Object.assign(p.style, {
      left: `${ox}px`, top: `${oy}px`, width: `${w}px`, height: `${w * (Math.random() < 0.5 ? 0.45 : 1)}px`,
      background: CONFETTI[i % CONFETTI.length], borderRadius: Math.random() < 0.3 ? "50%" : "2px",
    });
    layer.append(p);
    const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.25;
    const speed = 160 + Math.random() * 260;
    const dx = Math.cos(angle) * speed;
    const up = Math.sin(angle) * speed;
    const fall = innerHeight * (0.55 + Math.random() * 0.4);
    pieces.push(animate(p, {
      x: [0, dx * 0.7, dx],
      y: [0, up, up + fall],
      rotate: [0, (Math.random() - 0.5) * 720],
      opacity: [1, 1, 0],
    }, { duration: 1.6 + Math.random() * 0.9, ease: ["easeOut", "easeIn"], times: [0, 0.35, 1] }));
  }
  Promise.allSettled(pieces).then(() => layer.remove());
}

/** Draw an SVG tick (or any path) as if by hand. */
export function draw(path, { delay = 0, duration = 0.5 } = {}) {
  if (!enabled() || !path) return;
  animate(path, { pathLength: [0, 1] }, { delay, duration, ease: "easeInOut" });
}

// =========================================================================
// Uploading: your photos flying off one by one
// =========================================================================

/**
 * A fanned stack of the scan's own photos. advance(i) sends one off toward
 * the cloud; the stack shows the next. Shown only with motion on: otherwise
 * the plain progress bar says the same thing.
 */
export function photoDeck(container, urls) {
  container.innerHTML = "";
  if (!enabled() || !urls.length) {
    container.hidden = true;
    return { advance() {}, done() {} };
  }
  container.hidden = false;
  const shown = urls.slice(-7);
  const cloud = document.createElement("div");
  cloud.className = "deck-cloud";
  cloud.innerHTML = `<svg viewBox="0 0 48 36" aria-hidden="true"><path d="M14 30h22a8 8 0 0 0 1-16 11 11 0 0 0-21-3 9 9 0 0 0-2 19z" fill="var(--brand-soft)" stroke="var(--brand)" stroke-width="2"/><path d="M24 26V14m-5 5 5-5 5 5" fill="none" stroke="var(--brand)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  const stack = document.createElement("div");
  stack.className = "deck-stack";
  container.append(stack, cloud);
  const cards = shown.map((u, i) => {
    const img = document.createElement("img");
    img.src = u;
    img.alt = "";
    img.className = "deck-card";
    const rot = (i - shown.length / 2) * 4;
    img.style.transform = `rotate(${rot}deg)`;
    stack.append(img);
    animate(img, { opacity: [0, 1], y: [30, 0], rotate: [rot * 2, rot] }, { ...SETTLE, delay: i * 0.05 });
    return img;
  });
  let sent = 0;
  const flyEvery = Math.max(1, Math.round(urls.length / shown.length));
  return {
    advance(i) {
      if (i < flyEvery * (sent + 1) || sent >= cards.length) return;
      const card = cards[cards.length - 1 - sent++];
      const c = cloud.getBoundingClientRect(), k = card.getBoundingClientRect();
      const dx = c.left + c.width / 2 - (k.left + k.width / 2);
      const dy = c.top + c.height / 2 - (k.top + k.height / 2);
      animate(card, { x: dx, y: dy, scale: 0.15, rotate: 25, opacity: [1, 1, 0] }, { duration: 0.65, ease: "easeIn" });
      animate(cloud, { scale: [1, 1.12, 1] }, { duration: 0.35, delay: 0.5 });
    },
    done() {
      for (const card of cards.slice(0, cards.length - sent)) animate(card, { opacity: 0, scale: 0.8 }, { duration: 0.3 });
      animate(cloud, { scale: [1, 1.25, 1] }, POP);
    },
  };
}

// =========================================================================
// One call per page
// =========================================================================
export function initPage() {
  initPress();
  initTilt();
  initMagnetic();
  for (const g of document.querySelectorAll(".segmented")) initSegmented(g);
  document.addEventListener("change", (e) => {
    if (e.target.matches(".ack input, .confirm input, .tickable input")) popTick(e.target);
  });
  parallaxGlow();
}
