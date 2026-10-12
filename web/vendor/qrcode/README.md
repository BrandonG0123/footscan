# qrcode-generator (vendored)

[qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) 1.4.4
by Kazuhiko Arase, MIT licence (stated in the header of qrcode.js): the
browser file `qrcode.js` from the npm package, unmodified. Loaded as a classic
script, it sets `window.qrcode`.

Vendored because the site's Content Security Policy only allows scripts from
itself. Used by the studio's Import 3D page to show the code the footscan
capture iPhone app scans to connect to the studio.
