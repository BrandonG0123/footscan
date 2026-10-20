// Scanner engine shared by the customer scan flow and the research capture page.
//
// Owns the camera (or simulated camera), runs the frame-quality checks on a
// timer, finds the scan mat's markers, works out where the camera is, keeps
// good frames, tracks coverage, and reports state through onUpdate. It has no
// page-specific UI.
//
// Where the camera is, in order of trust:
//   1. The scan mat. Marker corners give the camera's position relative to
//      the mat directly (see mat-pose.js). This is a measurement.
//   2. The phone's motion sensors, aligned to the mat whenever the mat was
//      last seen. Fills gaps when the mat is briefly out of view.
//   3. Motion sensors alone, relative to where scanning started (the
//      instructions say to start behind the heel). Guidance only.
import {
  Coverage, SharpnessJudge, cellFor, coveredEnough, describeCell, exposureStats, judgeExposure,
  angularSpeed, laplacianVariance, nextMissing, shouldCapture, steerTo, toGray, viewFromOrientation, wrap360,
} from "./quality.js";
import { Cues, ScreenAwake } from "./cues.js";
import { MAX_HAMMING, estimateView, indexBoard } from "./mat-pose.js";
import { SimulatedCamera } from "./sim-camera.js";

const ANALYSIS_WIDTH = 240;
const DETECT_WIDTH = 960;
const TICK_MS = 120;
const DETECT_EVERY_TICKS = 2;
const MIN_INTERVAL_MS = 600;
const CHECK_INTERVAL_MS = 250;  // how often a photo is considered; bridging photos need this to be short
const TOO_FAST_DEG_PER_S = 35;  // turning faster than this leaves gaps and blur: ask to slow down
const MAT_FRESH_MS = 600;
const MIN_MAT_MARKERS = 2;
const RAD = Math.PI / 180;

let boardsPromise = null;
/** The printable mat's board definitions (both paper sizes), fetched once. */
export function loadBoards() {
  boardsPromise ??= Promise.all(["letter", "a4"].map((p) =>
    fetch(`/mat/footscan-mat-${p}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  )).then((list) => list.filter(Boolean));
  return boardsPromise;
}

export async function requestMotionPermission() {
  // iOS only grants motion sensors in response to a tap, so call this from a click handler.
  const DOE = window.DeviceOrientationEvent;
  if (DOE && typeof DOE.requestPermission === "function") {
    try { await DOE.requestPermission(); } catch { /* denied: scanning continues without sensors */ }
  }
}

export function cameraErrorMessage(err) {
  if (!navigator.mediaDevices) return "This browser can't open the camera on this page. Open the https:// address instead.";
  if (err?.name === "NotAllowedError") return "Camera permission was blocked. Allow camera access for this site in your browser settings, then try again.";
  if (err?.name === "NotFoundError") return "No camera was found on this device.";
  return `The camera couldn't start (${err?.name || "unknown error"}).${window.isSecureContext ? "" : " Camera access needs an https:// address."}`;
}

const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
};

export class Scanner {
  /** foot: "left"/"right", or null when scanning anything that isn't a foot. */
  constructor({ stage, simulated = false, targetFrames = 60, boards = [], requireMat = false, foot = "right", onUpdate = () => {}, onFrame = () => {} }) {
    Object.assign(this, { stage, simulated, targetFrames, foot, onUpdate, onFrame });
    this.boards = boards.map((b) => ({ board: b, index: indexBoard(b) }));
    this.detector = globalThis.AR && this.boards.length
      ? new globalThis.AR.Detector({ dictionaryName: "ARUCO_MIP_36h12", maxHammingDistance: MAX_HAMMING })
      : null;
    this.requireMat = requireMat && !!this.detector;
    this.frames = [];
    this.coverage = new Coverage();
    this.judge = new SharpnessJudge();
    this.rejected = { blur: 0, exposure: 0, no_mat: 0 };
    this.capturing = false;
    this.started = false;
    this.lastCaptureAt = 0;
    this.lastOpportunityAt = 0;
    this.ticks = 0;
    this.orientation = null;
    this.alpha0 = null;
    this.sensorOffset = null; // unit vector [cos, sin] of (mat azimuth - compass alpha)
    this.view = null;
    this.viewSamples = [];
    this.viewSource = null;
    this.mat = null;
    this.matLostSince = null;
    this.focalSamples = [];
    this.elapsedBefore = 0;
    this.startedAt = null;
    this.sensorSource = simulated ? "simulated" : "none";
    this.cues = new Cues();
    this.awake = new ScreenAwake();
    this.doneAnnounced = false;
    this.analysis = document.createElement("canvas");
    this.detectCanvas = document.createElement("canvas");
    this.grab = document.createElement("canvas");
    this._onOrientation = (e) => {
      if (e.alpha == null || e.beta == null) return;
      // True compass heading on iOS drifts less than relative alpha.
      const alpha = typeof e.webkitCompassHeading === "number" ? 360 - e.webkitCompassHeading : e.alpha;
      this.orientation = { alpha, beta: e.beta, gamma: e.gamma };
      this.sensorSource = "device_sensors";
    };
  }

  /** Opens the camera. Throws the getUserMedia error if it can't. */
  async open() {
    if (this.simulated) {
      this.sim = new SimulatedCamera(this.boards[0]?.board);
      globalThis.__footscanSimScanner = this; // debugging hook, simulated camera only
      this.sim.canvas.className = "feed";
      this.stage.prepend(this.sim.canvas);
      this.drawable = this.sim.canvas;
    } else {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      const video = document.createElement("video");
      Object.assign(video, { playsInline: true, muted: true, autoplay: true, className: "feed" });
      video.setAttribute("playsinline", "");
      video.srcObject = this.stream;
      this.stage.prepend(video);
      await video.play().catch(() => {});
      this.drawable = video;
      window.addEventListener("deviceorientation", this._onOrientation);
    }
    this.resumeLoop();
  }

  resumeLoop() {
    clearInterval(this.timer);
    this.timer = setInterval(() => this.tick(performance.now()), TICK_MS);
  }

  start() {
    // Audio and wake lock both need a user gesture; Start is that gesture.
    this.cues.start();
    this.awake.acquire();
    if (this.alpha0 == null) {
      const o = this.simulated ? this.sim.orientation() : this.orientation;
      this.alpha0 = o ? o.alpha : 0;
    }
    this.started = true;
    this.capturing = true;
    this.startedAt = performance.now();
  }

  pause() {
    if (!this.capturing) return;
    this.capturing = false;
    this.elapsedBefore += performance.now() - this.startedAt;
  }

  resume() {
    if (this.capturing) return;
    this.capturing = true;
    this.startedAt = performance.now();
  }

  /** Stops the loop but keeps the camera open (for "capture more"). */
  hold() {
    this.pause();
    clearInterval(this.timer);
  }

  /** Releases the camera and removes the feed from the page. */
  close() {
    this.hold();
    this.cues.stop();
    this.awake.release();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.drawable?.remove();
    window.removeEventListener("deviceorientation", this._onOrientation);
  }

  get elapsedMs() {
    return this.elapsedBefore + (this.capturing ? performance.now() - this.startedAt : 0);
  }

  get subjectName() {
    return this.foot === "left" || this.foot === "right" ? "the foot" : "the object";
  }

  get focalHint() {
    return median(this.focalSamples);
  }

  keptFrames() {
    return this.frames.filter((f) => !f.excluded);
  }

  recount() {
    const c = new Coverage();
    for (const f of this.keptFrames()) if (f.cell) c.add(f.cell);
    this.coverage = c;
    return c;
  }

  // ---- mat detection -------------------------------------------------------
  detectMat(src, w, h, now) {
    const dw = Math.min(DETECT_WIDTH, w), dh = Math.round((dw * h) / w);
    this.detectCanvas.width = dw;
    this.detectCanvas.height = dh;
    const ctx = this.detectCanvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(src, 0, 0, dw, dh);
    const raw = this.detector.detectImage(dw, dh, ctx.getImageData(0, 0, dw, dh).data);
    const s = w / dw;
    const detections = raw.map((m) => ({ id: m.id, corners: m.corners.map((c) => [c.x * s, c.y * s]) }));

    let best = null;
    for (const { board, index } of this.boards) {
      const r = estimateView(detections, index, board, w, h, this.focalHint);
      if (r.markers && (!best || r.markers > best.result.markers)) best = { board, index, result: r };
    }
    if (!best || best.result.markers < 1) return;
    const matched = detections.filter((d) => best.index.has(d.id));
    this.mat = { at: now, paper: best.board.paper, markers: matched, result: best.result };
    if (best.result.focalMeasured) {
      this.focalSamples.push(best.result.focalMeasured);
      if (this.focalSamples.length > 40) this.focalSamples.shift();
    }
  }

  matVisible(now) {
    return !!this.mat && now - this.mat.at < MAT_FRESH_MS && this.mat.markers.length >= MIN_MAT_MARKERS;
  }

  // ---- where is the camera -------------------------------------------------
  resolveView(now) {
    const matView = this.mat && now - this.mat.at < MAT_FRESH_MS ? this.mat.result.view : null;
    const o = this.orientation;
    if (matView) {
      if (o) {
        // Learn the offset between compass heading and the mat's azimuth,
        // averaged as a unit vector so 359 and 1 degrees agree.
        const d = (matView.azimuth - o.alpha) * RAD;
        const [c0, s0] = this.sensorOffset ?? [Math.cos(d), Math.sin(d)];
        const k = 0.2;
        const c = (1 - k) * c0 + k * Math.cos(d), s = (1 - k) * s0 + k * Math.sin(d);
        const n = Math.hypot(c, s) || 1;
        this.sensorOffset = [c / n, s / n];
      }
      return { view: matView, source: "mat" };
    }
    if (o && this.sensorOffset) {
      const offset = Math.atan2(this.sensorOffset[1], this.sensorOffset[0]) / RAD;
      return { view: { azimuth: wrap360(o.alpha + offset), elevation: Math.max(0, Math.min(90, 90 - Math.abs(o.beta))) }, source: "sensors_aligned" };
    }
    if (o && this.alpha0 != null) return { view: viewFromOrientation(o, this.alpha0), source: "sensors" };
    return { view: null, source: null };
  }

  tick(now) {
    if (this.simulated) {
      this.sim.render(now, this.capturing);
      this.orientation = this.sim.orientation();
    }
    const src = this.drawable;
    const w = src.videoWidth || src.width, h = src.videoHeight || src.height;
    if (!w || !h) return;
    this.ticks++;

    const aw = ANALYSIS_WIDTH, ah = Math.round((ANALYSIS_WIDTH * h) / w);
    this.analysis.width = aw;
    this.analysis.height = ah;
    const actx = this.analysis.getContext("2d", { willReadFrequently: true });
    actx.drawImage(src, 0, 0, aw, ah);
    const gray = toGray(actx.getImageData(0, 0, aw, ah).data, aw, ah);
    const sharpScore = laplacianVariance(gray, aw, ah);
    const expo = exposureStats(gray);
    const sharp = this.judge.judge(sharpScore);
    const exposure = judgeExposure(expo);

    if (this.detector && this.ticks % DETECT_EVERY_TICKS === 0) this.detectMat(src, w, h, now);
    const matVisible = this.matVisible(now);
    if (matVisible || !this.capturing) this.matLostSince = null;
    else this.matLostSince ??= now;

    const { view, source } = this.resolveView(now);
    this.view = view;
    this.viewSource = source;
    const hasView = view != null;
    const cell = view ? cellFor(view) : null;
    if (view) {
      this.viewSamples.push({ t: now, view });
      while (this.viewSamples.length && now - this.viewSamples[0].t > 1000) this.viewSamples.shift();
    }
    const tooFast = this.capturing && angularSpeed(this.viewSamples, now) > TOO_FAST_DEG_PER_S;

    if (this.capturing && now - this.lastOpportunityAt >= CHECK_INTERVAL_MS) {
      const matOk = !this.requireMat || matVisible;
      const keep = matOk && shouldCapture({
        sharpOk: sharp.ok, exposureOk: exposure.ok, now, lastCaptureAt: this.lastCaptureAt,
        view, lastView: this.lastKeptView,
        cell, coverage: this.coverage, minIntervalMs: MIN_INTERVAL_MS,
      });
      if (keep) {
        this.lastCaptureAt = now;
        this.lastKeptView = view;
        this.grabFrame(src, w, h, {
          sharpScore, relative: sharp.relative, exposure: expo, view, cell, viewSource: source,
          mat: matVisible ? this.matRecord() : null,
        });
      } else if (!exposure.ok) this.rejected.exposure++;
      else if (!sharp.ok) this.rejected.blur++;
      else if (!matOk) this.rejected.no_mat++;
      this.lastOpportunityAt = now;
    }

    const kept = this.keptFrames().length;
    const completeness = hasView ? this.coverage.completeness() : null;
    const next = hasView ? nextMissing(this.coverage, view) : null;
    const done = kept >= this.targetFrames && (!hasView || completeness >= 1);
    const covered = coveredEnough({ hasView, completeness, kept, targetFrames: this.targetFrames });
    // Progress for a single bar: frames and coverage both have to be there.
    const progress = Math.min(kept / this.targetFrames, completeness ?? 1);
    const matMarkers = this.mat && now - this.mat.at < MAT_FRESH_MS ? this.mat.markers.length : 0;
    const steer = this.capturing && !done ? steerTo(view, next) : { arrived: false, angle: null, text: "" };
    const guidance = this.guidance({ sharp, exposure, hasView, cell, next, kept, done, matVisible, now, tooFast });
    this.speak({ guidance, steer, done, sharp, exposure, matVisible, tooFast });

    this.onUpdate({
      sharp, exposure, hasView, viewSource: source, cell, next, kept, completeness, done, covered, progress, steer,
      matVisible, matMarkers, paper: this.mat?.paper ?? null, guidance,
    });
  }

  matRecord() {
    const r = this.mat.result;
    return {
      paper: this.mat.paper, sheet: r.sheet ?? null,
      markers: this.mat.markers.map((m) => ({ id: m.id, corners: m.corners.map(([x, y]) => [+x.toFixed(2), +y.toFixed(2)]) })),
      focal_px: r.focal ?? null, focal_measured: r.focalMeasured ?? null,
      camera_mm: r.camera?.map((v) => +v.toFixed(1)) ?? null, reprojection_rms_px: r.rms ?? null,
    };
  }

  /** Short spoken cues, and a sound when something needs attention. */
  speak({ guidance, steer, done, sharp, exposure, matVisible, tooFast = false }) {
    if (!this.capturing) return;
    if (done) {
      if (!this.doneAnnounced) {
        this.doneAnnounced = true;
        this.cues.complete();
        this.cues.say("All done. Tap finish.");
      }
      return;
    }
    this.doneAnnounced = false;
    if (!exposure.ok || !sharp.ok || (this.requireMat && !matVisible) || tooFast) {
      const problem = !exposure.ok
        ? (exposure.issue === "overexposed" ? "Too bright" : "Too dark")
        : !sharp.ok ? "Hold steadier" : tooFast ? "Slower" : "Show the mat";
      if (problem !== this.lastProblem) this.cues.problem();
      this.lastProblem = problem;
      this.cues.say(problem);
      return;
    }
    this.lastProblem = null;
    this.cues.say(steer.text || guidance.text);
  }

  guidance({ sharp, exposure, hasView, cell, next, kept, done, matVisible, now, tooFast = false }) {
    if (!this.started) {
      return this.requireMat && !matVisible
        ? { text: "Point the phone at the mat so you can see the black squares, then tap Start.", tone: "" }
        : { text: `Stand behind ${this.foot === "left" || this.foot === "right" ? "the heel" : "it"}, then tap Start.`, tone: "" };
    }
    if (!this.capturing) return { text: "Paused.", tone: "" };
    if (!exposure.ok) return { text: exposure.message, tone: "bad" };
    if (!sharp.ok) return { text: sharp.message, tone: "bad" };
    if (tooFast && !done) return { text: "Slow down a little. Move the phone smoothly.", tone: "bad" };
    if (this.requireMat && this.matLostSince != null && now - this.matLostSince > 800)
      return { text: `Move back a bit, until you can see the black squares around ${this.subjectName}.`, tone: "bad" };
    if (done) return { text: "All done! Tap Finish.", tone: "done" };
    if (!hasView)
      return { text: `Walk slowly around ${this.subjectName}: low down, then higher up, then from above. ${this.targetFrames - kept} photos to go.`, tone: "" };
    if (next && next !== cell) return { text: `Now move here: ${describeCell(next, this.foot)}.`, tone: "" };
    if (next) return { text: "Good. Hold still here for a moment.", tone: "" };
    return { text: `You have been all the way around. ${Math.max(0, this.targetFrames - kept)} more photos.`, tone: "" };
  }

  grabFrame(src, w, h, info) {
    this.grab.width = w;
    this.grab.height = h;
    this.grab.getContext("2d").drawImage(src, 0, 0, w, h);
    const frame = { n: this.frames.length + 1, t_ms: Math.round(this.elapsedMs), width: w, height: h, excluded: false, ...info };
    this.frames.push(frame);
    const before = info.cell ? this.coverage.fill(info.cell) : 1;
    if (info.cell) this.coverage.add(info.cell);
    // A click per photo, and a two-note chime when an angle is finished, so
    // you can keep your eyes on what you are scanning.
    if (info.cell && before < 1 && this.coverage.fill(info.cell) >= 1) this.cues.cellDone();
    else this.cues.shutter();
    this.grab.toBlob((blob) => {
      frame.blob = blob;
      frame.url = URL.createObjectURL(blob);
    }, "image/jpeg", 0.92);
    this.onFrame(frame);
  }

  /** Per-frame metadata for upload, numbered in upload order. */
  frameRecords() {
    return this.keptFrames().map((f, i) => ({
      file: `frame_${String(i + 1).padStart(4, "0")}.jpg`, original_n: f.n, t_ms: f.t_ms,
      width: f.width, height: f.height, sharpness: f.sharpScore, sharpness_relative: f.relative,
      exposure: f.exposure, view: f.view, view_source: f.viewSource, cell: f.cell, mat: f.mat,
    }));
  }

  summary() {
    const cov = this.recount();
    const kept = this.keptFrames();
    const withMat = kept.filter((f) => f.mat);
    const papers = [...new Set(withMat.map((f) => f.mat.paper))];
    const sources = {};
    for (const f of kept) sources[f.viewSource ?? "none"] = (sources[f.viewSource ?? "none"] ?? 0) + 1;
    return {
      frames_kept: kept.length, target_frames: this.targetFrames,
      rejected_blur: this.rejected.blur, rejected_exposure: this.rejected.exposure, rejected_no_mat: this.rejected.no_mat,
      coverage_completeness: kept.some((f) => f.view) ? cov.completeness() : null,
      frames_with_mat: withMat.length, mat_paper: papers.length === 1 ? papers[0] : papers.length ? papers : null,
      focal_px_median: this.focalHint, view_sources: sources,
      orientation_source: this.sensorSource, duration_s: Math.round(this.elapsedMs / 1000),
    };
  }

  /** Waits until every kept frame has finished JPEG encoding. */
  async ready() {
    while (this.keptFrames().some((f) => !f.blob)) await new Promise((r) => setTimeout(r, 50));
  }
}
