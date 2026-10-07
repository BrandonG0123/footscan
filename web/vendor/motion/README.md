# Motion (vendored)

[Motion](https://motion.dev) 14.0.0, MIT licence (see LICENSE.md): the
browser build `dist/motion.js` from the npm package `motion`, unmodified.

Vendored rather than loaded from a CDN because the site's Content Security
Policy only allows scripts from itself. It sets `window.Motion`;
`web/assets/motion.js` re-exports what the pages use. To update: `npm pack
motion`, copy `package/dist/motion.js` and `package/LICENSE.md` here, and
change the version above.
