// Tests for the iPhone app's own logic: the parts that don't need a camera.
// Run: xcodebuild test -project FootscanCapture.xcodeproj -scheme FootscanCapture
//      -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
import AVFoundation
import CoreImage
import Foundation
import RealityKit
import Testing
import UIKit
import WebKit
@testable import FootscanCapture

// MARK: - studio connect codes

@Suite("Studio connect codes")
struct ConnectCodes {
    let fp = String(repeating: "ab", count: 32) // 64 hex characters

    @Test func aGoodCodeIsRead() throws {
        let code = "footscan-capture://connect?url=https://192.168.1.20:8765&key=secret-key&fp=\(fp.uppercased())"
        let parsed = try #require(StudioStore.parse(code))
        #expect(parsed.link.url.absoluteString == "https://192.168.1.20:8765")
        #expect(parsed.link.host == "192.168.1.20")
        #expect(parsed.key == "secret-key")
        #expect(parsed.link.fingerprint == fp) // stored lower-case, so it matches the computed hash
    }

    @Test func aPublicAddressNeedsNoFingerprint() throws {
        let parsed = try #require(StudioStore.parse("footscan-capture://connect?url=https://footscan.example.dev&key=k",
                                                    allowPublic: true))
        #expect(parsed.link.fingerprint == nil)
    }

    @Test func withPublicStudiosRefusedOnlyACodeThatPinsItsCertificateIsAccepted() {
        // as in the App Store build (acceptsPublicStudios is false outside DEBUG; these tests build in Debug):
        // a public studio could be the developer's, and scans sent there would be collected data (docs/PRIVACY.md)
        #expect(StudioStore.parse("footscan-capture://connect?url=https://footscan.example.dev&key=k", allowPublic: false) == nil)
        let pin = String(repeating: "a", count: 64)
        #expect(StudioStore.parse("footscan-capture://connect?url=https://192.168.1.20:8765&key=k&fp=\(pin)", allowPublic: false) != nil)
        #expect(StudioStore.parse("footscan-capture://connect?url=https://100.113.53.83:8766&key=k&fp=\(pin)", allowPublic: false) != nil) // Tailscale
        // a pin alone isn't enough: a hosted studio at a public address can pin a self-made certificate too
        #expect(StudioStore.parse("footscan-capture://connect?url=https://studio.example.com&key=k&fp=\(pin)", allowPublic: false) == nil)
        #expect(StudioStore.parse("footscan-capture://connect?url=https://203.0.113.9:8766&key=k&fp=\(pin)", allowPublic: false) == nil)
    }

    @Test func withPublicStudiosRefusedTheKeyGoesOnlyToOwnNetworkAddresses() throws {
        let pin = String(repeating: "ab", count: 32)
        // a public alternate is dropped and the home and Tailscale addresses kept: every address is sent the key
        let parsed = try #require(StudioStore.parse(
            "footscan-capture://connect?url=https://192.168.1.20:8765&key=k&fp=\(pin)&alt=https://203.0.113.9:8765&alt=https://100.113.53.83:8765",
            allowPublic: false))
        #expect(parsed.link.alternates == [URL(string: "https://100.113.53.83:8765")!])
        // a development build keeps it
        #expect(StudioStore.parse("footscan-capture://connect?url=https://192.168.1.20:8765&key=k&fp=\(pin)&alt=https://203.0.113.9:8765",
                                  allowPublic: true)?.link.alternates.count == 1)
        // a saved studio with a public address among its addresses (saved by a development build) isn't used
        let saved = StudioLink(url: URL(string: "https://192.168.1.20:8765")!, fingerprint: pin,
                               alternates: [URL(string: "https://203.0.113.9:8765")!])
        #expect(!StudioStore.accepts(saved, allowPublic: false) && StudioStore.accepts(saved.using(saved.url), allowPublic: true))
        #expect(StudioStore.accepts(StudioLink(url: saved.url, fingerprint: pin), allowPublic: false))
    }

    @Test func ownNetworkAddressesAreTheHomeNetworkAndTailscaleOnly() {
        for own in ["https://192.168.11.233:8766", "https://10.0.0.5", "https://172.20.1.1", "https://169.254.3.4",
                    "https://100.64.0.1", "https://mac-mini.local:8766", "https://[fd7a:115c:a1e0::1]:8766",
                    "https://mac.local.:8766", "https://[fe90::1]", "https://[::ffff:192.168.1.5]"] {
            #expect(StudioStore.isOwnNetwork(URL(string: own)!), "\(own)")
        }
        for other in ["https://172.32.0.1", "https://100.128.0.1", "https://8.8.8.8", "https://footscan.example.dev",
                      "https://fd.example.com", "https://[2001:db8::1]", "https://[fd::1]", "https://[fc0::5]"] {
            #expect(!StudioStore.isOwnNetwork(URL(string: other)!), "\(other)")
        }
    }

    @Test(arguments: [
        "footscan-capture://connect?url=http://192.168.1.20:8765&key=k",          // not https: never send the key in the clear
        "footscan-capture://connect?url=https://192.168.1.20:8765",               // no key
        "footscan-capture://connect?url=https://192.168.1.20:8765&key=",          // empty key
        "footscan-capture://connect?url=https://h&key=k&fp=1234",                 // fingerprint the wrong length
        "footscan-capture://connect?url=https://h&key=k&fp=\(String(repeating: "zz", count: 32))", // not hex
        "https://192.168.1.20:8765/?key=k",                                        // not our link at all
        "footscan-capture://other?url=https://h&key=k",                           // wrong action
        "",
    ])
    func unsafeOrBrokenCodesAreRefused(_ code: String) {
        #expect(StudioStore.parse(code) == nil)
    }

    @Test func spacesRoundACodeAreIgnored() {
        #expect(StudioStore.parse("  footscan-capture://connect?url=https://h&key=k \n", allowPublic: true) != nil)
    }
}

// MARK: - the studio's key after the app is deleted

// Uses the real settings and Keychain of the app the tests run in, and puts back whatever was there. These are
// the only tests that touch them (the others parse codes or build messages); they run one at a time, since
// they share the one studio key.
@Suite("Studio key storage", .serialized)
struct StudioKeyStorage {
    @Test func aKeyLeftFromAnEarlierInstallIsDeletedNotReused() throws {
        // what was there, as stored (load() would leave out a link it won't use, and then lose it)
        let savedLink = UserDefaults.standard.data(forKey: StudioStore.linkKey), savedKey = StudioStore.readKey()
        defer {
            UserDefaults.standard.set(savedLink, forKey: StudioStore.linkKey) // nil removes it
            if let savedKey { StudioStore.writeKey(savedKey) } else { StudioStore.deleteKey() }
        }
        let link = StudioLink(url: URL(string: "https://192.168.1.20:8765")!, fingerprint: String(repeating: "a", count: 64))

        // a public studio saved by a development build isn't used where public studios aren't accepted (the
        // App Store build, updated in place over a development one, keeps its settings and Keychain)
        StudioStore.save(StudioLink(url: URL(string: "https://footscan.example.dev")!, fingerprint: nil), key: "k")
        #expect(StudioStore.load(allowPublic: false) == nil && StudioStore.load(allowPublic: true)?.key == "k")
        // and the launch-time cleanup removes it, key and all: the app has no Disconnect for a studio it won't use
        StudioStore.removeLeftoverKey(allowPublic: false)
        #expect(StudioStore.load(allowPublic: true) == nil && StudioStore.readKey() == nil)

        StudioStore.save(link, key: "old-key")
        #expect(StudioStore.load(allowPublic: false)?.key == "old-key")
        StudioStore.removeLeftoverKey(allowPublic: false) // a paired studio: nothing is left over
        #expect(StudioStore.load()?.key == "old-key")
        // Deleting the app clears its settings, but iOS keeps the Keychain item.
        UserDefaults.standard.removeObject(forKey: StudioStore.linkKey)
        #expect(StudioStore.load() == nil)
        // Reading doesn't delete anything; the launch-time cleanup does.
        UserDefaults.standard.set(try JSONEncoder().encode(link), forKey: StudioStore.linkKey)
        #expect(StudioStore.load()?.key == "old-key")
        UserDefaults.standard.removeObject(forKey: StudioStore.linkKey)
        StudioStore.removeLeftoverKey()
        // The key went with it: the address coming back doesn't bring the old password back.
        UserDefaults.standard.set(try JSONEncoder().encode(link), forKey: StudioStore.linkKey)
        #expect(StudioStore.load() == nil)
    }

    @Test func disconnectSaysItWorkedOnlyOnceTheKeyIsGone() {
        let savedLink = UserDefaults.standard.data(forKey: StudioStore.linkKey), savedKey = StudioStore.readKey()
        defer {
            UserDefaults.standard.set(savedLink, forKey: StudioStore.linkKey)
            if let savedKey { StudioStore.writeKey(savedKey) } else { StudioStore.deleteKey() }
        }
        StudioStore.save(StudioLink(url: URL(string: "https://192.168.1.20:8765")!, fingerprint: String(repeating: "a", count: 64)),
                         key: "k")
        #expect(StudioStore.clear())
        #expect(StudioStore.readKey() == nil && StudioStore.load() == nil)
        // nothing left to delete still counts as gone, so a second Disconnect doesn't report a failure
        #expect(StudioStore.deleteKey() && StudioStore.clear())
    }
}

// MARK: - a studio with more than one address (home Wi-Fi and Tailscale)

@Suite("Studio addresses")
struct StudioAddresses {
    let fp = String(repeating: "ab", count: 32)

    @Test func aCodeCarriesTheTailscaleAddressAsAnAlternate() throws {
        let code = "footscan-capture://connect?url=https://192.168.11.233:8766&key=k&fp=\(fp)"
            + "&alt=https%3A%2F%2F100.101.102.103%3A8766&alt=https://192.168.11.233:8766" // a repeat of url is dropped
        let parsed = try #require(StudioStore.parse(code))
        #expect(parsed.link.url.absoluteString == "https://192.168.11.233:8766")
        #expect(parsed.link.alternates.map(\.absoluteString) == ["https://100.101.102.103:8766"])
        #expect(parsed.link.fingerprint == fp) // one pin for every address: it's the same computer
    }

    @Test func aCodeWithNoPinnedCertificateUsesOnlyTheAddressItNames() throws {
        // every address is sent the key at once: without a pin, an "alternate" could be anyone's host
        let code = "footscan-capture://connect?url=https://footscan.example.dev&key=k&alt=https://other.example.com"
        let parsed = try #require(StudioStore.parse(code))
        #expect(parsed.link.alternates.isEmpty && parsed.link.url.absoluteString == "https://footscan.example.dev")
    }

    @Test func anAlternateInTheClearRefusesTheWholeCode() {
        #expect(StudioStore.parse("footscan-capture://connect?url=https://192.168.11.233:8766&key=k&alt=http://100.101.102.103:8766") == nil)
    }

    @Test func aLinkSavedBeforeAlternatesStillLoads() throws {
        let saved = Data(#"{"url":"https://192.168.1.20:8765","fingerprint":"\#(fp)"}"#.utf8)
        let link = try JSONDecoder().decode(StudioLink.self, from: saved)
        #expect(link.alternates.isEmpty && link.fingerprint == fp)
    }

    @Test func theAddressThatAnsweredGoesFirstAndNoneIsLost() throws {
        let home = try #require(URL(string: "https://192.168.11.233:8766"))
        let tailnet = try #require(URL(string: "https://100.101.102.103:8766"))
        let link = StudioLink(url: home, fingerprint: fp, alternates: [tailnet]).using(tailnet)
        #expect(link.url == tailnet && link.alternates == [home])
    }

    @Test(arguments: [
        ("192.168.11.233", StudioAddressKind.homeNetwork), ("10.0.0.4", .homeNetwork), ("172.20.1.1", .homeNetwork),
        ("mac.local", .homeNetwork), ("100.101.102.103", .tailscale), ("100.64.0.1", .tailscale),
        ("tank.example.ts.net", .tailscale), ("100.128.0.1", .other), ("172.32.0.1", .other),
        ("footscan.example.dev", .other), ("999.1.1.1", .other),
    ])
    func addressesAreToldApart(_ host: String, _ kind: StudioAddressKind) {
        #expect(StudioAddressKind(host: host) == kind)
    }
}

// MARK: - why "Test the connection" failed

@Suite("Connection test failures")
struct ConnectionTestFailures {
    let home = URL(string: "https://192.168.11.233:8766")!
    let tailnet = URL(string: "https://100.101.102.103:8766")!

    @Test func awayFromHomeTheHomeAddressIsSaidToNeedTheSameWiFi() {
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer)], pinned: true)
        #expect(text.contains("192.168.11.233 is the studio's home Wi-Fi address"))
        #expect(text.contains("same Wi-Fi"))
        #expect(text.contains("Check Footscan is running"))
        #expect(!text.contains("Mac")) // the studio may be on any computer
    }

    @Test func withTailscaleBothAddressesAreExplainedInOrder() throws {
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer), .init(address: tailnet, miss: .noAnswer)], pinned: true)
        let homeAt = try #require(text.range(of: "192.168.11.233")), tailnetAt = try #require(text.range(of: "100.101.102.103"))
        #expect(homeAt.lowerBound < tailnetAt.lowerBound)
        #expect(text.contains("Tailscale is on"))
    }

    @Test func aDifferentCertificateIsNotCalledUnreachable() {
        let text = StudioClient.Failure.explain([.init(address: tailnet, miss: .wrongCertificate)], pinned: true)
        #expect(text.contains("isn't the studio this phone connected to"))
        #expect(!text.contains("Check Footscan is running")) // something did answer
    }

    @Test func anotherDeviceAtTheHomeAddressOnAnotherWiFiIsSaidToBeAnotherWiFi() {
        // a café's router using 192.168.11.x too: a printer there answers at the studio's home address
        let text = StudioClient.Failure.explain([.init(address: home, miss: .wrongCertificate)], pinned: true)
        #expect(text.contains("another Wi-Fi that uses the same addresses"))
        #expect(!text.contains("Check Footscan is running"))
    }

    @Test func localNetworkAccessIsMentionedOnlyWhenThePhoneHadNoRouteHome() {
        let blocked = StudioClient.Failure.explain([.init(address: home, miss: .noRoute)], pinned: true)
        #expect(blocked.contains("Local Network"))
        let silent = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer)], pinned: true)
        #expect(!silent.contains("Local Network"))
    }

    @Test func aHomeAddressThatDoesntAnswerSuggestsScanningTheCodeAgain() {
        // the router may have given the studio a new address: the old advice to scan the code again stays
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer)], pinned: true)
        #expect(text.contains("Wi-Fi address has changed") && text.contains("scan it again"))
        let away = StudioClient.Failure.explain([.init(address: tailnet, miss: .noAnswer)], pinned: true)
        #expect(!away.contains("Wi-Fi address has changed"))
    }

    @Test func noRouteAnywhereIsPutDownToThePhonesOwnConnection() {
        // abroad with Data Roaming off, Airplane Mode, or mobile data off for the app: no address can be reached
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noRoute), .init(address: tailnet, miss: .noRoute)], pinned: true)
        #expect(text.contains("this phone's own connection") && text.contains("Data Roaming") && text.contains("Airplane Mode"))
        #expect(text.contains("100.101.102.103 is the studio's Tailscale address, but this phone has no connection"))
        #expect(!text.contains("answers from anywhere while Tailscale is on")) // it is on: that's not the problem
        let silent = StudioClient.Failure.explain([.init(address: tailnet, miss: .noAnswer)], pinned: true)
        #expect(!silent.contains("this phone's own connection"))
        // at home with Local Network access refused and Tailscale off: the phone's connection is fine
        let localOnly = StudioClient.Failure.explain([.init(address: home, miss: .noRoute), .init(address: tailnet, miss: .noAnswer)], pinned: true)
        #expect(!localOnly.contains("this phone's own connection") && localOnly.contains("Local Network"))
        // no route to either address: Local Network access can't stop the Tailscale one, so it isn't the cause
        #expect(!text.contains("Local Network"))
        // a code with only the home address and no route there: it may be either, so both are said
        let homeOnly = StudioClient.Failure.explain([.init(address: home, miss: .noRoute)], pinned: true)
        #expect(homeOnly.contains("this phone's own connection") && homeOnly.contains("Local Network"))
    }

    @Test func theSameAddressWrittenAnotherWayIsntTriedTwice() throws {
        let code = "footscan-capture://connect?url=https://192.168.11.233:8766/&key=k&fp=" + String(repeating: "a", count: 64)
            + "&alt=https://192.168.11.233:8766&alt=https://100.101.102.103:8766&alt=https://100.101.102.103:8766/"
        let parsed = try #require(StudioStore.parse(code))
        #expect(parsed.link.alternates == [URL(string: "https://100.101.102.103:8766")!])
    }

    @Test func theAddressKindsHaveOneLabelEverywhere() {
        #expect(StudioConnection.describe(home) == "192.168.11.233 (home Wi-Fi)")
        #expect(StudioConnection.describe(tailnet) == "100.101.102.103 (Tailscale)")
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer), .init(address: tailnet, miss: .noAnswer)], pinned: true)
        #expect(text.contains("home Wi-Fi address") && text.contains("Tailscale address"))
    }

    @Test func aDropMidSendIsNotBlamedOnTheWiFiAndTheScanWaits() {
        let failure = StudioClient.Failure.dropped(host: "192.168.11.233")
        #expect(failure.isUnreachable) // sent again once the studio is back
        #expect(!failure.offersReconnect) // it answered: no need to scan its code again
        #expect(StudioClient.Failure.unreachable([], pinned: true).offersReconnect)
        // no address tried at all still says what to do, not a blank line
        #expect(StudioClient.Failure.unreachable([], pinned: true).errorDescription?.contains("Check Footscan is running") == true)
        #expect(failure.errorDescription?.contains("same Wi-Fi") == false)
    }

    @Test(arguments: [
        // cancelled alone says nothing (the pin's own verdict is what tells a wrong certificate, below)
        (URLError.Code.cancelled, StudioClient.Miss.noAnswer),
        (.serverCertificateUntrusted, .wrongCertificate),
        (.secureConnectionFailed, .noAnswer), // a failed TLS set-up says nothing about which certificate
        (.notConnectedToInternet, .noRoute),
        (.timedOut, .noAnswer), (.cannotConnectToHost, .noAnswer),
    ])
    func networkErrorsAreSorted(_ code: URLError.Code, _ miss: StudioClient.Miss) {
        #expect(StudioClient.Miss(URLError(code)) == miss)
    }

    @Test func aCertificateThePinTurnedAwayIsAWrongCertificateWhateverTheErrorSays() {
        #expect(StudioClient.Miss(URLError(.cancelled), pinRefused: true) == .wrongCertificate)
        #expect(StudioClient.Miss(URLError(.secureConnectionFailed), pinRefused: true) == .wrongCertificate)
        #expect(PinnedTrust(fingerprint: String(repeating: "a", count: 64)).refusedCertificate == false)
    }

    // A studio answering with a redirect would otherwise send the key and the scan on to whatever address it
    // names, which may be a public one the connect code would have been refused for.
    @Test func aRedirectIsNeverFollowed() async throws {
        let trust = PinnedTrust(fingerprint: String(repeating: "a", count: 64))
        let session = URLSession(configuration: .ephemeral, delegate: trust, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let task = session.dataTask(with: URL(string: "https://192.168.1.20:8765/api/studio")!) // never started
        let answer = try #require(HTTPURLResponse(url: URL(string: "https://192.168.1.20:8765/api/studio")!, statusCode: 307,
                                                  httpVersion: nil, headerFields: ["Location": "https://203.0.113.5/api/studio"]))
        let followed: URLRequest?? = await withCheckedContinuation { done in
            trust.urlSession(session, task: task, willPerformHTTPRedirection: answer,
                             newRequest: URLRequest(url: URL(string: "https://203.0.113.5/api/studio")!)) { done.resume(returning: $0) }
        }
        #expect(followed == .some(nil))
    }
}

// MARK: - a send that dropped, tried again

@Suite("A send that dropped, tried again")
struct DroppedSends {
    let pin = String(repeating: "cd", count: 32)
    var studio: StudioLink { StudioLink(url: URL(string: "https://192.168.11.233:8766")!, fingerprint: pin,
                                        alternates: [URL(string: "https://100.113.53.83:8766")!]) }

    private func record(loadKg: Double? = nil) -> ScanRecord {
        var rec = ScanRecord(subject: .rightSole, created: Date(timeIntervalSince1970: 1_800_000_000), device: "test",
                             systemVersion: "0", appVersion: "0")
        rec.loadKg = loadKg
        return rec
    }

    @Test func aCaptureStillWaitingForItsModelIsSentInto() {
        let list: [[String: Any]] = [["capture_id": "LIDAR_nwb_relaxed_R_1", "status": "uploading"],
                                     ["capture_id": "LIDAR_nwb_relaxed_R_2", "status": "complete", "mesh": ["file": "mesh.ply"]]]
        #expect(StudioClient.existing("LIDAR_nwb_relaxed_R_1", in: list) == .waiting)
    }

    @Test func aCaptureThatAlreadyHasAModelIsTakenAsSentAndNeverSentIntoAgain() {
        // the earlier upload got there and only its answer was lost; or an insole was made from it since:
        // sending a model again would replace it, and the studio would remove the insole made from the old one
        let done: [[String: Any]] = [["capture_id": "C1", "status": "complete", "mesh": ["file": "mesh.ply"],
                                      "accuracy": ["median_mm": 1.0, "reference": "model"]]]
        guard case .done(let acc) = StudioClient.existing("C1", in: done) else { Issue.record("not taken as sent"); return }
        #expect(acc?.median_mm == 1.0)
        #expect(StudioClient.existing("C2", in: [["capture_id": "C2", "status": "uploading", "insole": ["file": "x"]]]) == .done(nil))
        #expect(StudioClient.existing("C3", in: [["capture_id": "C3", "status": "uploading", "clog": ["file": "x"]]]) == .done(nil))
    }

    @Test func aCaptureTheStudioNoLongerHasMeansANewOne() {
        #expect(StudioClient.existing("C1", in: []) == .gone)
        #expect(StudioClient.existing("C1", in: [["capture_id": "C9", "status": "uploading"]]) == .gone)
    }

    @Test func theNextTryUsesTheCaptureTheStudioAlreadyMadeAtWhicheverAddressItAnswers() {
        var rec = record()
        rec.pendingCapture = PendingCapture(id: "LIDAR_nwb_relaxed_R_1", studio: PendingCapture.identity(of: studio), loadKg: nil)
        #expect(rec.reusableCapture(at: studio) == "LIDAR_nwb_relaxed_R_1")
        // the same studio over Tailscale is the same studio
        #expect(rec.reusableCapture(at: studio.using(studio.alternates[0])) == "LIDAR_nwb_relaxed_R_1")
    }

    @Test func anotherStudiosCaptureIsNeverUsed() {
        var rec = record()
        rec.pendingCapture = PendingCapture(id: "LIDAR_nwb_relaxed_R_1", studio: PendingCapture.identity(of: studio), loadKg: nil)
        let other = StudioLink(url: studio.url, fingerprint: String(repeating: "ef", count: 32))
        #expect(rec.reusableCapture(at: other) == nil)
    }

    @Test func aDifferentScaleReadingNeedsANewCapture() {
        var rec = record(loadKg: 31.5)
        rec.pendingCapture = PendingCapture(id: "LIDAR_swb_R_1", studio: PendingCapture.identity(of: studio), loadKg: 30)
        #expect(rec.reusableCapture(at: studio) == nil)
        rec.loadKg = 30
        #expect(rec.reusableCapture(at: studio) == "LIDAR_swb_R_1")
    }

    @Test func thePendingCaptureIsKeptWithTheScanAndOlderRecordsStillRead() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let scan = Scan(folder: root)
        var rec = record()
        rec.pendingCapture = PendingCapture(id: "LIDAR_nwb_relaxed_R_1", studio: pin, loadKg: nil)
        scan.save(rec)
        #expect(scan.record?.pendingCapture == rec.pendingCapture)
        // a record written before pending captures existed reads, with none
        let old = #"{"subject":"right-sole","created":"2026-11-20T10:00:00Z","device":"iPhone18,1","systemVersion":"26.1","appVersion":"1.0","modelBuiltOnPhone":true,"units":"m","note":"n"}"#
        try Data(old.utf8).write(to: scan.recordURL)
        #expect(scan.record != nil && scan.record?.pendingCapture == nil)
    }
}

// MARK: - the phone's network changing

@Suite("Trying waiting scans when the network changes")
struct NetworkChanges {
    typealias Sig = NetworkWatch.Signature
    let cellular = Sig(satisfied: true, wifi: false, cellular: true, wired: false, other: false)
    let wifi = Sig(satisfied: true, wifi: true, cellular: false, wired: false, other: false)
    let none = Sig(satisfied: false, wifi: false, cellular: false, wired: false, other: false)

    @Test func joiningWiFiOrTurningTailscaleOnIsWorthATry() {
        #expect(NetworkWatch.worthTrying(from: cellular, to: wifi))  // home again
        var tailscale = cellular
        tailscale.other = true  // a VPN comes up as another kind of path
        #expect(NetworkWatch.worthTrying(from: cellular, to: tailscale))
        #expect(NetworkWatch.worthTrying(from: none, to: cellular))
    }

    @Test func losingTheNetworkTheFirstReadingAndNoChangeAreNot() {
        #expect(!NetworkWatch.worthTrying(from: wifi, to: none))
        #expect(!NetworkWatch.worthTrying(from: nil, to: wifi))  // just launched: nothing changed yet
        #expect(!NetworkWatch.worthTrying(from: wifi, to: wifi))
    }
}

// MARK: - how far a send has got

@Suite("Upload progress")
struct UploadProgressShown {
    @Test func eachWholePercentIsToldOnce() {
        var count = UploadProgress.Count()
        let first = count.next(sent: 0, total: 1000)
        let further = count.next(sent: 420, total: 1000)
        let same = count.next(sent: 425, total: 1000)  // still 42%
        #expect(first == 0)
        #expect(further == 42)
        #expect(same == nil)
    }

    @Test func oneHundredMeansEveryByteHasGone() {
        var count = UploadProgress.Count()
        let nearly = count.next(sent: 999, total: 1000)
        let all = count.next(sent: 1000, total: 1000)
        #expect(nearly == 99)
        #expect(all == 100)
        var over = UploadProgress.Count()
        let beyond = over.next(sent: 1200, total: 1000)
        #expect(beyond == 100)
    }

    @Test func sendingTheBodyAgainCountsFromTheStartAgain() {
        var count = UploadProgress.Count()
        _ = count.next(sent: 1000, total: 1000)
        let again = count.next(sent: 50, total: 1000)
        #expect(again == 5)
        #expect(count.percent == 5)
    }

    @Test func anUnknownSizeTellsNothing() {
        var count = UploadProgress.Count()
        let none = count.next(sent: 500, total: 0)
        let unknown = count.next(sent: 500, total: NSURLSessionTransferSizeUnknown)
        #expect(none == nil)
        #expect(unknown == nil)
    }

    @Test func theCardSaysHowFarAndThenThatTheStudioIsChecking() {
        #expect(SendingWords.chip(nil) == "Sending")
        #expect(SendingWords.chip(29) == "Sending 29%")  // a whole percent, never 28 from 0.29 * 100
        #expect(SendingWords.chip(57) == "Sending 57%")
        #expect(SendingWords.chip(100) == "Studio checking")
        #expect(SendingWords.detail(nil, calibration: false) == "Sending…")
        #expect(SendingWords.detail(7, calibration: false) == "Sending the model… 7%")
        #expect(SendingWords.detail(100, calibration: false) == "All sent. The studio is checking it…")
        #expect(SendingWords.detail(100, calibration: true) == "All sent. The studio is measuring its accuracy…")
    }
}

// MARK: - the studio refusing an incomplete scan

@Suite("Incomplete scans")
struct IncompleteScans {
    @Test func aScanMissingPartOfTheFootIsToldApartFromOtherRefusals() throws {
        let missing = ["THE TOES ARE MISSING: … Scan again with the toes relaxed and flat."]
        let failure = StudioClient.Failure.from(status: 422, json: ["error": "The studio didn't keep this scan", "incomplete": missing])
        guard case .incomplete(let why, let advice) = failure else { Issue.record("not read as incomplete: \(failure)"); return }
        #expect(why == missing)
        #expect(advice.isEmpty) // a studio that sends no steps: the lines alone
        #expect(failure.errorDescription?.hasPrefix("Scan again") == true)
        // any other refusal is still a plain one, with the studio's own words
        guard case .refused(let other) = StudioClient.Failure.from(status: 400, json: ["error": "bad capture id"]) else {
            Issue.record("a plain refusal was misread"); return
        }
        #expect(other == "bad capture id")
        guard case .refused("HTTP 500") = StudioClient.Failure.from(status: 500, json: [:]) else {
            Issue.record("an answer without JSON should name its status"); return
        }
    }

    @Test func theStudiosStepsForTheNextScanAreRead() throws {
        let json: [String: Any] = [
            "error": "The studio didn't keep this scan",
            "incomplete": ["THE FOREFOOT WAS ROLLED ONTO ONE EDGE: … Scan again with the ball of the foot level."],
            "retake": [["code": "forefoot_rolled", "title": "The ball of the foot wasn't level",
                        "steps": ["Relax the ankle.", "Lay a book across the ball of the foot."]]],
        ]
        guard case .incomplete(_, let advice) = StudioClient.Failure.from(status: 422, json: json) else {
            Issue.record("not read as incomplete"); return
        }
        #expect(advice == [RetakeAdvice(code: "forefoot_rolled", title: "The ball of the foot wasn't level",
                                        steps: ["Relax the ankle.", "Lay a book across the ball of the foot."])])
        // steps in a shape this app doesn't know: the refusal still stands, with the lines alone
        guard case .incomplete(_, let none) = StudioClient.Failure.from(status: 422, json: json.merging(["retake": "?"]) { $1 }) else {
            Issue.record("a malformed retake lost the refusal"); return
        }
        #expect(none.isEmpty)
    }

    @Test func aRefusalWithoutStepsStillSaysWhatToChange() {
        // records saved before the studio sent steps have only the lines: each becomes a title and its ending
        var rec = ScanRecord(subject: .rightSole, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        #expect(rec.nextTime.isEmpty)
        rec.retake = ["THE TOES ARE MISSING: the front of the scan ends square (80% …). Scan again with the toes relaxed and flat."]
        #expect(rec.nextTime == [RetakeAdvice(code: "other", title: "The toes are missing",
                                              steps: ["Scan again with the toes relaxed and flat."])])
        let steps = RetakeAdvice(code: "toes_missing", title: "The toes were cut off", steps: ["Let the toes relax."])
        rec.retakeAdvice = [steps]
        #expect(rec.nextTime == [steps])
    }

    @Test func aRecordSavedBeforeTheStepsExistedStillReads() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let scan = Scan(folder: dir)
        var rec = ScanRecord(subject: .leftSole, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        rec.retake = ["THE HEEL IS CUT OFF: … Scan again, taking the phone round behind the heel."]
        scan.save(rec)
        // saved without the new key, as an older app wrote it
        let json = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: scan.recordURL)) as? [String: Any])
        #expect(json["retake"] != nil && json["retakeAdvice"] == nil)
        let back = try #require(scan.record)
        #expect(back.retake == rec.retake && back.retakeAdvice == nil && back.nextTime.first?.title == "The heel is cut off")
    }

    @Test func soleScansSayWhatToCheckBeforeStart() {
        for s in Subject.allCases where s.scanKind == "sole_up" || s.scanKind == "sole_hanging" {
            #expect(s.startChecks?.contains("ball of the foot level") == true, "\(s)")
        }
        #expect(Subject.calibration.startChecks == nil && Subject.rightFoot.startChecks == nil)
    }

    @Test func whatsMissingIsKeptWithTheScan() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let scan = Scan(folder: dir)
        var rec = ScanRecord(subject: .leftSole, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        #expect(rec.retake == nil)
        rec.retake = ["THE HEEL IS CUT OFF: … Scan again, taking the phone round behind the heel."]
        scan.save(rec)
        #expect(scan.record?.retake == rec.retake && scan.record?.studioCaptureID == nil)
    }
}

// MARK: - scans on the phone

@Suite("Scan list")
struct ScanList {
    private func makeScan(in root: URL, folder: String, subject: Subject, created: Date?) throws {
        let dir = root.appending(path: folder, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        guard let created else { return }
        let scan = Scan(folder: dir)
        scan.save(ScanRecord(subject: subject, created: created, device: "test", systemVersion: "0", appVersion: "0"))
    }

    @Test func newestFirstByWhenTakenNotByName() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let day = 86_400.0
        let base = Date(timeIntervalSince1970: 1_800_000_000)
        // folder names sort the other way round from the dates
        try makeScan(in: root, folder: "right-foot-a", subject: .rightFoot, created: base)
        try makeScan(in: root, folder: "other-b", subject: .other, created: base + 2 * day)
        try makeScan(in: root, folder: "calibration-object-c", subject: .calibration, created: base + day)

        let order = ScanStore.all(in: root).map(\.folder.lastPathComponent)
        #expect(order == ["other-b", "calibration-object-c", "right-foot-a"])
    }

    @Test func aRecordSurvivesSavingAndReading() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        try makeScan(in: root, folder: "left-foot-x", subject: .leftFoot, created: Date(timeIntervalSince1970: 1_800_000_000))
        let scan = try #require(ScanStore.all(in: root).first)
        var rec = try #require(scan.record)
        rec.loadKg = 31.5
        rec.studioCaptureID = "LIDAR_swb_L_1"
        scan.save(rec)
        let back = try #require(scan.record)
        #expect(back.subject == .leftFoot && back.loadKg == 31.5 && back.studioCaptureID == "LIDAR_swb_L_1")
    }

    @Test func onlyAFootRestingOnTheFloorNeedsAScaleReading() {
        #expect(Subject.allCases.filter(\.needsScale) == [.rightFoot, .leftFoot])
    }

    @Test func everyKindHasAGetReadyListAndOnlyScaleListsMentionTheScale() {
        for s in Subject.allCases { #expect(!s.checklist.isEmpty) }
        for s in Subject.allCases where s.isFoot {
            #expect(s.checklist.contains { $0.1.localizedCaseInsensitiveContains("scale") } == s.needsScale)
        }
    }

    @Test func soleScansComeFirstAndTellTheStudioHowToReadThem() {
        let soles: [Subject] = [.rightSole, .leftSole, .rightSoleFlat, .leftSoleFlat, .rightPrint, .leftPrint]
        #expect(Array(Subject.allCases.prefix(6)) == soles)
        #expect(Subject.allCases.filter(\.needs3DCapture) == soles + [.shoeInsole])
        // the shoe's own insole: Apple's 3D capture, not a foot, its own studio condition (Make insole fits to it)
        #expect(!Subject.shoeInsole.isFoot && Subject.shoeInsole.scanKind == nil)
        #expect(Subject.shoeInsole.studioCondition == ("shoe_insole", nil))
        #expect(Subject.rightSole.scanKind == "sole_up" && Subject.leftPrint.scanKind == "impression")
        #expect(Subject.rightSoleFlat.scanKind == "sole_hanging" && Subject.leftSoleFlat.scanKind == "sole_hanging")
        #expect(Subject.leftSoleFlat.studioCondition == ("nwb_relaxed", "left"))
        #expect(Subject.rightFoot.scanKind == "foot" && Subject.other.scanKind == nil && Subject.calibration.scanKind == nil)
        #expect(Subject.rightSole.studioCondition == ("nwb_relaxed", "right"))
        #expect(Subject.leftPrint.studioCondition == ("swb", "left"))
        #expect(Subject.allCases.filter(\.isLeft) == [.leftSole, .leftSoleFlat, .leftPrint, .leftFoot])
    }

    @Test func scansSavedBeforeTheNewKindsStillRead() throws {
        // a scan.json written by the earlier app (no new fields) still decodes, as the same subject
        let json = #"{"subject":"right-foot","created":"2026-10-12T21:58:43Z","device":"iPhone18,1","systemVersion":"26.6.2","appVersion":"0.1","modelBuiltOnPhone":true,"units":"m","note":"n"}"#
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        let rec = try dec.decode(ScanRecord.self, from: Data(json.utf8))
        #expect(rec.subject == .rightFoot && rec.subject.needsScale)
        #expect(rec.stoppedEarly == nil)
    }

    /// A scan folder with `photos` empty files in its Images folder.
    private func scanWithPhotos(_ photos: Int, in root: URL) throws -> Scan {
        try makeScan(in: root, folder: "right-sole-p\(photos)", subject: .rightSole, created: Date(timeIntervalSince1970: 1_800_000_000))
        let scan = Scan(folder: root.appending(path: "right-sole-p\(photos)", directoryHint: .isDirectory))
        try FileManager.default.createDirectory(at: scan.images, withIntermediateDirectories: true)
        for i in 0..<photos { try Data().write(to: scan.images.appending(path: "IMG_\(i).HEIC")) }
        return scan
    }

    @Test func aCaptureWithPhotosAndNoModelWaitsToBeBuiltUnlessItWasStoppedPartway() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let scan = try scanWithPhotos(12, in: root)
        #expect(scan.waitsToBuild && !scan.keptNothing)
        var rec = try #require(scan.record)
        rec.stoppedEarly = Date()
        scan.save(rec)
        // kept (its page can still build it), but the home screen no longer asks for it
        #expect(!scan.waitsToBuild && !scan.keptNothing && scan.photoCount == 12)
        #expect(scan.record?.stoppedEarly != nil)
        // built from its page anyway, but its studio copy wasn't saved: home asks again
        try Data().write(to: scan.usdz)
        #expect(scan.waitsToBuild)
    }

    @Test func aStoppedOrFailedCaptureIsNeverTakenForAnEmptyOne() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        // stopped after shots the session counted, before their photos reached the folder
        let stopped = try scanWithPhotos(0, in: root)
        var rec = try #require(stopped.record)
        rec.stoppedEarly = Date()
        rec.shotsTaken = 3
        stopped.save(rec)
        #expect(!stopped.keptNothing)
        // failed before the first photo: its error explains what happened
        rec = try #require(stopped.record)
        rec.stoppedEarly = nil
        rec.shotsTaken = nil
        rec.error = "The capture stopped"
        stopped.save(rec)
        #expect(!stopped.keptNothing)
    }

    @Test func aCaptureCancelledBeforeItsFirstPhotoKeptNothing() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let scan = try scanWithPhotos(0, in: root)
        #expect(scan.keptNothing && !scan.waitsToBuild)
    }

    @Test func deletingSaysWhatIsLost() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let scan = try scanWithPhotos(3, in: root)
        #expect(scan.deleteWarning.contains("photos and model will be gone"))
        var rec = try #require(scan.record)
        rec.studioCaptureID = "LIDAR_nwb_relaxed_R_1"
        scan.save(rec)
        #expect(scan.deleteWarning.contains("studio stays"))
    }
}

// MARK: - model builds cut off by leaving the app

@Suite("A model build cut off by leaving the app")
struct InterruptedBuilds {
    @Test func aBuildCutOffByLeavingTheAppIsStartedAgainAFewTimesAtMost() {
        #expect(ScanLibrary.shouldResume(awayNow: true, secondsSinceBack: nil, resumesSoFar: 0))
        #expect(ScanLibrary.shouldResume(awayNow: true, secondsSinceBack: nil, resumesSoFar: ScanLibrary.maxResumes - 1))
        // one that keeps failing shows its own error instead of trying for ever
        #expect(!ScanLibrary.shouldResume(awayNow: true, secondsSinceBack: nil, resumesSoFar: ScanLibrary.maxResumes))
    }

    @Test func aFailureThatArrivesJustAfterComingBackStillCountsAsCutOff() {
        #expect(ScanLibrary.shouldResume(awayNow: false, secondsSinceBack: 2, resumesSoFar: 0))
        #expect(ScanLibrary.shouldResume(awayNow: false, secondsSinceBack: ScanLibrary.backGrace, resumesSoFar: 0))
    }

    @Test func aFailureOnScreenIsARealOneAndShowsItsOwnError() {
        #expect(!ScanLibrary.shouldResume(awayNow: false, secondsSinceBack: nil, resumesSoFar: 0))  // never left
        // left for a moment early on, failed on screen minutes later: not because of leaving
        #expect(!ScanLibrary.shouldResume(awayNow: false, secondsSinceBack: 180, resumesSoFar: 0))
    }

    @Test func theMessageSaysItCarriesOnByItself() {
        #expect(ScanLibrary.interruptedMessage.localizedCaseInsensitiveContains("by itself"))
    }
}

// MARK: - the camera

@Suite("The camera before a scan")
struct CameraBeforeAScan {
    @Test func theCamerasPermissionIsReadAsAllowedOffBlockedOrNotAsked() {
        #expect(CameraAccess.from(.authorized) == .allowed)
        #expect(CameraAccess.from(.notDetermined) == .notAsked)
        #expect(CameraAccess.from(.denied) == .off)
        #expect(CameraAccess.from(.restricted) == .blocked)
    }

    @Test func onlyACameraThatCantBeUsedHasSomethingToSay() {
        #expect(CameraAccess.allowed.message == nil && CameraAccess.notAsked.message == nil)
        // turned off for Footscan: where to turn it on
        #expect(CameraAccess.off.message?.contains("Settings > Footscan > Camera") == true)
        // blocked for the whole phone: there's no switch for Footscan, so it doesn't send them looking for one
        #expect(CameraAccess.blocked.message?.contains("Settings > Footscan") == false)
    }
}

// MARK: - the battery before a scan

@Suite("Battery before a scan")
struct BatteryBeforeAScan {
    @Test func aLowBatteryUnpluggedIsSaidWithItsLevel() {
        let note = BatteryCheck.note(level: 0.12, state: .unplugged)
        #expect(note?.hasPrefix("Battery at 12%.") == true)
        // just under the line reads as under it, never as the line itself
        #expect(BatteryCheck.note(level: 0.196, state: .unplugged)?.hasPrefix("Battery at 19%.") == true)
    }

    @Test func chargingOrEnoughOrUnknownSaysNothing() {
        #expect(BatteryCheck.note(level: 0.12, state: .charging) == nil)
        #expect(BatteryCheck.note(level: 0.12, state: .full) == nil)
        #expect(BatteryCheck.note(level: 0.2, state: .unplugged) == nil)
        #expect(BatteryCheck.note(level: 0.8, state: .unplugged) == nil)
        #expect(BatteryCheck.note(level: -1, state: .unknown) == nil)  // the simulator
        #expect(BatteryCheck.note(level: -1, state: .unplugged) == nil)
    }
}

// MARK: - coaching during a capture

@Suite("Coaching during a capture")
struct CaptureCoachingTests {
    @Test func aHotPhoneIsWarnedAboutAndACoolOneIsNot() {
        #expect(CaptureCoaching.thermalWarning(.nominal) == nil)
        #expect(CaptureCoaching.thermalWarning(.fair) == nil)
        #expect(CaptureCoaching.thermalWarning(.serious)?.contains("cool") == true)
        #expect(CaptureCoaching.thermalWarning(.critical)?.contains("cool") == true)
    }

    @Test func aTipThatFlickersIsReadOutOnceEveryFewSeconds() {
        var tips = TipRepeats()
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        let first = tips.shouldSay("Slow down a little.", at: t0)
        let again = tips.shouldSay("Slow down a little.", at: t0 + 1)
        let another = tips.shouldSay("Move a little closer.", at: t0 + 1)  // another tip isn't held back
        let later = tips.shouldSay("Slow down a little.", at: t0 + TipRepeats.quiet)
        #expect(first && !again && another && later)
    }

    @Test func losingTheSubjectAndOverCapturingAreSaid() {
        #expect(CaptureCoaching.tip([.objectNotDetected]) == "Lost track. Point the phone back at it.")
        #expect(CaptureCoaching.tip([.overCapturing]) == "Plenty from here. Move on round to a new angle.")
        #expect(CaptureCoaching.tip([]) == nil)
    }

    @Test func theTipMostWorthActingOnWins() {
        #expect(CaptureCoaching.tip([.overCapturing, .environmentTooDark]) == "Too dark. Turn on more lights.")
        #expect(CaptureCoaching.tip([.objectTooClose, .movingTooFast]) == "Slow down a little.")
        #expect(CaptureCoaching.tip([.objectTooFar, .objectNotDetected]) == "Lost track. Point the phone back at it.")
        #expect(CaptureCoaching.tip([.overCapturing, .outOfFieldOfView]) == "Keep it in the middle of the screen.")
    }
}

// MARK: - the calibration object's score

@Suite("The calibration object's score")
struct CalibrationScore {
    @Test func theStudiosAnswerIsReadWithItsWarningsAndWhatItWasComparedWith() throws {
        // the shape of recon/imported.py summarize(), extra keys and all (SYNTHETIC numbers, not a scan's)
        let json = #"""
        {"median_mm": 1.0, "p95_mm": 2.0, "signed_mean_mm": 0.5, "within_1mm": 0.5, "scan_within_2mm": 0.5,
         "length_mm": 1.0, "width_mm": 1.0, "dome_apex_mm": -1.0, "scale_pct": 1.35, "reference": "model",
         "floor": "made up below the base", "warnings": ["the phone made up the bottom"]}
        """#
        let acc = try JSONDecoder().decode(StudioAccuracy.self, from: Data(json.utf8))
        #expect(acc.scale_pct == 1.35 && acc.warnings == ["the phone made up the bottom"])
    }

    @Test func withCaliperReadingsTheNoteSaysEachSizeMayStillBeAgainstTheDesign() {
        // the studio marks the whole score "calipers" once any reading is typed in; sizes without one use the design
        #expect(AccuracyCard.referenceNote("calipers").contains("where you typed one in"))
        #expect(AccuracyCard.referenceNote("model").contains("design"))
        #expect(AccuracyCard.referenceNote(nil) == AccuracyCard.referenceNote("model"))
    }

    @Test func anAnswerSavedBeforeTheWarningsStillReads() throws {
        let acc = try JSONDecoder().decode(StudioAccuracy.self, from: Data(#"{"median_mm": 0.7, "reference": "model"}"#.utf8))
        #expect(acc.warnings == nil && acc.scale_pct == nil && acc.median_mm == 0.7)
    }

    @Test func theOverallSizeSaysWhichWay() {
        #expect(AccuracyCard.percent(0.9) == "+0.9%")
        #expect(AccuracyCard.percent(-1.24) == "−1.2%")
        #expect(AccuracyCard.percent(0) == "0.0%")
        #expect(AccuracyCard.percent(-0.04) == "0.0%")  // no direction where there's none to show
        #expect(AccuracyCard.signed(-1.0, places: 2) == "−1.00")
    }
}

// MARK: - the studio's camera page

@Suite("The studio's camera page")
struct StudioCameraPage {
    let studio = URL(string: "https://192.168.11.233:8766/")!

    func decide(_ scheme: String = "https", _ host: String = "192.168.11.233", _ port: Int = 8766,
                _ type: WKMediaCaptureType = .camera) -> WKPermissionDecision {
        StudioPage.mediaDecision(scheme: scheme, host: host, port: port, studio: studio, type: type)
    }

    @Test func onlyTheStudiosPageGetsTheCameraAndNothingGetsTheMicrophone() {
        #expect(decide() == .grant)
        #expect(decide("https", "203.0.113.5") == .deny)
        #expect(decide("https", "192.168.11.233", 8766, .microphone) == .deny)
        #expect(decide("https", "192.168.11.233", 8766, .cameraAndMicrophone) == .deny)
    }

    @Test func anotherProgramOnTheStudiosComputerIsAnotherSite() {
        #expect(decide("https", "192.168.11.233", 8765) == .deny)
        #expect(decide("http", "192.168.11.233", 8766) == .deny)
        #expect(decide("HTTPS", "192.168.11.233", 8766) == .grant)
    }

    @Test func aStudioOnTheDefaultPortMatchesWebKitsZero() {
        let plain = URL(string: "https://studio.example/")!
        #expect(StudioPage.mediaDecision(scheme: "https", host: "studio.example", port: 0, studio: plain, type: .camera) == .grant)
        #expect(StudioPage.mediaDecision(scheme: "https", host: "studio.example", port: 443, studio: plain, type: .camera) == .grant)
        #expect(StudioPage.mediaDecision(scheme: "https", host: "studio.example", port: 8766, studio: plain, type: .camera) == .deny)
    }
}

// MARK: - naming a scan

@Suite("Naming a scan")
struct ScanNames {
    func record(_ subject: Subject = .leftSole, name: String? = nil) -> ScanRecord {
        var r = ScanRecord(subject: subject, created: Date(timeIntervalSince1970: 1_700_000_000), device: "iPhone16,1",
                           systemVersion: "18.1", appVersion: "1.0")
        r.name = name
        return r
    }

    @Test func aTypedNameIsTidiedAndAnEmptyOneMeansNoName() {
        #expect(ScanRecord.cleanName("  Sam,   left foot ") == "Sam, left foot")
        #expect(ScanRecord.cleanName("   ") == nil)
        #expect(ScanRecord.cleanName("") == nil)
        #expect(ScanRecord.cleanName(String(repeating: "a", count: 60))?.count == ScanRecord.nameLimit)
        // cut at 40 just after a space: the space goes too
        #expect(ScanRecord.cleanName(String(repeating: "a", count: 39) + " b") == String(repeating: "a", count: 39))
    }

    @Test func theCardShowsTheNameElseWhatWasScanned() {
        #expect(record().heading == "Left sole")
        #expect(record(name: "Sam").heading == "Sam")
    }

    @Test func aNewerScanReplacesAnOlderOneOnlyForTheSameNamedFoot() {
        #expect(record().sameFoot(as: record()))
        #expect(record(name: "Sam").sameFoot(as: record(name: "Sam")))
        #expect(!record(name: "Sam").sameFoot(as: record()))  // someone else's left sole
        #expect(record(name: "Zoë").sameFoot(as: record(name: "zoe")))  // capitals and accents don't matter
        #expect(!record(.rightSole).sameFoot(as: record()))
    }

    @Test func aRecordSavedBeforeNamesStillReads() throws {
        let json = #"{"subject":"left-sole","created":"2026-11-01T10:00:00Z","device":"iPhone16,1","systemVersion":"18.1","appVersion":"1.0","modelBuiltOnPhone":false,"units":"m","note":"x"}"#
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        let r = try dec.decode(ScanRecord.self, from: Data(json.utf8))
        #expect(r.name == nil)
        #expect(r.heading == "Left sole")
    }
}

// MARK: - a capture that stopped by itself

@Suite("A capture that stopped by itself")
struct CaptureStoppedWords {
    @Test func photosSavedSoFarAreSaidToBeKeptAndTheErrorComesLast() {
        let w = CaptureStopped.words(photos: 37, error: "Session interrupted", free: 5_000_000_000, hot: false)
        #expect(w.body.hasPrefix("The 37 photos taken so far are kept"))
        #expect(w.cause == nil)
        #expect(w.detail == "What the phone said: Session interrupted")
    }

    @Test func withNoPhotosNothingIsSaidToBeKeptAndOnePhotoIsNotEnough() {
        #expect(CaptureStopped.words(photos: 0, error: "x", free: nil, hot: false).body.hasPrefix("No photos were saved"))
        #expect(CaptureStopped.words(photos: 1, error: "x", free: nil, hot: false).body.hasPrefix("The 1 photo taken so far is kept"))
    }

    @Test func aHotPhoneIsNamedBeforeSpace() {
        let w = CaptureStopped.words(photos: 5, error: "x", free: 100_000_000, hot: true)
        #expect(w.cause?.hasPrefix("The phone is hot") == true)
    }

    @Test func spaceIsNamedOnlyWhenThePhoneIsNearlyFull() {
        // under the 1.5 GB a capture asks for at the start, but not nearly full: not blamed
        #expect(CaptureStopped.words(photos: 5, error: "x", free: 1_200_000_000, hot: false).cause == nil)
        #expect(CaptureStopped.words(photos: 5, error: "x", free: 100_000_000, hot: false).cause?.hasPrefix("The phone is nearly full") == true)
        #expect(CaptureStopped.words(photos: 5, error: "x", free: nil, hot: false).cause == nil)
    }
}

// MARK: - the model's files

@Suite("Saving the model's files")
struct ModelFiles {
    func folder() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appending(path: "model-files-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// A single triangle, as a model Model I/O can read (SYNTHETIC: test geometry only).
    func triangle(in dir: URL) throws -> URL {
        let url = dir.appending(path: "source.obj")
        try "v 0 0 0\nv 0.1 0 0\nv 0 0 0.1\nf 1 2 3\n".write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    @Test func theExportLandsWholeAndLeavesNoWorkingFolder() throws {
        let dir = try folder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let out = dir.appending(path: "model.obj")
        try ModelBuilder.exportOBJ(from: try triangle(in: dir), to: out)
        let text = try String(contentsOf: out, encoding: .utf8)
        #expect(text.contains("v "))
        #expect(!FileManager.default.fileExists(atPath: dir.appending(path: ".obj-export").path()))
    }

    @Test func aFailedExportLeavesNoModelObjNotEvenAnEarlierOne() throws {
        let dir = try folder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let out = dir.appending(path: "model.obj")
        try "v 9 9 9\n".write(to: out, atomically: true, encoding: .utf8) // from an earlier model
        #expect(throws: (any Error).self) { try ModelBuilder.exportOBJ(from: dir.appending(path: "missing.usdz"), to: out) }
        #expect(!FileManager.default.fileExists(atPath: out.path()))
        #expect(!FileManager.default.fileExists(atPath: dir.appending(path: ".obj-export").path()))
    }

    @Test func workingFilesACutOffBuildLeftAreClearedAndTheModelStays() throws {
        let dir = try folder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let model = dir.appending(path: "model.usdz")
        try Data("model".utf8).write(to: model)
        try Data("half".utf8).write(to: dir.appending(path: ModelBuilder.buildingName))
        let export = dir.appending(path: ModelBuilder.exportFolderName, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: export, withIntermediateDirectories: true)
        try Data("half".utf8).write(to: export.appending(path: "model.obj"))
        ModelBuilder.clearLeftovers(in: dir)
        #expect(!FileManager.default.fileExists(atPath: dir.appending(path: ModelBuilder.buildingName).path()))
        #expect(!FileManager.default.fileExists(atPath: export.path()))
        #expect(FileManager.default.fileExists(atPath: model.path()))
    }

    @Test func puttingAFileInPlaceReplacesWhatWasThere() throws {
        let dir = try folder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let old = dir.appending(path: "model.usdz"), new = dir.appending(path: "model-building.usdz")
        try Data("old".utf8).write(to: old)
        try Data("new".utf8).write(to: new)
        try ModelBuilder.putInPlace(new, at: old)
        #expect(try Data(contentsOf: old) == Data("new".utf8))
        #expect(!FileManager.default.fileExists(atPath: new.path()))
    }
}

// MARK: - the Photos + mat page failing

@Suite("The Photos + mat page failing")
struct PhotoPageFailing {
    let cancel = NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled)
    let interrupted = NSError(domain: "WebKitErrorDomain", code: 102)
    let timedOut = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut)

    func said(_ e: Error, shown: Bool, pin: Bool = false) -> String? {
        PhotoPageWords.failure(e, pageShown: shown, pinRefused: pin, studio: "192.168.11.233 (home Wi-Fi)")
    }

    @Test func aCancelWithTheStudiosPageShowingSaysNothing() {
        #expect(said(cancel, shown: true) == nil)
        #expect(said(interrupted, shown: true) == nil)  // a link sent to Safari
    }

    @Test func aCancelBeforeThePageEverShowedIsSaidAsUnreachable() {
        // nothing would be on screen: say something and offer Try again
        #expect(said(cancel, shown: false)?.hasPrefix("Couldn't reach the studio") == true)
        #expect(said(interrupted, shown: false)?.hasPrefix("Couldn't reach the studio") == true)
    }

    @Test func aRefusedCertificateIsSaidAsSuchNotSwallowedAsACancel() {
        #expect(said(cancel, shown: false, pin: true)?.contains("different certificate") == true)
        #expect(said(cancel, shown: true, pin: true)?.contains("different certificate") == true)
    }

    @Test func aDropIsUnreachableWhetherOrNotThePageHadShown() {
        #expect(said(timedOut, shown: false)?.hasPrefix("Couldn't reach the studio") == true)
        #expect(said(timedOut, shown: true)?.hasPrefix("Couldn't reach the studio") == true)
    }

    @Test func aStoppedPageSaysWhatIsKeptAndWhatIsGone() {
        #expect(PhotoPageWords.pageStopped.contains("already saved to the studio are kept"))
        #expect(PhotoPageWords.pageStopped.contains("not yet saved are gone"))
    }
}

// MARK: - a connect code read from a picture

@Suite("A connect code read from a picture")
struct CodeFromAPicture {
    /// A QR code of `text`, as the studio draws one, scaled up as a screenshot would show it.
    func qr(_ text: String) -> CIImage {
        let filter = CIFilter(name: "CIQRCodeGenerator")!
        filter.setValue(Data(text.utf8), forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        return filter.outputImage!.transformed(by: CGAffineTransform(scaleX: 12, y: 12))
    }

    @Test func theStudiosCodeIsReadFromAPictureOfIt() {
        let code = "footscan-capture://connect?url=https%3A%2F%2F192.168.11.233%3A8766&key=SYNTHETIC-test-key"
        #expect(CodeInPicture.codes(in: qr(code)) == [code])
    }

    @Test func theStudiosCodeIsReadFromAPictureFilesBytes() async throws {
        let code = "footscan-capture://connect?url=https%3A%2F%2F192.168.11.233%3A8766&key=SYNTHETIC-test-key"
        let png = try #require(CIContext().pngRepresentation(of: qr(code), format: .RGBA8,
                                                              colorSpace: CGColorSpaceCreateDeviceRGB()))
        #expect(await CodeInPicture.codes(inPicture: png) == [code])
        #expect(await CodeInPicture.codes(inPicture: Data("not a picture".utf8)) == nil)
    }

    @Test func aPictureWithNoCodeReadsNothing() {
        let blank = CIImage(color: .white).cropped(to: CGRect(x: 0, y: 0, width: 400, height: 400))
        #expect(CodeInPicture.codes(in: blank).isEmpty)
    }
}

// MARK: - free space

@Suite("Free space before a capture")
struct FreeSpace {
    @Test func enoughRoomSaysNothing() {
        #expect(DiskSpace.captureProblem(free: DiskSpace.neededForCapture) == nil)
        #expect(DiskSpace.captureProblem(free: 50_000_000_000) == nil)
    }

    @Test func tooLittleRoomSaysHowMuchIsFree() throws {
        let message = try #require(DiskSpace.captureProblem(free: 300_000_000))
        #expect(message.contains(ByteCountFormatter.string(fromByteCount: 300_000_000, countStyle: .file)))
        #expect(message.localizedCaseInsensitiveContains("delete"))
    }

    @Test func unknownFreeSpaceDoesNotBlockScanning() {
        #expect(DiskSpace.captureProblem(free: nil) == nil)
    }

    /// A scan folder with a file in Checkpoint, and (`built`) its model and studio copy.
    private func scan(_ name: String, in root: URL, built: Bool) throws -> Scan {
        let scan = Scan(folder: root.appending(path: name, directoryHint: .isDirectory))
        try FileManager.default.createDirectory(at: scan.checkpoint, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: scan.images, withIntermediateDirectories: true)
        try Data(count: 1000).write(to: scan.checkpoint.appending(path: "work.bin"))
        try Data(count: 10).write(to: scan.images.appending(path: "IMG_0.HEIC"))
        if built {
            try Data(count: 10).write(to: scan.usdz)
            try Data(count: 10).write(to: scan.obj)
        }
        return scan
    }

    @Test func onlyBuiltModelsWorkingDataCanGoAndThePhotosAndModelStay() throws {
        let root = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        defer { try? FileManager.default.removeItem(at: root) }
        let built = try scan("built", in: root, built: true)
        let waiting = try scan("waiting", in: root, built: false)
        // a scan still waiting for its model needs its working data to build it
        #expect(ScanLibrary.workingDataToRemove([built, waiting]) == [built.checkpoint])
        #expect(ScanLibrary.bytes(in: ScanLibrary.workingDataToRemove([built, waiting])) == 1000)
        // once emptied there's nothing more to remove; the folder itself, the photos and the model are still there,
        // and the other scan's working data wasn't touched
        ScanLibrary.empty(ScanLibrary.workingDataToRemove([built, waiting]))
        #expect(ScanLibrary.workingDataToRemove([built, waiting]).isEmpty)
        #expect(FileManager.default.fileExists(atPath: built.checkpoint.path(percentEncoded: false)))
        #expect(built.hasModel && built.hasOBJ && built.photoCount == 1)
        #expect(ScanLibrary.bytes(in: [waiting.checkpoint]) == 1000)
    }
}

// MARK: - the welcome scene's ring

@Suite("Drag the phone round the foot")
@MainActor
struct Ring {
    @Test func positionsMapToTheTwelveSides() {
        #expect(OrbitModel.side(0) == 0)
        #expect(OrbitModel.side(0.999) == 11)
        #expect(OrbitModel.side(1.04) == 0)    // wraps round
        #expect(OrbitModel.side(-0.04) == 11)  // and backwards
    }

    @Test func aFastDragCannotSkipASide() {
        let model = OrbitModel()
        model.drag(to: 0.01)
        model.drag(to: 0.45) // nearly half a turn in one jump
        #expect(model.lit == Set(0...5))
    }

    @Test func aFullCircleLightsEverythingAndCelebrates() {
        let model = OrbitModel()
        for k in 0...24 { model.drag(to: Double(k) / 24) }
        #expect(model.lit.count == OrbitModel.sides)
        #expect(model.celebrateUntil > Date())
    }

    @Test func goingTheShortWayRoundBackwards() {
        let model = OrbitModel()
        model.drag(to: 0.05)
        model.drag(to: 0.95) // back across the join, not forward round the long way
        #expect(model.lit == [0, 11])
    }
}

// MARK: - the scale reading

@Suite("Scale reading in kg or lb")
struct ScaleReadingTests {
    @Test func poundsAreSentAsKilograms() {
        // 150 lb is 68.04 kg: typed with the box on lb, the studio must not get 150 kg
        #expect(ScaleReading.kilograms("150", unit: .lb) == 68.04)
        #expect(ScaleReading.kilograms("150", unit: .kg) == 150)
    }

    @Test func aCommaIsADecimalMark() {
        #expect(ScaleReading.kilograms("68,5", unit: .kg) == 68.5)
        #expect(ScaleReading.kilograms(" 68.5 ", unit: .kg) == 68.5)
        #expect(ScaleReading.kilograms("68.5\n", unit: .kg) == 68.5) // pasted with its line end
        #expect(ScaleReading.kilograms(".5", unit: .kg) == 0.5)
    }

    @Test func onlyPlainNumbersAreReadings() {
        // Double() reads these too: pasted text mustn't become a load
        #expect(ScaleReading.kilograms("0x40", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("6.85e1", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("1.2.3", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("+68", unit: .kg) == nil)
    }

    @Test func readingsTheStudioWouldRefuseAreNotTaken() {
        #expect(ScaleReading.kilograms("", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("abc", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("0", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("-5", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("400", unit: .kg) == nil)
        #expect(ScaleReading.kilograms("inf", unit: .kg) == nil)
        // 880 lb is 399.2 kg, so it's taken in lb; 900 lb (408 kg) is not
        #expect(ScaleReading.kilograms("880", unit: .lb) != nil)
        #expect(ScaleReading.kilograms("900", unit: .lb) == nil)
    }

    @Test func aSavedReadingShowsBackAsTyped() {
        let kg = ScaleReading.kilograms("150", unit: .lb)!
        #expect(ScaleReading.text(kilograms: kg, unit: .lb) == "150")
        #expect(ScaleReading.text(kilograms: 68.5, unit: .kg) == "68.5")
        #expect(ScaleReading.text(kilograms: 70, unit: .kg) == "70")
        // sending a reopened scan again sends the same number, not one rounded on the way into the box
        #expect(ScaleReading.kilograms(ScaleReading.text(kilograms: 68.25, unit: .kg), unit: .kg) == 68.25)
        #expect(ScaleReading.kilograms(ScaleReading.text(kilograms: kg, unit: .lb), unit: .lb) == kg)
    }

    @Test func theLineUnderTheBoxShowsWhatIsSent() {
        #expect(ScaleReading.sentAs(ScaleReading.kilograms("150", unit: .lb)!) == "Sent to the studio as 68.04 kg")
    }

    @Test func theDetailsRowGivesKilogramsAndPoundsWhenOnPounds() {
        #expect(ScaleReading.detail(kilograms: 68.04, unit: .kg) == "68.04 kg")
        #expect(ScaleReading.detail(kilograms: 68.04, unit: .lb) == "68.04 kg (150 lb)")
    }

    @Test func theUnitStartsFromThePhonesRegion() {
        #expect(ScaleUnit.usual(for: Locale(identifier: "en_US")) == .lb)
        #expect(ScaleUnit.usual(for: Locale(identifier: "en_GB")) == .kg)
        #expect(ScaleUnit.usual(for: Locale(identifier: "de_DE")) == .kg)
    }
}

// MARK: - keeping the screen on

@MainActor
@Suite("Screen kept on", .serialized)
struct ScreenKeptOn {
    @Test func theScreenStaysOnUntilEveryClaimIsLetGo() {
        let photoPage = KeepAlive.screen()
        let upload = KeepAlive.screen()
        #expect(UIApplication.shared.isIdleTimerDisabled)
        photoPage()
        #expect(UIApplication.shared.isIdleTimerDisabled) // the upload still holds it
        upload()
        #expect(!UIApplication.shared.isIdleTimerDisabled)
    }

    @Test func lettingGoTwiceCountsOnce() {
        let other = KeepAlive.screen()
        let page = KeepAlive.screen()
        page()
        page() // a second onDisappear mustn't release someone else's claim
        #expect(UIApplication.shared.isIdleTimerDisabled)
        other()
        #expect(!UIApplication.shared.isIdleTimerDisabled)
    }
}

// MARK: - Settings

@Suite("Delete all says what is lost")
struct DeleteAllWarning {
    @Test func scansOnlyOnThisPhoneAreCounted() {
        #expect(DeleteAllWords.message(total: 5, unsent: 2)
                == "2 of them haven't been sent to the studio: their photos and models will be gone for good. Copies already in the studio stay there.")
        #expect(DeleteAllWords.message(total: 5, unsent: 1).hasPrefix("1 of them hasn't been sent"))
    }

    @Test func allSentSaysTheStudioKeepsThem() {
        #expect(DeleteAllWords.message(total: 3, unsent: 0) == "Copies already in the studio stay there.")
    }

    @Test func noneSentSaysAllAreGone() {
        #expect(DeleteAllWords.message(total: 3, unsent: 3).hasPrefix("None of them has been sent"))
        #expect(DeleteAllWords.message(total: 1, unsent: 1) == "It hasn't been sent to the studio: its photos and model will be gone for good.")
    }

    @Test func theVersionShowsItsBuildNumber() {
        #expect(AppVersion.shown(version: "1.0", build: "3") == "1.0 (3)")
        #expect(AppVersion.shown(version: "1.0", build: "1.0") == "1.0")
        #expect(AppVersion.shown(version: "1.0", build: nil) == "1.0")
        #expect(AppVersion.shown(version: nil, build: "3") == "?")
    }
}

// MARK: - a link to another studio

@Suite("A link to a different studio asks first")
struct OtherStudioLinks {
    let pinA = String(repeating: "a", count: 64)
    let pinB = String(repeating: "b", count: 64)

    func link(_ address: String, fp: String?, alt: [String] = []) -> StudioLink {
        StudioLink(url: URL(string: address)!, fingerprint: fp, alternates: alt.map { URL(string: $0)! })
    }

    @Test func theSameCertificateIsTheSameStudioAtAnyAddress() {
        let home = link("https://192.168.1.20:8766", fp: pinA)
        #expect(home.isSameStudio(as: link("https://100.113.53.83:8766", fp: pinA.uppercased())))
        #expect(!home.isSameStudio(as: link("https://192.168.1.20:8766", fp: pinB))) // a new certificate: ask
    }

    @Test func withoutPinsAnAddressInCommonIsTheSameStudio() {
        let home = link("https://192.168.1.20:8766", fp: nil, alt: ["https://100.113.53.83:8766"])
        #expect(home.isSameStudio(as: link("https://100.113.53.83:8766", fp: nil)))
        #expect(!home.isSameStudio(as: link("https://192.168.1.99:8766", fp: nil)))
        // written another way, the same address: capitals in the host, the port left out where it's 443
        let named = link("https://studio.example.dev", fp: nil)
        #expect(named.isSameStudio(as: link("https://Studio.example.dev:443/", fp: nil)))
        #expect(!home.isSameStudio(as: link("https://192.168.1.20:8766", fp: pinA))) // one pinned, one not: ask
    }

    @Test func onlyACodeForAnotherStudioIsAskedAbout() {
        let code = { (address: String, pin: String) in "footscan-capture://connect?url=\(address)&key=k&fp=\(pin)" }
        let home = link("https://192.168.1.20:8766", fp: pinA)
        let other = code("https://192.168.1.99:8766", pinB)
        #expect(StudioConnection.otherStudio(in: other, connected: nil) == nil)                   // nothing connected yet
        #expect(StudioConnection.otherStudio(in: code("https://192.168.1.20:8766", pinA), connected: home) == nil) // same one
        #expect(StudioConnection.otherStudio(in: "not a code", connected: home) == nil)            // connect() says why
        #expect(StudioConnection.otherStudio(in: other, connected: home) == "192.168.1.99 (home Wi-Fi)")
    }

    @Test func aQuestionLeftUnseenForMinutesIsDropped() {
        // opened while a capture covered the screen: it mustn't turn up out of the blue much later
        let asked = Date(timeIntervalSince1970: 1_800_000_000)
        #expect(StudioConnection.stillAsking(since: asked, now: asked + 60))
        #expect(!StudioConnection.stillAsking(since: asked, now: asked + StudioConnection.switchQuestionLasts))
        #expect(!StudioConnection.stillAsking(since: asked, now: asked - 60)) // the clock went back
    }
}
