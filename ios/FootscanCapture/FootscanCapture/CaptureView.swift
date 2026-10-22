// The capture itself: Apple's Object Capture, with plain-language coaching.
//
// Object Capture does the hard parts: it tracks the phone with ARKit, uses
// LiDAR to find the object and give the model real-world size, shows which
// sides still need photos, and only keeps sharp, useful shots. The steps:
//
//   ready      -> point at the object, tap Continue
//   detecting  -> a box appears round it; adjust, tap Start capture
//   capturing  -> walk all the way round slowly; a ring fills in
//                 (after one lap: Finish, or Another lap higher up)
//   finishing  -> it saves the last photos
//   completed  -> on to building the model
import RealityKit
import SwiftUI

struct CaptureView: View {
    let scan: Scan
    var onDone: (Scan) -> Void
    var onCancel: () -> Void

    @State private var session: ObjectCaptureSession?
    @State private var passes = 1
    /// A lap has been completed: Object Capture's ring has photos from every side. Finish waits for this.
    @State private var allSides = false
    @State private var startError: String?
    @State private var releaseScreen: (() -> Void)?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let session {
                // The camera view gets its own space and nothing is drawn over its
                // middle or bottom, where Object Capture draws the box and the
                // progress ring: the hints sit along its top edge, the
                // instructions and buttons in a panel below it.
                VStack(spacing: 8) {
                    ObjectCaptureView(session: session)
                        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
                        .overlay(alignment: .top) {
                            Controls(session: session, subject: scan.record?.subject ?? .other, passes: $passes, allSides: $allSides,
                                     part: .top, onCancel: cancel)
                        }
                    Controls(session: session, subject: scan.record?.subject ?? .other, passes: $passes, allSides: $allSides,
                             part: .panel, onCancel: cancel)
                }
                .task { await follow(session) }
            } else if let startError {
                VStack(spacing: 16) {
                    Text(startError).foregroundStyle(.white).multilineTextAlignment(.center)
                    Button("Back", action: onCancel).buttonStyle(.borderedProminent)
                }.padding()
            } else {
                ProgressView().tint(.white)
            }
        }
        .onAppear {
            releaseScreen = KeepAlive.screen() // no dimming halfway round
            start()
        }
        .onDisappear { releaseScreen?(); releaseScreen = nil }
        .statusBarHidden()
    }

    private func start() {
        guard session == nil else { return }
        guard ObjectCaptureSession.isSupported else {
            startError = "This device can't run Object Capture. It needs an iPhone or iPad with LiDAR."
            return
        }
        var config = ObjectCaptureSession.Configuration()
        config.checkpointDirectory = scan.checkpoint
        config.isOverCaptureEnabled = false
        let s = ObjectCaptureSession()
        s.start(imagesDirectory: scan.images, configuration: config)
        session = s
    }

    /// Watch the session's state; when it has saved everything, hand over.
    private func follow(_ session: ObjectCaptureSession) async {
        for await state in session.stateUpdates {
            switch state {
            case .completed:
                var rec = scan.record
                rec?.shotsTaken = session.numberOfShotsTaken
                rec?.scanPasses = passes
                if let rec { scan.save(rec) }
                self.session = nil // free the camera and memory before the model is built
                onDone(scan)
                return
            case .failed(let error):
                var rec = scan.record
                rec?.error = error.localizedDescription
                if let rec { scan.save(rec) }
                startError = "The capture stopped: \(error.localizedDescription)"
                self.session = nil
                return
            default:
                continue
            }
        }
    }

    private func cancel() {
        session?.cancel()
        session = nil
        onCancel()
    }
}

/// The capture's controls: along the camera view's top edge, and in a panel below it.
private struct Controls: View {
    let session: ObjectCaptureSession
    let subject: Subject
    @Binding var passes: Int
    @Binding var allSides: Bool
    /// The cancel button, photo count and hints (over the top edge of the camera), or the panel below it.
    enum Part { case top, panel }
    var part: Part
    var onCancel: () -> Void

    static let legsFlatPhotos = 40
    private var enoughPhotos: Bool { subject.scanKind == "sole_hanging" && session.numberOfShotsTaken >= Self.legsFlatPhotos }

    /// Where you are: 0 point at it, 1 fit the box, 2 walk round.
    private var stepIndex: Int {
        switch session.state {
        case .ready, .initializing: 0
        case .detecting: 1
        default: 2
        }
    }

    var body: some View {
        Group {
            switch part {
            case .top: top
            case .panel: panel
            }
        }
    }

    private var top: some View {
        VStack(spacing: 0) {
            HStack {
                Button(action: onCancel) {
                    Image(systemName: "xmark").font(.headline).frame(width: 40, height: 40)
                        .background(.ultraThinMaterial, in: Circle())
                }
                .tint(.white)
                .accessibilityLabel("Cancel this scan")
                Spacer()
                if session.state == .capturing {
                    HStack(spacing: 6) {
                        Image(systemName: "camera.fill").font(.caption)
                        Text("\(session.numberOfShotsTaken)")
                            .font(.callout.monospacedDigit().weight(.bold))
                            .contentTransition(.numericText(value: Double(session.numberOfShotsTaken)))
                        Text("photos").font(.callout)
                        Divider().frame(height: 14).overlay(Color.white.opacity(0.4))
                        Image(systemName: allSides ? "checkmark.circle.fill" : "circle.dashed")
                            .foregroundStyle(allSides ? Color.fsAccent : .white)
                            .contentTransition(.symbolEffect(.replace))
                        Text(allSides ? "All sides" : "Sides").font(.callout.weight(allSides ? .bold : .regular))
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(session.numberOfShotsTaken) photos. \(allSides ? "Every side has photos." : "Not every side has photos yet.")")
                    .foregroundStyle(.white)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(.ultraThinMaterial, in: Capsule())
                    .animation(.snappy, value: session.numberOfShotsTaken)
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .padding(12)
            if let tip = feedbackText {
                Label(tip, systemImage: "exclamationmark.triangle.fill")
                    .font(.headline)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Color.fsAccent, in: Capsule())
                    .foregroundStyle(Color.fsAccentInk)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .padding(.top, 4)
            }
        }
        .animation(.spring(duration: 0.35, bounce: 0.3), value: feedbackText)
    }

    private var panel: some View {
        VStack(spacing: 14) {
            StepDots(index: stepIndex)
            Text(instruction)
                .font(.title3.weight(.semibold))
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
                .contentTransition(.opacity)
                .fixedSize(horizontal: false, vertical: true)
            buttons
        }
        .padding(18)
        .frame(maxWidth: .infinity)
        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 28, style: .continuous))
        .environment(\.colorScheme, .dark)
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
        .animation(.spring(duration: 0.45, bounce: 0.2), value: stepIndex)
        // the haptics live here only: the top part is a second copy of this view
        .sensoryFeedback(.selection, trigger: session.numberOfShotsTaken)
        .sensoryFeedback(.success, trigger: session.userCompletedScanPass)
        // once any lap has gone all the way round, Finish stays available (a further lap only adds photos)
        .onChange(of: session.userCompletedScanPass, initial: true) { _, done in if done { allSides = true } }
        .sensoryFeedback(.impact(weight: .medium), trigger: stepIndex)
    }

    private var instruction: String {
        switch session.state {
        case .initializing: "Getting the camera ready…"
        case .ready:
            switch subject.scanKind {
            case "sole_up": "Point the phone down at the sole, from about arm's length."
            case "sole_hanging": "Stand behind the feet and point the phone at the sole."
            case "impression": "Point the phone at the foam box, from about arm's length."
            default: "Point the phone at it, from about arm's length."
            }
        case .detecting:
            switch subject.scanKind {
            case "sole_up", "sole_hanging": "Drag the box's edges so it holds the foot and a hand's width of the leg, then Start."
            case "impression": "Drag the box's edges so it holds the whole foam box, then Start."
            default: "A box appears round it. Drag the box's edges so it holds just the object, then Start."
            }
        case .capturing:
            switch (subject.scanKind, session.userCompletedScanPass) {
            case ("sole_hanging", _):
                enoughPhotos
                    ? "Enough photos. Another sweep a little higher or lower makes it better; or Finish."
                    : "Sweep slowly from the inner side, round behind the foot, to the outer side. Then again higher and lower."
            case ("sole_up", false): "Walk slowly all the way round the foot, looking down at the sole, until the ring is full. Finish unlocks then."
            case ("sole_up", true): "Lap done. One more, closer and looking straight down at the arch, makes it better. Then Finish."
            case ("impression", false): "Walk slowly all the way round, looking down into the print, until the ring is full. Finish unlocks then."
            case ("impression", true): "Lap done. One more, higher up and looking straight down into the print, makes it better. Then Finish."
            case (_, true): "Lap done. Best results: 2 or 3 laps, one higher up looking down, one low. Then Finish."
            default: "Walk slowly all the way round until the ring is full. Finish unlocks then."
            }
        case .finishing: "Saving the last photos…"
        case .completed: "Done."
        case .failed: "Something went wrong."
        @unknown default: ""
        }
    }

    @ViewBuilder private var buttons: some View {
        switch session.state {
        case .ready:
            big("Continue") { _ = session.startDetecting() }
        case .detecting:
            HStack(spacing: 10) {
                Button("Find it again") { session.resetDetection() }
                    .buttonStyle(SecondaryButtonStyle())
                big("Start capture") { session.startCapturing() }
            }
        case .capturing:
            HStack(spacing: 10) {
                if session.userCompletedScanPass {
                    Button("Another lap") {
                        passes += 1
                        session.beginNewScanPass()
                    }
                    .buttonStyle(SecondaryButtonStyle())
                }
                // Not a photo count: twenty photos can all be from one side. Finish waits until
                // Object Capture says a lap went all the way round.
                // Legs flat: the bed is in the way, so Apple's ring can't fill all the way round; enough
                // photos from behind (the side the sole faces) is what counts there.
                let ready = allSides || enoughPhotos
                big(ready ? "Finish" : subject.scanKind == "sole_hanging"
                    ? "Keep sweeping (\(session.numberOfShotsTaken)/\(Self.legsFlatPhotos))" : "Go all the way round") { session.finish() }
                    .disabled(!ready)
            }
        default:
            EmptyView()
        }
    }

    private func big(_ title: String, action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(PrimaryButtonStyle(tint: .fsAccent, ink: .fsAccentInk))
    }

    /// Object Capture's own warnings, in footscan's words. The most useful one wins.
    private var feedbackText: String? {
        let f = session.feedback
        if f.contains(.environmentTooDark) { return "Too dark. Turn on more lights." }
        if f.contains(.environmentLowLight) { return "A bit dark. More light helps." }
        if f.contains(.movingTooFast) { return "Slow down a little." }
        if f.contains(.objectTooClose) { return "Step back a little." }
        if f.contains(.objectTooFar) { return "Move a little closer." }
        if f.contains(.outOfFieldOfView) { return "Keep it in the middle of the screen." }
        return nil
    }
}

/// Three dots and labels: point at it, fit the box, walk round.
private struct StepDots: View {
    let index: Int
    private let labels = ["Point", "Box", "Walk round"]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(0..<3, id: \.self) { i in
                HStack(spacing: 6) {
                    Circle()
                        .fill(i <= index ? Color.fsAccent : Color.white.opacity(0.3))
                        .frame(width: 8, height: 8)
                    if i == index {
                        Text(labels[i]).font(.caption.weight(.bold)).foregroundStyle(.white)
                            .transition(.opacity.combined(with: .scale(scale: 0.8, anchor: .leading)))
                    }
                }
                if i < 2 { Capsule().fill(i < index ? Color.fsAccent : Color.white.opacity(0.25)).frame(width: 18, height: 2) }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(index + 1) of 3: \(labels[index])")
    }
}
