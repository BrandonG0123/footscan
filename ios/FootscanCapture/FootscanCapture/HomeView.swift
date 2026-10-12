// The home screen: pick what you're scanning, start, and see past scans.
import QuickLook
import RealityKit
import SwiftUI

struct HomeView: View {
    // Starts on "Something else", so a calibration-object scan is always a deliberate choice.
    @State private var subject: Subject = .other
    @State private var scans: [Scan] = ScanStore.all()
    @State private var capturing: Scan?
    @State private var path: [Scan] = []
    @State private var autoBuild: Scan?
    @State private var error: String?
    @State private var showStudio = false
    @Environment(StudioConnection.self) private var studio

    var body: some View {
        NavigationStack(path: $path) {
            List {
                Section {
                    SafetyNote()
                }
                Section("What are you scanning?") {
                    Picker("Scanning", selection: $subject) {
                        ForEach(Subject.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.menu)
                    Text(subject.howTo).font(.callout).foregroundStyle(.secondary)
                    Button {
                        start()
                    } label: {
                        Label("Start scanning", systemImage: "camera.viewfinder")
                            .frame(maxWidth: .infinity).padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!ObjectCaptureSession.isSupported)
                    if !ObjectCaptureSession.isSupported {
                        Text("This device has no LiDAR, so it can't run Object Capture. Use an iPhone Pro or iPad Pro.")
                            .font(.footnote).foregroundStyle(.red)
                    }
                    if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                }
                Section("Scans on this phone") {
                    if scans.isEmpty {
                        Text("None yet.").foregroundStyle(.secondary)
                    }
                    ForEach(scans) { scan in
                        NavigationLink(value: scan) { ScanRow(scan: scan) }
                    }
                    .onDelete { idx in
                        idx.map { scans[$0] }.forEach(ScanStore.delete)
                        scans = ScanStore.all()
                    }
                }
            }
            .navigationTitle("footscan capture")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showStudio = true } label: {
                        Label("Studio", systemImage: studio.link == nil ? "desktopcomputer" : "desktopcomputer.and.arrow.down")
                    }
                }
            }
            .sheet(isPresented: $showStudio) { StudioView() }
            .navigationDestination(for: Scan.self) { scan in
                ScanDetail(scan: scan, buildNow: autoBuild == scan, onChange: { scans = ScanStore.all() })
            }
        }
        // The studio's code, read by the iPhone's own Camera app, opens here.
        .onOpenURL { url in
            showStudio = true
            Task { await studio.connect(url.absoluteString) }
        }
        .fullScreenCover(item: $capturing) { scan in
            CaptureView(scan: scan, onDone: { done in
                capturing = nil
                scans = ScanStore.all()
                autoBuild = done
                path = [done]
            }, onCancel: {
                capturing = nil
                scans = ScanStore.all()
            })
        }
    }

    private func start() {
        do {
            capturing = try ScanStore.create(subject)
            error = nil
        } catch {
            self.error = "Couldn't make a folder for the scan: \(error.localizedDescription)"
        }
    }
}

private struct SafetyNote: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("NOT A MEDICAL DEVICE").font(.caption.weight(.heavy)).foregroundStyle(.orange)
            Text("A test app for measuring how accurate LiDAR scanning is. It doesn't design or treat anything.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }
}

private struct ScanRow: View {
    let scan: Scan
    var body: some View {
        let rec = scan.record
        VStack(alignment: .leading, spacing: 2) {
            Text(rec?.subject.label ?? scan.folder.lastPathComponent).font(.headline)
            HStack(spacing: 6) {
                if let d = rec?.created { Text(d, style: .date); Text(d, style: .time) }
                Text("· \(scan.photoCount) photos")
                if scan.hasModel { Image(systemName: "cube.fill").foregroundStyle(.green) }
            }
            .font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct ScanDetail: View {
    let scan: Scan
    var buildNow: Bool
    var onChange: () -> Void

    @State private var builder = ModelBuilder()
    @State private var preview: URL?
    @State private var sending = false
    @State private var sendError: String?
    @State private var loadText = ""
    @State private var showStudio = false
    @State private var refresh = 0
    @Environment(StudioConnection.self) private var studio

    var body: some View {
        let rec = scan.record
        List {
            Section("Capture") {
                LabeledContent("What", value: rec?.subject.label ?? "?")
                LabeledContent("Photos kept", value: "\(scan.photoCount)")
                if let passes = rec?.scanPasses { LabeledContent("Laps", value: "\(passes)") }
                LabeledContent("Phone", value: "\(rec?.device ?? "?"), iOS \(rec?.systemVersion ?? "?")")
                if let err = rec?.error { Text(err).foregroundStyle(.red).font(.footnote) }
            }
            Section("3D model") {
                switch builder.phase {
                case .building(let f):
                    ProgressView(value: f) { Text("Building the model on the phone… \(Int(f * 100))%") }
                    Text("Keep the app open. This can take a few minutes.").font(.footnote).foregroundStyle(.secondary)
                case .converting:
                    ProgressView { Text("Saving a copy for the studio…") }
                case .failed(let msg):
                    Text(msg).foregroundStyle(.red).font(.footnote)
                    buildButton("Try again")
                default:
                    if scan.hasModel {
                        if let s = rec?.modelSeconds { LabeledContent("Built in", value: "\(Int(s)) s") }
                        Button { preview = scan.usdz } label: { Label("Look at it", systemImage: "cube") }
                    } else if scan.photoCount > 0 {
                        buildButton("Build the 3D model")
                    } else {
                        Text("No photos were kept.").foregroundStyle(.secondary)
                    }
                }
            }
            if scan.hasOBJ, let rec {
                studioSection(rec)
            }
            if scan.hasModel {
                Section {
                    if scan.hasOBJ {
                        ShareLink(item: scan.obj) { Label("Send model.obj (for the studio)", systemImage: "square.and.arrow.up") }
                    }
                    ShareLink(item: scan.usdz) { Label("Send model.usdz", systemImage: "square.and.arrow.up") }
                } header: {
                    Text("Send to the Mac")
                } footer: {
                    Text("Or AirDrop model.obj to your Mac, then in the studio use Import 3D. For the calibration object, run `footscan accuracy-mesh` on it. To rebuild in more detail on the Mac, copy this scan's Images folder over: in Finder, open your iPhone, then Files, then footscan capture.")
                }
            }
        }
        .id(refresh)
        .sheet(isPresented: $showStudio) { StudioView() }
        .navigationTitle(rec?.subject.label ?? "Scan")
        .navigationBarTitleDisplayMode(.inline)
        .quickLookPreview($preview)
        .task {
            if buildNow && !scan.hasModel && builder.phase == .idle { await build() }
        }
    }

    // Sending to the studio, and what came back.
    @ViewBuilder private func studioSection(_ rec: ScanRecord) -> some View {
        Section {
            if let id = rec.studioCaptureID {
                Label("Sent to \(rec.studioHost ?? "the studio")", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                LabeledContent("Capture", value: id).font(.footnote)
                if let acc = rec.studioAccuracy { AccuracyRows(acc: acc) }
            }
            if rec.subject.isFoot && rec.studioCaptureID == nil {
                TextField("Scale reading under this foot (kg)", text: $loadText)
                    .keyboardType(.decimalPad)
            }
            if studio.client == nil {
                Button { showStudio = true } label: { Label("Connect to your studio to send it straight there", systemImage: "desktopcomputer") }
            } else if sending {
                ProgressView { Text(rec.subject == .calibration ? "Sending and measuring accuracy…" : "Sending…") }
            } else {
                Button { Task { await send(rec) } } label: {
                    Label(rec.studioCaptureID == nil ? "Send to studio" : "Send again", systemImage: "paperplane")
                }
                .disabled(rec.subject.isFoot && rec.studioCaptureID == nil && parsedLoad == nil)
            }
            if let sendError { Text(sendError).font(.footnote).foregroundStyle(.red) }
        } header: {
            Text("Studio")
        } footer: {
            if rec.subject.isFoot && rec.studioCaptureID == nil {
                Text("A seated foot scan is part-loaded: the studio records the scale reading with it, as in the Phase 0 protocol.")
            }
        }
    }

    private var parsedLoad: Double? {
        let v = Double(loadText.replacingOccurrences(of: ",", with: "."))
        return v.flatMap { $0 > 0 && $0 < 400 ? $0 : nil }
    }

    private func send(_ rec: ScanRecord) async {
        guard let client = studio.client else { return }
        sending = true
        sendError = nil
        defer { sending = false }
        var record = rec
        if record.subject.isFoot, let load = parsedLoad { record.loadKg = load }
        do {
            let sent = try await client.upload(scan, record: record)
            record.studioCaptureID = sent.captureID
            record.studioHost = client.link.host
            record.sentAt = Date()
            record.studioAccuracy = sent.accuracy
            scan.save(record)
            refresh += 1
            onChange()
        } catch {
            sendError = error.localizedDescription
        }
    }

    private func buildButton(_ title: String) -> some View {
        Button { Task { await build() } } label: { Label(title, systemImage: "cube.transparent") }
    }

    private func build() async {
        await builder.build(scan)
        onChange()
    }
}

/// The calibration object's accuracy, as the studio measured it.
private struct AccuracyRows: View {
    let acc: StudioAccuracy

    var body: some View {
        if let error = acc.error {
            Text(error).font(.footnote).foregroundStyle(.orange)
        } else {
            LabeledContent("Surface, typical error", value: mm(acc.median_mm, signed: false))
            LabeledContent("Surface, worst 5%", value: mm(acc.p95_mm, signed: false))
            LabeledContent("Too big (+) or small (−)", value: mm(acc.signed_mean_mm))
            LabeledContent("Length", value: mm(acc.length_mm))
            LabeledContent("Width", value: mm(acc.width_mm))
            LabeledContent("Dome top height", value: mm(acc.dome_apex_mm))
            Text(acc.reference == "calipers"
                 ? "Compared with your caliper readings of the print."
                 : "Compared with the object's design. Add caliper readings in the studio for a fairer comparison.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func mm(_ v: Double?, signed: Bool = true) -> String {
        guard let v else { return "not measured" }
        return (signed && v > 0 ? "+" : "") + String(format: "%.2f mm", v)
    }
}
