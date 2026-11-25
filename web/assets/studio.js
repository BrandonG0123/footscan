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
