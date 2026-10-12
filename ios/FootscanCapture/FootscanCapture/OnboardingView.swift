// First launch: what footscan is, the safety points, how to scan well, the
// camera, and (optionally) the studio. Shown once; replayable from Settings.
import AVFoundation
import SwiftUI

struct OnboardingView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(StudioConnection.self) private var studio
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Page: Int, CaseIterable { case welcome, safety, howTo, camera, studio }
    @State private var page: Page = .welcome
    @State private var forward = true
    @State private var acks = Set<Int>()
    @State private var camera = AVCaptureDevice.authorizationStatus(for: .video)
    @State private var showStudio = false

    static let acknowledgments: [(String, String)] = [
        ("This is not a medical device.", "It's homemade. A doctor didn't prescribe it, and it doesn't treat any illness or injury."),
        ("Before sport, a clinician checks it.", "A foot doctor (podiatrist), physical therapist, sports doctor or athletic trainer looks at it first. The wrong shape under a foot can hurt knees, hips or back."),
        ("I'll wear it a little at a time.", "One hour on day one, a bit more each day for two weeks. If anything starts to hurt, I stop."),
        ("Scans I send are kept.", "Scans stay on this phone until I send them; the studio keeps the ones I send, so an insole can be made."),
    ]

    var body: some View {
        VStack(spacing: 0) {
            progress
                .padding(.horizontal, 24).padding(.top, 12)
            ZStack {
                content(page)
                    .id(page)
                    .transition(reduceMotion ? .opacity : .asymmetric(
                        insertion: .move(edge: forward ? .trailing : .leading).combined(with: .opacity),
                        removal: .move(edge: forward ? .leading : .trailing).combined(with: .opacity)))
            }
            .frame(maxHeight: .infinity)
            .clipped()
            .gesture(DragGesture(minimumDistance: 30).onEnded { g in
                if g.translation.width < -60 { next() } else if g.translation.width > 60 { back() }
            })
            controls
                .padding(.horizontal, 24).padding(.bottom, 16)
        }
        .background(Color.fsBackground.ignoresSafeArea())
        .sensoryFeedback(.selection, trigger: page)
        .sheet(isPresented: $showStudio) { StudioView() }
    }

    // MARK: pieces

    private var progress: some View {
        HStack(spacing: 6) {
            ForEach(Page.allCases, id: \.self) { p in
                Capsule()
                    .fill(p.rawValue <= page.rawValue ? Color.fsBrand : Color.fsLine)
                    .frame(height: 5)
                    .frame(maxWidth: p == page ? .infinity : 28)
            }
        }
        .animation(.spring(duration: 0.45, bounce: 0.3), value: page)
        .accessibilityLabel("Step \(page.rawValue + 1) of \(Page.allCases.count)")
    }

    @ViewBuilder private func content(_ p: Page) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                switch p {
                case .welcome: welcome
                case .safety: safety
                case .howTo: howTo
                case .camera: cameraPage
                case .studio: studioPage
                }
            }
            .padding(.horizontal, 24).padding(.vertical, 20)
        }
        .scrollBounceBehavior(.basedOnSize)
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 16) {
            OrbitScene()
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 8)
            Text("Scan it.\nMeasure it.")
                .font(.system(size: 40, weight: .bold, design: .rounded))
                .foregroundStyle(Color.fsInk)
            Text("footscan turns a walk round your foot with your iPhone into a 3D model in real millimetres. Try it: drag the phone round the foot above.")
                .font(.body).foregroundStyle(Color.fsMuted)
            SafetyStrip()
        }
    }

    private var safety: some View {
        VStack(alignment: .leading, spacing: 14) {
            header("Before anything else", "Please read these and tick all four. They stay true for every scan.", symbol: "checkmark.shield.fill")
            ForEach(Array(Self.acknowledgments.enumerated()), id: \.offset) { i, ack in
                Button {
                    if acks.contains(i) { acks.remove(i) } else { acks.insert(i) }
                } label: {
                    HStack(alignment: .top, spacing: 14) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(acks.contains(i) ? Color.fsBrand : Color.fsSurface)
                                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .stroke(acks.contains(i) ? Color.fsBrand : Color.fsLine, lineWidth: 2))
                            Image(systemName: "checkmark")
                                .font(.system(size: 14, weight: .heavy))
                                .foregroundStyle(Color.fsBrandInk)
                                .scaleEffect(acks.contains(i) ? 1 : 0.2)
                                .opacity(acks.contains(i) ? 1 : 0)
                        }
                        .frame(width: 28, height: 28)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(ack.0).font(.headline).foregroundStyle(Color.fsInk)
                            Text(ack.1).font(.subheadline).foregroundStyle(Color.fsMuted).fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                    }
                    .card(padding: 16)
                    .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .stroke(acks.contains(i) ? Color.fsBrand.opacity(0.6) : .clear, lineWidth: 1.5))
                }
                .buttonStyle(PressableStyle())
                .animation(.spring(duration: 0.3, bounce: 0.5), value: acks)
                .sensoryFeedback(.impact(weight: .light), trigger: acks.contains(i))
                .accessibilityAddTraits(acks.contains(i) ? [.isSelected] : [])
            }
        }
    }

    private var howTo: some View {
        VStack(alignment: .leading, spacing: 14) {
            header("Three things make a good scan", "The phone does the measuring. Your part is easy.", symbol: "sparkles")
            tip("sun.max.fill", "Bright, even light", "No harsh shadows. Matte things scan best; shiny or plain white ones come out patchy.", 0)
            tip("arrow.trianglehead.2.clockwise.rotate.90", "Walk all the way round", "Slowly, keeping it in the middle of the screen. Then a lap higher up, looking down. 2 or 3 laps in all.", 1)
            tip("figure.stand", "Keep it still", "For a foot: sit, foot bare and flat on the mat, and let someone else hold the phone.", 2)
        }
    }

    private var cameraPage: some View {
        VStack(alignment: .leading, spacing: 16) {
            header("The camera", "Scanning uses the camera and the LiDAR sensor next to it. Photos stay on this phone unless you send them.", symbol: "camera.aperture")
            HStack(spacing: 14) {
                Image(systemName: cameraSymbol)
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(camera == .authorized ? Color.fsOK : Color.fsBrand)
                    .symbolEffect(.bounce, value: camera == .authorized)
                    .frame(width: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(cameraTitle).font(.headline)
                    Text(cameraDetail).font(.subheadline).foregroundStyle(Color.fsMuted)
                }
            }
            .card()
            if camera == .denied || camera == .restricted {
                Button("Open Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }
                .buttonStyle(SecondaryButtonStyle())
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            camera = AVCaptureDevice.authorizationStatus(for: .video)
        }
    }

    private var studioPage: some View {
        VStack(alignment: .leading, spacing: 16) {
            header("Send scans to your Mac", "Optional. Connect to the footscan studio once and every finished scan is sent there by itself.", symbol: "desktopcomputer.and.arrow.down")
            HStack(spacing: 14) {
                Image(systemName: studio.link == nil ? "desktopcomputer" : "checkmark.circle.fill")
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(studio.link == nil ? Color.fsBrand : Color.fsOK)
                    .contentTransition(.symbolEffect(.replace))
                    .frame(width: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(studio.link == nil ? "Not connected" : "Connected to \(studio.link!.host)").font(.headline)
                    Text(studio.link == nil
                         ? "On your Mac, open the footscan studio, go to Import 3D and tap Show the connect code. Then tap Connect and point the camera at it."
                         : "Finished scans will be sent there by themselves.")
                        .font(.subheadline).foregroundStyle(Color.fsMuted)
                }
            }
            .card()
            if studio.link == nil {
                Button("Connect now") { showStudio = true }.buttonStyle(SecondaryButtonStyle())
            }
        }
    }

    private var controls: some View {
        HStack(spacing: 12) {
            if page != .welcome {
                Button { back() } label: { Image(systemName: "chevron.left").font(.headline) }
                    .buttonStyle(SecondaryButtonStyle())
                    .frame(width: 64)
                    .accessibilityLabel("Back")
            }
            if page == .camera && camera == .notDetermined {
                Button("Allow the camera") { askCamera() }
                    .buttonStyle(PrimaryButtonStyle())
            } else {
                Button(nextTitle) { next() }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(page == .safety && acks.count < Self.acknowledgments.count)
            }
        }
        .overlay(alignment: .top) {
            if page == .camera && camera == .notDetermined {
                Button("Not now") { next() }
                    .font(.subheadline.weight(.semibold))
                    .offset(y: -34)
            }
        }
    }

    /// Ask once; if allowed, carry straight on.
    private func askCamera() {
        AVCaptureDevice.requestAccess(for: .video) { granted in
            Task { @MainActor in
                camera = AVCaptureDevice.authorizationStatus(for: .video)
                if granted {
                    try? await Task.sleep(for: .milliseconds(650)) // let the tick land first
                    if page == .camera { next() }
                }
            }
        }
    }

    // MARK: helpers

    private func header(_ title: String, _ detail: String, symbol: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let symbol { PageIllustration(symbol: symbol).padding(.bottom, 10) }
            Text(title).font(.system(.title, design: .rounded, weight: .bold)).foregroundStyle(Color.fsInk)
            Text(detail).font(.body).foregroundStyle(Color.fsMuted)
        }
        .padding(.bottom, 4)
    }

    private func tip(_ symbol: String, _ title: String, _ detail: String, _ index: Int) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(Color.fsBrand)
                .frame(width: 44, height: 44)
                .background(Color.fsBrandSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(Color.fsMuted).fixedSize(horizontal: false, vertical: true)
            }
        }
        .card(padding: 16)
        .modifier(StaggeredAppear(index: index))
    }

    private var nextTitle: String {
        switch page {
        case .welcome: "Get started"
        case .safety: acks.count < Self.acknowledgments.count ? "Tick all four to continue" : "I agree"
        case .studio: "Start scanning"
        default: "Continue"
        }
    }

    private var cameraSymbol: String {
        switch camera {
        case .authorized: "checkmark.circle.fill"
        case .denied, .restricted: "camera.badge.ellipsis"
        default: "camera.fill"
        }
    }
    private var cameraTitle: String {
        switch camera {
        case .authorized: "Camera allowed"
        case .denied, .restricted: "Camera is off for this app"
        default: "Not asked yet"
        }
    }
    private var cameraDetail: String {
        switch camera {
        case .authorized: "You're ready to scan."
        case .denied, .restricted: "Turn it on in Settings > footscan capture > Camera."
        default: "iOS will ask once."
        }
    }

    private func next() {
        if page == .safety && acks.count < Self.acknowledgments.count { return }
        if page == .safety && settings.safetyAcknowledgedAt == nil { settings.safetyAcknowledgedAt = Date() }
        guard let n = Page(rawValue: page.rawValue + 1) else {
            withAnimation(.smooth) { settings.onboarded = true }
            return
        }
        forward = true
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) { page = n }
    }

    private func back() {
        guard let p = Page(rawValue: page.rawValue - 1) else { return }
        forward = false
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) { page = p }
    }
}

/// Rises into place a beat after the one before it.
struct StaggeredAppear: ViewModifier {
    let index: Int
    @State private var shown = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .opacity(shown || reduceMotion ? 1 : 0)
            .offset(y: shown || reduceMotion ? 0 : 22)
            .onAppear {
                withAnimation(.spring(duration: 0.55, bounce: 0.25).delay(0.08 + Double(index) * 0.08)) { shown = true }
            }
    }
}

/// A big symbol in a soft disc, at the top of each intro page.
struct PageIllustration: View {
    let symbol: String
    @State private var shown = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Circle().fill(Color.fsBrandSoft).frame(width: 96, height: 96)
            Circle().stroke(Color.fsBrand.opacity(0.15), lineWidth: 10).frame(width: 118, height: 118)
                .scaleEffect(shown || reduceMotion ? 1 : 0.7).opacity(shown || reduceMotion ? 1 : 0)
            Image(systemName: symbol)
                .font(.system(size: 40, weight: .semibold))
                .foregroundStyle(Color.fsBrand)
                .symbolEffect(.bounce, value: shown)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityHidden(true)
        .onAppear { withAnimation(.spring(duration: 0.6, bounce: 0.4).delay(0.1)) { shown = true } }
    }
}
