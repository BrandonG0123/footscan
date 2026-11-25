// One scan: the 3D model (spin it with a finger), where it's at, and what
// came back from the studio.
import QuickLook
import SwiftUI

struct ScanDetailView: View {
    let scan: Scan
    /// Start a new scan of the same kind, with what to change shown first (the studio refused this one).
    var onScanAgain: ((Scan) -> Void)?
    @Environment(ScanLibrary.self) private var library
    @Environment(StudioConnection.self) private var studio
    @Environment(AppSettings.self) private var settings
    @Environment(\.dismiss) private var dismiss
    @State private var loadText = ""
    @State private var showStudio = false
    @State private var confirmDelete = false
    @State private var preview: URL?
    @State private var naming: Scan?
    @FocusState private var loadFocused: Bool

    var body: some View {
        let _ = library.version
        let rec = scan.record
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                modelCard
                steps(rec)
                if let acc = rec?.studioAccuracy { AccuracyCard(acc: acc).scrollReveal() }
                details(rec).scrollReveal()
                if scan.hasModel { shareCard.scrollReveal() }
                Button(role: .destructive) { confirmDelete = true } label: {
                    Label("Delete this scan", systemImage: "trash").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(.fsStop)
                .padding(.top, 6)
                .disabled(library.work[scan.folder] != nil)
                if library.work[scan.folder] != nil {
                    Text("You can delete it once it has finished.").font(.footnote).foregroundStyle(Color.fsMuted)
                        .frame(maxWidth: .infinity)
                }
            }
            .padding(20)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Color.fsBackground.ignoresSafeArea())
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done") { loadFocused = false }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { naming = scan } label: { Image(systemName: "pencil") }
                    .accessibilityLabel("Name this scan")
                    .disabled(library.work[scan.folder] != nil)
            }
        }
        .modifier(NameScanAlert(scan: $naming))
        // VoiceOver says when the model or the send finishes while this scan is open, so nobody has to keep
        // feeling for the step to find out
        .onChange(of: modelState) { old, new in
            StepAnnouncement.post(StepAnnouncement.words(step: "3D model", from: old, to: new, detail: modelDetail(scan.record),
                                                         problem: library.problems[scan.folder]))
        }
        .onChange(of: studioState(rec)) { old, new in
            StepAnnouncement.post(StepAnnouncement.words(step: "Studio", from: old, to: new, detail: studioDetail(scan.record),
                                                         problem: library.problems[scan.folder]))
        }
        // and a tap you can feel when the send ends: a success, or an error when it stopped with a problem
        .sensoryFeedback(trigger: studioState(rec)) { old, new in
            StepAnnouncement.feedback(from: old, to: new, problem: library.problems[scan.folder] != nil)
        }
        .navigationTitle(rec?.heading ?? "Scan")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showStudio) { StudioView() }
        .quickLookPreview($preview)
        .confirmationDialog("Delete this scan from the phone?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { library.delete(scan); dismiss() }
        } message: {
            Text(scan.deleteWarning)
        }
        .onAppear { if let l = rec?.loadKg { loadText = ScaleReading.text(kilograms: l, unit: settings.scaleUnit) } }
        // a scan built before the phone checked models (or by an older check) is checked when it's opened
        .task { await library.check(scan) }
    }

    // MARK: the model

    @ViewBuilder private var modelCard: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(LinearGradient(colors: [.fsBrandSoft, .fsSurface], startPoint: .top, endPoint: .bottom))
            switch library.work[scan.folder] {
            case .building(let f): BuildRing(fraction: f, label: "Building the 3D model")
            case .converting: BuildRing(fraction: 1, label: "Finishing")
            default:
                if scan.hasModel {
                    ModelViewer(url: scan.usdz)
                        .accessibilityLabel("3D model of the scan. Drag to turn it.")
                        .transition(.scale(scale: 0.8).combined(with: .opacity))
                        .overlay(alignment: .bottomTrailing) {
                            Button { preview = scan.usdz } label: {
                                Label("Full screen", systemImage: "arkit").labelStyle(.iconOnly)
                                    .font(.headline).padding(10)
                                    .background(.ultraThinMaterial, in: Circle())
                            }
                            .padding(12)
                            .accessibilityLabel("Look at it full screen, or in your room")
                        }
                        .overlay(alignment: .bottomLeading) {
                            Label("Drag to turn", systemImage: "hand.draw")
                                .font(.caption.weight(.semibold)).foregroundStyle(Color.fsMuted)
                                .padding(12)
                        }
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "cube.transparent").font(.system(size: 44, weight: .light)).foregroundStyle(Color.fsBrand)
                        Text(scan.photoCount > 0 ? "No 3D model yet" : "No photos were kept").font(.headline)
                    }
                }
            }
        }
        .frame(height: 320)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(Color.fsLine, lineWidth: 1))
        .animation(.spring(duration: 0.6, bounce: 0.3), value: library.work[scan.folder])
        .animation(.spring(duration: 0.6, bounce: 0.3), value: scan.hasModel)
    }

    // MARK: where it's at

    private func steps(_ rec: ScanRecord?) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            StepRow(state: scan.photoCount > 0 ? .done : .failed, title: "Captured",
                    detail: "\(scan.photoCount) photos\(rec?.scanPasses.map { ", \($0) lap\($0 == 1 ? "" : "s")" } ?? "")",
                    isLast: false)
            StepRow(state: modelState, title: "3D model", detail: modelDetail(rec), isLast: false) {
                if !scan.hasOBJ && scan.photoCount > 0 && library.work[scan.folder] == nil {
                    Button(scan.hasModel ? "Finish it" : library.problems[scan.folder] == nil ? "Build it" : "Try again") {
                        Task { await library.finish(scan, settings: settings, studio: studio) }
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            StepRow(state: studioState(rec), title: "Studio", detail: studioDetail(rec), isLast: true) {
                studioActions(rec)
            }
            // what the phone's check found that doesn't mean scanning again
            ForEach(rec?.phoneCheck?.notes ?? [], id: \.self) { note in
                Label(note.detail, systemImage: "info.circle.fill")
                    .font(.footnote).foregroundStyle(Color.fsMuted)
                    .padding(.top, 8)
            }
            if let problem = library.problems[scan.folder] {
                Label(problem, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote).foregroundStyle(Color.fsWarn)
                    .padding(.top, 8)
                if library.reconnect.contains(scan.folder) {
                    Button { showStudio = true } label: { Label("Reconnect to the studio", systemImage: "qrcode.viewfinder") }
                        .font(.subheadline.weight(.semibold))
                        .padding(.leading, 28)
                }
            }
        }
        .card()
    }

    private var modelState: StepState {
        if case .building = library.work[scan.folder] { return .working }
        if library.work[scan.folder] == .converting { return .working }
        if scan.hasOBJ { return .done }
        if scan.hasModel || library.problems[scan.folder] != nil { return .failed }
        return .todo
    }

    private func modelDetail(_ rec: ScanRecord?) -> String {
        switch library.work[scan.folder] {
        case .building(let f): return "Building on the phone… \(Int(f * 100))%"
        case .converting: return "Saving a copy for the studio…"
        case .checking: return "Checking the model…"
        default:
            if scan.hasModel && !scan.hasOBJ { return "Built, but the copy for the studio wasn't saved" }
            if scan.hasModel { return rec?.modelSeconds.map { "Built on the phone in \(Int($0)) s" } ?? "Built on the phone" }
            if scan.photoCount > 0 && rec?.stoppedEarly != nil { return "Not built: the scan was stopped before the end" }
            return scan.photoCount > 0 ? "Not built yet" : "Nothing to build from"
        }
    }

    private func studioState(_ rec: ScanRecord?) -> StepState {
        if library.work[scan.folder] == .sending { return .working }
        if rec?.studioCaptureID != nil { return .done }
        if rec?.retake != nil || rec?.heldByPhoneCheck == true { return .failed }
        return .todo
    }

    private func studioDetail(_ rec: ScanRecord?) -> String {
        if library.work[scan.folder] == .sending {
            return SendingWords.detail(library.uploaded[scan.folder], calibration: rec?.subject == .calibration)
        }
        if rec?.studioCaptureID != nil {
            let when = rec?.sentAt.map { " \($0.formatted(.relative(presentation: .named)))" } ?? ""
            return "Sent to \(rec?.studioHost ?? "the studio")\(when)"
        }
        if rec?.retake != nil { return "Not kept: this scan won't make a good insole. Scan this foot again." }
        if library.work[scan.folder] == .checking { return "Checking the model first…" }
        if rec?.heldByPhoneCheck == true {
            return rec?.subject.isFoot == true ? "Not sent: the phone found a problem with this scan. Scan this foot again."
                : "Not sent: the phone found a problem with this scan. Scan it again."
        }
        if studio.client == nil { return "Not connected to a studio" }
        if rec?.subject.needsScale == true && rec?.loadKg == nil { return "Add the scale reading, then send" }
        if scan.hasOBJ { return "Ready to send" }
        return settings.autoSend ? "Sends by itself once the model is ready" : "Waiting for the model"
    }

    @ViewBuilder private func studioActions(_ rec: ScanRecord?) -> some View {
        if let rec, library.work[scan.folder] == nil {
            if let missing = rec.retake {
                // the studio refused it: what to change, and a new scan one tap away; no way to send it again
                VStack(alignment: .leading, spacing: 12) {
                    RetakeSteps(advice: rec.nextTime, heading: "Next time")
                    if let onScanAgain {
                        Button { onScanAgain(scan) } label: {
                            Label("Scan again", systemImage: "camera.viewfinder")
                        }
                        .buttonStyle(PrimaryButtonStyle())
                    } else {
                        Text("Start a new \(rec.subject.label.lowercased()) scan from the home screen.")
                            .font(.footnote).foregroundStyle(Color.fsMuted)
                    }
                    // the studio's own words, with its measurements, for anyone who wants them
                    if !missing.isEmpty {
                        DisclosureGroup("What the studio found") {
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(missing, id: \.self) { Text($0).font(.footnote).foregroundStyle(Color.fsMuted) }
                            }
                            .padding(.top, 6)
                        }
                        .font(.footnote.weight(.semibold))
                    }
                }
            } else if let check = rec.phoneCheck, rec.heldByPhoneCheck {
                // the phone's own check: what to change, a new scan one tap away, and the way to send it anyway
                VStack(alignment: .leading, spacing: 12) {
                    RetakeSteps(advice: rec.nextTime, heading: "What to change")
                    if let onScanAgain {
                        Button { onScanAgain(scan) } label: {
                            Label("Scan again", systemImage: "camera.viewfinder")
                        }
                        .buttonStyle(PrimaryButtonStyle())
                    }
                    DisclosureGroup("What the phone found") {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(check.scanAgain, id: \.self) { Text($0.detail).font(.footnote).foregroundStyle(Color.fsMuted) }
                            Text("The phone's check is quick and rough. The studio checks every scan again when it arrives.")
                                .font(.footnote).foregroundStyle(Color.fsMuted)
                        }
                        .padding(.top, 6)
                    }
                    .font(.footnote.weight(.semibold))
                    // a quiet way past it: the studio still checks the scan, and refuses it if it's no good. A seated
                    // foot scan needs its scale reading for that too, so the box is here as well.
                    if studio.client != nil && scan.hasOBJ && rec.subject.needsScale { scaleBox }
                    if studio.client != nil && scan.hasOBJ && !(rec.subject.needsScale && parsedLoad == nil) {
                        Button("Send anyway") {
                            Task { await library.sendAnyway(scan, studio: studio, loadKg: parsedLoad) }
                        }
                        .font(.footnote.weight(.semibold))
                        .buttonStyle(.borderless)
                    }
                }
            } else if studio.client == nil {
                Button("Connect") { showStudio = true }.buttonStyle(.bordered)
            } else if scan.hasOBJ {
                VStack(alignment: .leading, spacing: 8) {
                    if rec.subject.needsScale && rec.studioCaptureID == nil { scaleBox }
                    if rec.studioCaptureID == nil {
                        Button("Send to studio") {
                            Task { await library.send(scan, studio: studio, loadKg: parsedLoad) }
                        }
                        .buttonStyle(.borderedProminent)
                        // the reading on screen is what gets sent: never fall back to an older saved one
                        .disabled(rec.subject.needsScale && parsedLoad == nil)
                    } else {
                        // already there: sending again makes a second copy, so it's a quiet option
                        Button("Send another copy") {
                            Task { await library.send(scan, studio: studio, loadKg: parsedLoad) }
                        }
                        .font(.footnote.weight(.semibold))
                        .buttonStyle(.borderless)
                    }
                }
            }
        }
    }

    private var parsedLoad: Double? { ScaleReading.kilograms(loadText, unit: settings.scaleUnit) }

    /// The bathroom-scale reading for a seated foot scan, in kg or lb (what the scale shows), with what the studio
    /// will get in kg under it.
    private var scaleBox: some View {
        @Bindable var settings = settings
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: "scalemass").foregroundStyle(Color.fsBrand)
                TextField("Scale reading", text: $loadText)
                    .keyboardType(.decimalPad)
                    .focused($loadFocused)
                // the number stays as typed: the switch says which unit the scale showed it in
                Picker("Scale unit", selection: $settings.scaleUnit) {
                    ForEach(ScaleUnit.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .fixedSize()
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            .background(Color.fsSurface2, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            if let kg = parsedLoad {
                Text(ScaleReading.sentAs(kg)).font(.footnote).foregroundStyle(Color.fsMuted)
            }
        }
    }

    // MARK: details and sharing

    private func details(_ rec: ScanRecord?) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Details").font(.headline)
            // with a name in the title, what was scanned is said here
            if let rec, rec.name != nil { row("What", rec.subject.label) }
            if let d = rec?.created { row("Scanned", d.formatted(date: .abbreviated, time: .shortened)) }
            row("Phone", "\(ScanStore.phoneName(rec?.device ?? "?")), iOS \(rec?.systemVersion ?? "?")")
            if let l = rec?.loadKg { row("Scale reading", ScaleReading.detail(kilograms: l, unit: settings.scaleUnit)) }
            if let id = rec?.studioCaptureID { row("In the studio", id) }
            if let err = rec?.error { row("Last problem", err) }
        }
        .card()
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(k).font(.subheadline).foregroundStyle(Color.fsMuted).frame(width: 110, alignment: .leading)
            Text(v).font(.subheadline).foregroundStyle(Color.fsInk)
        }
    }

    private var shareCard: some View {
        let rec = scan.record
        return VStack(alignment: .leading, spacing: 10) {
            Text("Share").font(.headline)
            HStack(spacing: 10) {
                if scan.hasOBJ { ShareLink(item: SharedFile(scan.obj, record: rec), preview: SharePreview("3D model")) { Label(".obj", systemImage: "square.and.arrow.up") }.buttonStyle(.bordered) }
                ShareLink(item: SharedFile(scan.usdz, record: rec), preview: SharePreview("3D model")) { Label(".usdz", systemImage: "square.and.arrow.up") }.buttonStyle(.bordered)
            }
            Text("Shared files are named after the scan. The .obj goes into the studio's Import 3D. To rebuild in more detail on a Mac, copy this scan's Images folder over (Finder > iPhone > Files > Footscan).")
                .font(.footnote).foregroundStyle(Color.fsMuted)
        }
        .card()
    }
}

// MARK: - pieces

enum StepState { case todo, working, done, failed }

/// What VoiceOver says when a step that was under way ends: done, needs a look, or stopped with a problem.
/// Nothing for a step that changes without having been under way (opening a scan, a tap on Delete).
enum StepAnnouncement {
    static func words(step: String, from old: StepState, to new: StepState, detail: String, problem: String?) -> String? {
        guard old == .working, new != .working else { return nil }
        switch new {
        case .done: return "\(step) done. \(detail)"
        case .failed: return "\(step) needs a look. \(problem ?? detail)"
        case .todo, .working: return problem.map { "\(step) stopped. \($0)" }
        }
    }

    /// What the phone does in the hand when a step that was under way ends.
    static func feedback(from old: StepState, to new: StepState, problem: Bool) -> SensoryFeedback? {
        guard old == .working, new != .working else { return nil }
        switch new {
        case .done: return .success
        case .failed: return .error
        case .todo, .working: return problem ? .error : nil
        }
    }

    /// Queued behind whatever VoiceOver is saying, rather than cutting it off.
    static func post(_ words: String?) {
        guard let words, UIAccessibility.isVoiceOverRunning else { return }
        let queued = NSAttributedString(string: words, attributes: [.accessibilitySpeechQueueAnnouncement: true])
        UIAccessibility.post(notification: .announcement, argument: queued)
    }
}

/// One step of a scan's progress, with a line joining it to the next.
struct StepRow<Actions: View>: View {
    let state: StepState
    let title: String
    let detail: String
    let isLast: Bool
    @ViewBuilder var actions: () -> Actions

    init(state: StepState, title: String, detail: String, isLast: Bool, @ViewBuilder actions: @escaping () -> Actions = { EmptyView() }) {
        self.state = state; self.title = title; self.detail = detail; self.isLast = isLast; self.actions = actions
    }

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(spacing: 0) {
                ZStack {
                    Circle().fill(fill).frame(width: 30, height: 30)
                    switch state {
                    case .done: Image(systemName: "checkmark").font(.caption.weight(.heavy)).foregroundStyle(Color.fsBrandInk)
                    case .working: ProgressView().controlSize(.small).tint(Color.fsBrandInk)
                    case .failed: Image(systemName: "exclamationmark").font(.caption.weight(.heavy)).foregroundStyle(.white)
                    case .todo: Circle().fill(Color.fsMuted.opacity(0.5)).frame(width: 8, height: 8)
                    }
                }
                .animation(.spring(duration: 0.35, bounce: 0.5), value: state)
                if !isLast {
                    Rectangle().fill(state == .done ? Color.fsBrand : Color.fsLine).frame(width: 2).frame(minHeight: 22)
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(Color.fsMuted).fixedSize(horizontal: false, vertical: true)
                    .contentTransition(.numericText())
                actions()
            }
            .padding(.bottom, isLast ? 0 : 14)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(title): \(stateWords). \(detail)")
    }

    private var stateWords: String {
        switch state {
        case .done: "done"
        case .working: "in progress"
        case .failed: "needs a look"
        case .todo: "not yet"
        }
    }

    private var fill: Color {
        switch state {
        case .done, .working: .fsBrand
        case .failed: .fsStop
        case .todo: .fsSurface2
        }
    }
}

/// A ring that fills as the model builds.
struct BuildRing: View {
    let fraction: Double
    let label: String

    var body: some View {
        VStack(spacing: 14) {
            ZStack {
                Circle().stroke(Color.fsLine, lineWidth: 10)
                Circle()
                    .trim(from: 0, to: max(0.02, fraction))
                    .stroke(AngularGradient(colors: [.fsBrand, .fsAccent, .fsBrand], center: .center),
                            style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(.smooth, value: fraction)
                Text("\(Int(fraction * 100))%")
                    .font(.system(.title, design: .rounded, weight: .bold).monospacedDigit())
                    .contentTransition(.numericText(value: fraction))
                    .animation(.smooth, value: fraction)
            }
            .frame(width: 120, height: 120)
            Text(label).font(.headline)
            Text("Keep the app open. It takes a minute or two.").font(.footnote).foregroundStyle(Color.fsMuted)
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue("\(Int(fraction * 100)) percent")
    }
}

/// The calibration object's accuracy, as the studio measured it.
struct AccuracyCard: View {
    let acc: StudioAccuracy

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Accuracy", systemImage: "ruler").font(.headline)
            if let error = acc.error {
                Text(error).font(.subheadline).foregroundStyle(Color.fsWarn)
            } else {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 12) {
                    statRow("Typical error", mm(acc.median_mm, signed: false))
                    statRow("Worst 5%", mm(acc.p95_mm, signed: false))
                    statRow("Too big (+) / small (−)", mm(acc.signed_mean_mm))
                    statRow("Captured within 1 mm", acc.within_1mm.map { "\(Int(($0 * 100).rounded()))%" } ?? "—")
                    // differences, not sizes: "+1.30 mm" is 1.3 mm longer than the design (or the calipers)
                    statRow("Length off by", mm(acc.length_mm))
                    statRow("Width off by", mm(acc.width_mm))
                    if acc.dome_apex_mm != nil { statRow("Dome height off by", mm(acc.dome_apex_mm)) }
                    if let pct = acc.scale_pct { statRow("Size overall", Self.percent(pct)) }
                }
                if let warnings = acc.warnings, !warnings.isEmpty {
                    DisclosureGroup("What the studio noticed (\(warnings.count))") {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(Array(warnings.enumerated()), id: \.offset) { _, w in
                                Text(w).font(.footnote).foregroundStyle(Color.fsMuted)
                            }
                        }
                        .padding(.top, 6)
                    }
                    .font(.footnote.weight(.semibold))
                }
                Text(Self.referenceNote(acc.reference))
                    .font(.footnote).foregroundStyle(Color.fsMuted)
            }
        }
        .card()
    }

    private func statRow(_ k: String, _ v: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(k).font(.caption).foregroundStyle(Color.fsMuted)
            Text(v).font(.system(.title3, design: .rounded, weight: .semibold).monospacedDigit())
        }
    }

    /// "+0.9%" bigger than it should be, "−1.2%" smaller.
    static func percent(_ v: Double) -> String { Self.signed(v, places: 1) + "%" }

    /// What the "off by" sizes are the scan minus. The studio says "calipers" once any reading was typed in, and
    /// each size is then compared with its own reading if there is one, else with the design: so it says both.
    static func referenceNote(_ reference: String?) -> String {
        reference == "calipers"
            ? "Off by: the scan minus your caliper reading of the print where you typed one in, else minus the object's design."
            : "Off by: the scan minus the object's design. Type caliper readings of the print in the studio for a fairer comparison."
    }

    /// Rounded first, so a tiny difference shows as 0.0, with no sign; a true minus sign, as in "−1.2".
    static func signed(_ v: Double, places: Int) -> String {
        let scale = pow(10.0, Double(places))
        let r = (v * scale).rounded() / scale
        return (r > 0 ? "+" : r < 0 ? "−" : "") + String(format: "%.\(places)f", abs(r))
    }

    private func mm(_ v: Double?, signed: Bool = true) -> String {
        guard let v else { return "—" }
        return (signed ? Self.signed(v, places: 2) : String(format: "%.2f", v)) + " mm"
    }
}
