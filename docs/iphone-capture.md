# iPhone LiDAR capture (test app)

> Not a medical device. See [SAFETY.md](SAFETY.md). This app measures how
> accurate LiDAR scanning is; it designs and treats nothing.

Step 1 of moving footscan to an iPhone app: before building a whole app,
find out whether LiDAR scanning is more accurate than footscan's photo
pipeline. `ios/FootscanCapture` is a small app that scans with Apple's
Object Capture (iPhone/iPad with LiDAR), builds the 3D model on the phone,
and sends it to the Mac for the same accuracy study the photo scans get.

## Put it on your phone (free, no paid developer account)

1. Open `ios/FootscanCapture/FootscanCapture.xcodeproj` in Xcode.
2. Xcode > Settings > Accounts: add your Apple ID.
3. Click the project in the left bar, then the **FootscanCapture** target,
   then **Signing & Capabilities**: Team = your name (Personal Team). If
   Xcode says the bundle identifier is taken, change it to anything unique,
   e.g. `dev.yourname.footscan.capture`.
4. Plug in the iPhone, unlock it, tap **Trust**. On the phone: Settings >
   Privacy & Security > **Developer Mode** on (it restarts).
5. Choose the iPhone at the top of Xcode and press **Run** (the play button).
6. First launch only: on the phone, Settings > General > VPN & Device
   Management > your Apple ID > **Trust**.

With a free account the app stops opening after **7 days**; plug in and
press Run again. (A paid account, US$99 a year, makes it last a year and
allows TestFlight.)

## Scan the calibration object

1. Print it (Project page in the studio, or `footscan calib-object`) at
   100%, matte light filament. Measure it with calipers if you have them.
2. In the app: *Calibration object* > **Start scanning**. Put it on a plain
   matte table with room to walk round, in even light.
3. **Continue**, adjust the box so it holds just the object, **Start
   capture**. Walk slowly all the way round; when the ring is full, do
   **Another lap** higher up, looking down, then **Finish**.
4. The phone builds the model (a few minutes; keep the app open).
5. **Send model.obj** > AirDrop to the Mac.
6. In the studio: **Import 3D** > *The calibration object (accuracy test)* >
   choose the file > Import. The score appears straight away, and in the
   research library. Type your caliper readings of the print into the
   boxes under it and press *Save and re-score*: lengths are then compared
   with the real print instead of the design.

Or from the command line:

```bash
.venv/bin/footscan accuracy-mesh ~/Downloads/model.obj -o reports/lidar-calib.json
# with caliper readings of the print:
.venv/bin/footscan accuracy-mesh ~/Downloads/model.obj --calipers calipers.json
```

It reports the same numbers as the photo pipeline's study: surface
deviation (median, 95th percentile, signed mean), coverage, and the
caliper dimensions (length, width, heights, dome radius). The alignment
never rescales, so if LiDAR gets the size wrong, it shows.

Keep the object flat on the table; don't raise it on a stand (the stand ends
up in the model and is taken for the floor). The phone never sees the
underside, so Object Capture makes one up, and it can hang well below the
object: on the first real scan (17 Nov 2026) it was a wedge about 30 mm deep. The
studio spots that (the lowest points sit more than 3 mm below where the base
slab's flat top says the bottom is, allowing for the model's own size),
stands the model on the slab's top less its 10 mm (or your caliper
reading), cuts the made-up part away, and says so under the score. The base thickness is then not measured; the length, width
and the other heights still are. Next to a made-up bottom the lowest part of a
tall wall can bend into it, so the terrace end and the sides beside the
terraces are then read 14-20 mm up instead of 2-8 mm. If the slab's top
can't be found, the score says the bottom couldn't be checked.

### More detail on the Mac

The phone builds the *reduced* level of detail. The same photos (they carry
the LiDAR depth inside them) can be rebuilt on the Mac at medium, full or raw
detail. Copy the scan's `Images` folder over (Finder > your iPhone > Files >
footscan capture > Scans > the scan), then:

```bash
swiftc -O ios/tools/reconstruct-mac.swift -o /tmp/reconstruct-mac
/tmp/reconstruct-mac path/to/Images /tmp/calib-full.usdz full
.venv/bin/footscan accuracy-mesh /tmp/calib-full.obj
```

## Feet

For an insole, scan the sole: *Right/Left sole* (lying face down, knee
bent, sole to the ceiling) or *Right/Left foam print* (the print in a foam
impression box). Both use 3D capture, need no mat and no scale reading,
and go straight to the studio for **Make insole** (see docs/insole.md).
A sole scan missing its toes or heel (or with its forefoot rolled) is
refused when it reaches the studio (docs/insole.md, *Refused on arrival*):
the card reads *Scan again*, and that scan is never sent again. The scan's
page lists what to change next time, a few numbered steps per problem (the
studio's `completeness.retake_advice`, with its full findings folded away
under *What the studio found*), and a **Scan again** button. That opens the
get-ready list with the steps on top, then the camera; until capture starts,
the camera shows "Last time: ..." and the checks to make before Start.
Where the studio was started with `--check-scans-with-claude`, a sole scan
that passes its checks is also looked at by Claude, and a *scan again* from
it comes back the same way (docs/insole.md, *Claude's look on arrival*).

### The phone's own check, before anything is sent

The studio's check only runs once a scan arrives, and by then the person
who was scanned may have gone. So as soon as the phone has built a model it
takes its own quick look (`ScanCheck.swift`), with no studio and no network.
Object Capture always hands back a finished-looking model: whatever the
photos didn't show it fills in with a smooth guess, so a model can look
fine on the phone and still be no use.

- **Left/Right sole** (sole up). The phone turns the model over and tries
  every tilt up to 50 degrees, keeping the one that lays the most underside
  flat on the floor: the sole resting on the heel and the ball of the foot.
  From there it reads which way the sole faced while it was scanned, and the
  outline below 30 mm (as the insole's outline is read). It says scan again
  when the sole faced more than 25 degrees to one side (then nothing else is
  judged: the floor it found can't be trusted), when the toes or the heel end
  square (cut off), when the outline isn't one foot's size and shape, and when
  one side of the ball of the foot sits more than 7 mm above the other. The
  last three use the studio's own limits except the ball, where the studio
  refuses past 5 mm from its more careful floor.
- **Your shoe's insole**: if the phone guessed the underside (under half of it
  lies flat, within 3 mm of the bottom), scan again.
- **Calibration object**: the same underside check, but only as a note: the
  block's top still tells the phone's scale, so it isn't a reason to scan again.
- Other kinds (legs flat, foam prints, a whole foot) aren't checked on the phone.

A scan it says to scan again isn't sent by itself. Its page says *Not sent*,
lists what to change (as for a studio refusal), and has **Scan again**, with
the measurements folded away under *What the phone found*. A quiet **Send
anyway** sends it regardless; the studio still checks it when it arrives.
Scans built before this check existed are checked when they're opened or
before they're sent.

The first real cases, 17 Nov 2026: a left sole-up scan whose sole faced
40 degrees to the side (the studio read it as a thin blade, 231 x 61 mm, and
refused it after it was sent), and the calibration block, whose underside the
phone made up as a wedge (4% of it flat). Those numbers come from a Python copy
of the same steps run on the two models; the Swift itself is tested on
synthetic shapes (`ScanCheckTests.swift`). To see what it says about real
scans on the Mac, before changing a threshold:

```bash
swiftc -O ios/FootscanCapture/FootscanCapture/ScanCheck.swift ios/tools/scan-check.swift -o /tmp/scan-check
/tmp/scan-check sole_up data/captures/*/original.obj
```

Scan *Whole right foot* / *Whole left foot* the same way (sit, foot flat on the mat,
keep still; someone else holds the phone). There is no ground truth for a
foot, so these go to the studio's **Import 3D**, then **Landmarks**, like
any imported scan, for comparison with photo scans of the same foot.

## What this decides

Whether the full iPhone app (step 2 onward: native capture with coaching,
upload to the studio, the questionnaire and break-in guide inside the app)
is worth building, based on a real accuracy number rather than a guess.
Nothing is concluded until the calibration object has actually been scanned.

## Tests

The app's own logic (studio connect codes, the scan list's order, the
free-space check, the welcome scene's ring, the phone's own scan check) has unit tests in
`ios/FootscanCapture/FootscanCaptureTests`. In Xcode press Cmd-U, or:

```bash
cd ios/FootscanCapture && xcodebuild test -project FootscanCapture.xcodeproj \
  -scheme FootscanCapture -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Capture itself needs a phone with LiDAR and isn't covered.

## What's been checked so far

- The app compiles for iPhone (iOS 18+). It has **not run on a phone yet**:
  the simulator has no camera or LiDAR.
- `reconstruct-mac` built a model from the one real capture on disk (114
  iPhone photos of a shoe, no LiDAR) in 84 s. Without LiDAR or the mat its
  size is meaningless (it came out 2.5 "metres" across), which is the point
  of LiDAR or the mat.
- `accuracy-mesh` is tested on synthetic models: a perfect model
  exported the way Object Capture does (metres, Y up, tilted table) comes
  back perfect, one 1% too big reports 1% too big, and one with a made-up
  wedge underneath is stood on its base slab and scored as perfect.
- One real LiDAR scan so far: the printed block, Object Capture on the
  iPhone at reduced detail, 17 Nov 2026 (capture
  LIDAR_calibration_X_20261117-102255-bff2), against the design (no caliper
  readings yet). Before the made-up-bottom handling it scored dome top 70.1 mm
  (design 30) and couldn't measure length or width. With it: length 151.3
  (150), width 71.3 (70), high terrace 35.0 (35), low terrace 22.0 (22), dome
  top 29.0 (30), dome radius 18.0 (20); surface median 0.69 mm, 95th
  percentile 3.55 mm, 84% of the scan within 2 mm. Length and width, the
  two numbers that don't lean on the assumed 10 mm base, read 0.9% and 1.8%
  big. The dome's sphere fit reads 10% small; why isn't known yet. One scan,
  against the design: not yet a repeatable number.
