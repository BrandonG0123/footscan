// Home: start a scan in one tap, and see every scan with where it's at.
//
// The first time, the intro runs instead (OnboardingView). Before the first
// scan of each kind, a short "get ready" list (PrepSheet); after that, Start
// goes straight to the camera, and the model is built (and sent, with a
// studio connected) by itself.
import RealityKit
import SwiftUI

struct RootView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(StudioConnection.self) private var studio
    @Environment(ScanLibrary.self) private var library
    @Environment(\.scenePhase) private var scenePhase
    @State private var showStudio = false

    var body: some View {
        ZStack {
            if settings.onboarded {
                HomeView().transition(.opacity.combined(with: .scale(scale: 1.04)))
            } else {
                OnboardingView().transition(.opacity)
            }
        }
        .animation(.smooth(duration: 0.5), value: settings.onboarded)
        // The studio's code, read by the iPhone's own Camera app, opens here,
        // whatever is on screen (even the intro, on a brand-new install).
        .onOpenURL { url in
            showStudio = true
            Task { await studio.connect(url.absoluteString) }
        }
        .sheet(isPresented: $showStudio) { StudioView() }
        // Scans that couldn't go before go now: when a studio is connected
        // (or reconnected), when the app comes back to the front, and when
        // "send automatically" is switched on.
        .onChange(of: studio.connections) { sendWaiting() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { sendWaiting() } }
        .onChange(of: settings.autoSend) { _, on in if on { sendWaiting() } }
    }

    private func sendWaiting() {
        Task { await library.sendWaiting(settings: settings, studio: studio) }
    }
}

struct HomeView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(StudioConnection.self) private var studio
    @Environment(ScanLibrary.self) private var library

    @AppStorage("lastSubject") private var subjectRaw = Subject.rightSole.rawValue
    @State private var capturing: Scan?
    @State private var path: [Scan] = []
    @State private var prep: PrepRequest?
    @State private var showSettings = false
    @State private var showStudio = false
    @State private var error: String?
    @State private var startAfterPrep: Subject?
    @State private var photoCapture: Subject?

    struct PrepRequest: Identifiable {
        let subject: Subject
        let mustTick: Bool
        var id: String { subject.rawValue + (mustTick ? "!" : "") }
    }

    /// What this phone can scan: sole and foam-print scans need Apple's 3D capture.
    private var subjects: [Subject] { Subject.allCases.filter { CaptureMethod.lidarAvailable || !$0.needs3DCapture } }

    private var subject: Subject {
        Subject(rawValue: subjectRaw).flatMap { subjects.contains($0) ? $0 : nil } ?? subjects[0]
    }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    hero
                    if let need = needsYou { attention(need) }
                    newScan
                    scansSection
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 40)
            }
            .scrollIndicators(.hidden)
            .background(Color.fsBackground.ignoresSafeArea())
            .navigationTitle("Footscan")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("Footscan")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.fsInk)
                        .accessibilityAddTraits(.isHeader)
                }
                ToolbarItem(placement: .topBarLeading) { studioPill }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape.fill") }
                        .accessibilityLabel("Settings")
                }
            }
            .navigationDestination(for: Scan.self) { ScanDetailView(scan: $0) }
            .refreshable { library.reload() }
        }
        .tint(.fsBrand)
        .sheet(isPresented: $showSettings) { SettingsView() }
        .sheet(isPresented: $showStudio) { StudioView() }
        // The camera opens only once the get-ready sheet has fully gone:
        // presenting it while the sheet is still closing can lose it.
        .sheet(item: $prep, onDismiss: {
            if let s = startAfterPrep { startAfterPrep = nil; begin(s) }
        }) { req in
            PrepSheet(subject: req.subject, mustTick: req.mustTick) { startAfterPrep = req.subject }
                .presentationDragIndicator(.visible)
        }
        .fullScreenCover(item: $photoCapture) { s in
            if let link = studio.link, let key = studio.client?.key {
                PhotoCaptureView(subject: s, link: link, key: key) {
                    settings.markPrepared(s)
                    photoCapture = nil
                }
            }
        }
        .fullScreenCover(item: $capturing) { scan in
            CaptureView(scan: scan, onDone: { done in
                capturing = nil
                if let s = done.record?.subject { settings.markPrepared(s) }
                library.reload()
                path = [done]
                Task { await library.finish(done, settings: settings, studio: studio) }
            }, onCancel: {
                capturing = nil
                library.reload()
            })
        }
    }

    // MARK: sections

    /// Where you are on the way to an insole, in one compact card (with the
    /// not-a-medical-device line built in). It fades as the page scrolls up.
    private var hero: some View {
        InsolePath(step: insoleStep, studioConnected: studio.link != nil, autoSend: settings.autoSend) {
            switch insoleStep {
            case 0:  // pick the sole scan
                withAnimation(.spring(duration: 0.35, bounce: 0.35)) { subjectRaw = subjects.first(where: \.needs3DCapture)?.rawValue ?? subjectRaw }
            case 1:  // open the scan that's waiting to go, where Send is
                if let waiting = soleScans.first(where: { $0.record?.studioCaptureID == nil }) { path.append(waiting) }
            default:
                break
            }
        }
        .visualEffect { content, proxy in
            let up: CGFloat = min(1, max(0, -proxy.frame(in: .scrollView).minY / 160))
            return content.opacity(Double(1 - up)).scaleEffect(1 - up * 0.04, anchor: .bottom)
        }
    }

    /// 0 scan the sole, 1 send it, 2 make the insole on the Mac (sign-off follows there).
    private var soleScans: [Scan] { library.scans.filter { ($0.record?.subject).map { $0.needs3DCapture && $0.isFoot } == true && $0.hasOBJ } }

    private var insoleStep: Int {
        let soles = soleScans
        if soles.contains(where: { $0.record?.studioCaptureID != nil }) { return 2 }
        return soles.isEmpty ? 0 : 1
    }

    private var newScan: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New scan").font(.system(.title2, design: .rounded, weight: .bold))
            ScrollViewReader { reader in
            ScrollView(.horizontal) {
                HStack(spacing: 12) {
                    ForEach(subjects) { s in
                        SubjectCard(subject: s, selected: s == subject, firstTime: !settings.hasPrepared(s)) {
                            withAnimation(.spring(duration: 0.35, bounce: 0.35)) { subjectRaw = s.rawValue }
                        }
                        .scrollTransition(.interactive, axis: .horizontal) { content, phase in
                            content
                                .scaleEffect(phase.isIdentity ? 1 : 0.9)
                                .rotation3DEffect(.degrees(phase.value * -14), axis: (0, 1, 0), perspective: 0.6)
                                .opacity(phase.isIdentity ? 1 : 0.6)
                        }
                        .id(s.rawValue)
                    }
                }
                .scrollTargetLayout()
                .padding(.vertical, 6)
            }
            .scrollTargetBehavior(.viewAligned)
            .scrollIndicators(.hidden)
            .contentMargins(.horizontal, 2, for: .scrollContent)
            .sensoryFeedback(.selection, trigger: subjectRaw)
            .onAppear { reader.scrollTo(subjectRaw, anchor: .center) }
            .onChange(of: subjectRaw) { _, new in withAnimation(.smooth) { reader.scrollTo(new, anchor: .center) } }
            }

            methodPicker

            Button {
                if method == .photos && studio.client == nil { showStudio = true } else { start() }
            } label: {
                Label(method == .photos && studio.client == nil
                      ? "Connect to your studio first"
                      : "Scan \(subject.label.lowercased())",
                      systemImage: method == .photos && studio.client == nil ? "desktopcomputer" : "camera.viewfinder")
                    .contentTransition(.numericText())
            }
            .buttonStyle(PrimaryButtonStyle())
            .animation(.smooth, value: subjectRaw)
            .animation(.smooth, value: method)

            HStack {
                if settings.hasPrepared(subject) {
                    Button { prep = PrepRequest(subject: subject, mustTick: false) } label: {
                        Label("Tips", systemImage: "lightbulb")
                    }
                    .font(.subheadline.weight(.semibold))
                } else {
                    Label("A short get-ready list comes first, this once.", systemImage: "checklist")
                        .font(.footnote).foregroundStyle(Color.fsMuted)
                }
                Spacer()
            }
            if let error { Text(error).font(.footnote).foregroundStyle(Color.fsStop) }
        }
    }

    private var scansSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("Your scans").font(.system(.title2, design: .rounded, weight: .bold))
                Spacer()
                Text("\(library.scans.count)")
                    .font(.subheadline.monospacedDigit().weight(.semibold))
                    .foregroundStyle(Color.fsMuted)
                    .contentTransition(.numericText())
            }
            if library.scans.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "cube.transparent")
                        .font(.system(size: 40, weight: .light))
                        .foregroundStyle(Color.fsBrand)
                        .symbolEffect(.pulse)
                    Text("No scans yet").font(.headline)
                    Text("Your first one will appear here, with its 3D model.").font(.subheadline).foregroundStyle(Color.fsMuted)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 30)
                .card()
            } else {
                LazyVStack(spacing: 12) {
                    ForEach(library.scans) { scan in
                        NavigationLink(value: scan) { ScanCard(scan: scan) }
                            .buttonStyle(PressableStyle())
                            .scrollReveal()
                            .contextMenu {
                                if scan.hasOBJ { ShareLink(item: scan.obj) { Label("Share model.obj", systemImage: "square.and.arrow.up") } }
                                Button(role: .destructive) { withAnimation { library.delete(scan) } } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                                .disabled(library.work[scan.folder] != nil)
                            }
                    }
                }
                .animation(.spring(duration: 0.4), value: library.scans)
            }
        }
    }

    /// The first scan that's waiting on you, and what it needs.
    private var needsYou: (scan: Scan, title: String, detail: String)? {
        for s in library.scans where library.work[s.folder] == nil {
            guard let r = s.record else { continue }
            if let p = library.problems[s.folder] { return (s, "\(r.subject.label) needs a look", p) }
            if s.photoCount > 0 && !s.hasOBJ && CaptureMethod.lidarAvailable {
                return (s, "Finish your \(r.subject.label.lowercased()) scan", "Its 3D model hasn't been built yet.")
            }
            if studio.client != nil, s.hasOBJ, r.studioCaptureID == nil, r.subject.needsScale, r.loadKg == nil {
                return (s, "Add the scale reading", "Then your \(r.subject.label.lowercased()) scan can go to the studio.")
            }
        }
        return nil
    }

    private func attention(_ need: (scan: Scan, title: String, detail: String)) -> some View {
        Button { path.append(need.scan) } label: {
            HStack(spacing: 14) {
                Image(systemName: "exclamationmark.circle.fill")
                    .font(.title2).foregroundStyle(Color.fsWarn)
                    .symbolEffect(.pulse, options: .repeating)
                VStack(alignment: .leading, spacing: 2) {
                    Text(need.title).font(.headline).foregroundStyle(Color.fsInk)
                    Text(need.detail).font(.subheadline).foregroundStyle(Color.fsMuted).lineLimit(2)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Color.fsMuted)
            }
            .padding(16)
            .background(Color.fsWarnSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
        .buttonStyle(PressableStyle())
        .transition(.move(edge: .top).combined(with: .opacity))
    }

    private var studioPill: some View {
        Button { showStudio = true } label: {
            Image(systemName: studio.link == nil ? "desktopcomputer" : "desktopcomputer.and.arrow.down")
                .symbolRenderingMode(.hierarchical)
                .overlay(alignment: .topTrailing) {
                    Circle().fill(studio.link == nil ? Color.fsMuted : Color.fsOK)
                        .frame(width: 8, height: 8)
                        .offset(x: 4, y: -3)
                }
        }
        .accessibilityLabel(studio.link == nil ? "Studio: not connected" : "Studio: connected to \(studio.link!.host)")
    }

    // MARK: actions

    /// The way this phone will scan: the chosen one, or photos where 3D capture isn't available.
    private var method: CaptureMethod {
        guard CaptureMethod.lidarAvailable else { return .photos }
        return subject.needs3DCapture ? .lidar : settings.method
    }

    @ViewBuilder private var methodPicker: some View {
        @Bindable var settings = settings
        if subject.needs3DCapture {
            Label("Uses 3D capture: the phone builds the model, then sends it to your studio for the insole.",
                  systemImage: "cube.transparent")
                .font(.footnote).foregroundStyle(Color.fsMuted)
        } else if CaptureMethod.lidarAvailable {
            VStack(alignment: .leading, spacing: 6) {
                Picker("How to scan", selection: $settings.method) {
                    ForEach(CaptureMethod.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                Text(method.detail).font(.footnote).foregroundStyle(Color.fsMuted)
                    .contentTransition(.opacity)
            }
            .sensoryFeedback(.selection, trigger: settings.method)
        } else {
            Label("This iPhone scans with photos on the printed mat (it can't run Apple's 3D capture). The studio on your Mac builds the model.",
                  systemImage: "camera.on.rectangle")
                .font(.footnote).foregroundStyle(Color.fsMuted)
        }
    }

    private func start() {
        if settings.hasPrepared(subject) { begin(subject) } else { prep = PrepRequest(subject: subject, mustTick: true) }
    }

    private func begin(_ s: Subject) {
        if method == .photos {
            // photos go straight to the studio: nothing big is kept on the phone
            guard studio.client != nil else { showStudio = true; return }
            photoCapture = s
            return
        }
        if let problem = DiskSpace.captureProblem() {
            withAnimation(.smooth) { error = problem }
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
            return
        }
        do {
            capturing = try ScanStore.create(s)
            error = nil
        } catch {
            self.error = "Couldn't make a folder for the scan: \(error.localizedDescription)"
        }
    }
}

// MARK: - cards

private struct SubjectCard: View {
    let subject: Subject
    let selected: Bool
    let firstTime: Bool
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: subject.symbol)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(selected ? Color.fsAccentInk : Color.fsBrand)
                    .frame(width: 44, height: 44)
                    .background(selected ? Color.fsAccent : Color.fsBrandSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .scaleEffect(x: subject.isLeft ? -1 : 1)
                    .symbolEffect(.bounce, value: selected)
                Spacer(minLength: 0)
                Text(subject.shortLabel).font(.headline).foregroundStyle(selected ? Color.fsBrandInk : Color.fsInk)
                    .lineLimit(1).minimumScaleFactor(0.8)
                Text(firstTime ? "First time · \(subject.purpose)" : subject.purpose).font(.caption.weight(.semibold))
                    .lineLimit(1).minimumScaleFactor(0.8)
                    .foregroundStyle(selected ? Color.fsBrandInk.opacity(0.8) : Color.fsMuted)
            }
            .padding(14)
            .frame(width: 156, alignment: .topLeading)
            .frame(minHeight: 150, alignment: .topLeading)
            .background(selected ? Color.fsBrand : Color.fsSurface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(selected ? .clear : Color.fsLine, lineWidth: 1))
            .shadow(color: selected ? Color.fsBrand.opacity(0.35) : .black.opacity(0.04), radius: selected ? 14 : 8, y: 6)
        }
        .buttonStyle(PressableStyle())
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

struct ScanCard: View {
    let scan: Scan
    @Environment(ScanLibrary.self) private var library

    var body: some View {
        let _ = library.version
        let rec = scan.record
        HStack(spacing: 14) {
            ScanThumb(scan: scan)
                .frame(width: 72, height: 72)
            VStack(alignment: .leading, spacing: 6) {
                Text(rec?.subject.label ?? scan.folder.lastPathComponent).font(.headline).foregroundStyle(Color.fsInk)
                if let d = rec?.created {
                    Text("\(d.formatted(date: .abbreviated, time: .shortened)) · \(scan.photoCount) photos")
                        .font(.caption).foregroundStyle(Color.fsMuted)
                }
                ScanStatus(scan: scan)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Color.fsMuted)
                .accessibilityHidden(true)
        }
        .card(padding: 12)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the scan")
    }
}

/// Where a scan is at, as one chip (with live progress while something is happening).
struct ScanStatus: View {
    let scan: Scan
    @Environment(ScanLibrary.self) private var library

    var body: some View {
        let _ = library.version
        let rec = scan.record
        Group {
            switch library.work[scan.folder] {
            case .building(let f): Chip(text: "Building model \(Int(f * 100))%", symbol: "gearshape.2.fill")
            case .converting: Chip(text: "Finishing model", symbol: "gearshape.2.fill")
            case .sending: Chip(text: "Sending", symbol: "paperplane.fill")
            case nil:
                if library.problems[scan.folder] != nil {
                    Chip(text: "Needs a look", symbol: "exclamationmark.triangle.fill", tint: .fsWarn, soft: .fsWarnSoft)
                } else if rec?.studioCaptureID != nil {
                    Chip(text: "Sent to studio", symbol: "checkmark.circle.fill", tint: .fsOK, soft: .fsOKSoft)
                } else if scan.hasModel {
                    Chip(text: "Model ready", symbol: "cube.fill")
                } else if scan.photoCount > 0 {
                    Chip(text: "Photos only", symbol: "photo.stack", tint: .fsMuted, soft: .fsSurface2)
                } else {
                    Chip(text: "Empty", symbol: "xmark", tint: .fsMuted, soft: .fsSurface2)
                }
            }
        }
        .contentTransition(.numericText())
        .animation(.smooth, value: library.work[scan.folder])
    }
}

struct ScanThumb: View {
    let scan: Scan
    @Environment(ScanLibrary.self) private var library
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.fsBrandSoft)
            if let image {
                Image(uiImage: image).resizable().scaledToFit().padding(6).transition(.opacity)
            } else {
                Image(systemName: scan.record?.subject.symbol ?? "cube")
                    .font(.title2).foregroundStyle(Color.fsBrand.opacity(0.7))
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .task(id: library.version) {
            if image == nil, !FileManager.default.fileExists(atPath: scan.thumbnail.path()), scan.hasModel {
                await library.makeThumbnail(scan)
            }
            if let ui = UIImage(contentsOfFile: scan.thumbnail.path()) {
                withAnimation(.smooth) { image = ui }
            }
        }
    }
}

// MARK: - the way to an insole

private struct InsolePath: View {
    let step: Int
    let studioConnected: Bool
    let autoSend: Bool
    var onTap: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let steps: [(symbol: String, label: String)] = [
        ("shoeprints.fill", "Scan sole"), ("arrow.up.forward.app.fill", "Send"),
        ("cube.fill", "Make insole"), ("checkmark.seal.fill", "Sign-off"),
    ]

    private var title: String {
        ["Scan the bottom of your foot", "Send it to your studio", "Make the insole on your Mac"][step]
    }

    private var detail: String {
        switch step {
        case 0: CaptureMethod.lidarAvailable
            ? "Sole up or a foam print: it's the shape the insole is made from."
            : "Sole and foam-print scans need an iPhone with LiDAR (a Pro model)."
        case 1:
            if !studioConnected { autoSend ? "Connect to the studio on your Mac; then it goes by itself."
                                           : "Connect to the studio on your Mac, then open the scan and tap Send." }
            else if autoSend { "It goes by itself when the phone is on the same Wi-Fi as the Mac." }
            else { "Sending automatically is off: tap here to open the scan, then Send." }
        default: "Research library, then Make insole. A podiatrist or athletic trainer signs the summary sheet before you play in it."
        }
    }

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text("YOUR INSOLE").font(.caption.weight(.heavy)).tracking(1.2).foregroundStyle(Color.fsAccent)
                    Spacer()
                    Text("Step \(step + 1) of 4").font(.caption.weight(.semibold).monospacedDigit())
                        .foregroundStyle(.white.opacity(0.6))
                        .contentTransition(.numericText())
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.system(.title3, design: .rounded, weight: .bold)).foregroundStyle(.white)
                    Text(detail).font(.subheadline).foregroundStyle(.white.opacity(0.72))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .id(step)
                .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity),
                                        removal: .move(edge: .leading).combined(with: .opacity)))
                track
                Divider().overlay(Color.white.opacity(0.12))
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("NOT A MEDICAL DEVICE").font(.caption2.weight(.heavy)).foregroundStyle(Color.fsAccent)
                    Text("See a foot doctor before sport.").font(.caption2).foregroundStyle(.white.opacity(0.7))
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(LinearGradient(colors: [Color(light: 0x15201f, dark: 0x0a0f0e), Color(light: 0x0e4f4a, dark: 0x113a36)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            }
            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(Color.fsAccent.opacity(0.25), lineWidth: 1))
            .shadow(color: Color.fsBrand.opacity(0.25), radius: 18, y: 8)
        }
        .buttonStyle(PressableStyle())
        .animation(.spring(duration: 0.5, bounce: 0.2), value: step)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Your insole, step \(step + 1) of 4: \(title). \(detail) Not a medical device.")
    }

    private var track: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(steps.indices, id: \.self) { i in
                VStack(spacing: 6) {
                    node(i)
                    Text(steps[i].label).font(.caption2.weight(i == step ? .bold : .medium))
                        .foregroundStyle(i <= step ? .white : .white.opacity(0.45))
                        .lineLimit(1).minimumScaleFactor(0.8)
                }
                .frame(maxWidth: .infinity)
                .background(alignment: .top) {
                    if i < steps.count - 1 {  // the line to the next step, filled once this one is done
                        GeometryReader { g in
                            Capsule().fill(Color.white.opacity(0.15))
                                .overlay(alignment: .leading) {
                                    Capsule().fill(Color.fsAccent).frame(width: i < step ? g.size.width : 0)
                                }
                                .frame(width: g.size.width - 40, height: 3)
                                .offset(x: g.size.width / 2 + 20, y: 15)
                        }
                    }
                }
            }
        }
    }

    private func node(_ i: Int) -> some View {
        let done = i < step, current = i == step
        return ZStack {
            Circle().fill(done ? Color.fsAccent.opacity(0.18) : current ? Color.fsAccent : Color.white.opacity(0.08))
            Circle().stroke(done || current ? Color.fsAccent : Color.white.opacity(0.25), lineWidth: 1.5)
            Image(systemName: done ? "checkmark" : steps[i].symbol)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(current ? Color.fsAccentInk : done ? Color.fsAccent : .white.opacity(0.5))
                .contentTransition(.symbolEffect(.replace))
        }
        .frame(width: 32, height: 32)
        .background {
            if current && !reduceMotion {  // a slow glow round the step you're on
                Circle().fill(Color.fsAccent.opacity(0.35))
                    .phaseAnimator([false, true]) { c, on in c.scaleEffect(on ? 1.55 : 1).opacity(on ? 0 : 0.8) }
                        animation: { _ in .easeOut(duration: 1.6) }
            }
        }
    }
}
