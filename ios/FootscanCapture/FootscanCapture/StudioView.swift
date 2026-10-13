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
            status = "That isn't a Footscan studio code. In the studio, open Import 3D and tap Show the connect code."
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
    @State private var confirmDisconnect = false

    private var canScan: Bool { DataScannerViewController.isSupported && DataScannerViewController.isAvailable }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    PageIllustration(symbol: studio.link == nil ? "desktopcomputer" : "desktopcomputer.and.arrow.down")
                    VStack(alignment: .leading, spacing: 6) {
                        Text(studio.link == nil ? "Connect to your studio" : "Your studio")
                            .font(.system(.title, design: .rounded, weight: .bold))
                        Text("Scans go straight from this phone to the Footscan studio on your Mac, over your Wi-Fi.")
                            .foregroundStyle(Color.fsMuted)
                    }
                    if let link = studio.link { connected(link) } else { howTo }
                    if let status = studio.status {
                        Label(status, systemImage: "info.circle")
                            .font(.footnote).foregroundStyle(Color.fsMuted)
                            .transition(.opacity)
                    }
                }
                .padding(20)
                .animation(.smooth, value: studio.status)
                .animation(.smooth, value: studio.link)
            }
            .background(Color.fsBackground.ignoresSafeArea())
            .safeAreaInset(edge: .bottom) {
                Group {
                    if studio.link == nil {
                        Button { scanning = true } label: { Label("Scan the studio's code", systemImage: "qrcode.viewfinder") }
                            .buttonStyle(PrimaryButtonStyle())
                    } else {
                        Button { scanning = true } label: { Label("Connect to a different studio", systemImage: "qrcode.viewfinder") }
                            .buttonStyle(SecondaryButtonStyle())
                    }
                }
                .disabled(!canScan)
                .padding(.horizontal, 20).padding(.vertical, 10)
                .background(.bar)
            }
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $scanning) {
                CodeScanner { text in
                    scanning = false
                    Task { await studio.connect(text) }
                }
                .ignoresSafeArea()
            }
            .confirmationDialog("Disconnect from this studio?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
                Button("Disconnect", role: .destructive) { studio.disconnect() }
            } message: {
                Text("Scans stay on this phone. You can connect again with the code.")
            }
        }
        .tint(.fsBrand)
        .sensoryFeedback(.success, trigger: studio.link)
    }

    private var howTo: some View {
        VStack(alignment: .leading, spacing: 12) {
            step(1, "On your Mac, open the Footscan studio")
            step(2, "Go to Import 3D and tap Show the connect code")
            step(3, "Tap the button below and point this camera at it")
            if !canScan {
                Text("This device can't read codes with its camera. Point the iPhone's Camera app at the code instead; it opens this app.")
                    .font(.footnote).foregroundStyle(Color.fsWarn)
            }
        }
        .card()
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)").font(.headline).foregroundStyle(Color.fsBrandInk)
                .frame(width: 28, height: 28).background(Color.fsBrand, in: Circle())
            Text(text).font(.body).foregroundStyle(Color.fsInk).padding(.top, 3)
        }
    }

    private func connected(_ link: StudioLink) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.circle.fill").font(.title2).foregroundStyle(Color.fsOK)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Connected").font(.headline)
                    Text(link.host).font(.subheadline.monospaced()).foregroundStyle(Color.fsMuted)
                }
            }
            Label(link.fingerprint == nil ? "Public address, checked the normal way" : "Talks only to this Mac (its certificate is pinned)",
                  systemImage: "lock.fill")
                .font(.footnote).foregroundStyle(Color.fsMuted)
            HStack {
                Button("Test the connection") { Task { await studio.check() } }
                Spacer()
                Button("Disconnect", role: .destructive) { confirmDisconnect = true }
            }
            .font(.subheadline.weight(.semibold))
        }
        .card()
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
