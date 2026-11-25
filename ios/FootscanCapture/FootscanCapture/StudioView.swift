// Connecting the app to the studio, by scanning the code it shows.
import PhotosUI
import SwiftUI
import VisionKit

@MainActor
@Observable
final class StudioConnection {
    var link: StudioLink?
    private(set) var key: String?
    var status: String?
    /// Goes up by one on every successful connect, including reconnecting to
    /// the same studio, so waiting scans can be sent then.
    private(set) var connections = 0

    init() {
        StudioStore.removeLeftoverKey() // a key an earlier install left behind (docs/PRIVACY.md)
        if let saved = StudioStore.load() { link = saved.link; key = saved.key }
    }

    var client: StudioClient? {
        guard let link, let key else { return nil }
        return StudioClient(link: link, key: key)
    }

    /// Try a connect code; save it only if the studio answers to it (at any of its addresses).
    func connect(_ text: String) async -> Bool {
        pendingSwitch = nil // connecting any way answers the question
        guard let parsed = StudioStore.parse(text) else {
            if let other = StudioStore.parse(text, allowPublic: true) {
                status = other.link.fingerprint != nil
                    // the person's own computer, at an address that isn't its home-network or Tailscale one
                    ? "This code names \(other.link.host), which isn't an address on your home network or Tailscale. This app connects to your studio only at one of those: start Footscan on that computer on your Wi-Fi (or with Tailscale on), show the connect code again and scan it."
                    : "This app connects only to a studio on your own computer, over your Wi-Fi or Tailscale, not to one at a public internet address. Show the connect code in the studio on that computer and scan it."
            } else {
                status = "That isn't a Footscan studio code. In the studio, open Import 3D and tap Show the connect code."
            }
            return false
        }
        status = "Checking \(parsed.link.addresses.map(StudioLink.host(of:)).joined(separator: " and "))…"
        let reached: StudioClient
        do {
            reached = try await StudioClient(link: parsed.link, key: parsed.key).reach()
        } catch {
            status = error.localizedDescription
            return false
        }
        guard StudioStore.save(reached.link, key: parsed.key) else {
            status = "The studio answered, but this phone couldn't keep its key (the iPhone's Keychain refused it). Try again; if it keeps happening, restart the phone."
            return false
        }
        link = reached.link
        key = parsed.key
        connections += 1
        status = "Connected to \(Self.describe(reached.link.url))."
        return true
    }

    /// A connect code that came from outside the app (a link, or the iPhone's own Camera app) for a different
    /// studio from the connected one, waiting for a yes on the studio screen. The studio's own Scan the code and
    /// screenshot paths don't ask: the person chose to connect there.
    var pendingSwitch: (code: String, address: String)?

    /// A code from outside the app: connected straight away, unless it would put a different studio in place of
    /// the connected one, which is asked first (scans waiting to go would go to the new studio by themselves).
    func open(_ code: String) async {
        if let address = Self.otherStudio(in: code, connected: link) {
            pendingSwitch = (code, address)
            status = nil
            return
        }
        _ = await connect(code)
    }

    /// Yes to the pending switch: connect to the studio the link named.
    func confirmSwitch() async {
        guard let pending = pendingSwitch else { return }
        pendingSwitch = nil
        _ = await connect(pending.code)
    }

    /// The address of the studio `code` names, when it's a different studio from `connected`; nil when nothing
    /// is connected, when it's the same studio again (a new key, say), or when it isn't a studio code at all
    /// (connect() then says why).
    nonisolated static func otherStudio(in code: String, connected: StudioLink?) -> String? {
        guard let connected, let parsed = StudioStore.parse(code), !connected.isSameStudio(as: parsed.link) else { return nil }
        return describe(parsed.link.url)
    }

    /// Test the connection: try every address the studio has, and say which one answered.
    func check() async {
        guard let client else { return }
        status = "Checking…"
        do {
            let reached = try await client.reach()
            remember(reached.link)
            status = "The studio is answering at \(Self.describe(reached.link.url))."
            connections += 1 // back in touch: let waiting scans go
        } catch {
            status = error.localizedDescription
        }
    }

    /// Before opening the studio's camera page: use whichever address answers from here. Quiet: if none
    /// does, the page itself says it couldn't reach the studio.
    func findAddress() async {
        guard let client, !client.link.alternates.isEmpty,
              let reached = try? await client.reach(timeout: 3) else { return }
        remember(reached.link)
    }

    /// The studio answered at this address: use it first from now on. Ignored if the studio changed meanwhile.
    func remember(_ reached: StudioLink) {
        guard let link, reached != link, Set(reached.addresses) == Set(link.addresses),
              reached.fingerprint == link.fingerprint, key != nil else { return }
        self.link = reached
        StudioStore.saveLink(reached) // only the address order changed: the key in the Keychain stays as it is
    }

    /// "100.88.1.2 (Tailscale)": the address, and how it's reached.
    nonisolated static func describe(_ url: URL) -> String {
        let host = StudioLink.host(of: url)
        return StudioAddressKind(host: host).label.map { "\(host) (\($0))" } ?? host
    }

    func disconnect() {
        guard StudioStore.clear() else {
            status = "Couldn't remove the studio's key from this phone. Try Disconnect again."
            return
        }
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
    /// A screenshot or photo of the code, chosen instead of pointing the camera at it.
    @State private var picture: PhotosPickerItem?
    /// A connect is under way (from the camera or a picture): one at a time, so their answers can't cross.
    @State private var connecting = false

    private var canScan: Bool { DataScannerViewController.isSupported && DataScannerViewController.isAvailable }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    PageIllustration(symbol: studio.link == nil ? "desktopcomputer" : "desktopcomputer.and.arrow.down")
                    VStack(alignment: .leading, spacing: 6) {
                        Text(studio.link == nil ? "Connect to your studio" : "Your studio")
                            .font(.system(.title, design: .rounded, weight: .bold))
                        Text("Scans go straight from this phone to the Footscan studio on your computer: over your Wi-Fi at home, or over Tailscale from anywhere if the studio has it.")
                            .foregroundStyle(Color.fsMuted)
                    }
                    if let pending = studio.pendingSwitch { switchQuestion(pending.address) }
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
                VStack(spacing: 8) {
                    Group {
                        if studio.link == nil {
                            Button { scanning = true } label: { Label("Scan the studio's code", systemImage: "qrcode.viewfinder") }
                                .buttonStyle(PrimaryButtonStyle())
                        } else {
                            Button { scanning = true } label: { Label("Connect to a different studio", systemImage: "qrcode.viewfinder") }
                                .buttonStyle(SecondaryButtonStyle())
                        }
                    }
                    .disabled(!canScan || connecting)
                    // the code on this phone's own screen (a remote-desktop app), or sent as a picture
                    PhotosPicker(selection: $picture, matching: .images) {
                        Label("Use a screenshot of the code", systemImage: "photo.on.rectangle")
                            .font(.subheadline.weight(.semibold))
                    }
                    .disabled(connecting)
                }
                .padding(.horizontal, 20).padding(.vertical, 10)
                .background(.bar)
            }
            .onChange(of: picture) { _, item in
                guard let item, !connecting else { return }
                picture = nil
                connecting = true
                Task {
                    await connect(from: item)
                    connecting = false
                }
            }
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $scanning) {
                CodeScanner { text in
                    scanning = false
                    guard !connecting else { return }
                    connecting = true
                    Task {
                        _ = await studio.connect(text)
                        connecting = false
                    }
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

    /// Read the connect code from the chosen picture, and connect with it.
    private func connect(from item: PhotosPickerItem) async {
        studio.status = "Reading the picture…"
        guard let data = try? await item.loadTransferable(type: Data.self),
              let codes = await CodeInPicture.codes(inPicture: data) else {
            studio.status = "Couldn't open that picture. Choose it again, or scan the code with the camera."
            return
        }
        guard let code = codes.first else {
            studio.status = CodeInPicture.noneFound
            return
        }
        if await studio.connect(code) {
            studio.status = (studio.status.map { $0 + " " } ?? "") + CodeInPicture.deleteIt
        }
    }

    private var howTo: some View {
        VStack(alignment: .leading, spacing: 12) {
            step(1, "On your computer, open the Footscan studio")
            step(2, "Go to Import 3D and tap Show the connect code")
            step(3, "Tap Scan below and point this camera at it, or use a screenshot of it")
            if !canScan {
                Text("This device can't read codes with its camera. Point the iPhone's Camera app at the code instead (it opens this app), or take a screenshot of the code and use that.")
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

    /// A link named a different studio from the connected one: connect to it, or keep this one.
    private func switchQuestion(_ address: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Connect to a different studio?", systemImage: "arrow.left.arrow.right").font(.headline)
            Text("The code you opened is for the studio at \(address). Scans waiting to be sent would go there instead. "
                 + "Only connect if it's your own studio.")
                .font(.subheadline).foregroundStyle(Color.fsMuted)
            HStack {
                Button("Connect to \(address)") { Task { await studio.confirmSwitch() } }
                    .buttonStyle(PrimaryButtonStyle())
                Button("Keep this one") { studio.pendingSwitch = nil }
                    .buttonStyle(SecondaryButtonStyle())
            }
        }
        .card()
    }

    private func connected(_ link: StudioLink) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.circle.fill").font(.title2).foregroundStyle(Color.fsOK)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Connected").font(.headline)
                    ForEach(link.addresses, id: \.self) { address in
                        Text(StudioConnection.describe(address)).font(.subheadline.monospaced()).foregroundStyle(Color.fsMuted)
                    }
                }
            }
            Label(link.fingerprint == nil ? "Public address, checked the normal way (development builds only)" : "Talks only to this studio's computer (its certificate is pinned)",
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
