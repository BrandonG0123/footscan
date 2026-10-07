// The customer pages answering the scroll, and a few more things to touch.
//
// Scroll:
// - The welcome picture sinks back and fades as you scroll past it, slower
//   than the page (parallax), while the words beside it move at their own pace.
// - Numbered steps have a line running down through the numbers that fills
//   in as you read, lighting each number as it passes the middle of the screen.
// - Long pages (the mat and wearing pages) get a thin reading-progress bar
//   under the header, and the header lifts off the page once you scroll.
// - [data-parallax] blocks drift a little against the page.
//
// Touch:
// - The mat drawing tapes itself together when it comes into view, and again
//   when you tap it.
//
// Same rules as fx.js: decoration only, nothing waits on an animation to be
// readable, "reduce motion" turns it all off, and nothing here touches the
// camera stage or anything around it.
import { animate, inView, scroll, stagger } from "./motion.js";
import { enabled, POP, SETTLE } from "./fx.js";

// =========================================================================
// Scroll: the welcome picture
// =========================================================================
export function heroParallax(scene, copy) {
  if (!enabled() || !scene) return;
  // It shrinks toward its top edge as it lags behind, so on a phone (picture
  // above the words) its bottom never slides down over the heading.
  scene.style.transformOrigin = "50% 0%";
  const range = { target: scene, offset: ["start start", "end start"] };
  scroll(animate(scene, { y: [0, 36], scale: [1, 0.86], opacity: [1, 0.2] }, { ease: "linear" }), range);
  if (copy) scroll(animate(copy, { y: [0, -12] }, { ease: "linear" }), range);
}

/** Blocks marked data-parallax="0.2" drift against the page by that much. */
export function parallaxBlocks() {
  if (!enabled()) return;
  for (const el of document.querySelectorAll("[data-parallax]")) {
    const d = (Number(el.dataset.parallax) || 0.15) * 120;
    scroll(animate(el, { y: [d, -d] }, { ease: "linear" }), { target: el, offset: ["start end", "end start"] });
  }
}

// =========================================================================
// Scroll: steps that light up as you read them
// =========================================================================
const READ_LINE = 0.62; // how far down the screen counts as "being read"

function updateRails() {
  const atBottom = scrollY + innerHeight >= document.documentElement.scrollHeight - 4;
  const line = innerHeight * READ_LINE;
  for (const list of document.querySelectorAll("main ol.howto")) {
    if (list.offsetParent === null || list.closest("#v-scan")) continue;
    list.classList.add("rail");
    const items = [...list.children].filter((el) => el.tagName === "LI");
    if (items.length < 2) continue;
    const box = list.getBoundingClientRect();
    // the number circles are each item's ::before; find their centres
    const dot = parseFloat(getComputedStyle(items[0], "::before").width) || 30;
    const centre = (li) => li.offsetTop + dot / 2;
    const top = centre(items[0]), bottom = centre(items[items.length - 1]);
    list.style.setProperty("--rail-x", `${items[0].offsetLeft + dot / 2}px`);
    list.style.setProperty("--rail-top", `${top}px`);
    list.style.setProperty("--rail-h", `${bottom - top}px`);
    const at = atBottom ? Infinity : line - box.top;
    list.style.setProperty("--rail-p", String(Math.max(0, Math.min(1, (at - top) / (bottom - top)))));
    for (const li of items) {
      const lit = centre(li) <= at;
      if (lit !== li.classList.contains("lit")) li.classList.toggle("lit", lit); // the pop is CSS
    }
  }
}

export function stepRails() {
  if (!enabled()) return;
  scroll(() => updateRails());
  addEventListener("resize", updateRails);
  // A view changing on the scan page doesn't scroll anything, so it says so.
  document.addEventListener("fx:view", () => requestAnimationFrame(updateRails));
  requestAnimationFrame(updateRails);
}

// =========================================================================
// Scroll: where you are on a long page
// =========================================================================
export function readingProgress() {
  if (!enabled()) return;
  const header = document.querySelector(".site-header");
  if (!header) return;
  if (document.body.hasAttribute("data-longread")) {
    const bar = document.createElement("div");
    bar.className = "read-progress";
    bar.setAttribute("aria-hidden", "true");
    header.append(bar);
    scroll(animate(bar, { scaleX: [0, 1] }, { ease: "linear" }));
  }
  scroll((_, info) => header.classList.toggle("lifted", info.y.current > 8));
}

// =========================================================================
// Headings that arrive a word at a time
// =========================================================================
/**
 * Splits a heading's words into their own boxes and lets them rise in turn.
 * Screen readers get the heading as it was: the original text stays in a
 * visually hidden copy and the moving words are hidden from them.
 */
export function riseWords(el, { delay = 0.1 } = {}) {
  if (!enabled() || !el || el.dataset.risen) return;
  el.dataset.risen = "1";
  const plain = el.textContent.replace(/\s+/g, " ").trim();
  const words = [];
  const split = (node) => {
    const out = document.createDocumentFragment();
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.TEXT_NODE) {
        for (const part of child.textContent.split(/(\s+)/)) {
          if (!part) continue;
          if (/^\s+$/.test(part)) { out.append(" "); continue; }
          const w = document.createElement("span");
          w.className = "word";
          const inner = document.createElement("span");
          inner.textContent = part;
          w.append(inner);
          words.push(inner);
          out.append(w);
        }
      } else {
        const copy = child.cloneNode(false);
        copy.append(split(child));
        out.append(copy);
      }
    }
    return out;
  };
  const shown = document.createElement("span");
  shown.setAttribute("aria-hidden", "true");
  shown.append(split(el));
  const sr = document.createElement("span");
  sr.className = "sr-only";
  sr.textContent = plain;
  el.replaceChildren(sr, shown);
  animate(words, { y: ["110%", "0%"], opacity: [0, 1], rotate: [4, 0] }, { ...SETTLE, delay: stagger(0.06, { startDelay: delay }) });
}

// =========================================================================
// Touch: the mat tapes itself together
// =========================================================================
/**
 * The two sheets slide in from either end and meet, the dashed seam runs
 * across, the black squares pop in, and the foot steps on. Plays when the
 * drawing comes into view, and again on a tap.
 */
export function assembleMat(host) {
  if (!enabled() || !host || host.dataset.assemble) return;
  host.dataset.assemble = "1";
  const play = () => {
    const svg = host.querySelector("svg");
    if (!svg) return;
    const q = (s) => [...svg.querySelectorAll(s)];
    const [top, bottom] = [q(".sheet-2"), q(".sheet-1")];
    animate(top, { y: [-34, 0], rotate: [-5, 0], opacity: [0, 1] }, SETTLE);
    animate(bottom, { y: [34, 0], rotate: [4, 0], opacity: [0, 1] }, { ...SETTLE, delay: 0.08 });
    animate(q(".mat-seam"), { scaleX: [0, 1], opacity: [0, 1] }, { duration: 0.45, delay: 0.45, ease: "easeOut" });
    animate(q(".mat-sheet rect[width='9']"), { scale: [0, 1] }, { ...POP, delay: stagger(0.015, { startDelay: 0.5 }) });
    animate(q(".mat-foot-at"), { opacity: [0, 1], y: [-16, 0], scale: [1.25, 1] }, { ...SETTLE, delay: 0.85 });
    animate(q(".mat-legend"), { opacity: [0, 1] }, { duration: 0.4, delay: 1.1 });
  };
  inView(host, () => { play(); }, { amount: 0.45 });
  host.style.cursor = "pointer";
  host.addEventListener("click", play);
}

// =========================================================================
// Touch: bars that grow (the two-week wearing plan)
// =========================================================================
export function growBars(container, selector = ".bar") {
  if (!enabled() || !container) return;
  inView(container, () => {
    animate([...container.querySelectorAll(selector)], { scaleY: [0, 1] }, { ...SETTLE, delay: stagger(0.045) });
  }, { amount: 0.4 });
}

/** One call per customer page (from layout.js). */
export function initInteract() {
  stepRails();
  readingProgress();
  parallaxBlocks();
  const h1 = document.querySelector("main h1");
  if (h1 && h1.offsetParent !== null) riseWords(h1);
}
