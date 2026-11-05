// Sending scans straight to the footscan studio on the Mac.
//
// Connecting: the studio (Import 3D page) shows a code holding
//   footscan-capture://connect?url=https://192.168.1.20:8765&key=…&fp=…
// Scan it in the app (or with the iPhone's Camera, which offers to open this
// app). `url` is where the studio answers, `key` opens it, and `fp` is the
// SHA-256 of the Mac's own HTTPS certificate. The Mac's certificate is
// self-made (no authority vouches for it), so instead of switching off the
// phone's checks the app pins it: it talks only to a server presenting
// exactly that certificate. A public studio's code (a real certificate, no
// `fp`, the phone's normal checks) is accepted by development builds only:
// see `StudioStore.acceptsPublicStudios`.
//
// The key is a password to the studio, so it is kept in the Keychain.
import CryptoKit
import Foundation
import Security

struct StudioLink: Codable, Equatable {
    var url: URL
    var fingerprint: String?

    var host: String { url.host() ?? url.absoluteString }
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
    /// certificate the code pins, at an address on the person's own network or Tailscale. A pin alone isn't
    /// enough: a hosted studio at a public address can pin a self-made certificate too.
    static func accepts(_ link: StudioLink, allowPublic: Bool = acceptsPublicStudios) -> Bool {
        allowPublic || (link.fingerprint != nil && isOwnNetwork(link.url))
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

    static func save(_ link: StudioLink, key: String) {
        UserDefaults.standard.set(try? JSONEncoder().encode(link), forKey: linkKey)
        writeKey(key)
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: linkKey)
        deleteKey()
    }

    static func deleteKey() {
        SecItemDelete([kSecClass: kSecClassGenericPassword, kSecAttrService: service] as CFDictionary)
    }

    /// Parse a connect code. Only https studios are accepted, and (``allowPublic`` false, as in the App Store
    /// build) only ones ``accepts(_:allowPublic:)`` allows: see ``acceptsPublicStudios``.
    static func parse(_ text: String, allowPublic: Bool = acceptsPublicStudios) -> (link: StudioLink, key: String)? {
        guard let comps = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              comps.scheme == "footscan-capture", comps.host == "connect" else { return nil }
        let q = Dictionary((comps.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        guard let urlText = q["url"], let url = URL(string: urlText), url.scheme == "https",
              let key = q["key"], !key.isEmpty else { return nil }
        let fp = q["fp"].flatMap { $0.isEmpty ? nil : $0.lowercased() }
        if let fp, fp.count != 64 || !fp.allSatisfy(\.isHexDigit) { return nil }
        let link = StudioLink(url: url, fingerprint: fp)
        guard accepts(link, allowPublic: allowPublic) else { return nil }
        return (link, key)
    }

    static func readKey() -> String? {
        var out: CFTypeRef?
        let q: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: service,
                                  kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne]
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func writeKey(_ key: String) {
        deleteKey()
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
        return got == fingerprint ? (.useCredential, URLCredential(trust: trust)) : (.cancelAuthenticationChallenge, nil) // not the Mac we paired with
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

    enum Failure: LocalizedError {
        /// `incomplete`: the studio found part of the foot missing (toes, heel) and didn't keep the scan;
        /// each line says what's missing and how to scan again.
        case refused(String), unreachable(host: String), incomplete([String])
        var errorDescription: String? {
            switch self {
            case .refused(let why): "The studio said no: \(why)"
            case .incomplete(let why): "Scan again: the studio didn't keep this scan. \(why.joined(separator: " "))"
            case .unreachable(let host):
                "The studio at \(host) isn't answering. Check Footscan is running on your Mac and both are on the same Wi-Fi. If your Mac's Wi-Fi address has changed, reconnect by scanning its code again."
            }
        }
        var isUnreachable: Bool { if case .unreachable = self { true } else { false } }

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
            throw Failure.unreachable(host: link.host)
        }
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw Failure.from(status: code, json: json) }
        return json
    }

    /// Is the studio there, and does it accept the key?
    func check(timeout: TimeInterval = 8) async throws {
        _ = try await send(request("api/studio"), timeout: timeout)
    }

    struct Sent { var captureID: String; var accuracy: StudioAccuracy? }

    /// Make a research capture for this scan and upload its model.
    func upload(_ scan: Scan, record: ScanRecord) async throws -> Sent {
        // A quick hello first: a studio that isn't there fails in seconds, not after a long upload timeout.
        try await check(timeout: 6)
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
        return Sent(captureID: id, accuracy: accuracy)
    }
}
