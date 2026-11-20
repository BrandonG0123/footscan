// The phone's own check of a model it built (ScanCheck): a scan it can already
// tell won't make a good insole says "scan again" before it's sent.
//
// Every shape here is SYNTHETIC, built below (the app's tests can't run the
// studio's tests/synth.py): the plan of synth.shaped_foot (heel, ball and toes
// as three circles in a rubber band, 250 x 100 mm, heel 64 mm wide), 25 mm
// thick, with a leg standing over the heel, turned the way the phone hands a
// sole-up scan over. Real scans: ios/tools/scan-check.swift.
import Foundation
import Testing
@testable import FootscanCapture

private typealias V2 = SIMD2<Double>
private typealias V3 = SIMD3<Double>

private enum Shapes {
    /// The plan of synth.shaped_foot, shifted `dy` mm across.
    static func footPlan(dy: Double = 0) -> [V2] {
        hull(circle(V2(32, 45 + dy), 32) + circle(V2(165, 45 + dy), 50) + circle(V2(222, 45 + dy), 28))
    }

    static func circle(_ c: V2, _ r: Double) -> [V2] {
        (0..<72).map { k in c + V2(cos(Double(k) * .pi / 36), sin(Double(k) * .pi / 36)) * r }
    }

    /// The rubber band round `pts`, counter-clockwise (Andrew's monotone chain).
    static func hull(_ pts: [V2]) -> [V2] {
        let p = pts.sorted { $0.x != $1.x ? $0.x < $1.x : $0.y < $1.y }
        func turn(_ o: V2, _ a: V2, _ b: V2) -> Double { (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x) }
        var lower: [V2] = [], upper: [V2] = []
        for q in p {
            while lower.count >= 2 && turn(lower[lower.count - 2], lower[lower.count - 1], q) <= 0 { lower.removeLast() }
            lower.append(q)
        }
        for q in p.reversed() {
            while upper.count >= 2 && turn(upper[upper.count - 2], upper[upper.count - 1], q) <= 0 { upper.removeLast() }
            upper.append(q)
        }
        return Array(lower.dropLast() + upper.dropLast())
    }

    /// Inside a convex, counter-clockwise outline.
    static func inside(_ poly: [V2], _ p: V2) -> Bool {
        for i in poly.indices {
            let a = poly[i], b = poly[(i + 1) % poly.count]
            if (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) < 0 { return false }
        }
        return true
    }

    /// A closed solid in foot coordinates (mm, z up): every `cell` square whose centre `inside` says is in, from
    /// `bottom` up to `top` (each read at the square's corners, so neighbouring squares share their corners).
    static func solid(x: ClosedRange<Double>, y: ClosedRange<Double>, cell: Double = 2.5,
                      inside: (V2) -> Bool, top: (V2) -> Double, bottom: (V2) -> Double = { _ in 0 }) -> ScanCheck.Mesh {
        let nx = Int(((x.upperBound - x.lowerBound) / cell).rounded(.up))
        let ny = Int(((y.upperBound - y.lowerBound) / cell).rounded(.up))
        func at(_ i: Int, _ j: Int) -> V2 { V2(x.lowerBound + Double(i) * cell, y.lowerBound + Double(j) * cell) }
        var cells = Set<SIMD2<Int>>()
        for i in 0..<nx { for j in 0..<ny where inside(at(i, j) + cell / 2) { cells.insert(SIMD2(i, j)) } }
        var points: [V3] = []
        var index: [SIMD3<Int>: Int] = [:]
        func v(_ i: Int, _ j: Int, _ upper: Int) -> Int {
            if let k = index[SIMD3(i, j, upper)] { return k }
            let p = at(i, j)
            points.append(V3(p.x, p.y, upper == 1 ? top(p) : bottom(p)))
            index[SIMD3(i, j, upper)] = points.count - 1
            return points.count - 1
        }
        var faces: [(Int, Int, Int)] = []
        // corners counter-clockwise seen from outside, so every normal points out
        func quad(_ a: Int, _ b: Int, _ c: Int, _ d: Int) { faces.append((a, b, c)); faces.append((a, c, d)) }
        for c in cells {
            let i = c.x, j = c.y
            quad(v(i, j, 1), v(i + 1, j, 1), v(i + 1, j + 1, 1), v(i, j + 1, 1))
            quad(v(i, j, 0), v(i, j + 1, 0), v(i + 1, j + 1, 0), v(i + 1, j, 0))
            if !cells.contains(SIMD2(i, j - 1)) { quad(v(i, j, 0), v(i + 1, j, 0), v(i + 1, j, 1), v(i, j, 1)) }
            if !cells.contains(SIMD2(i, j + 1)) { quad(v(i + 1, j + 1, 0), v(i, j + 1, 0), v(i, j + 1, 1), v(i + 1, j + 1, 1)) }
            if !cells.contains(SIMD2(i - 1, j)) { quad(v(i, j + 1, 0), v(i, j, 0), v(i, j, 1), v(i, j + 1, 1)) }
            if !cells.contains(SIMD2(i + 1, j)) { quad(v(i + 1, j, 0), v(i + 1, j + 1, 0), v(i + 1, j + 1, 1), v(i + 1, j, 1)) }
        }
        return ScanCheck.Mesh(points: points, faces: faces)
    }

    /// A right foot (x heel to toes, y toward its inner side, z up), 25 mm thick, with a 28 mm leg over the heel
    /// standing 140 mm. `keep` cuts the plan (a missing end, closed over as Object Capture closes it).
    static func foot(plan: [V2] = Shapes.footPlan(), keep: (V2) -> Bool = { _ in true }, legs: [V2] = [V2(45, 45)]) -> ScanCheck.Mesh {
        solid(x: -5...260, y: -60...170, inside: { inside(plan, $0) && keep($0) },
              top: { p in legs.contains { length(p - $0) < 28 } ? 140 : 25 })
    }

    /// Both feet in the box, side by side and touching at the ball, one piece.
    static func twoFeet() -> ScanCheck.Mesh {
        let right = footPlan(), left = footPlan(dy: 98)
        return solid(x: -5...260, y: -60...200, inside: { inside(right, $0) || inside(left, $0) },
                     top: { p in [V2(45, 45), V2(45, 143)].contains { length(p - $0) < 28 } ? 140 : 25 })
    }

    /// The forefoot rolled onto its outer edge (the inner side up) by `deg`, about that edge (y = -5), building
    /// across the midfoot (x 110-140), as tests/test_insole.py's _rolled_forefoot_scan.
    static func rolled(_ m: ScanCheck.Mesh, deg: Double) -> ScanCheck.Mesh {
        var out = m
        out.points = m.points.map { p in
            let a = deg * .pi / 180 * min(1, max(0, (p.x - 110) / 30))
            let dy = p.y + 5, dz = p.z
            return V3(p.x, -5 + dy * cos(a) - dz * sin(a), dy * sin(a) + dz * cos(a))
        }
        return out
    }

    /// As the phone hands a sole-up scan over (synth.sole_up_capture): toes pointing down `pitch` degrees (a
    /// relaxed foot), turned `sideways` about its length, sole up, turned `yaw` about the vertical, Y up. Millimetres.
    static func soleUp(_ m: ScanCheck.Mesh, pitch: Double = 25, sideways: Double = 0, yaw: Double = 63) -> ScanCheck.Mesh {
        let p = pitch * .pi / 180, s = sideways * .pi / 180, w = yaw * .pi / 180
        var out = m
        out.points = m.points.map { q in
            var v = V3(q.x * cos(p) + q.z * sin(p), q.y, -q.x * sin(p) + q.z * cos(p))       // toes down
            let dy = v.y - 45
            v = V3(v.x, 45 + dy * cos(s) - v.z * sin(s), dy * sin(s) + v.z * cos(s))        // turned on its side
            v = V3(v.x, -v.y, -v.z)                                                          // sole up
            v = V3(v.x * cos(w) - v.y * sin(w), v.x * sin(w) + v.y * cos(w), v.z)          // turned round
            return V3(v.x + 40, v.z + 7, -(v.y - 25))                                        // Y up
        }
        return out
    }

    /// Something lying on a table, from foot coordinates to the phone's (Y up).
    static func onTable(_ m: ScanCheck.Mesh) -> ScanCheck.Mesh {
        var out = m
        out.points = m.points.map { V3($0.x, $0.z, -$0.y) }
        return out
    }

    static func length(_ v: V2) -> Double { (v * v).sum().squareRoot() }
}

private func codes(_ m: ScanCheck.Mesh) throws -> [String] {
    let measured = try #require(ScanCheck.SoleUp.measure(m))
    return ScanCheck.SoleUp.findings(measured).map(\.code)
}

@Suite("Phone's own scan check: sole up")
struct SoleUpCheck {
    @Test(arguments: [(25.0, 63.0), (25.0, 10.0), (45.0, 200.0), (10.0, -30.0)])
    func aWholeFootPassesHoweverItWasTurned(_ pitch: Double, _ yaw: Double) throws {
        let m = try #require(ScanCheck.SoleUp.measure(Shapes.soleUp(Shapes.foot(), pitch: pitch, yaw: yaw)))
        #expect(ScanCheck.SoleUp.findings(m).isEmpty, "\(m)")
        #expect(abs(m.lengthMM - 250) <= 6 && abs(m.widthMM - 100) <= 6, "\(m)")
        #expect(abs(m.pitchDeg.magnitude - pitch) <= 3 && abs(m.sidewaysDeg) <= 8, "\(m)")
    }

    @Test(arguments: [35.0, -35.0])
    func aSoleFacingTheSideSaysScanAgainWithTheSoleUp(_ sideways: Double) throws {
        // the cousin's real scan of 17 Nov 2026 read 40 degrees this way (scratch run of the same steps in Python)
        let m = try #require(ScanCheck.SoleUp.measure(Shapes.soleUp(Shapes.foot(), sideways: sideways)))
        #expect(abs(m.sidewaysDeg) > ScanCheck.SoleUp.sidewaysDeg, "\(m)")
        let found = ScanCheck.SoleUp.findings(m)
        #expect(found.map(\.code) == ["sole_not_up"])   // alone: the rest is measured from a floor that's wrong
        #expect(found.allSatisfy(\.scanAgain) && found.first?.steps.contains { $0.contains("ceiling") } == true)
    }

    @Test func aSoleTurnedALittleIsLeftAlone() throws {
        #expect(try codes(Shapes.soleUp(Shapes.foot(), sideways: 10)) == [])
    }

    @Test func toesCutOffAreCaught() throws {
        #expect(try codes(Shapes.soleUp(Shapes.foot(keep: { $0.x < 200 }))) == ["toes_missing"])
    }

    @Test func aHeelCutOffIsCaught() throws {
        #expect(try codes(Shapes.soleUp(Shapes.foot(keep: { $0.x > 15 }))) == ["heel_cut_off"])
    }

    @Test func bothFeetInTheBoxAreNotOneFoot() throws {
        #expect(try codes(Shapes.soleUp(Shapes.twoFeet())) == ["not_one_foot"])
    }

    @Test func aRolledForefootIsCaughtAndASlightRollIsNot() throws {
        let rolled = try #require(ScanCheck.SoleUp.measure(Shapes.soleUp(Shapes.rolled(Shapes.foot(), deg: 15))))
        #expect(ScanCheck.SoleUp.findings(rolled).map(\.code) == ["forefoot_rolled"], "\(rolled)")
        let slight = try #require(ScanCheck.SoleUp.measure(Shapes.soleUp(Shapes.rolled(Shapes.foot(), deg: 5))))
        #expect(ScanCheck.SoleUp.findings(slight).isEmpty, "\(slight)")
    }

    @Test func tooLittleOfAFootToMeasureSaysScanAgain() throws {
        let scrap = Shapes.solid(x: 0...20, y: 0...20, cell: 10, inside: { _ in true }, top: { _ in 5 })
        #expect(ScanCheck.SoleUp.measure(Shapes.soleUp(scrap)) == nil)
        let url = try writeOBJ(Shapes.soleUp(scrap))
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(try ScanCheck.run(obj: url, kind: .soleUp).findings.map(\.code) == ["foot_not_found"])
    }

    @Test func theModelIsReadFromTheOBJThePhoneSavesInMetres() throws {
        let scan = Shapes.soleUp(Shapes.foot())
        let url = try writeOBJ(scan)
        defer { try? FileManager.default.removeItem(at: url) }
        let read = try ScanCheck.run(obj: url, kind: .soleUp)
        let direct = try #require(ScanCheck.SoleUp.measure(scan))
        #expect(read.findings.isEmpty)
        // the same to within a 2 mm square and a fraction of a degree (millimetres written as metres and read back)
        #expect(abs((read.measures["length_mm"] ?? 0) - direct.lengthMM) <= 2)
        #expect(abs((read.measures["sideways_deg"] ?? 99) - direct.sidewaysDeg) <= 0.6)
    }

    @Test func aFaceWithMoreCornersAndOtherIndicesIsRead() throws {
        let url = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).obj")
        defer { try? FileManager.default.removeItem(at: url) }
        try """
        # Apple ModelIO OBJ File: model
        v 0 0 0
        v 0.1 0 0
        v 0.1 0 0.1
        v 0 0 0.1
        vt 0 0
        vn 0 1 0
        f 1/1/1 2/1/1 3/1/1 4/1/1
        f -4 -2 -1
        f 1 2 9
        """.write(to: url, atomically: true, encoding: .utf8)
        let m = try ScanCheck.Mesh.readOBJ(url)
        #expect(m.points.count == 4)
        #expect(m.faces.count == 3)  // the square as two, the negative one, and not the one past the end
        let corner = m.inMillimetres().points[2]
        #expect(abs(corner.x - 100) < 1e-9 && corner.y == 0 && abs(corner.z - 100) < 1e-9)
    }
}

@Suite("Phone's own scan check: things on a table")
struct UndersideCheck {
    // the calibration block's size, 150 x 70, 35 mm high (src/footscan/recon/calib.py)
    private func block(bottom: @escaping (V2) -> Double = { _ in 0 }) -> ScanCheck.Mesh {
        Shapes.onTable(Shapes.solid(x: 0...150, y: 0...70, inside: { _ in true }, top: { _ in 35 }, bottom: bottom))
    }

    /// A made-up wedge under it, as on the real scan of 17 Nov 2026: down to 34 mm below the base along the middle.
    private var wedged: ScanCheck.Mesh { block(bottom: { -34 * (1 - abs($0.y - 35) / 35) }) }

    @Test func aFlatUndersideSaysNothing() throws {
        let m = try #require(ScanCheck.Underside.measure(block()))
        #expect(m.flatShare > 0.95)
        #expect(ScanCheck.Underside.findings(m, kind: .calibration).isEmpty)
        #expect(ScanCheck.Underside.findings(m, kind: .shoeInsole).isEmpty)
    }

    @Test func aGuessedUndersideIsFound() throws {
        let m = try #require(ScanCheck.Underside.measure(wedged))
        #expect(m.flatShare < 0.3 && m.depthMM > 20, "\(m)")
        // the block's top still tells the phone's scale: a note, not scan again
        let block = ScanCheck.Underside.findings(m, kind: .calibration)
        #expect(block.map(\.code) == ["underside_guessed"] && !block[0].scanAgain)
        // a shoe's insole is read from its outline on the table: scan again
        let insole = ScanCheck.Underside.findings(m, kind: .shoeInsole)
        #expect(insole.map(\.code) == ["underside_guessed"] && insole[0].scanAgain)
    }
}

@Suite("Phone's own scan check: the scan's record")
struct PhoneCheckRecord {
    private let toes = ScanCheck.Finding(code: "toes_missing", title: "The toes were cut off", detail: "…",
                                         steps: ["Let the toes relax."], scanAgain: true)
    private let note = ScanCheck.Finding(code: "underside_guessed", title: "The phone guessed the block's underside",
                                         detail: "…", steps: [], scanAgain: false)

    @Test func aScanTheCheckSaysToScanAgainIsHeldBackWithItsSteps() {
        var rec = ScanRecord(subject: .leftSole, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        #expect(!rec.heldByPhoneCheck && rec.nextTime.isEmpty)
        rec.phoneCheck = PhoneCheck(version: ScanCheck.version, findings: [toes, note], measures: [:])
        #expect(rec.heldByPhoneCheck)
        #expect(rec.nextTime == [RetakeAdvice(code: "toes_missing", title: "The toes were cut off", steps: ["Let the toes relax."])])
        // Send anyway lets it go (the studio still checks it)
        rec.phoneCheck?.sentAnyway = Date()
        #expect(!rec.heldByPhoneCheck)
    }

    @Test func aNoteAloneHoldsNothingBack() {
        var rec = ScanRecord(subject: .calibration, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        rec.phoneCheck = PhoneCheck(version: ScanCheck.version, findings: [note], measures: [:])
        #expect(!rec.heldByPhoneCheck && rec.nextTime.isEmpty && rec.phoneCheck?.notes == [note])
    }

    @Test func theStudiosRefusalComesBeforeThePhones() {
        var rec = ScanRecord(subject: .rightSole, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        rec.phoneCheck = PhoneCheck(version: ScanCheck.version, findings: [toes], measures: [:])
        let studio = RetakeAdvice(code: "forefoot_rolled", title: "The ball of the foot wasn't level", steps: ["Lay a book."])
        rec.retake = ["THE FOREFOOT WAS ROLLED ONTO ONE EDGE: … Scan again."]
        rec.retakeAdvice = [studio]
        #expect(rec.nextTime == [studio])
    }

    @Test func onlySoleUpScansAndThingsOnATableAreChecked() {
        #expect(Subject.rightSole.checkKind == .soleUp && Subject.leftSole.checkKind == .soleUp)
        #expect(Subject.shoeInsole.checkKind == .shoeInsole && Subject.calibration.checkKind == .calibration)
        for s in [Subject.rightSoleFlat, .leftSoleFlat, .rightPrint, .leftPrint, .rightFoot, .leftFoot, .other] {
            #expect(s.checkKind == nil, "\(s)")
        }
    }

    @Test func theCheckIsKeptWithTheScanAndOlderRecordsStillRead() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString, directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let scan = Scan(folder: dir)
        var rec = ScanRecord(subject: .leftSole, created: Date(), device: "test", systemVersion: "0", appVersion: "0")
        scan.save(rec)
        #expect(scan.record?.phoneCheck == nil)  // saved without the key, as an older app wrote it
        rec.phoneCheck = PhoneCheck(version: ScanCheck.version, findings: [toes], measures: ["length_mm": 201.5])
        scan.save(rec)
        let back = try #require(scan.record?.phoneCheck)
        #expect(back.findings == [toes] && back.measures["length_mm"] == 201.5 && back.sentAnyway == nil)
    }
}

/// The mesh as the phone saves its model: OBJ, in metres.
private func writeOBJ(_ m: ScanCheck.Mesh) throws -> URL {
    var text = "# Apple ModelIO OBJ File: model\n"
    for p in m.points { text += "v \(p.x / 1000) \(p.y / 1000) \(p.z / 1000)\n" }
    for f in m.faces { text += "f \(f.0 + 1)/\(f.0 + 1)/\(f.0 + 1) \(f.1 + 1)/\(f.1 + 1)/\(f.1 + 1) \(f.2 + 1)/\(f.2 + 1)/\(f.2 + 1)\n" }
    let url = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).obj")
    try text.write(to: url, atomically: true, encoding: .utf8)
    return url
}
