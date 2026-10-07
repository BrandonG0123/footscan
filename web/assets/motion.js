// Motion (https://motion.dev, MIT), vendored at /vendor/motion/motion.js.
//
// The browser build is a classic script that sets window.Motion, loaded on
// each page just before the modules. This file re-exports what the pages use,
// so everything else imports from one place. If the script didn't load,
// `available` is false and every effect quietly does nothing: the pages work
// exactly the same, just without movement.
const M = globalThis.Motion ?? null;

export const available = !!M?.animate;
export const animate = M?.animate;
export const stagger = M?.stagger;
export const inView = M?.inView;
export const scroll = M?.scroll;
