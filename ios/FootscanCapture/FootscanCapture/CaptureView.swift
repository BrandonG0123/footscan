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
        .onAppear(perform: start)
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

    var body: some View {
        VStack {
            HStack {
                Button("Cancel", action: onCancel)
                    .buttonStyle(.bordered).tint(.white)
                Spacer()
                if session.state == .capturing {
                    Text("\(session.numberOfShotsTaken) photos")
                        .font(.callout.monospacedDigit().weight(.semibold))
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(.ultraThinMaterial, in: Capsule())
                }
            }
            .padding()
            Spacer()
            VStack(spacing: 12) {
                if let tip = feedbackText {
                    Text(tip)
                        .font(.headline)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(.orange.opacity(0.9), in: Capsule())
                        .foregroundStyle(.black)
                        .transition(.opacity.combined(with: .scale(scale: 0.9)))
                }
                Text(instruction)
                    .font(.title3.weight(.semibold))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white)
                    .shadow(radius: 4)
                buttons
            }
            .padding()
            .padding(.bottom, 12)
            .animation(.spring(duration: 0.3), value: feedbackText)
        }
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
            HStack {
                Button("Find it again") { session.resetDetection() }
                    .buttonStyle(.bordered).tint(.white)
                big("Start capture") { session.startCapturing() }
            }
        case .capturing:
            HStack {
                if session.userCompletedScanPass {
                    Button("Another lap") {
                        passes += 1
                        session.beginNewScanPass()
                    }
                    .buttonStyle(.bordered).tint(.white)
                }
                big("Finish") { session.finish() }
                    .disabled(session.numberOfShotsTaken < 20)
            }
        default:
            EmptyView()
        }
    }

    private func big(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.headline).frame(minWidth: 160).padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
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
