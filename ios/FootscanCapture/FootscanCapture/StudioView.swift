// Connecting the app to the studio, by scanning the code it shows.
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
    /// A studio waiting for the person's yes: a connect code that came from outside the app (the Camera app, a
    /// link in Safari or Messages) naming a different studio from the one saved. Connecting replaces the saved
    /// studio, and with "send automatically" on, every scan not yet sent would go to the new one at once.
    /// Each has its own `id`: a yes counts only for the one the question named (``confirm(_:)``).
    struct Pending: Identifiable, Equatable {
        let id = UUID()
        let code: String
        let link: StudioLink
        /// The studio's address in the question, so the person knows which one they're saying yes to.
        var address: String { StudioConnection.describe(link.url) }
    }
    var pending: Pending?

    /// Each connect attempt's number: only the newest may save. One that finishes after a later one started
    /// (two links opened close together, a slow reconnect after a yes to another studio) changes nothing.
    private var attempt = 0

    /// The network check and the Keychain save, replaceable in tests (which mustn't touch either).
    private let reachStudio: (StudioLink, String) async throws -> StudioLink
    private let saveStudio: (StudioLink, String) -> Bool

    init() {
        reachStudio = { link, key in try await StudioClient(link: link, key: key).reach().link }
        saveStudio = { link, key in StudioStore.save(link, key: key) }
        StudioStore.removeLeftoverKey() // a key an earlier install left behind (docs/PRIVACY.md)
        if let saved = StudioStore.load() { link = saved.link; key = saved.key }
    }

    /// For tests: a connection that starts with `saved` and never touches the network, Keychain or settings.
    init(saved: (link: StudioLink, key: String)?,
         reach: @escaping (StudioLink, String) async throws -> StudioLink,
         save: @escaping (StudioLink, String) -> Bool = { _, _ in true }) {
        reachStudio = reach
        saveStudio = save
        link = saved?.link
        key = saved?.key
    }

    var client: StudioClient? {
        guard let link, let key else { return nil }
        return StudioClient(link: link, key: key)
    }

    /// A code opened from outside the app. Connects without asking only when it can't take scans anywhere new:
    /// no studio is saved, or it is the saved studio (its key made again, a new Wi-Fi address). A different
    /// studio is asked first (``pending``); a newer link replaces the question, which then names the newer one.
    /// Codes scanned with the app's own button use ``connect(_:confirmed:)`` with `confirmed` true: tapping
    /// "Connect to a different studio" already said yes.
    func open(_ text: String) async {
        if let current = link, let parsed = StudioStore.parse(text), !StudioStore.isSameStudio(current, parsed.link) {
            attempt += 1 // a connect still running for an earlier link mustn't save under this question
            pending = Pending(code: text, link: parsed.link)
            status = nil
            return
        }
        _ = await connect(text, confirmed: false)
    }

    /// The person said yes to the question naming `asked`. Ignored unless that is still the question showing:
    /// a yes is never carried over to a link that arrived after it was asked.
    func confirm(_ asked: Pending) async {
        guard pending == asked else { return }
        pending = nil
        _ = await connect(asked.code, confirmed: true)
    }

    /// The person said no (or the question was dismissed): only that question goes.
    func decline(_ asked: Pending) {
        if pending == asked { pending = nil }
    }

    /// Try a connect code; save it only if the studio answers to it (at any of its addresses), this is still the
    /// newest attempt, and (`confirmed` false) it doesn't replace a different studio saved meanwhile: that is
    /// asked first, as in ``open(_:)``.
    func connect(_ text: String, confirmed: Bool) async -> Bool {
        attempt += 1
        let mine = attempt
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
        let reached: StudioLink
        do {
            reached = try await reachStudio(parsed.link, parsed.key)
        } catch {
            if mine == attempt { status = error.localizedDescription }
            return false
        }
        guard mine == attempt else { return false } // a newer link or a yes came meanwhile: that one decides
        if !confirmed, let current = link, !StudioStore.isSameStudio(current, reached) {
            // another studio was saved while this one was being checked: ask, as for a link that arrives then
            attempt += 1
            pending = Pending(code: text, link: parsed.link)
            status = nil
            return false
        }
        guard saveStudio(reached, parsed.key) else {
            status = "The studio answered, but this phone couldn't keep its key (the iPhone's Keychain refused it). Try again; if it keeps happening, restart the phone."
            return false
        }
        link = reached
        key = parsed.key
        connections += 1
        status = "Connected to \(Self.describe(reached.url))."
        return true
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
                    Task { _ = await studio.connect(text, confirmed: true) } // the person chose to scan a code
                }
                .ignoresSafeArea()
            }
            .confirmationDialog("Switch to a different studio?", isPresented: Binding(
                get: { studio.pending != nil }, set: { if !$0, let asked = studio.pending { studio.decline(asked) } }),
                                titleVisibility: .visible, presenting: studio.pending) { asked in
                Button("Switch to \(asked.address)") { Task { await studio.confirm(asked) } }
                Button("Keep the studio I have", role: .cancel) { studio.decline(asked) }
            } message: { asked in
                Text("A link opened Footscan with the code of the studio at \(asked.address). Switch only if that's your own studio: scans not sent yet will go to it.")
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
            step(1, "On your computer, open the Footscan studio")
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
