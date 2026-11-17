// The phone's own look at a scan, right after it builds the 3D model, while
// the person and their helper are still there to scan again.
//
// Object Capture always hands back a finished-looking model: whatever the
// photos didn't show, it fills in with a smooth guess. So a model can look
// fine on the phone and still be no use. Two real cases from 17 Nov 2026:
//
// - A left sole-up scan (a cousin's foot) whose sole faced about 40 degrees
//   to the side instead of the ceiling. The studio turned it so its sole was
//   down and read a thin blade, 231 x 61 mm, with the ball of the foot rolled
//   12 mm; it was refused, but only after it had been sent, and the person
//   had gone.
// - The calibration block, whose underside the phone never saw: it made up a
//   wedge reaching about 36 mm under the block's real base.
//
// The studio's checks (src/footscan/recon/completeness.py, foot_prep.py) stay
// the ones that decide; this is a quicker, rougher look so that the obvious
// failures are caught on the spot. It needs no studio and no network.
//
// Plain Swift and Foundation only, so the same file builds into the app, its
// tests, and ios/tools/scan-check.swift (run it over a folder of real scans).
// Thresholds are this file's own choices, each written next to what it was
// set on; most come from the studio's.
import Foundation

enum ScanCheck {
    /// Bump when a check changes: scans checked by an older version are checked again (until they're sent).
    static let version = 1

    // MARK: what it finds

    /// One thing wrong with a scan: what was found (with its numbers), and what to do differently.
    struct Finding: Codable, Hashable {
        /// Matches the studio's refusal codes where it's the same problem (completeness.RETAKE_STEPS).
        var code: String
        /// Short, for a sentence on the phone: "The sole wasn't facing the ceiling".
        var title: String
        /// What was found, with its numbers, in plain words.
        var detail: String
        /// What to do differently next time, in order.
        var steps: [String]
        /// true: the scan won't make a good insole, so it's held back and the phone says scan again.
        /// false: worth knowing, but the scan can still be used.
        var scanAgain: Bool
    }

    /// The kinds of scan the phone checks, and how.
    enum Kind: String {
        /// The sole faced the ceiling (the person lay face down, knee bent): the left and right sole scans.
        case soleUp = "sole_up"
        /// The printed calibration block on a table: its underside is never seen.
        case calibration
        /// The shoe's own insole lying flat on a table.
        case shoeInsole = "shoe_insole"
    }

    /// Everything the check measured, for the scan's record (and for tuning the thresholds on real scans).
    struct Report: Codable, Hashable {
        var findings: [Finding]
        var measures: [String: Double]
    }

    /// Read a model (OBJ, as the phone saves it) and check it as `kind`.
    static func run(obj url: URL, kind: Kind) throws -> Report {
        let mesh = try Mesh.readOBJ(url).inMillimetres()
        switch kind {
        case .soleUp:
            guard let m = SoleUp.measure(mesh) else {
                return Report(findings: [Finding.notFound], measures: [:])
            }
            return Report(findings: SoleUp.findings(m), measures: m.asDictionary)
        case .calibration, .shoeInsole:
            guard let u = Underside.measure(mesh) else { return Report(findings: [], measures: [:]) }
            return Report(findings: Underside.findings(u, kind: kind), measures: u.asDictionary)
        }
    }
}

// MARK: - the mesh

extension ScanCheck {
    typealias Vec = SIMD3<Double>

    /// Triangles: corner positions (in the model's own frame, Y up) and three corner indices each.
    struct Mesh {
        var points: [Vec]
        var faces: [(Int, Int, Int)]

        enum ReadError: LocalizedError {
            case empty
            var errorDescription: String? { "The model has no triangles in it." }
        }

        /// Only the shape: `v` lines and the position index of each `f` corner (texture and normal indices
        /// are skipped; a face with more than three corners becomes a fan of triangles).
        static func readOBJ(_ url: URL) throws -> Mesh {
            let text = try String(contentsOf: url, encoding: .utf8)
            var points: [Vec] = []
            var faces: [(Int, Int, Int)] = []
            for line in text.split(whereSeparator: \.isNewline) {
                if line.hasPrefix("v ") {
                    let p = line.split(separator: " ", omittingEmptySubsequences: true)
                    guard p.count >= 4, let x = Double(p[1]), let y = Double(p[2]), let z = Double(p[3]) else { continue }
                    points.append(Vec(x, y, z))
                } else if line.hasPrefix("f ") {
                    let corners: [Int] = line.split(separator: " ", omittingEmptySubsequences: true).dropFirst().compactMap { token in
                        guard let first = token.split(separator: "/", omittingEmptySubsequences: false).first,
                              let i = Int(first) else { return nil }
                        return i > 0 ? i - 1 : points.count + i  // OBJ counts from 1; negative counts back from the end
                    }
                    guard corners.count >= 3, corners.allSatisfy({ $0 >= 0 && $0 < points.count }) else { continue }
                    for k in 1..<(corners.count - 1) { faces.append((corners[0], corners[k], corners[k + 1])) }
                }
            }
            guard !faces.isEmpty else { throw ReadError.empty }
            return Mesh(points: points, faces: faces)
        }

        /// In millimetres, as the studio reads it (imported.to_millimetres): a model under 5 units across is in
        /// metres (Object Capture's own), under 50 in centimetres.
        func inMillimetres() -> Mesh {
            var lo = Vec(repeating: .infinity), hi = Vec(repeating: -.infinity)
            for p in points { lo = pointwiseMin(lo, p); hi = pointwiseMax(hi, p) }
            let extent = (hi - lo).max()
            let factor = extent < 5 ? 1000.0 : extent < 50 ? 10.0 : 1.0
            return Mesh(points: points.map { $0 * factor }, faces: faces)
        }

        /// Corners at the same place made one (to the nearest thousandth of a millimetre), so triangles either
        /// side of a seam in the model's texture count as joined.
        func welded() -> Mesh {
            var index: [SIMD3<Int64>: Int] = [:]
            var map = [Int](repeating: 0, count: points.count)
            for (i, p) in points.enumerated() {
                let key = SIMD3<Int64>(Int64((p.x * 1000).rounded()), Int64((p.y * 1000).rounded()), Int64((p.z * 1000).rounded()))
                if let j = index[key] { map[i] = j } else { index[key] = i; map[i] = i }
            }
            return Mesh(points: points, faces: faces.map { (map[$0.0], map[$0.1], map[$0.2]) })
        }

        /// Only the faces that `keep` says yes to (given each face's centre).
        func keeping(_ keep: (Vec) -> Bool) -> Mesh {
            Mesh(points: points, faces: faces.filter { keep(centre($0)) })
        }

        /// The biggest connected piece (by area): specks and scraps the phone made off to one side go, as in the
        /// studio's preparation (foot_prep._largest_piece).
        func largestPiece() -> Mesh {
            var parent = Array(0..<points.count)
            func root(_ i: Int) -> Int {
                var i = i
                while parent[i] != i { parent[i] = parent[parent[i]]; i = parent[i] }
                return i
            }
            for f in faces {
                let a = root(f.0)
                parent[root(f.1)] = a
                parent[root(f.2)] = a
            }
            var area: [Int: Double] = [:]
            let roots = faces.map { root($0.0) }
            for (f, r) in zip(faces, roots) { area[r, default: 0] += self.area(f) }
            guard let biggest = area.max(by: { $0.value != $1.value ? $0.value < $1.value : $0.key > $1.key })?.key else { return self }
            return Mesh(points: points, faces: zip(faces, roots).filter { $0.1 == biggest }.map { $0.0 })
        }

        func centre(_ f: (Int, Int, Int)) -> Vec { (points[f.0] + points[f.1] + points[f.2]) / 3 }

        /// The face's normal (unit length, by the right-hand rule of its corners) and its area.
        func normalAndArea(_ f: (Int, Int, Int)) -> (Vec, Double) {
            let c = cross3(points[f.1] - points[f.0], points[f.2] - points[f.0])
            let len = length3(c)
            return (len > 0 ? c / len : .zero, len / 2)
        }

        func area(_ f: (Int, Int, Int)) -> Double { normalAndArea(f).1 }

        /// Points all over the surface, no further apart than about `step` mm: each triangle's edges split into
        /// equal parts and the grid of points between them. (A model's triangles are of every size; measuring
        /// from their corners alone would leave big gaps where the triangles are big.)
        func samples(step: Double = 1.5) -> [Vec] {
            var out: [Vec] = []
            out.reserveCapacity(faces.count * 6)
            for f in faces {
                let a = points[f.0], b = points[f.1], c = points[f.2]
                let longest = max(length3(b - a), length3(c - a), length3(c - b))
                let n = min(400, max(1, Int((longest / step).rounded(.up))))
                for i in 0...n {
                    for j in 0...(n - i) {
                        out.append(a + (b - a) * (Double(i) / Double(n)) + (c - a) * (Double(j) / Double(n)))
                    }
                }
            }
            return out
        }
    }
}

// MARK: - sole-up scans

extension ScanCheck {
    /// A sole-up scan, as the phone sees it: which way the sole faced, and the foot's outline from below.
    ///
    /// The studio turns the model over and rests it on its convex hull (foot_prep.prepare_sole_up). The phone
    /// does something simpler that comes to the same thing on a whole foot: turned over (sole down, shin up),
    /// it tries every tilt up to `maxTipDeg` and keeps the one that lays the most downward-facing surface
    /// within `floorBandMM` of the lowest point. That is the sole resting flat, on the heel and the ball of the
    /// foot. Everything below `outlineMM` is then the foot seen from above, as the insole's outline is
    /// (insole.SILHOUETTE_HEIGHT_MM), and its length runs along the outline's longest direction.
    enum SoleUp {
        static let keepMM = 300.0          // the foot and some shin, as foot_prep.SOLE_UP_KEEP_MM
        static let maxTipDeg = 50.0        // as foot_prep.SOLE_UP_MAX_TIP_DEG: a relaxed foot points its toes down this far
        static let floorBandMM = 10.0
        static let downward = -0.3         // a face's normal at least this far down counts as underside
        static let outlineMM = 30.0        // insole.SILHOUETTE_HEIGHT_MM
        static let shinAboveMM = 80.0      // the shin: well above the foot, over the heel
        static let cellMM = 2.0
        static let ball = (from: 0.60, to: 0.75)  // foot_prep.BALL_FROM, BALL_TO: the ball of the foot, from the heel
        static let ballBelowMM = 40.0      // foot_prep.OPEN_EDGE_BELOW_MM

        // What counts as wrong.
        // The sole facing the side: SYNTHETIC whole feet (tests/synth.py's shaped and curved feet, turned as a
        // phone hands them over) read 1-5 degrees, the same feet turned 15 and 30 degrees about their length read
        // 20 and 30-37; the cousin's real scan 40.4.
        static let sidewaysDeg = 25.0
        // Square ends and the size of one foot: the studio's own (completeness.TOE_END_SQUARE, HEEL_END_SQUARE,
        // foot_prep.FOOT_LENGTH_MM, FOOT_RATIO). Measured the phone's way, SYNTHETIC: toes whole 0.31-0.39 (bent up
        // 35 degrees 0.48), cut 25 mm short 0.62, 50 mm 0.85; heel whole 0.42-0.50, cut 15 mm 0.75.
        static let toeEndSquare = 0.6
        static let heelEndSquare = 0.65
        static let footLengthMM = 180.0...330.0
        static let footRatio = 0.28...0.50
        // The ball rolled. The studio refuses past 5 mm (foot_prep.BALL_ROLL_WARN_MM), from its own tripod floor. The
        // phone's floor leaves whole SYNTHETIC feet reading 0.2-5.4 mm (a forefoot rolled 5 degrees 1.6 mm, 15 degrees
        // 12.1 mm), so the phone waits for 7: past what a whole foot reads here, short of the real left scan the
        // studio found rolled 8.6 mm (LIDAR_nwb_relaxed_L_20261027-151404-89df, studio's measure).
        static let ballRollMM = 7.0

        struct Measure: Hashable {
            /// How far the floor had to be tipped to rest the sole flat, and that split into toes-down (pitch, normal
            /// for a relaxed foot) and sideways (the sole turned to one side).
            var tipDeg, pitchDeg, sidewaysDeg: Double
            var lengthMM, widthMM: Double
            /// The outline's width 4-6 mm in from the toes, as a share of its widest; and from the heel, as a share
            /// of the heel's widest (the back 30%). Near 1: that end is square, cut off.
            var toeEnd, heelEnd: Double?
            /// How much higher one side of the ball of the foot sits than the other (mm).
            var ballRollMM: Double?

            var asDictionary: [String: Double] {
                var d = ["tip_deg": tipDeg, "pitch_deg": pitchDeg, "sideways_deg": sidewaysDeg,
                         "length_mm": lengthMM, "width_mm": widthMM]
                d["toe_end"] = toeEnd
                d["heel_end"] = heelEnd
                d["ball_roll_mm"] = ballRollMM
                return d.mapValues { ($0 * 100).rounded() / 100 }
            }
        }

        static func measure(_ model: Mesh) -> Measure? {
            // Turned over, as the studio does: Y up becomes Z up, then half a turn about x, so the sole is down.
            var pts = model.points.map { Vec($0.x, $0.z, -$0.y) }
            let bottom = pts.map(\.z).min() ?? 0
            pts = pts.map { Vec($0.x, $0.y, $0.z - bottom) }
            let m = Mesh(points: pts, faces: model.faces).welded().keeping { $0.z < keepMM }.largestPiece()
            guard m.faces.count >= 100 else { return nil }

            let geometry = m.faces.map { f -> (centre: Vec, normal: Vec, area: Double) in
                let (n, a) = m.normalAndArea(f)
                return (m.centre(f), n, a)
            }
            let used = Array(Set(m.faces.flatMap { [$0.0, $0.1, $0.2] })).sorted()
            func lowest(_ up: Vec) -> Double { used.reduce(Double.infinity) { min($0, dot3(m.points[$1], up)) } }
            func underside(_ up: Vec) -> Double {
                let lo = lowest(up)
                var s = 0.0
                for g in geometry where dot3(g.normal, up) < downward && dot3(g.centre, up) - lo < floorBandMM { s += g.area }
                return s
            }
            func up(_ tx: Double, _ ty: Double) -> Vec {
                let v = Vec(tan(tx * .pi / 180), tan(ty * .pi / 180), 1)
                return v / length3(v)
            }
            // every 5 degrees, then every 1 round the best, then every half round that
            var best = -1.0, at = (0.0, 0.0)
            for (span, step, aroundBest) in [(maxTipDeg, 5.0, false), (5.0, 1.0, true), (1.0, 0.5, true)] {
                let (cx, cy) = aroundBest ? at : (0.0, 0.0)
                let k = Int((span / step).rounded())
                for i in -k...k {
                    for j in -k...k {
                        let tx = cx + Double(i) * step, ty = cy + Double(j) * step
                        guard (tx * tx + ty * ty).squareRoot() <= maxTipDeg else { continue }
                        let s = underside(up(tx, ty))
                        if s > best { best = s; at = (tx, ty) }
                    }
                }
            }
            let u = up(at.0, at.1)
            let e1 = unit3(cross3(Vec(0, 1, 0), u)), e2 = cross3(u, e1)
            let lo = lowest(u)

            // the outline: everything low enough, in 2 mm cells across the floor
            let points = m.samples()
            var outline: [SIMD2<Double>] = []
            var shin: [SIMD2<Double>] = []
            for p in points {
                let h = dot3(p, u) - lo
                let xy = SIMD2(dot3(p, e1), dot3(p, e2))
                if h < outlineMM { outline.append(xy) } else if h > shinAboveMM { shin.append(xy) }
            }
            guard outline.count >= 100 else { return nil }
            var cells = Set<SIMD2<Int>>()
            for q in outline { cells.insert(SIMD2(Int((q.x / cellMM).rounded(.down)), Int((q.y / cellMM).rounded(.down)))) }
            let centres = cells.map { (SIMD2<Double>(Double($0.x), Double($0.y)) + 0.5) * cellMM }
            let mu = centres.reduce(SIMD2<Double>.zero, +) / Double(centres.count)
            var cxx = 0.0, cyy = 0.0, cxy = 0.0
            for c in centres { let d = c - mu; cxx += d.x * d.x; cyy += d.y * d.y; cxy += d.x * d.y }
            let theta = 0.5 * atan2(2 * cxy, cxx - cyy)  // the outline's longest direction
            var along = SIMD2(cos(theta), sin(theta))

            func slices(_ along: SIMD2<Double>) -> (across: SIMD2<Double>, start: Int, widths: [Double]) {
                let across = SIMD2(-along.y, along.x)
                var grid = Set<SIMD2<Int>>()
                for q in outline {
                    let d = q - mu
                    grid.insert(SIMD2(Int(((d * along).sum() / cellMM).rounded(.down)), Int(((d * across).sum() / cellMM).rounded(.down))))
                }
                let s0 = grid.map(\.x).min()!, s1 = grid.map(\.x).max()!
                var count = [Int](repeating: 0, count: s1 - s0 + 1)
                for g in grid { count[g.x - s0] += 1 }
                return (across, s0, count.map { Double($0) * cellMM })
            }
            // heel at the start: the shin stands over the heel; without a shin, the widest part (the ball) is
            // nearer the toes
            let towardsShin: Bool
            if !shin.isEmpty {
                towardsShin = shin.reduce(0.0) { $0 + (($1 - mu) * along).sum() } / Double(shin.count) > 0
            } else {
                let w = slices(along).widths
                towardsShin = Double(w.indices.max { w[$0] < w[$1] } ?? 0) < Double(w.count) / 2
            }
            if towardsShin { along = -along }
            let (across, s0, widths) = slices(along)
            let n = widths.count
            let length = Double(n) * cellMM, width = widths.max() ?? 0
            var toeEnd: Double?, heelEnd: Double?
            if n >= 6, width > 0 {
                toeEnd = widths[n - 3] / width
                heelEnd = widths[2] / (widths[0..<max(3, Int(0.3 * Double(n)))].max() ?? width)
            }

            // the ball of the foot: the underside across it, split in thirds; the lowest of each outer third
            let start = Double(s0) * cellMM
            var xs: [Double] = [], zs: [Double] = []
            for g in geometry where dot3(g.normal, u) < downward {
                let d = SIMD2(dot3(g.centre, e1), dot3(g.centre, e2)) - mu
                let al = (d * along).sum(), h = dot3(g.centre, u) - lo
                guard al > start + ball.from * length, al < start + ball.to * length, h < ballBelowMM else { continue }
                xs.append((d * across).sum()); zs.append(h)
            }
            var roll: Double?
            if xs.count >= 30 {
                let sorted = xs.sorted()
                let p2 = quantile(sorted, 2), p98 = quantile(sorted, 98), third = (p98 - p2) / 3
                let a = zip(xs, zs).filter { $0.0 < p2 + third }.map { $0.1 }.sorted()
                let b = zip(xs, zs).filter { $0.0 > p98 - third }.map { $0.1 }.sorted()
                if a.count >= 10, b.count >= 10 { roll = abs(quantile(a, 2) - quantile(b, 2)) }
            }

            // which way "up" was when it was scanned, against the sole's own frame
            let vertical = Vec(0, 0, 1)
            let along3 = along.x * e1 + along.y * e2, across3 = across.x * e1 + across.y * e2
            let deg = 180 / Double.pi
            return Measure(tipDeg: acos(min(1, max(-1, u.z))) * deg,
                           pitchDeg: atan2(dot3(vertical, along3), dot3(vertical, u)) * deg,
                           sidewaysDeg: atan2(dot3(vertical, across3), dot3(vertical, u)) * deg,
                           lengthMM: length, widthMM: width, toeEnd: toeEnd, heelEnd: heelEnd, ballRollMM: roll)
        }

        /// What's wrong, worst first. A sole that faced the side comes alone: the rest is measured from a floor
        /// that can't be trusted then.
        static func findings(_ m: Measure) -> [Finding] {
            if abs(m.sidewaysDeg) > sidewaysDeg || m.tipDeg > maxTipDeg - 1 {
                return [Finding(
                    code: "sole_not_up", title: "The sole wasn't facing the ceiling",
                    detail: String(format: "The sole faced %.0f degrees to one side instead of up at the ceiling, so the "
                                   + "model can't be turned into a foot standing flat. ", abs(m.sidewaysDeg))
                        + "Scan again with the sole facing straight up.",
                    steps: ["Lie face down and bend this knee so the shin points straight up at the ceiling.",
                            "Let the ankle relax. Turn the foot until the sole faces the ceiling, not turned in or out.",
                            "Before you tap Start, lay a book (anything flat and stiff) across the ball of the foot. The "
                            + "big-toe side and the little-toe side should both touch it. Then take it away and keep still."],
                    scanAgain: true)]
            }
            var out: [Finding] = []
            if let t = m.toeEnd, t > toeEndSquare {
                out.append(Finding(
                    code: "toes_missing", title: "The toes were cut off",
                    detail: String(format: "The front of the scan ends square (%.0f%% of the foot's width 5 mm from its end), "
                                   + "where toes would round off. Scan again with the toes relaxed and flat, and the phone going "
                                   + "all the way round them.", t * 100),
                    // completeness.RETAKE_STEPS "toes_missing"
                    steps: ["Let the toes relax and lie straight: wiggle them, then let go. Don't pull them back.",
                            "Before you tap Start, make sure the box reaches past the tips of the toes.",
                            "On the second lap, go slowly round the toes, close in."],
                    scanAgain: true))
            }
            if let h = m.heelEnd, h > heelEndSquare {
                out.append(Finding(
                    code: "heel_cut_off", title: "The back of the heel was cut off",
                    detail: String(format: "The back of the scan ends square (%.0f%% of the heel's width 5 mm from its end), "
                                   + "where a heel rounds off. Scan again, taking the phone round behind the heel.", h * 100),
                    steps: ["Before you tap Start, make sure the box reaches past the back of the heel.",
                            "Take the phone right round behind the heel, low enough to see its back."],
                    scanAgain: true))
            }
            let ratio = m.widthMM / max(m.lengthMM, 1e-9)
            if out.isEmpty, !footLengthMM.contains(m.lengthMM) || !footRatio.contains(ratio) {
                out.append(Finding(
                    code: "not_one_foot", title: "This doesn't look like one whole foot",
                    detail: String(format: "Seen from above the scan is %.0f x %.0f mm, but a foot is about %.0f-%.0f mm long "
                                   + "and %.2f-%.2f times as wide as long. Part of the foot may be missing, or more than this "
                                   + "foot was in the box. Scan again with the whole foot in view and only this foot.",
                                   m.lengthMM, m.widthMM, footLengthMM.lowerBound, footLengthMM.upperBound,
                                   footRatio.lowerBound, footRatio.upperBound),
                    steps: ["Move the other foot well out of the way: a forearm's width between the feet.",
                            "Drag the box's edges in so it holds only this foot and a hand's width of the leg.",
                            "Go all the way round until the ring is full, then a second lap, closer."],
                    scanAgain: true))
            }
            if let r = m.ballRollMM, r > ballRollMM {
                out.append(Finding(
                    code: "forefoot_rolled", title: "The ball of the foot wasn't level",
                    detail: String(format: "One side of the ball of the foot is %.0f mm higher than the other, so the insole "
                                   + "would put a wedge under it. Scan again with the ball of the foot level: a book laid "
                                   + "across it touches both sides.", r),
                    // completeness.RETAKE_STEPS "forefoot_rolled"
                    steps: ["Relax the ankle at a right angle: don't point the foot.",
                            "Before you tap Start, lay a book (anything flat and stiff) across the ball of the foot. The "
                            + "big-toe side and the little-toe side should both touch it.",
                            "If one side doesn't, turn the foot gently until it does. Then take the book away and keep still."],
                    scanAgain: true))
            }
            return out
        }
    }
}

// MARK: - things lying on a table

extension ScanCheck {
    /// Something flat on a table (the calibration block, a shoe's insole): its underside is never seen, and
    /// Object Capture fills it in. Usually it fills it in flat, where the table was. When it doesn't, it can
    /// hang a made-up wedge or bulge under the object, and everything measured from the bottom is wrong.
    ///
    /// Seen from below in 2 mm squares, the lowest surface in each: on a flat underside nearly all of them are
    /// within `flatMM` of the bottom (its 1st percentile, so a speck doesn't set it). The share that are is
    /// `flatShare`.
    enum Underside {
        static let cellMM = 2.0
        static let flatMM = 3.0
        // Below this share the underside was guessed. Set on: the calibration block's design (tests' synthetic
        // copy of calib.build()) 1.00; the real calibration scan of 17 Nov 2026 (LIDAR_calibration_X_..._bff2),
        // with its made-up wedge, 0.04.
        static let minFlatShare = 0.5

        struct Measure: Hashable {
            var flatShare: Double
            /// How far the underside rises from its lowest (its 90th percentile), mm.
            var depthMM: Double
            var asDictionary: [String: Double] {
                ["flat_share": (flatShare * 1000).rounded() / 1000, "underside_depth_mm": (depthMM * 10).rounded() / 10]
            }
        }

        static func measure(_ model: Mesh) -> Measure? {
            let m = model.welded().largestPiece()
            var lowest: [SIMD2<Int>: Double] = [:]
            for p in m.samples() {
                let key = SIMD2(Int((p.x / cellMM).rounded(.down)), Int((p.z / cellMM).rounded(.down)))
                lowest[key] = min(lowest[key] ?? .infinity, p.y)
            }
            guard lowest.count >= 50 else { return nil }
            let heights = lowest.values.sorted()
            let floor = quantile(heights, 1)
            let rise = heights.map { $0 - floor }
            return Measure(flatShare: Double(rise.filter { $0 < flatMM }.count) / Double(rise.count),
                           depthMM: quantile(rise, 90))
        }

        static func findings(_ m: Measure, kind: Kind) -> [Finding] {
            guard m.flatShare < minFlatShare else { return [] }
            let what = kind == .calibration ? "block" : "insole"
            let found = String(format: "Only %.0f%% of the %@'s underside is flat; the rest reaches as much as %.0f mm "
                               + "below it. The phone never saw the underside and guessed it.", m.flatShare * 100, what, m.depthMM)
            // the one way to rescan the block, as the accuracy work settled it on 17 Nov 2026
            let steps = ["Put it flat on a plain, matte table. Don't raise it on a stand: the stand ends up in the model.",
                         "Keep the box tight round it.",
                         "Go all the way round until the ring is full, then a second lap, lower down."]
            if kind == .calibration {
                // its top is what tells the phone's scale, and the top was fine on the real scan: worth knowing, not
                // a reason to scan again
                return [Finding(code: "underside_guessed", title: "The phone guessed the block's underside",
                                detail: found + " Its top can still be measured, so you don't have to scan it again.",
                                steps: steps, scanAgain: false)]
            }
            return [Finding(code: "underside_guessed", title: "The phone guessed the insole's underside",
                            detail: found + " Scan again so its outline is read from what was really there.",
                            steps: ["Take the insole out of the shoe and lay it flat on a plain, matte table, top side up."]
                                + steps.dropFirst(),
                            scanAgain: true)]
        }
    }
}

extension ScanCheck.Finding {
    /// The model came out with too little of a foot in it to measure at all.
    static let notFound = ScanCheck.Finding(
        code: "foot_not_found", title: "The phone couldn't find the whole foot",
        detail: "The model has too little of a foot in it to measure. Scan again, covering the whole sole.",
        // completeness.RETAKE_STEPS "foot_not_found"
        steps: ["Keep the whole foot inside the box, with a hand's width of the leg.",
                "Go all the way round until the ring is full."],
        scanAgain: true)
}

// MARK: - small maths (file-private, so nothing else in the app picks these names up)

private func dot3(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> Double { (a * b).sum() }
private func cross3(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> SIMD3<Double> {
    SIMD3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)
}
private func length3(_ a: SIMD3<Double>) -> Double { dot3(a, a).squareRoot() }
private func unit3(_ a: SIMD3<Double>) -> SIMD3<Double> { a / length3(a) }

/// numpy's default percentile (linear between the two nearest), of values already sorted.
private func quantile(_ sorted: [Double], _ p: Double) -> Double {
    guard !sorted.isEmpty else { return .nan }
    let x = p / 100 * Double(sorted.count - 1)
    let i = Int(x.rounded(.down)), f = x - Double(i)
    return i + 1 < sorted.count ? sorted[i] + (sorted[i + 1] - sorted[i]) * f : sorted[i]
}
