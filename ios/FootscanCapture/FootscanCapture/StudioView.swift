// Connecting the app to the studio, by scanning the code it shows.
import SwiftUI
import VisionKit

@MainActor
@Observable
final class StudioConnection {
    var link: StudioLink?
    private(set) var key: String?
    var status: String?

    init() {
        if let saved = StudioStore.load() { link = saved.link; key = saved.key }
    }

    var client: StudioClient? {
        guard let link, let key else { return nil }
        return StudioClient(link: link, key: key)
    }

    /// Try a connect code; save it only if the studio answers to it.
    func connect(_ text: String) async -> Bool {
        guard let parsed = StudioStore.parse(text) else {
            status = "That isn't a footscan studio code. In the studio, open Import 3D and tap Show the connect code."
            return false
        }
        status = "Checking \(parsed.link.host)…"
        do {
            try await StudioClient(link: parsed.link, key: parsed.key).check()
        } catch {
            status = error.localizedDescription
            return false
        }
        StudioStore.save(parsed.link, key: parsed.key)
        link = parsed.link
        key = parsed.key
        status = "Connected to \(parsed.link.host)."
        return true
    }

    func check() async {
        guard let client else { return }
        status = "Checking…"
        do {
            try await client.check()
            status = "The studio is answering."
        } catch {
            status = error.localizedDescription
        }
    }

    func disconnect() {
        StudioStore.clear()
        link = nil
        key = nil
        status = "Disconnected. Scans stay on this phone."
    }
}

struct StudioView: View {
    @Environment(StudioConnection.self) private var studio
    @Environment(\.dismiss) private var dismiss
    @State private var scanning = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if let link = studio.link {
                        LabeledContent("Connected to", value: link.host)
                        LabeledContent("Security", value: link.fingerprint == nil
                                       ? "Public address (normal certificate checks)"
                                       : "This Mac only (pinned certificate)")
                        Button("Test the connection") { Task { await studio.check() } }
                        Button("Disconnect", role: .destructive) { studio.disconnect() }
                    } else {
                        Text("Not connected. Scans can still be sent by AirDrop.").foregroundStyle(.secondary)
                    }
                    if let status = studio.status { Text(status).font(.footnote) }
                }
                Section {
                    Button {
                        scanning = true
                    } label: {
                        Label(studio.link == nil ? "Connect: scan the studio's code" : "Connect to a different studio",
                              systemImage: "qrcode.viewfinder")
                    }
                    .disabled(!(DataScannerViewController.isSupported && DataScannerViewController.isAvailable))
                } footer: {
                    Text("On the Mac, start footscan with --host 0.0.0.0 --https, open the studio's Import 3D page and tap Show the connect code. The phone and Mac need to be on the same Wi-Fi.")
                }
            }
            .navigationTitle("Studio")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $scanning) {
                CodeScanner { text in
                    scanning = false
                    Task { await studio.connect(text) }
                }
                .ignoresSafeArea()
            }
        }
    }
}

/// The camera, looking for a QR code; reports the first one it reads.
struct CodeScanner: UIViewControllerRepresentable {
    var onCode: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let vc = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])],
                                           qualityLevel: .balanced, isHighlightingEnabled: true)
        vc.delegate = context.coordinator
        try? vc.startScanning()
        return vc
    }

    func updateUIViewController(_ vc: DataScannerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onCode: onCode) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let onCode: (String) -> Void
        private var done = false
        init(onCode: @escaping (String) -> Void) { self.onCode = onCode }

        func dataScanner(_ scanner: DataScannerViewController, didAdd items: [RecognizedItem], allItems: [RecognizedItem]) {
            for case .barcode(let code) in items {
                guard !done, let text = code.payloadStringValue else { continue }
                done = true
                scanner.stopScanning()
                onCode(text)
                return
            }
        }
    }
}
