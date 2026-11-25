// Small helpers shared by studio pages.
export const STATUS = {
  uploading: { label: "Unfinished", cls: "" },
  received: { label: "New", cls: "brand" },
  needs_rescan: { label: "Waiting for rescan", cls: "warn" },
  archived: { label: "Archived", cls: "" },
};

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/**
 * A studio answer's JSON, or {error} in plain words when the answer isn't JSON: an error page from the server
 * itself (a request it couldn't read), a login page from Cloudflare Access when that sign-in has run out (the
 * public studio sits behind it), or a dropped connection. `r.json()` alone throws "Unexpected token '<'" there,
 * which says nothing about what to do.
 */
export async function answer(r) {
  const type = r.headers.get("Content-Type") || "";
  if (type.includes("application/json")) {
    try { return await r.json(); } catch { return { error: `the studio's answer was cut off (${r.status}); try again` }; }
  }
  if (r.redirected || type.includes("text/html")) {
    return { error: r.ok || r.redirected
      ? "the studio answered with a web page instead of data: if it asks you to sign in (Cloudflare Access), reload this page and sign in again"
      : `the studio refused the request (${r.status} ${r.statusText || "error"})` };
  }
  return { error: `the studio answered ${r.status} ${r.statusText || ""} with no data`.trim() };
}

/**
 * fetch() whose failures become {error}: no network (studio off, phone off the Wi-Fi) included.
 * -> [ok, data, status]; status 0 when the studio couldn't be reached at all.
 */
export async function ask(url, init) {
  let r;
  try {
    r = await fetch(url, init);
  } catch {
    return [false, { error: "can't reach the studio (is it running, and is this device on its Wi-Fi or Tailscale?)" }, 0];
  }
  const isJson = (r.headers.get("Content-Type") || "").includes("application/json");
  return [r.ok && isJson, await answer(r), r.status];
}

// The studio key this browser was given (layout.js keeps it: ?key= once, then this device's storage), or null.
function studioKey() {
  try {
    return new URL(location.href).searchParams.get("key") || localStorage.getItem("footscan.studioKey");
  } catch {
    return null;
  }
}

// A studio address with the studio key on it (as layout.js puts it on links), for a page that moves on by itself:
// before the #, so the studio sees it
export function withStudioKey(href, key = studioKey()) {
  if (!key || /[?&]key=/.test(href.split("#")[0])) return href;
  const [path, ...hash] = href.split("#");
  return `${path}${path.includes("?") ? "&" : "?"}key=${encodeURIComponent(key)}${hash.length ? `#${hash.join("#")}` : ""}`;
}

/**
 * Send a file with a progress report (fetch can't say how much of an upload has gone): onProgress(0..1) while
 * it goes up, then onSent() while the studio reads it. -> [ok, data, status] as ask() gives them. Carries the
 * studio key as layout.js's fetch does, for a browser that keeps no cookie.
 */
export function sendWithProgress(url, { method = "PUT", body, headers = {} } = {}, onProgress, onSent) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url);
    const key = studioKey();
    if (key) xhr.setRequestHeader("X-Studio-Key", key);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.addEventListener("progress", (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); });
    xhr.upload.addEventListener("load", () => onSent?.());
    xhr.addEventListener("load", async () => {
      // sent on somewhere else (Cloudflare Access's sign-in, when it has run out): what fetch calls redirected
      if (xhr.responseURL && new URL(xhr.responseURL).href !== new URL(url, location.href).href) {
        resolve([false, { error: "the studio answered with a web page instead of data: if it asks you to sign in (Cloudflare Access), reload this page and sign in again" }, xhr.status]);
        return;
      }
      const type = xhr.getResponseHeader("Content-Type") || "";
      const r = new Response(xhr.responseText, { status: xhr.status, statusText: xhr.statusText, headers: { "Content-Type": type } });
      resolve([xhr.status >= 200 && xhr.status < 300 && type.includes("application/json"), await answer(r), xhr.status]);
    });
    // the connection lost, or (no way to tell them apart here) sent to a sign-in page on another site
    const unreachable = () => resolve([false, { error: "the connection to the studio was lost while sending (weak Wi-Fi?), or its sign-in ran out: reload this page and try again" }, 0]);
    xhr.addEventListener("error", unreachable);
    xhr.addEventListener("abort", unreachable);
    xhr.send(body);
  });
}
