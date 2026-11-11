// Sending scans straight to the footscan studio on your computer (a Mac, or
// a Windows PC left on all the time).
//
// Connecting: the studio (Import 3D page) shows a code holding
//   footscan-capture://connect?url=https://192.168.1.20:8765&key=…&fp=…[&alt=https://100.x.y.z:8765]
// Scan it in the app (or with the iPhone's Camera, which offers to open this
// app). `url` is where the studio answers on its home network, `key` opens
// it, and `fp` is the SHA-256 of the computer's own HTTPS certificate. That
// certificate is self-made (no authority vouches for it), so instead of
// switching off the phone's checks the app pins it: it talks only to a
// server presenting exactly that certificate. A public studio's code (a real
// certificate, no `fp`, the phone's normal checks) is accepted by development
// builds only: see `StudioStore.acceptsPublicStudios`.
//
// `alt` (repeatable) is another address of the same studio, such as its
// Tailscale address, which answers away from home. The app tries every
// address at once and uses the first that answers, under the same pin.
// They are IP addresses: Apple's App Transport Security lets the app accept
// a self-made certificate only at IP and local addresses.
//
// The key is a password to the studio, so it is kept in the Keychain.
import CryptoKit
import Foundation
import Security

struct StudioLink: Codable, Equatable {
    /// The address the studio answered at last; the one tried first is no better than the others.
    var url: URL
    var fingerprint: String?
    /// The same studio's other addresses (its Tailscale address, say), checked against the same fingerprint.
    var alternates: [URL] = []

    var host: String { Self.host(of: url) }
    var addresses: [URL] { [url] + alternates }

    /// The same studio, with `address` as the one in use (it's the one that answered).
    func using(_ address: URL) -> StudioLink {
        var link = self
        link.url = address
        link.alternates = addresses.filter { $0 != address }
        return link
    }

    static func host(of url: URL) -> String { url.host() ?? url.absoluteString }
}

extension StudioLink {
    // A link saved before studios had more than one address has no "alternates".
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(URL.self, forKey: .url)
        fingerprint = try c.decodeIfPresent(String.self, forKey: .fingerprint)
        alternates = try c.decodeIfPresent([URL].self, forKey: .alternates) ?? []
    }
}

/// What kind of address a studio address is, so a failed test can say what it needs.
enum StudioAddressKind: Equatable {
    /// 192.168.x.x and the like: answers only on the studio computer's own network.
    case homeNetwork
    /// 100.64.0.0/10 (or a .ts.net name): answers from anywhere while Tailscale is on, here and there.
    case tailscale
    case other

    /// How the address is reached, in the words the app uses everywhere: "home Wi-Fi", "Tailscale".
    var label: String? {
        switch self {
        case .homeNetwork: "home Wi-Fi"
        case .tailscale: "Tailscale"
        case .other: nil
        }
    }

    init(host: String) {
        let h = host.lowercased()
        let parts = h.split(separator: ".", omittingEmptySubsequences: false)
        let octets = parts.compactMap { UInt8($0) }
        if parts.count == 4, octets.count == 4 {
            switch (octets[0], octets[1]) {
            case (100, 64...127): self = .tailscale
            case (10, _), (192, 168), (169, 254), (172, 16...31): self = .homeNetwork
            default: self = .other
            }
        } else if h.hasSuffix(".ts.net") || h.hasPrefix("fd7a:115c:a1e0:") {
            self = .tailscale
        } else if h.hasSuffix(".local") || (h.contains(":") && (h.hasPrefix("fd") || h.hasPrefix("fc") || h.hasPrefix("fe80:"))) {
            self = .homeNetwork
        } else {
            self = .other
        }
    }
}

enum StudioStore {
    static let linkKey = "studio.link"
    private static let service = "footscan.studio"

    /// Studios at a public internet address (a real certificate, no fingerprint in the code) are someone else's
    /// server, possibly the developer's own hosted studio: scans sent there would be data the developer
    /// collects, which the privacy manifest and policy say never happens. So the App Store build pairs only
    /// with a studio on a computer the person runs, whose own certificate the code pins, at an address on
    /// their home network or Tailscale; development builds still accept public addresses, for the developer's
    /// own testing.
    #if DEBUG
    static let acceptsPublicStudios = true
    #else
    static let acceptsPublicStudios = false
    #endif

    /// Is this a studio this build may send scans to? With ``allowPublic`` false (the App Store build): one whose
    /// certificate the code pins, with every address it is tried at on the person's own network or Tailscale
    /// (the key goes to each). A pin alone isn't enough: a hosted studio at a public address can pin a
    /// self-made certificate too.
    static func accepts(_ link: StudioLink, allowPublic: Bool = acceptsPublicStudios) -> Bool {
        allowPublic || (link.fingerprint != nil && link.addresses.allSatisfy(isOwnNetwork))
    }

    /// An address only the person's own network or Tailscale reaches: a private or link-local IP (10/8,
    /// 172.16/12, 192.168/16, 169.254/16, IPv6 fc00::/7 and fe80::/10), Tailscale's 100.64/10, or a .local name.
    static func isOwnNetwork(_ url: URL) -> Bool {
        guard var host = url.host()?.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "[]")) else { return false }
        if host.hasSuffix(".") { host.removeLast() } // "mac.local." is "mac.local"
        if host.hasPrefix("::ffff:") { // an IPv4 address written as IPv6: ::ffff:192.168.1.5, or ::ffff:c0a8:105
            host.removeFirst(7)
            let g = host.split(separator: ":").compactMap { UInt16($0, radix: 16) }
            if g.count == 2 { host = "\(g[0] >> 8).\(g[0] & 0xff).\(g[1] >> 8).\(g[1] & 0xff)" }
        }
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        let octets = parts.compactMap { UInt8($0) }
        if parts.count == 4, octets.count == 4 {
            switch (octets[0], octets[1]) {
            case (10, _), (192, 168), (169, 254), (172, 16...31), (100, 64...127): return true
            default: return false
            }
        }
        if host.contains(":") {
            // the first 16 bits, as a number (leading zeros may be left out: "fd::1" is 00fd::1)
            guard let first = host.split(separator: ":", omittingEmptySubsequences: false).first,
                  !first.isEmpty, let group = UInt16(first, radix: 16) else { return false }
            return group & 0xfe00 == 0xfc00 || group & 0xffc0 == 0xfe80 // fc00::/7 unique-local, fe80::/10 link-local
        }
        return host.hasSuffix(".local")
    }

    /// The saved studio and its key, or nil. Reads only. A studio this build doesn't accept (a public one saved
    /// by a development build, which the App Store build updated in place keeps) isn't used: the launch-time
    /// cleanup, ``removeLeftoverKey()``, removes it.
    static func load(allowPublic: Bool = acceptsPublicStudios) -> (link: StudioLink, key: String)? {
        guard let data = UserDefaults.standard.data(forKey: linkKey),
              let link = try? JSONDecoder().decode(StudioLink.self, from: data),
              accepts(link, allowPublic: allowPublic),
              let key = readKey() else { return nil }
        return (link, key)
    }

    /// Run once at launch. iOS keeps Keychain items after the app is deleted, but not its settings, so a key
    /// with no studio address is left from an earlier install (or a cut-off clear()): delete it, so a deleted
    /// app's studio password is gone the next time the app is installed and opened (the privacy policy,
    /// docs/PRIVACY.md, says so; Disconnect before deleting removes it at once). Only when the key can be read:
    /// before the phone's first unlock after a restart the settings can read as empty too, and the key is
    /// unreadable then, so a real pairing is never thrown away. A saved studio this build won't use (see
    /// ``load(allowPublic:)``) goes too, address and key: the app shows "Not connected" with no Disconnect
    /// for it, and its key would otherwise stay on the phone for good.
    static func removeLeftoverKey(allowPublic: Bool = acceptsPublicStudios) {
        if let data = UserDefaults.standard.data(forKey: linkKey) {
            // one that no longer reads (another build's format, or damaged) can't be used or disconnected either
            let link = try? JSONDecoder().decode(StudioLink.self, from: data)
            if link.map({ !accepts($0, allowPublic: allowPublic) }) ?? true {
                clear()
                return
            }
        }
        guard UserDefaults.standard.data(forKey: linkKey) == nil, readKey() != nil else { return }
        deleteKey()
    }

    /// false when the key couldn't be kept in the Keychain: then nothing is saved (a link with the old studio's
    /// key would be refused on every send, after saying "Connected").
    @discardableResult
    static func save(_ link: StudioLink, key: String) -> Bool {
        guard writeKey(key) else { return false }
        saveLink(link)
        return true
    }

    /// The studio's addresses (which to try first) without touching its key in the Keychain.
    static func saveLink(_ link: StudioLink) {
        UserDefaults.standard.set(try? JSONEncoder().encode(link), forKey: linkKey)
    }

    /// Forget the studio: its key first, then its address. false when the Keychain wouldn't delete the key:
    /// then the address stays too, so the studio still shows with its Disconnect button to try again (with the
    /// address gone and the key kept, nothing on screen would say a password is still on the phone).
    @discardableResult
    static func clear() -> Bool {
        guard deleteKey() else { return false }
        UserDefaults.standard.removeObject(forKey: linkKey)
        return true
    }

    /// true when no studio key is left in the Keychain (deleted now, or there was none).
    @discardableResult
    static func deleteKey() -> Bool {
        let status = SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: service] as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }

    /// Parse a connect code. Only https studios are accepted, at every address, and (``allowPublic`` false, as
    /// in the App Store build) only ones ``accepts(_:allowPublic:)`` allows: see ``acceptsPublicStudios``.
    /// That build drops an alternate address outside the person's own network, and keeps the rest.
    static func parse(_ text: String, allowPublic: Bool = acceptsPublicStudios) -> (link: StudioLink, key: String)? {
        guard let comps = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              comps.scheme == "footscan-capture", comps.host == "connect" else { return nil }
        let items = comps.queryItems ?? []
        let q = Dictionary(items.map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        guard let urlText = q["url"], let url = URL(string: urlText), url.scheme == "https",
              let key = q["key"], !key.isEmpty else { return nil }
        let fp = q["fp"].flatMap { $0.isEmpty ? nil : $0.lowercased() }
        if let fp, fp.count != 64 || !fp.allSatisfy(\.isHexDigit) { return nil }
        var alternates: [URL] = []
        for item in items where item.name == "alt" {
            // one address in the clear would send the key in the clear: refuse the whole code
            guard let text = item.value, let alt = URL(string: text), alt.scheme == "https", alt.host() != nil else { return nil }
            // the same studio address written another way (a trailing slash, capitals) is the same address
            if !([url] + alternates).contains(where: { sameAddress($0, alt) }) { alternates.append(alt) }
        }
        // Every address is tried at once with the key. Without a pinned certificate, any host with a trusted
        // certificate could be named as an "alternate" and be sent the key: only the address the code names.
        if fp == nil { alternates = [] }
        // the App Store build sends the key only within the person's own network or Tailscale
        if !allowPublic { alternates = alternates.filter(isOwnNetwork) }
        let link = StudioLink(url: url, fingerprint: fp, alternates: alternates)
        guard accepts(link, allowPublic: allowPublic) else { return nil }
        return (link, key)
    }

    /// Same host (any case) and port: the same address of the studio, however the URL is written.
    static func sameAddress(_ a: URL, _ b: URL) -> Bool {
        a.host()?.lowercased() == b.host()?.lowercased() && (a.port ?? 443) == (b.port ?? 443)
    }

    static func readKey() -> String? {
        var out: CFTypeRef?
        let q: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: service,
                                  kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne]
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Changed in place when there is one (never a moment with no key, which a delete-then-add has: an app
    /// stopped between the two would come back "Not connected"); added when there isn't.
    /// Any other failure to change it (an item an older build wrote with other attributes) falls back to
    /// replacing it. -> whether the Keychain now holds this key.
    @discardableResult
    static func writeKey(_ key: String) -> Bool {
        let match = [kSecClass: kSecClassGenericPassword, kSecAttrService: service] as CFDictionary
        let update = [kSecValueData: Data(key.utf8),
                      kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly] as CFDictionary
        let updated = SecItemUpdate(match, update)
        if updated == errSecSuccess { return true }
        if updated != errSecItemNotFound { SecItemDelete(match) }
        return SecItemAdd([kSecClass: kSecClassGenericPassword, kSecAttrService: service,
                           kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                           kSecValueData: Data(key.utf8)] as CFDictionary, nil) == errSecSuccess
    }
}

/// Trusts exactly the pinned certificate (when there is one); otherwise the phone's normal checks.
final class PinnedTrust: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    let fingerprint: String?
    init(fingerprint: String?) { self.fingerprint = fingerprint }

    private let lock = NSLock()
    private var refused = false
    /// Did this session turn a server's certificate away (it isn't the pinned one)? Then a failed request was
    /// a wrong certificate, said for certain, not guessed from the error it ended with.
    var refusedCertificate: Bool { lock.withLock { refused } }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        let (disposition, credential) = Self.decide(challenge, fingerprint: fingerprint)
        if disposition == .cancelAuthenticationChallenge { lock.withLock { refused = true } }
        completionHandler(disposition, credential)
    }

    /// Never follow a redirect. The studio never sends one, and following it would carry the key and the scan
    /// to whatever address it names, past the own-network rule (``StudioStore/accepts(_:allowPublic:)``) that
    /// the privacy policy promises. The 3xx answer comes back as the answer instead, and is reported as a refusal.
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    /// The pinning rule, shared by uploads and the in-app capture page.
    static func decide(_ challenge: URLAuthenticationChallenge, fingerprint: String?)
        -> (URLSession.AuthChallengeDisposition, URLCredential?) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust else {
            return (.performDefaultHandling, nil)
        }
        guard let fingerprint else { return (.performDefaultHandling, nil) }
        guard let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let leaf = chain.first else {
            return (.cancelAuthenticationChallenge, nil)
        }
        let der = SecCertificateCopyData(leaf) as Data
        let got = SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
        return got == fingerprint ? (.useCredential, URLCredential(trust: trust)) : (.cancelAuthenticationChallenge, nil) // not the studio we paired with
    }
}

/// What the studio answers about an imported calibration object.
struct StudioAccuracy: Codable, Equatable {
    var median_mm: Double?
    var p95_mm: Double?
    var signed_mean_mm: Double?
    var within_1mm: Double?
    var length_mm: Double?
    var width_mm: Double?
    var dome_apex_mm: Double?
    var reference: String?
    var error: String?
}

struct StudioClient {
    let link: StudioLink
    let key: String

    /// Why one address gave no answer from the studio.
    enum Miss: Equatable {
        /// Something answered, but not with the studio's certificate (the pin didn't match, or a public
        /// address's certificate isn't trusted).
        case wrongCertificate
        /// The phone has no way there: no connection at all, or (at a home-network address) the app isn't
        /// allowed onto the local network.
        case noRoute
        /// Nothing answered in time, or the computer turned the connection away (Footscan not running).
        case noAnswer

        /// `pinRefused`: the pin itself turned the certificate away (PinnedTrust.refusedCertificate), which is
        /// known for certain; the request then ends as "cancelled", which alone could be anything.
        init(_ error: Error, pinRefused: Bool = false) {
            if pinRefused { self = .wrongCertificate; return }
            switch (error as? URLError)?.code {
            // the phone's own checks, for a studio with no pinned certificate
            // (.secureConnectionFailed is a TLS set-up failure, not a certificate: it counts as no answer)
            case .serverCertificateUntrusted?, .serverCertificateHasBadDate?, .serverCertificateHasUnknownRoot?,
                 .serverCertificateNotYetValid?: self = .wrongCertificate
            case .notConnectedToInternet?, .dataNotAllowed?, .internationalRoamingOff?: self = .noRoute
            default: self = .noAnswer
            }
        }
    }

    struct Missed: Equatable {
        var address: URL
        var miss: Miss
    }

    enum Failure: LocalizedError {
        /// `incomplete`: the studio found part of the foot missing (toes, heel) and didn't keep the scan;
        /// each line says what's missing and how to scan again, and `advice` what to change, step by step
        /// (empty from a studio that doesn't send it).
        /// `unreachable`: none of the studio's addresses answered as the studio, in the order they were tried.
        /// `dropped`: the studio answered, then the connection failed partway through sending.
        case refused(String), unreachable([Missed], pinned: Bool), incomplete([String], advice: [RetakeAdvice]),
             dropped(host: String)
        var errorDescription: String? {
            switch self {
            case .refused(let why): "The studio said no: \(why)"
            case .incomplete(let why, _): "Scan again: the studio didn't keep this scan. \(why.joined(separator: " "))"
            case .unreachable(let misses, let pinned): Self.explain(misses, pinned: pinned)
            case .dropped(let host): "The connection to the studio at \(host) dropped partway through sending. Try again; the scan is still on this \(DeviceKind.current.noun)."
            }
        }
        /// Worth sending again once the studio is back (waiting scans go then).
        var isUnreachable: Bool {
            switch self {
            case .unreachable, .dropped: true
            default: false
            }
        }

        /// Worth offering "Reconnect to the studio" (scan its code again): no address answered. Not after a
        /// drop mid-send, as the studio did answer: trying again is all it needs.
        var offersReconnect: Bool {
            if case .unreachable = self { return true }
            return false
        }

        /// What each address needs, in plain words: away from home the home-network address can't answer,
        /// the Tailscale one needs Tailscale on, and a different certificate means a different server.
        /// `device`: whose connection it is, for the words ("this iPad" on an iPad).
        static func explain(_ misses: [Missed], pinned: Bool, device: DeviceKind = .current) -> String {
            guard !misses.isEmpty else { // no address was tried: still say something to do
                return "The studio isn't answering. Check Footscan is running on the studio computer, then show its connect code and scan it again."
            }
            var lines: [String] = []
            for m in misses {
                let host = StudioLink.host(of: m.address)
                switch (m.miss, StudioAddressKind(host: host)) {
                case (.wrongCertificate, .homeNetwork) where pinned:
                    // another Wi-Fi (a café's, a friend's) often uses the same private addresses: something
                    // else there answers at the studio's home address
                    lines.append("Something else answered at \(host), the studio's \(StudioAddressKind.homeNetwork.label!) address: this \(device.noun) is probably on another Wi-Fi that uses the same addresses. The studio only answers there on the same Wi-Fi as the studio computer. If this \(device.noun) is on that Wi-Fi, the studio was set up again: show its connect code and scan it again.")
                case (.wrongCertificate, _):
                    lines.append(pinned
                        ? "Something answered at \(host), but it isn't the studio this \(device.noun) connected to (its certificate is different). If the studio was set up again, show its connect code and scan it again."
                        : "\(host) answered, but its certificate isn't one this \(device.noun) trusts.")
                case (_, .homeNetwork):
                    lines.append("\(host) is the studio's \(StudioAddressKind.homeNetwork.label!) address: it only answers while this \(device.noun) is on the same Wi-Fi as the studio computer.")
                case (.noRoute, .tailscale):
                    lines.append("\(host) is the studio's \(StudioAddressKind.tailscale.label!) address, but this \(device.noun) has no connection to reach it right now.")
                case (_, .tailscale):
                    lines.append("\(host) is the studio's \(StudioAddressKind.tailscale.label!) address: it answers from anywhere while Tailscale is on, on this \(device.noun) and on the studio computer.")
                case (.noRoute, .other):
                    lines.append("This \(device.noun) has no connection to reach \(host) right now.")
                case (_, .other):
                    lines.append("Nothing answered at \(host).")
                }
            }
            let noRouteAnywhere = !misses.isEmpty && misses.allSatisfy({ $0.miss == .noRoute })
            if noRouteAnywhere {
                // the phone's own connection: every address fails this way abroad with Data Roaming off, in
                // Airplane Mode, or with Mobile Data switched off for this app. (Only the home address failing
                // so may be Local Network access, below.)
                lines.append("Check this \(device.noun)'s own connection: Airplane Mode off, Wi-Fi or mobile data on, Data Roaming on if you're abroad, and mobile data allowed for Footscan (Settings > Cellular).")
            }
            // Local Network access stops only the home address. When an address elsewhere had no route either,
            // it's the phone's own connection, and asking about Local Network would send them the wrong way.
            let elsewhereNoRoute = misses.contains(where: { $0.miss == .noRoute && StudioAddressKind(host: StudioLink.host(of: $0.address)) != .homeNetwork })
            if !elsewhereNoRoute && misses.contains(where: { $0.miss == .noRoute && StudioAddressKind(host: StudioLink.host(of: $0.address)) == .homeNetwork }) {
                lines.append("If the \(device.noun) just asked to find devices on your local network, tap Allow and test again (Settings > Privacy & Security > Local Network).")
            }
            if misses.contains(where: { $0.miss == .noAnswer && StudioAddressKind(host: StudioLink.host(of: $0.address)) == .homeNetwork }) {
                // routers hand out new addresses: the code the phone scanned may name the studio's old one
                lines.append("If the studio computer's Wi-Fi address has changed, show its connect code and scan it again.")
            }
            guard misses.contains(where: { $0.miss != .wrongCertificate }) else {
                return lines.joined(separator: " ") // something did answer: "isn't answering" would mislead
            }
            lines.append("Check Footscan is running on the studio computer.")
            return (["The studio isn't answering."] + lines).joined(separator: " ")
        }

        /// What a refusal (an answer outside 200-299) means, from the studio's JSON answer.
        static func from(status: Int, json: [String: Any]) -> Failure {
            if let missing = json["incomplete"] as? [String], !missing.isEmpty {
                let advice = json["retake"].flatMap { JSONSerialization.isValidJSONObject($0) ? $0 : nil }
                    .flatMap { try? JSONSerialization.data(withJSONObject: $0) }
                    .flatMap { try? JSONDecoder().decode([RetakeAdvice].self, from: $0) }
                return .incomplete(missing, advice: advice ?? [])
            }
            return .refused(json["error"] as? String ?? "HTTP \(status)")
        }
    }

    private func session(timeout: TimeInterval = 20) -> (URLSession, PinnedTrust) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.waitsForConnectivity = false
        let trust = PinnedTrust(fingerprint: link.fingerprint)
        return (URLSession(configuration: config, delegate: trust, delegateQueue: nil), trust)
    }

    private func request(_ path: String, method: String = "GET", query: [URLQueryItem] = [], body: Data? = nil,
                         contentType: String = "application/json") -> URLRequest {
        var comps = URLComponents(url: link.url.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { comps.queryItems = query }
        var req = URLRequest(url: comps.url!)
        req.httpMethod = method
        req.setValue(key, forHTTPHeaderField: "X-Studio-Key")
        if let body {
            req.httpBody = body
            req.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        return req
    }

    private func send(_ req: URLRequest, timeout: TimeInterval = 20) async throws -> [String: Any] {
        let (s, trust) = session(timeout: timeout)
        defer { s.finishTasksAndInvalidate() }
        let data: Data, response: URLResponse
        do {
            (data, response) = try await s.data(for: req)
        } catch {
            if Task.isCancelled { throw CancellationError() } // another address answered first: not a miss
            throw Failure.unreachable([Missed(address: link.url, miss: Miss(error, pinRefused: trust.refusedCertificate))],
                                      pinned: link.fingerprint != nil)
        }
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw Failure.from(status: code, json: json) }
        return json
    }

    /// Is the studio there at this client's address, and does it accept the key?
    private func hello(timeout: TimeInterval) async throws {
        _ = try await send(request("api/studio"), timeout: timeout)
    }

    /// How long a home-network address is waited for after another address answered first: at home it
    /// answers within a moment, and then it's the better way (straight over the Wi-Fi, where a Tailscale
    /// path may go round through a relay).
    static let homeGrace: Duration = .seconds(1)

    /// Which of the studio's addresses answers now, with the key accepted? Every address is tried at once, so
    /// one that can't answer from here (the home-network address, away from home) costs no extra wait. Returns
    /// a client for the home-network address if it answers, else for the first that does (waiting at most
    /// `homeGrace` for the home address once another has answered); if none does, says why for each.
    func reach(timeout: TimeInterval = 8) async throws -> StudioClient {
        let addresses = link.addresses
        let home = addresses.filter { StudioAddressKind(host: StudioLink.host(of: $0)) == .homeNetwork }
        return try await withThrowingTaskGroup(of: StudioClient?.self) { group in
            for address in addresses {
                let client = StudioClient(link: link.using(address), key: key)
                group.addTask { try await client.hello(timeout: timeout); return client }
            }
            var misses: [Missed] = []
            var answered: StudioClient?
            var homeWaiting = home.count  // home addresses not heard from yet
            while !group.isEmpty {
                do {
                    guard let result = try await group.next() else { break }
                    guard let client = result else { break }  // the grace time ran out: the first answer it is
                    let isHome = home.contains(client.link.url)
                    if isHome || homeWaiting == 0 {
                        group.cancelAll()
                        return client
                    }
                    if answered == nil {
                        answered = client
                        group.addTask { try? await Task.sleep(for: Self.homeGrace); return nil }
                    }
                } catch Failure.unreachable(let missed, _) {
                    homeWaiting -= missed.filter { home.contains($0.address) }.count
                    misses += missed
                    if let answered, homeWaiting == 0 {
                        group.cancelAll()
                        return answered
                    }
                } catch {
                    // the studio answered but said no (a wrong key): that's the answer, now, without waiting
                    // for the other addresses to time out (unless another address already let us in)
                    group.cancelAll()
                    if let answered { return answered }
                    throw error
                }
            }
            group.cancelAll()
            if let answered { return answered }
            misses.sort { (addresses.firstIndex(of: $0.address) ?? 0) < (addresses.firstIndex(of: $1.address) ?? 0) }
            throw Failure.unreachable(misses, pinned: link.fingerprint != nil)
        }
    }

    /// `link`: the studio, with the address the scan went to as the one in use.
    struct Sent { var captureID: String; var accuracy: StudioAccuracy?; var link: StudioLink }

    /// Make a research capture for this scan and upload its model, at whichever address answers.
    func upload(_ scan: Scan, record: ScanRecord) async throws -> Sent {
        // A quick hello first: a studio that isn't there fails in seconds, not after a long upload timeout.
        let here: StudioClient
        do {
            here = try await reach(timeout: 6)
        } catch is CancellationError {
            // stopped during the hello (the system ending background time): the scan waits to go again
            throw Failure.dropped(host: link.host)
        }
        do {
            return try await here.uploadHere(scan, record: record)
        } catch Failure.unreachable {
            throw Failure.dropped(host: here.link.host) // it answered the hello: not a question of which Wi-Fi
        } catch is CancellationError {
            // the send itself was stopped (the system ending background time): the scan waits to go again
            throw Failure.dropped(host: here.link.host)
        }
    }

    private func uploadHere(_ scan: Scan, record: ScanRecord) async throws -> Sent {
        let (condition, foot) = record.subject.studioCondition
        var setup: [String: Any] = [
            "condition": condition, "session": "LIDAR", "method": "imported_mesh",
            "device": "\(record.device), iOS \(record.systemVersion)",
            "notes": "Footscan \(DeviceKind.current.model) app \(record.appVersion), Apple Object Capture, \(record.shotsTaken ?? 0) photos, "
                + "\(record.scanPasses ?? 1) lap(s), model built on the \(DeviceKind.current.noun)",
        ]
        if let foot { setup["foot"] = foot }
        if let kind = record.subject.scanKind { setup["scan_kind"] = kind }
        if let load = record.loadKg { setup["load_kg"] = load }
        let created = try await send(request("api/captures", method: "POST",
                                             body: try JSONSerialization.data(withJSONObject: setup)))
        guard let id = created["id"] as? String else { throw Failure.refused("no capture id came back") }
        let obj = try Data(contentsOf: scan.obj)
        let answer = try await send(request("api/captures/\(id)/mesh", method: "PUT",
                                            query: [URLQueryItem(name: "ext", value: "obj"), URLQueryItem(name: "up", value: "y")],
                                            body: obj, contentType: "application/octet-stream"),
                                    timeout: 180) // the calibration object is scored before the answer comes back
        var accuracy: StudioAccuracy?
        if let acc = answer["accuracy"], !(acc is NSNull),
           let data = try? JSONSerialization.data(withJSONObject: acc) {
            accuracy = try? JSONDecoder().decode(StudioAccuracy.self, from: data)
        }
        return Sent(captureID: id, accuracy: accuracy, link: link)
    }
}
