// Tests for the iPhone app's own logic: the parts that don't need a camera.
// Run: xcodebuild test -project FootscanCapture.xcodeproj -scheme FootscanCapture
//      -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
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
        let parsed = try #require(StudioStore.parse("footscan-capture://connect?url=https://footscan.example.dev&key=k"))
        #expect(parsed.link.fingerprint == nil)
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
        #expect(StudioStore.parse("  footscan-capture://connect?url=https://h&key=k \n") != nil)
    }
}

// MARK: - the studio refusing an incomplete scan

@Suite("Incomplete scans")
struct IncompleteScans {
    @Test func aScanMissingPartOfTheFootIsToldApartFromOtherRefusals() throws {
        let missing = ["THE TOES ARE MISSING: … Scan again with the toes relaxed and flat."]
        let failure = StudioClient.Failure.from(status: 422, json: ["error": "The studio didn't keep this scan", "incomplete": missing])
        guard case .incomplete(let why) = failure else { Issue.record("not read as incomplete: \(failure)"); return }
        #expect(why == missing)
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
