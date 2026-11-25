# Putting footscan on the internet

> Not a medical device. Read the checklist at the end **before** anyone you
> don't know uses this. Some of it is legal, and this document is not legal
> advice.

By default footscan runs on your own computer and your own Wi-Fi. That's the
safest place for it. This page covers the next step: letting a phone anywhere
reach it.

## The easy way: a Cloudflare tunnel

A tunnel gives your computer a public `https://` address without touching your
router. It also fixes the "This Connection Is Not Private" warning, because the
address has a real certificate.

1. Install the tunnel tool once:

   ```bash
   brew install cloudflared
   ```

2. Start footscan in **public mode** (plain HTTP on this computer only; the
   tunnel adds HTTPS):

   ```bash
   .venv/bin/footscan serve --public
   ```

3. In a second Terminal window, open the tunnel:

   ```bash
   cloudflared tunnel --url http://localhost:8765
   ```

   It prints an address like `https://something-random.trycloudflare.com`.
   That's the scan page to share.

4. Open the studio at `https://something-random.trycloudflare.com/studio/?key=YOUR-KEY`.
   The key is printed when footscan starts, and stored in `.studio_key`.

Quick tunnels get a new random address every time. For a fixed address, set up
a named tunnel with your own domain (Cloudflare's docs cover this).

### Why `--public` matters

A tunnel runs on your own computer, so every visitor's request reaches footscan
from "this computer". Normally that means "the operator", and it opens the
studio. So:

- footscan treats any request carrying proxy headers (`X-Forwarded-For`,
  `CF-Connecting-IP` and similar) as coming from outside, always.
- `--public` goes further and trusts nothing as local. Only the studio key opens
  the studio, even on your own computer.

**Always use `--public` behind a tunnel or proxy.** Both protections are
covered by tests.

## What's protected already

- **Studio:** key-only in public mode; the key is set in an `HttpOnly`,
  `SameSite=Strict`, `Secure` cookie.
- **Uploads:** each submission gets a random one-time token; sending the scans
  closes it. Rescan links get a fresh token.
- **Limits:** frames are capped at 8 MB each and 200 per scan, 3D files at
  150 MB, and new submissions at 20 per client per hour.
- **Headers:** a Content-Security-Policy, `nosniff`, no framing, and no
  `Referer`, so keys and tokens in URLs don't leak to other sites. The policy
  runs scripts only from the site's own files (`script-src 'self'`): no page
  carries a script inside it (a test checks), so text that slips into a page
  unescaped can't run as code.
- **Deletion:** the studio can delete a person's photos and answers
  completely.

## What isn't, yet

- **Backups.** Everything lives in `data/` on one computer. Back it up.
- **Encryption at rest.** Photos are ordinary files on disk; turn on FileVault.
- **More than one operator.** There's a single studio key. If it leaks, delete
  `.studio_key` and restart to make a new one.
- **Uptime.** When your computer sleeps, the site is gone.

## Checklist before strangers use it

These are questions for someone qualified to answer. They are not things this
project can decide for you.

- [ ] **Medical device rules.** Custom foot orthoses can be regulated medical
      devices (for example by the FDA in the US, the MHRA in the UK, or under
      the EU MDR), especially when made to measure or sold. Find out what
      applies before offering insoles to the public, and certainly before
      charging for them.
- [ ] **Health data.** Foot photos plus answers about diabetes, circulation and
      pain count as health information under many privacy laws (GDPR in the
      UK/EU, several US state laws). You'll need a privacy notice saying what
      you collect, why, how long you keep it, and how people get it deleted.
- [ ] **Children.** In the US, collecting personal information online from
      under-13s needs *verifiable* parental consent (COPPA). The current
      "a parent or guardian agrees" tick box is **not** verifiable consent.
      Until that's solved properly, don't accept scans from under-13s through
      a public link.
- [ ] **Liability.** Who is responsible if an insole hurts someone? Ask about
      insurance.
- [ ] **Clinician sign-off** still applies to every insole, for everyone.

Until those are answered, the sensible scope is people you know, with you
there in person.
