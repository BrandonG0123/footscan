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
    @State private var startError: String?
    @State private var releaseScreen: (() -> Void)?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let session {
                ObjectCaptureView(session: session)
                    .ignoresSafeArea()
                Controls(session: session, passes: $passes, onCancel: cancel)
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

/// The buttons and words at the bottom of the camera view.
private struct Controls: View {
    let session: ObjectCaptureSession
    @Binding var passes: Int
    var onCancel: () -> Void

    /// Where you are: 0 point at it, 1 fit the box, 2 walk round.
    private var stepIndex: Int {
        switch session.state {
        case .ready, .initializing: 0
        case .detecting: 1
        default: 2
        }
    }

    var body: some View {
        VStack {
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
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(.ultraThinMaterial, in: Capsule())
                    .animation(.snappy, value: session.numberOfShotsTaken)
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .padding()
            Spacer()
            if let tip = feedbackText {
                Label(tip, systemImage: "exclamationmark.triangle.fill")
                    .font(.headline)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Color.fsAccent, in: Capsule())
                    .foregroundStyle(Color.fsAccentInk)
                    .transition(.scale(scale: 0.85).combined(with: .opacity))
                    .padding(.bottom, 10)
            }
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
            .background(.ultraThinMaterial.opacity(0.92), in: RoundedRectangle(cornerRadius: 28, style: .continuous))
            .environment(\.colorScheme, .dark)
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
        }
        .animation(.spring(duration: 0.35, bounce: 0.3), value: feedbackText)
        .animation(.spring(duration: 0.45, bounce: 0.2), value: stepIndex)
        .sensoryFeedback(.selection, trigger: session.numberOfShotsTaken)
        .sensoryFeedback(.success, trigger: session.userCompletedScanPass)
        .sensoryFeedback(.impact(weight: .medium), trigger: stepIndex)
    }

    private var instruction: String {
        switch session.state {
        case .initializing: "Getting the camera ready…"
        case .ready: "Point the phone at it, from about arm's length."
        case .detecting: "A box appears round it. Drag the box's edges so it holds just the object, then Start."
        case .capturing:
            session.userCompletedScanPass
                ? "Lap done. Best results: 2 or 3 laps, one higher up looking down, one low. Then Finish."
                : "Walk slowly all the way round. Keep it in the middle of the screen."
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
                big(session.numberOfShotsTaken < 20 ? "Keep going…" : "Finish") { session.finish() }
                    .disabled(session.numberOfShotsTaken < 20)
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
