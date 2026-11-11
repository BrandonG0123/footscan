// Tests for the iPhone and iPad app's own logic: the parts that don't need a camera.
// Run: xcodebuild test -project FootscanCapture.xcodeproj -scheme FootscanCapture
//      -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
// (and the same with an iPad simulator, e.g. name=iPad Pro 13-inch (M5), for the iPad).
import CoreGraphics
import Foundation
import Testing
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
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer)], pinned: true, device: .phone)
        #expect(text.contains("192.168.11.233 is the studio's home Wi-Fi address"))
        #expect(text.contains("same Wi-Fi"))
        #expect(text.contains("Check Footscan is running"))
        #expect(!text.contains("Mac")) // the studio may be on any computer
    }

    @Test func withTailscaleBothAddressesAreExplainedInOrder() throws {
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer), .init(address: tailnet, miss: .noAnswer)], pinned: true, device: .phone)
        let homeAt = try #require(text.range(of: "192.168.11.233")), tailnetAt = try #require(text.range(of: "100.101.102.103"))
        #expect(homeAt.lowerBound < tailnetAt.lowerBound)
        #expect(text.contains("Tailscale is on"))
    }

    @Test func aDifferentCertificateIsNotCalledUnreachable() {
        let text = StudioClient.Failure.explain([.init(address: tailnet, miss: .wrongCertificate)], pinned: true, device: .phone)
        #expect(text.contains("isn't the studio this phone connected to"))
        #expect(!text.contains("Check Footscan is running")) // something did answer
    }

    @Test func anotherDeviceAtTheHomeAddressOnAnotherWiFiIsSaidToBeAnotherWiFi() {
        // a café's router using 192.168.11.x too: a printer there answers at the studio's home address
        let text = StudioClient.Failure.explain([.init(address: home, miss: .wrongCertificate)], pinned: true, device: .phone)
        #expect(text.contains("another Wi-Fi that uses the same addresses"))
        #expect(!text.contains("Check Footscan is running"))
    }

    @Test func localNetworkAccessIsMentionedOnlyWhenThePhoneHadNoRouteHome() {
        let blocked = StudioClient.Failure.explain([.init(address: home, miss: .noRoute)], pinned: true, device: .phone)
        #expect(blocked.contains("Local Network"))
        let silent = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer)], pinned: true, device: .phone)
        #expect(!silent.contains("Local Network"))
    }

    @Test func aHomeAddressThatDoesntAnswerSuggestsScanningTheCodeAgain() {
        // the router may have given the studio a new address: the old advice to scan the code again stays
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer)], pinned: true, device: .phone)
        #expect(text.contains("Wi-Fi address has changed") && text.contains("scan it again"))
        let away = StudioClient.Failure.explain([.init(address: tailnet, miss: .noAnswer)], pinned: true, device: .phone)
        #expect(!away.contains("Wi-Fi address has changed"))
    }

    @Test func noRouteAnywhereIsPutDownToThePhonesOwnConnection() {
        // abroad with Data Roaming off, Airplane Mode, or mobile data off for the app: no address can be reached
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noRoute), .init(address: tailnet, miss: .noRoute)], pinned: true, device: .phone)
        #expect(text.contains("this phone's own connection") && text.contains("Data Roaming") && text.contains("Airplane Mode"))
        #expect(text.contains("100.101.102.103 is the studio's Tailscale address, but this phone has no connection"))
        #expect(!text.contains("answers from anywhere while Tailscale is on")) // it is on: that's not the problem
        let silent = StudioClient.Failure.explain([.init(address: tailnet, miss: .noAnswer)], pinned: true, device: .phone)
        #expect(!silent.contains("this phone's own connection"))
        // at home with Local Network access refused and Tailscale off: the phone's connection is fine
        let localOnly = StudioClient.Failure.explain([.init(address: home, miss: .noRoute), .init(address: tailnet, miss: .noAnswer)], pinned: true, device: .phone)
        #expect(!localOnly.contains("this phone's own connection") && localOnly.contains("Local Network"))
        // no route to either address: Local Network access can't stop the Tailscale one, so it isn't the cause
        #expect(!text.contains("Local Network"))
        // a code with only the home address and no route there: it may be either, so both are said
        let homeOnly = StudioClient.Failure.explain([.init(address: home, miss: .noRoute)], pinned: true, device: .phone)
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
        let text = StudioClient.Failure.explain([.init(address: home, miss: .noAnswer), .init(address: tailnet, miss: .noAnswer)], pinned: true, device: .phone)
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

// MARK: - on an iPad

@Suite("iPad")
@MainActor
struct OnIPad {
    /// The built app's own Info.plist (tests run inside the app, so this is the app's bundle), read from the
    /// file as built: `Bundle.infoDictionary` resolves "~ipad" keys for the device it runs on, so on an iPad the
    /// plain orientations key would return the iPad's list, and on an iPhone the "~ipad" key would be missing.
    private var info: [String: Any] {
        guard let url = Bundle.main.url(forResource: "Info", withExtension: "plist"), let data = try? Data(contentsOf: url),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
        else { return [:] }
        return plist
    }

    @Test func theAppIsBuiltForIPhoneAndIPad() {
        // UIDeviceFamily 1 is iPhone, 2 is iPad: without 2 an iPad runs it as a magnified iPhone app
        let families = info["UIDeviceFamily"] as? [Int] ?? []
        #expect(Set(families) == [1, 2])
    }

    @Test func anIPadCanHoldItAnyWayRoundAndShareTheScreen() {
        let iPad = Set(info["UISupportedInterfaceOrientations~ipad"] as? [String] ?? [])
        #expect(iPad == ["UIInterfaceOrientationPortrait", "UIInterfaceOrientationPortraitUpsideDown",
                         "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"])
        // full-screen-only is deprecated from iPadOS 26 and ignored by apps built with the iOS 27 SDK:
        // the layout copes with any window size instead
        #expect(info["UIRequiresFullScreen"] as? Bool != true)
        // an iPhone stays portrait: you walk round a foot holding it upright
        #expect(info["UISupportedInterfaceOrientations"] as? [String] == ["UIInterfaceOrientationPortrait"])
    }

    @Test func connectionAdviceNamesTheIPadOnAnIPad() {
        let home = URL(string: "https://192.168.11.233:8766")!, tailnet = URL(string: "https://100.101.102.103:8766")!
        let cases: [[StudioClient.Missed]] = [
            [.init(address: home, miss: .noRoute), .init(address: tailnet, miss: .noRoute)],
            [.init(address: home, miss: .wrongCertificate)],
            [.init(address: tailnet, miss: .wrongCertificate)],
            [.init(address: home, miss: .noAnswer), .init(address: tailnet, miss: .noAnswer)],
            [.init(address: URL(string: "https://studio.example.dev")!, miss: .noRoute)],
        ]
        for misses in cases {
            let text = StudioClient.Failure.explain(misses, pinned: true, device: .pad)
            #expect(text.contains("iPad"), "\(text)")
            #expect(!text.lowercased().contains("phone"), "\(text)")
        }
        // and the same advice on an iPhone still says phone
        #expect(StudioClient.Failure.explain(cases[0], pinned: true, device: .phone).contains("this phone's own connection"))
    }

    @Test func whereThreeDCaptureCantRunItSaysWhichModelsCan() {
        #expect(DeviceKind.pad.needsLiDAR.contains("iPad Pro"))
        #expect(DeviceKind.phone.needsLiDAR.contains("iPhone"))
        #expect(DeviceKind.pad.noun == "iPad" && DeviceKind.phone.noun == "phone")
    }

    @Test func theScanPanelGoesBesideTheCameraOnlyInAWideLandscapeWindow() {
        #expect(CaptureView.panelBeside(CGSize(width: 1376, height: 1032)))   // 13-inch iPad Pro, sideways
        #expect(CaptureView.panelBeside(CGSize(width: 1210, height: 834)))    // 11-inch, sideways
        #expect(!CaptureView.panelBeside(CGSize(width: 1032, height: 1376)))  // upright: panel below
        #expect(!CaptureView.panelBeside(CGSize(width: 402, height: 874)))    // an iPhone
        #expect(!CaptureView.panelBeside(CGSize(width: 600, height: 400)))    // sideways but narrow: no room
    }

    @Test func aWindowSmallerThanTheScreenIsSharingIt() {
        let screen = CGSize(width: 1032, height: 1376)
        #expect(!CaptureView.isSmaller(window: screen, than: screen))
        #expect(!CaptureView.isSmaller(window: CGSize(width: 1376, height: 1032), than: screen)) // full screen, sideways
        #expect(CaptureView.isSmaller(window: CGSize(width: 678, height: 1032), than: screen))   // Split View
        #expect(CaptureView.isSmaller(window: CGSize(width: 320, height: 980), than: screen))    // Slide Over
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
