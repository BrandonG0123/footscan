// Shared safety strip, header and footer. Every page carries the
// not-a-medical-device statement, on both the customer side and the studio.

export const FOOT_PATH =
  "M100 182C80 182 71 167 71 149C71 128 78 113 76 96C74 79 69 63 73 49C77 35 89 28 104 28C119 28 129 36 131 51C133 65 129 81 127 97C125 117 129 132 129 150C129 168 119 182 100 182Z";
export const TOES = [[85, 17, 9.5], [102, 13, 6.2], [114, 16, 5.6], [124, 22, 5], [131, 30, 4.4]];

export function footSvg({ mirror = false, cls = "" } = {}) {
  const t = mirror ? ' transform="translate(200 0) scale(-1 1)"' : "";
  const toes = TOES.map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r}"/>`).join("");
  return `<g class="${cls}"${t}><path d="${FOOT_PATH}"/>${toes}</g>`;
}

const NAV = {
  customer: [["/", "Scan"], ["/mat.html", "Scan mat"], ["/care.html", "Wearing it"]],
  studio: [
    ["/studio/", "Submissions"],
    ["/studio/capture.html", "Research capture"],
    ["/studio/captures.html", "Research library"],
    ["/studio/import.html", "Import 3D"],
    ["/mat.html", "Scan mat"],
    ["/studio/project.html", "Project"],
  ],
};

import { addPageGlow, initReveal } from "./reveal.js";

const KEY_STORE = "footscan.studioKey";

/**
 * Studio pages are opened with ?key=... once. Remember the key on this device
 * and put it back on studio links and requests, so the studio keeps working if
 * the cookie is refused or cleared (Safari over a self-signed certificate,
 * private browsing, or a link opened without the key).
 */
function rememberStudioKey() {
  const fromUrl = new URL(location.href).searchParams.get("key");
  if (fromUrl) {
    try { localStorage.setItem(KEY_STORE, fromUrl); } catch { /* private mode: the URL still carries it */ }
    return fromUrl;
  }
  try { return localStorage.getItem(KEY_STORE); } catch { return null; }
}

function useStudioKey(key) {
  if (!key) return;
  const fetchWithKey = globalThis.fetch;
  globalThis.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (url && !/^https?:/i.test(url)) {
      init = { ...init, headers: { ...(init.headers || {}), "X-Studio-Key": key } };
    }
    return fetchWithKey(input, init);
  };
  addEventListener("DOMContentLoaded", () => {
    for (const a of document.querySelectorAll('a[href^="/studio/"]')) {
      if (!a.href.includes("key=")) a.href += (a.href.includes("?") ? "&" : "?") + `key=${encodeURIComponent(key)}`;
    }
  });
}

function mountLayout() {
  const area = document.body.dataset.area || "customer";
  const here = location.pathname.replace(/index\.html$/, "");
  const studioKey = area === "studio" ? rememberStudioKey() : null;
  useStudioKey(studioKey);

  const strip = document.createElement("div");
  strip.className = "safety-strip";
  strip.setAttribute("role", "note");
  strip.innerHTML = `<div class="wrap"><strong>NOT A MEDICAL DEVICE</strong>
    <span class="strip-long">${area === "studio"
      ? "Nothing leaves the studio for sport without clinician sign-off."
      : "This insole is homemade, not from a doctor. Show it to a foot doctor before you play sport in it."}</span>
    <span class="strip-short">${area === "studio" ? "Clinician sign-off before sport." : "See a foot doctor before sport."}</span></div>`;

  const header = document.createElement("header");
  header.className = "site-header";
  header.innerHTML = `<div class="wrap">
    <a class="site-brand" href="${area === "studio" ? "/studio/" : "/"}">
      <svg class="site-brand-mark" viewBox="0 0 200 200" aria-hidden="true"><rect width="200" height="200" rx="46" fill="var(--brand)"/>
        <g fill="var(--brand-ink)" transform="translate(40 26) scale(0.6)">${footSvg()}</g></svg>
      footscan${area === "studio" ? ' <span class="badge brand" style="margin-left:4px">Studio</span>' : ""}</a>
    <nav class="nav" aria-label="Main">${NAV[area].map(([href, label]) => {
      const url = studioKey && href.startsWith("/studio/") ? `${href}?key=${encodeURIComponent(studioKey)}` : href;
      return `<a href="${url}"${href === here ? ' aria-current="page"' : ""}>${label}</a>`;
    }).join("")}</nav></div>`;

  const footer = document.createElement("footer");
  footer.className = "site-footer";
  footer.innerHTML = `<div class="wrap">
    <p><strong>footscan is not a medical device.</strong> It does not treat any illness or injury. These insoles are
    not the same as insoles a doctor prescribes, and are not a replacement for them. The wrong shape under a foot can
    cause knee, hip or back problems. Show it to a foot doctor (podiatrist), physical therapist, sports doctor or
    athletic trainer before sport. Wear it a little at a time, and stop if anything hurts.</p></div>`;

  document.body.prepend(header);
  document.body.prepend(strip);
  document.body.append(footer);
  addPageGlow();
  if (area === "customer") {
    // Customer pages: springs, ripples and scroll reveals from Motion (fx.js).
    Promise.all([import("./fx.js"), import("./interact.js")]).then(([fx, interact]) => {
      fx.initPage();
      fx.revealOnScroll("main > section, main > .layout, [data-reveal] > *");
      interact.initInteract();
    });
  } else {
    initReveal();
  }
}

mountLayout();
