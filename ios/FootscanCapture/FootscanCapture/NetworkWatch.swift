// Noticing when the phone's network changes, so scans waiting for the studio go then.
//
// A scan whose send failed because the studio didn't answer (away from home, Tailscale off, the studio
// computer asleep) waits on the phone. Until now it went again only when the app came back to the front,
// a studio was connected, or "send automatically" was switched on. Walking in the door and joining the home
// Wi-Fi, or switching Tailscale on (it shows up as a new network path), is when it can go: this watches for
// that. It only reads whether the phone has a network and which kinds (Wi-Fi, mobile, VPN); nothing is sent
// or kept.
import Foundation
import Network

@MainActor
@Observable
final class NetworkWatch {
    /// Goes up by one each time the phone's network settles into a different state that has a way out.
    private(set) var changes = 0

    /// How long a change is left to settle (a new Wi-Fi hands out its address, a VPN finishes connecting)
    /// before anything is tried over it. Changes inside this time count once.
    static let settle: Duration = .seconds(3)

    private let monitor = NWPathMonitor()
    private var last: Signature?
    private var pending: Task<Void, Never>?

    /// The parts of a network path that matter for reaching the studio.
    struct Signature: Equatable {
        var satisfied: Bool
        var wifi: Bool
        var cellular: Bool
        var wired: Bool
        var other: Bool  // VPNs such as Tailscale show up as "other"

        init(satisfied: Bool, wifi: Bool, cellular: Bool, wired: Bool, other: Bool) {
            self.satisfied = satisfied; self.wifi = wifi; self.cellular = cellular; self.wired = wired; self.other = other
        }

        init(_ path: NWPath) {
            self.init(satisfied: path.status == .satisfied, wifi: path.usesInterfaceType(.wifi),
                      cellular: path.usesInterfaceType(.cellular), wired: path.usesInterfaceType(.wiredEthernet),
                      other: path.usesInterfaceType(.other))
        }
    }

    /// Is going from `old` to `new` worth trying the studio again? Only a change that leaves a way out (no point
    /// trying with no network), and not the first reading after launch (nothing has changed yet).
    nonisolated static func worthTrying(from old: Signature?, to new: Signature) -> Bool {
        guard let old else { return false }
        return new.satisfied && new != old
    }

    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let now = Signature(path)
            Task { @MainActor in self?.update(now) }
        }
        monitor.start(queue: DispatchQueue(label: "footscan.network-watch", qos: .utility))
    }

    deinit { monitor.cancel() }

    private func update(_ now: Signature) {
        defer { last = now }
        // gone again before it settled: nothing to try over
        if !now.satisfied { pending?.cancel(); pending = nil }
        guard Self.worthTrying(from: last, to: now) else { return }
        pending?.cancel()
        pending = Task {
            try? await Task.sleep(for: Self.settle)
            guard !Task.isCancelled else { return }
            changes += 1
        }
    }
}
