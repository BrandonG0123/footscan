// The home screen: pick what you're scanning, start, and see past scans.
import QuickLook
import RealityKit
import SwiftUI

struct HomeView: View {
    @State private var subject: Subject = .calibration
    @State private var scans: [Scan] = ScanStore.all()
    @State private var capturing: Scan?
    @State private var path: [Scan] = []
    @State private var autoBuild: Scan?
    @State private var error: String?

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
            .navigationDestination(for: Scan.self) { scan in
                ScanDetail(scan: scan, buildNow: autoBuild == scan, onChange: { scans = ScanStore.all() })
            }
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
            if scan.hasModel {
                Section {
                    if scan.hasOBJ {
                        ShareLink(item: scan.obj) { Label("Send model.obj (for the studio)", systemImage: "square.and.arrow.up") }
                    }
                    ShareLink(item: scan.usdz) { Label("Send model.usdz", systemImage: "square.and.arrow.up") }
                } header: {
                    Text("Send to the Mac")
                } footer: {
                    Text("AirDrop model.obj to your Mac, then in the studio use Import 3D. For the calibration object, run `footscan accuracy-mesh` on it. To rebuild in more detail on the Mac, copy this scan's Images folder over: in Finder, open your iPhone, then Files, then footscan capture.")
                }
            }
        }
        .navigationTitle(rec?.subject.label ?? "Scan")
        .navigationBarTitleDisplayMode(.inline)
        .quickLookPreview($preview)
        .task {
            if buildNow && !scan.hasModel && builder.phase == .idle { await build() }
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
