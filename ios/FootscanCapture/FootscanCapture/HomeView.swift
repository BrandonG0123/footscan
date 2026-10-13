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
        .onChange(of: studio.link) { _, link in if link != nil { sendWaiting() } }
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

    @AppStorage("lastSubject") private var subjectRaw = Subject.other.rawValue
    @State private var capturing: Scan?
    @State private var path: [Scan] = []
    @State private var prep: PrepRequest?
    @State private var showSettings = false
    @State private var showStudio = false
    @State private var error: String?
    @State private var startAfterPrep: Subject?

    struct PrepRequest: Identifiable {
        let subject: Subject
        let mustTick: Bool
        var id: String { subject.rawValue + (mustTick ? "!" : "") }
    }

    private var subject: Subject { Subject(rawValue: subjectRaw) ?? .other }

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

    private var hero: some View {
        VStack(alignment: .leading, spacing: 10) {
            OrbitScene(interactive: false)
                .frame(height: 240)
                .frame(maxWidth: .infinity)
            SafetyStrip()
        }
        // The scene and the safety strip shrink back and fade together as the
        // page scrolls up (so the strip never shows through the title bar);
        // they stretch a little on pull-down.
        .visualEffect { content, proxy in
            let y: CGFloat = proxy.frame(in: .scrollView).minY
            let up: CGFloat = min(1, max(0, -y / 200))
            let grow: CGFloat = y > 0 ? 1 + y / 900 : 1 - up * 0.18
            return content.scaleEffect(grow, anchor: .bottom).opacity(Double(1 - up)).blur(radius: up * 4)
        }
    }

    private var newScan: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New scan").font(.system(.title2, design: .rounded, weight: .bold))
            ScrollViewReader { reader in
            ScrollView(.horizontal) {
                HStack(spacing: 12) {
                    ForEach(Subject.allCases) { s in
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

            Button {
                start()
            } label: {
                Label(ObjectCaptureSession.isSupported ? "Scan \(subject.label.lowercased())" : "Needs an iPhone with LiDAR",
                      systemImage: "camera.viewfinder")
                    .contentTransition(.numericText())
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(!ObjectCaptureSession.isSupported)
            .animation(.smooth, value: subjectRaw)

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
            if s.photoCount > 0 && !s.hasOBJ && ObjectCaptureSession.isSupported {
                return (s, "Finish your \(r.subject.label.lowercased()) scan", "Its 3D model hasn't been built yet.")
            }
            if studio.client != nil, s.hasOBJ, r.studioCaptureID == nil, r.subject.isFoot, r.loadKg == nil {
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

    private func start() {
        if settings.hasPrepared(subject) { begin(subject) } else { prep = PrepRequest(subject: subject, mustTick: true) }
    }

    private func begin(_ s: Subject) {
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
                    .scaleEffect(x: subject == .leftFoot ? -1 : 1)
                    .symbolEffect(.bounce, value: selected)
                Spacer(minLength: 0)
                Text(subject.shortLabel).font(.headline).foregroundStyle(selected ? Color.fsBrandInk : Color.fsInk)
                    .lineLimit(1).minimumScaleFactor(0.8)
                Text(firstTime ? "First time" : "Ready").font(.caption.weight(.semibold))
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
