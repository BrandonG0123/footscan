// Sending scans straight to the footscan studio on the Mac.
//
// Connecting: the studio (Import 3D page) shows a code holding
//   footscan-capture://connect?url=https://192.168.1.20:8765&key=…&fp=…
// Scan it in the app (or with the iPhone's Camera, which offers to open this
// app). `url` is where the studio answers, `key` opens it, and `fp` is the
// SHA-256 of the Mac's own HTTPS certificate. The Mac's certificate is
// self-made (no authority vouches for it), so instead of switching off the
// phone's checks the app pins it: it talks only to a server presenting
// exactly that certificate. Through the public address (a real certificate)
// there is no `fp` and the phone's normal checks apply.
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

    /// Parse a connect code. Only https studios are accepted.
    static func parse(_ text: String) -> (link: StudioLink, key: String)? {
        guard let comps = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              comps.scheme == "footscan-capture", comps.host == "connect" else { return nil }
        let q = Dictionary((comps.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        guard let urlText = q["url"], let url = URL(string: urlText), url.scheme == "https",
              let key = q["key"], !key.isEmpty else { return nil }
        let fp = q["fp"].flatMap { $0.isEmpty ? nil : $0.lowercased() }
        if let fp, fp.count != 64 || !fp.allSatisfy(\.isHexDigit) { return nil }
        return (StudioLink(url: url, fingerprint: fp), key)
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
