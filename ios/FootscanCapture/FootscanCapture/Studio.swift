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
// server presenting exactly that certificate. Through the public address (a
// real certificate) there is no `fp` and the phone's normal checks apply.
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
    private static let linkKey = "studio.link"
    private static let service = "footscan.studio"

    static func load() -> (link: StudioLink, key: String)? {
        guard let data = UserDefaults.standard.data(forKey: linkKey),
              let link = try? JSONDecoder().decode(StudioLink.self, from: data),
              let key = readKey() else { return nil }
        return (link, key)
    }

    static func save(_ link: StudioLink, key: String) {
        UserDefaults.standard.set(try? JSONEncoder().encode(link), forKey: linkKey)
        writeKey(key)
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: linkKey)
        SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: service] as CFDictionary)
    }

    /// Parse a connect code. Only https studios are accepted, at every address.
    static func parse(_ text: String) -> (link: StudioLink, key: String)? {
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
            if alt != url && !alternates.contains(alt) { alternates.append(alt) }
        }
        return (StudioLink(url: url, fingerprint: fp, alternates: alternates), key)
    }

    private static func readKey() -> String? {
        var out: CFTypeRef?
        let q: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: service,
                                  kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne]
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func writeKey(_ key: String) {
        SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: service] as CFDictionary)
        SecItemAdd([kSecClass: kSecClassGenericPassword, kSecAttrService: service,
                    kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                    kSecValueData: Data(key.utf8)] as CFDictionary, nil)
    }
}

/// Trusts exactly the pinned certificate (when there is one); otherwise the phone's normal checks.
final class PinnedTrust: NSObject, URLSessionDelegate {
    let fingerprint: String?
    init(fingerprint: String?) { self.fingerprint = fingerprint }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        let (disposition, credential) = Self.decide(challenge, fingerprint: fingerprint)
        completionHandler(disposition, credential)
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

        init(_ error: Error) {
            switch (error as? URLError)?.code {
            // .cancelled: the pin cancels the challenge when the certificate differs
            // (.secureConnectionFailed is a TLS set-up failure, not a certificate: it counts as no answer)
            case .cancelled?, .serverCertificateUntrusted?, .serverCertificateHasBadDate?, .serverCertificateHasUnknownRoot?,
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
        /// each line says what's missing and how to scan again.
        /// `unreachable`: none of the studio's addresses answered as the studio, in the order they were tried.
        /// `dropped`: the studio answered, then the connection failed partway through sending.
        case refused(String), unreachable([Missed], pinned: Bool), incomplete([String]), dropped(host: String)
        var errorDescription: String? {
            switch self {
            case .refused(let why): "The studio said no: \(why)"
            case .incomplete(let why): "Scan again: the studio didn't keep this scan. \(why.joined(separator: " "))"
            case .unreachable(let misses, let pinned): Self.explain(misses, pinned: pinned)
            case .dropped(let host): "The connection to the studio at \(host) dropped partway through sending. Try again; the scan is still on this phone."
            }
        }
        /// Worth sending again once the studio is back (waiting scans go then).
        var isUnreachable: Bool {
            switch self {
            case .unreachable, .dropped: true
            default: false
            }
        }

        /// What each address needs, in plain words: away from home the home-network address can't answer,
        /// the Tailscale one needs Tailscale on, and a different certificate means a different server.
        static func explain(_ misses: [Missed], pinned: Bool) -> String {
            var lines: [String] = []
            for m in misses {
                let host = StudioLink.host(of: m.address)
                switch (m.miss, StudioAddressKind(host: host)) {
                case (.wrongCertificate, _):
                    lines.append(pinned
                        ? "Something answered at \(host), but it isn't the studio this phone connected to (its certificate is different). If the studio was set up again, show its connect code and scan it again."
                        : "\(host) answered, but its certificate isn't one this phone trusts.")
                case (_, .homeNetwork):
                    lines.append("\(host) is the studio's home-network address: it only answers while this phone is on the same Wi-Fi as the studio computer.")
                case (_, .tailscale):
                    lines.append("\(host) is the studio's Tailscale address: it answers from anywhere while Tailscale is on, on this phone and on the studio computer.")
                case (_, .other):
                    lines.append("Nothing answered at \(host).")
                }
            }
            if misses.contains(where: { $0.miss == .noRoute && StudioAddressKind(host: StudioLink.host(of: $0.address)) == .homeNetwork }) {
                lines.append("If the phone just asked to find devices on your local network, tap Allow and test again (Settings > Privacy & Security > Local Network).")
            }
            guard misses.contains(where: { $0.miss != .wrongCertificate }) else {
                return lines.joined(separator: " ") // something did answer: "isn't answering" would mislead
            }
            lines.append("Check Footscan is running on the studio computer.")
            return (["The studio isn't answering."] + lines).joined(separator: " ")
        }

        /// What a refusal (an answer outside 200-299) means, from the studio's JSON answer.
        static func from(status: Int, json: [String: Any]) -> Failure {
            if let missing = json["incomplete"] as? [String], !missing.isEmpty { return .incomplete(missing) }
            return .refused(json["error"] as? String ?? "HTTP \(status)")
        }
    }

    private func session(timeout: TimeInterval = 20) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.waitsForConnectivity = false
        return URLSession(configuration: config, delegate: PinnedTrust(fingerprint: link.fingerprint), delegateQueue: nil)
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
        let s = session(timeout: timeout)
        defer { s.finishTasksAndInvalidate() }
        let data: Data, response: URLResponse
        do {
            (data, response) = try await s.data(for: req)
        } catch {
            // a cancelled task also ends with URLError.cancelled: that isn't a wrong certificate
            if Task.isCancelled { throw CancellationError() }
            throw Failure.unreachable([Missed(address: link.url, miss: Miss(error))], pinned: link.fingerprint != nil)
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

    /// Which of the studio's addresses answers now, with the key accepted? Every address is tried at once, so
    /// one that can't answer from here (the home-network address, away from home) costs no extra wait. Returns
    /// a client for the first that answers; if none does, says why for each.
    func reach(timeout: TimeInterval = 8) async throws -> StudioClient {
        let addresses = link.addresses
        return try await withThrowingTaskGroup(of: StudioClient.self) { group in
            for address in addresses {
                let client = StudioClient(link: link.using(address), key: key)
                group.addTask { try await client.hello(timeout: timeout); return client }
            }
            var misses: [Missed] = []
            var refusal: Error?
            while !group.isEmpty {
                do {
                    if let client = try await group.next() {
                        group.cancelAll()
                        return client
                    }
                } catch Failure.unreachable(let missed, _) {
                    misses += missed
                } catch {
                    refusal = refusal ?? error // the studio answered but said no (a wrong key): that's the answer
                }
            }
            if let refusal { throw refusal }
            misses.sort { (addresses.firstIndex(of: $0.address) ?? 0) < (addresses.firstIndex(of: $1.address) ?? 0) }
            throw Failure.unreachable(misses, pinned: link.fingerprint != nil)
        }
    }

    /// `link`: the studio, with the address the scan went to as the one in use.
    struct Sent { var captureID: String; var accuracy: StudioAccuracy?; var link: StudioLink }

    /// Make a research capture for this scan and upload its model, at whichever address answers.
    func upload(_ scan: Scan, record: ScanRecord) async throws -> Sent {
        // A quick hello first: a studio that isn't there fails in seconds, not after a long upload timeout.
        let here = try await reach(timeout: 6)
        do {
            return try await here.uploadHere(scan, record: record)
        } catch Failure.unreachable {
            throw Failure.dropped(host: here.link.host) // it answered the hello: not a question of which Wi-Fi
        }
    }

    private func uploadHere(_ scan: Scan, record: ScanRecord) async throws -> Sent {
        let (condition, foot) = record.subject.studioCondition
        var setup: [String: Any] = [
            "condition": condition, "session": "LIDAR", "method": "imported_mesh",
            "device": "\(record.device), iOS \(record.systemVersion)",
            "notes": "Footscan iPhone app \(record.appVersion), Apple Object Capture, \(record.shotsTaken ?? 0) photos, "
                + "\(record.scanPasses ?? 1) lap(s), model built on the phone",
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
