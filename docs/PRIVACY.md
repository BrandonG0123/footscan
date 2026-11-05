# Footscan privacy policy

> Footscan is not a medical device. It does not diagnose, treat or prevent any condition.
> See [SAFETY.md](SAFETY.md).

This policy covers the Footscan iPhone app. Last changed: 5 November 2026.

## The short version

The app keeps your scans on your iPhone. It sends them only to a Footscan studio that **you** connected
it to. Nothing goes to the app's developer, and there are no accounts, ads, analytics or tracking.

## What the app handles, and where it goes

| What | Why | Where it is kept |
| --- | --- | --- |
| Photos and depth readings of your foot, and the 3-D model built from them (3D capture) | To make the model an insole can be designed from | On your iPhone, in the app's own storage, which you can also see in the Files app under Footscan |
| Photos of your foot on the printed mat (Photos + mat) | The studio builds the 3-D model from them | Held only in the photo page while you take them, then sent to your studio when you tap Save to library (Discard sends nothing); not saved on the phone |
| What each scan is of (which foot, sole up or a foam print), the date, your phone model and iOS version | So the studio can tell scans apart and read them the right way | With the scan on your iPhone |
| A bathroom-scale reading, if you enter one: how much weight was on the foot during a loaded scan | The studio needs it to read a loaded foot scan | With the scan on your iPhone |
| The address and key of your studio | To send scans to it | The address in the app's settings; the key in the iPhone's Keychain, on this phone only |
| Your settings (for example, whether to send scans automatically) | So you're asked things once | In the app's settings on your iPhone |

Your foot's shape and your weight are personal information about your body, so the app treats them
carefully: they stay with you and the studio you chose. The app asks for the **camera** (to take the scan)
and the **local network** (to reach a studio on your Wi-Fi). It does not ask about medical conditions,
read Apple Health data, or use your location or contacts.

If iCloud Backup is turned on for your iPhone, iOS includes the app's files in that backup, as it does for
other apps' files. Turn off backup for Footscan in the iPhone's iCloud settings if you'd rather it didn't.

## Sending scans to a studio

A 3D-capture scan leaves your phone only when it is sent to the studio you connected, or when you share or
export it yourself (the Share buttons for a scan's model files, and the app's folder in the Files app, which
you can copy from). Once a studio is
connected, each finished model is sent to it automatically; you can turn that off in Settings and tap Send
yourself instead. Photos + mat photos go to the studio when you tap Save to library. Everything is sent over an
encrypted (HTTPS) connection. For a studio on your home network, the app checks it is talking to that
exact computer.

The studio is software run by you, or by someone you chose, on their own computer. The App Store version
of the app accepts only the connect code a studio on a computer like that shows: it carries that
computer's own certificate (the app checks it is talking to that very computer) and an address on your
own network or Tailscale. It refuses a code for a studio at a public internet address, such as a hosted
one the app's developer might run. It sends scans only to the studio
whose code you scanned. Once a scan is at the studio, it is kept there, under the control of whoever runs
it, not the app's developer.

## Deleting your data

- One scan: open it and tap **Delete this scan**.
- Every scan on the phone: Settings, then **Delete all scans**.
- The studio connection: Settings, then Studio, then **Disconnect**. This removes the studio's address and key.
- Everything: tap **Disconnect** (above) first, which removes the studio's key at once, then delete the
  app. iOS keeps an app's Keychain items after the app is deleted, so a key left by deleting without
  disconnecting stays on the phone (and in its encrypted backups) until the app is installed and opened
  again, when the app deletes it.
- Scans already sent to a studio stay there until they are deleted in that studio.

## Children

Footscan is not meant for children, and its developer collects no information from anyone through it.

## Changes and contact

If this policy changes, the new version is published at this address with a new date. Questions:
[Footscan support](https://github.com/BrandonG0123/footscan/issues). That page is public, so please
don't post scans, photos or anything about your health there.
