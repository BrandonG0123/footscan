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

    @Test func onlyFeetNeedAScaleReading() {
        #expect(Subject.allCases.filter(\.isFoot) == [.rightFoot, .leftFoot])
    }

    @Test func everyKindHasAGetReadyListAndFootListsMentionTheScale() {
        for s in Subject.allCases { #expect(!s.checklist.isEmpty) }
        for s in Subject.allCases where s.isFoot {
            #expect(s.checklist.contains { $0.1.localizedCaseInsensitiveContains("scale") })
        }
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
