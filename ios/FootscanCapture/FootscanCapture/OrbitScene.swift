// The welcome picture: the whole idea of footscan in one looping scene.
//
// A foot stands on the printed mat. A phone walks all the way round it; the
// ring of 12 sides lights up as it goes (the same "every side" idea the real
// capture uses). Then a scan line passes over, and the foot becomes an insole
// with a lattice inside. Drag the phone and it's yours: light all 12 sides
// and the insole appears. Let go for a few seconds and it plays by itself.
//
// With Reduce Motion on, it's a still picture of the finished insole.
import SwiftUI

/// The foot outline from the website (layout.js), in a 200 x 200 box.
enum FootShape {
    static let path = "M100 182C80 182 71 167 71 149C71 128 78 113 76 96C74 79 69 63 73 49C77 35 89 28 104 28C119 28 129 36 131 51C133 65 129 81 127 97C125 117 129 132 129 150C129 168 119 182 100 182Z"
    static let toes: [(CGFloat, CGFloat, CGFloat)] = [(85, 17, 9.5), (102, 13, 6.2), (114, 16, 5.6), (124, 22, 5), (131, 30, 4.4)]

    /// The outline as a SwiftUI Path (the path uses only M, C and Z).
    static func outline() -> Path {
        var p = Path()
        let tokens = path.replacingOccurrences(of: "M", with: " M ").replacingOccurrences(of: "C", with: " C ")
            .replacingOccurrences(of: "Z", with: " Z ").split(separator: " ").map(String.init)
        var i = 0
        var cmd = ""
        func num() -> CGFloat { defer { i += 1 }; return CGFloat(Double(tokens[i]) ?? 0) }
        while i < tokens.count {
            if ["M", "C", "Z"].contains(tokens[i]) { cmd = tokens[i]; i += 1; if cmd == "Z" { p.closeSubpath() }; continue }
            switch cmd {
            case "M": p.move(to: CGPoint(x: num(), y: num()))
            case "C":
                let c1 = CGPoint(x: num(), y: num()), c2 = CGPoint(x: num(), y: num()), e = CGPoint(x: num(), y: num())
                p.addCurve(to: e, control1: c1, control2: c2)
            default: i += 1
            }
        }
        return p
    }
}

@MainActor
@Observable
final class OrbitModel {
    static let sides = 12
    var lit = Set<Int>()
    var manualAngle: Double?     // 0..1 round the ring while you're driving
    var lastTouch: Date = .distantPast
    var celebrateUntil: Date = .distantPast

    var driving: Bool { Date().timeIntervalSince(lastTouch) < 4 || Date() < celebrateUntil }

    func drag(to t: Double) {
        let wrapped = (t.truncatingRemainder(dividingBy: 1) + 1).truncatingRemainder(dividingBy: 1)
        if manualAngle == nil || !driving { lit.removeAll() }
        lastTouch = Date()
        if let from = manualAngle {
            // light every side passed on the way (short way round), so a fast drag can't skip one
            var d = wrapped - from
            if d > 0.5 { d -= 1 } else if d < -0.5 { d += 1 }
            let steps = max(1, Int(abs(d) * Double(Self.sides) * 4))
            for k in 0...steps { lit.insert(Self.side(from + d * Double(k) / Double(steps))) }
        } else {
            lit.insert(Self.side(wrapped))
        }
        manualAngle = wrapped
        if lit.count == Self.sides && Date() >= celebrateUntil {
            celebrateUntil = Date().addingTimeInterval(3.5)
        }
    }

    static func side(_ t: Double) -> Int {
        let f = (t.truncatingRemainder(dividingBy: 1) + 1).truncatingRemainder(dividingBy: 1)
        return min(sides - 1, Int(f * Double(sides)))
    }
}

struct OrbitScene: View {
    var interactive = true
    @State private var model = OrbitModel()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    /// Only animate while some of it is on screen and the app is in front:
    /// a scene nobody can see shouldn't keep the graphics chip busy.
    @State private var onScreen = true
    private let cycle: Double = 9

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            TimelineView(.animation(minimumInterval: 1 / 60, paused: reduceMotion || !onScreen || scenePhase != .active)) { timeline in
                let frame = frameFor(timeline.date)
                Canvas { ctx, _ in draw(&ctx, size: size, frame: frame) }
            }
            .contentShape(Rectangle())
            .gesture(interactive && !reduceMotion ? DragGesture(minimumDistance: 0).onChanged { g in
                let c = CGPoint(x: size.width / 2, y: size.height / 2)
                let a = atan2((g.location.y - c.y) / (size.height * 0.36), (g.location.x - c.x) / (size.width * 0.42))
                let t = (a - .pi / 2) / (2 * .pi)
                let before = model.lit.count
                model.drag(to: t)
                if model.lit.count > before { UISelectionFeedbackGenerator().selectionChanged() }
                if model.lit.count == OrbitModel.sides && before < OrbitModel.sides {
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                }
            } : nil)
        }
        .aspectRatio(1.2, contentMode: .fit)
        .onScrollVisibilityChange(threshold: 0.05) { onScreen = $0 }
        .accessibilityElement()
        .accessibilityLabel("A phone circles a foot standing on the printed mat, taking photos from every side; the foot then becomes an insole shaped to it.")
        .accessibilityAddTraits(.isImage)
    }

    // MARK: what to show at a moment

    struct Frame {
        var phoneT: Double        // where the phone is, 0..1 round the ring (0 = at the heel, bottom)
        var lit: Set<Int>
        var scan: Double?         // scan line progress 0..1, while scanning
        var insole: Double        // 0 = foot, 1 = insole
        var flash: Double         // 0..1 brightness of the camera flash
    }

    private func frameFor(_ date: Date) -> Frame {
        if reduceMotion { return Frame(phoneT: 0.62, lit: Set(0..<OrbitModel.sides), scan: nil, insole: 1, flash: 0) }
        if model.driving, let t = model.manualAngle {
            let celebrating = date < model.celebrateUntil
            let left = model.celebrateUntil.timeIntervalSince(date)
            return Frame(phoneT: t, lit: model.lit, scan: nil,
                         insole: celebrating ? min(1, (3.5 - left) / 1.2) : 0, flash: 0)
        }
        let s = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: cycle) / cycle
        let orbitEnd = 0.55, scanEnd = 0.66, holdEnd = 0.92
        if s < orbitEnd {
            let k = s / orbitEnd
            let e = k < 0.5 ? 2 * k * k : 1 - pow(-2 * k + 2, 2) / 2 // ease in-out
            let n = Int(e * Double(OrbitModel.sides) + 0.999)
            let frac = (e * Double(OrbitModel.sides)).truncatingRemainder(dividingBy: 1)
            return Frame(phoneT: e, lit: Set(0..<min(n, OrbitModel.sides)), scan: nil, insole: 0,
                         flash: frac < 0.25 && e > 0.01 ? 1 - frac * 4 : 0)
        }
        let all = Set(0..<OrbitModel.sides)
        if s < scanEnd { return Frame(phoneT: 1, lit: all, scan: (s - orbitEnd) / (scanEnd - orbitEnd), insole: 0, flash: 0) }
        if s < holdEnd { return Frame(phoneT: 1, lit: all, scan: nil, insole: min(1, (s - scanEnd) / 0.08), flash: 0) }
        return Frame(phoneT: 0, lit: [], scan: nil, insole: max(0, 1 - (s - holdEnd) / 0.05), flash: 0)
    }

    // MARK: drawing

    private func draw(_ ctx: inout GraphicsContext, size: CGSize, frame f: Frame) {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        // leave room top and bottom for the phone (it's taller than the ring is thick)
        let rx = size.width * 0.42, ry = size.height * 0.36
        func onRing(_ t: Double, _ k: CGFloat = 1) -> CGPoint {
            let a = CGFloat(Double.pi / 2 + t * 2 * Double.pi)
            return CGPoint(x: c.x + rx * k * cos(a), y: c.y + ry * k * sin(a))
        }
        let n = OrbitModel.sides
        let current = OrbitModel.side(f.phoneT)

        // a soft pool of colour the whole scene sits in
        let glow = CGRect(x: c.x - rx * 0.95, y: c.y - ry * 0.95, width: rx * 1.9, height: ry * 1.9)
        ctx.fill(Path(ellipseIn: glow), with: .radialGradient(
            Gradient(colors: [Color.fsBrandSoft.opacity(0.85), Color.fsBrandSoft.opacity(0)]),
            center: c, startRadius: 0, endRadius: rx * 0.95))

        // the path the phone walks: a fine dotted line
        var orbit = Path()
        orbit.addEllipse(in: CGRect(x: c.x - rx, y: c.y - ry, width: 2 * rx, height: 2 * ry))
        ctx.stroke(orbit, with: .color(.fsBrand.opacity(0.22)), style: StrokeStyle(lineWidth: 1.2, lineCap: .round, dash: [0.1, 6]))

        // the ring of sides: thin rounded arcs; the side the phone is on glows
        for i in 0..<n {
            var arc = Path()
            let steps = 14
            for j in 0...steps {
                let t = (Double(i) + 0.1 + 0.8 * Double(j) / Double(steps)) / Double(n)
                let p = onRing(t, 1.1)
                j == 0 ? arc.move(to: p) : arc.addLine(to: p)
            }
            let on = f.lit.contains(i)
            if on && i == current && f.insole == 0 {
                ctx.stroke(arc, with: .color(.fsAccent.opacity(0.55)), style: StrokeStyle(lineWidth: 10, lineCap: .round))
            }
            ctx.stroke(arc, with: .color(on ? Color.fsBrand : Color.fsLine.opacity(0.9)),
                       style: StrokeStyle(lineWidth: on ? 5 : 4, lineCap: .round))
        }

        // the mat: a sheet of paper with a soft shadow; its markers are small
        // and faint, background texture behind the foot rather than the subject
        let mw = size.width * 0.29, mh = size.height * 0.5
        let mat = CGRect(x: c.x - mw / 2, y: c.y - mh / 2, width: mw, height: mh)
        var paper = ctx
        paper.addFilter(.shadow(color: .black.opacity(0.1), radius: 10, x: 0, y: 5))
        paper.fill(Path(roundedRect: mat, cornerRadius: 8), with: .color(.fsSurface))
        let sq = mw * 0.055
        var y = mat.minY + sq * 1.2
        while y < mat.maxY - sq * 2 {
            if abs(y + sq / 2 - c.y) > sq * 1.5 {
                for x in [mat.minX + sq * 0.9, mat.maxX - sq * 1.9] {
                    ctx.fill(Path(roundedRect: CGRect(x: x, y: y, width: sq, height: sq), cornerRadius: sq * 0.25),
                             with: .color(.fsInk.opacity(0.16)))
                }
            }
            y += sq * 2.3
        }
        var seam = Path()
        seam.move(to: CGPoint(x: mat.minX + 6, y: c.y)); seam.addLine(to: CGPoint(x: mat.maxX - 6, y: c.y))
        ctx.stroke(seam, with: .color(.fsBrand.opacity(0.3)), style: StrokeStyle(lineWidth: 1, dash: [3, 4]))

        // the foot: the subject. Larger than the clear middle of the mat, with
        // its own shadow, so it sits on top of the paper
        let scale = mh * 0.9 / 200
        let foot = FootShape.outline()
            .applying(CGAffineTransform(translationX: -100, y: -100))
            .applying(CGAffineTransform(scaleX: scale, y: scale))
            .applying(CGAffineTransform(translationX: c.x, y: c.y + 6))
        let box = foot.boundingRect
        var footCtx = ctx
        footCtx.addFilter(.shadow(color: Color.fsBrand.opacity(0.25), radius: 8, x: 0, y: 4))
        footCtx.fill(foot, with: .linearGradient(Gradient(colors: [.fsBrandSoft, .fsSurface]),
                                                 startPoint: CGPoint(x: box.midX, y: box.minY),
                                                 endPoint: CGPoint(x: box.midX, y: box.maxY)))
        if f.insole > 0 {
            var lattice = ctx
            lattice.clip(to: foot)
            lattice.opacity = f.insole
            lattice.fill(foot, with: .color(.fsAccent.opacity(0.3)))
            let h: CGFloat = 9 * scale * 1.6
            var row = 0
            var yy = box.minY - h
            while yy < box.maxY + h {
                var xx = box.minX - h + (row % 2 == 0 ? 0 : h * 0.866)
                while xx < box.maxX + h {
                    lattice.stroke(hexagon(CGPoint(x: xx, y: yy), r: h * 0.5), with: .color(.fsBrand.opacity(0.5)), lineWidth: 0.8)
                    xx += h * 1.732
                }
                yy += h * 1.5
                row += 1
            }
        }
        ctx.stroke(foot, with: .color(.fsBrand), lineWidth: 2 + 1.5 * f.insole)
        for (x, yv, r) in FootShape.toes {
            let p = CGPoint(x: c.x + (x - 100) * scale, y: c.y + 6 + (yv - 100) * scale)
            let circle = Path(ellipseIn: CGRect(x: p.x - r * scale, y: p.y - r * scale, width: 2 * r * scale, height: 2 * r * scale))
            var toe = ctx
            toe.opacity = 1 - f.insole * 0.85
            toe.fill(circle, with: .color(.fsBrandSoft))
            toe.stroke(circle, with: .color(.fsBrand), lineWidth: 1.8)
        }

        // the scanner: one bright line with a soft glow, sweeping heel to toe over the foot
        if let s = f.scan {
            let yLine = box.maxY - CGFloat(s) * box.height
            var scanCtx = ctx
            scanCtx.clip(to: foot)
            let band = CGRect(x: box.minX, y: yLine - 14, width: box.width, height: 28)
            scanCtx.fill(Path(band), with: .linearGradient(
                Gradient(colors: [.fsAccent.opacity(0), .fsAccent.opacity(0.55), .fsAccent.opacity(0)]),
                startPoint: CGPoint(x: band.midX, y: band.minY), endPoint: CGPoint(x: band.midX, y: band.maxY)))
            var line = Path()
            line.move(to: CGPoint(x: mat.minX + 4, y: yLine)); line.addLine(to: CGPoint(x: mat.maxX - 4, y: yLine))
            ctx.stroke(line, with: .color(.fsAccent), style: StrokeStyle(lineWidth: 2, lineCap: .round))
        }

        // the phone, facing the middle: rounded body, lit screen, lens
        let p = onRing(f.phoneT)
        if f.flash > 0 {
            let r = 14 + 10 * (1 - f.flash)
            ctx.stroke(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)),
                       with: .color(.fsAccent.opacity(0.8 * f.flash)), lineWidth: 3)
        }
        var phone = ctx
        phone.translateBy(x: p.x, y: p.y)
        let facing = Double(atan2(c.x - p.x, -(c.y - p.y))) + Double.pi
        phone.rotate(by: .radians(facing))
        phone.addFilter(.shadow(color: .black.opacity(0.25), radius: 6, x: 0, y: 3))
        let body = CGRect(x: -12, y: -21, width: 24, height: 42)
        phone.fill(Path(roundedRect: body, cornerRadius: 7), with: .color(Color(light: 0x15201f, dark: 0x0a0f0e)))
        var screenCtx = ctx
        screenCtx.translateBy(x: p.x, y: p.y)
        screenCtx.rotate(by: .radians(facing))
        screenCtx.fill(Path(roundedRect: body.insetBy(dx: 2.5, dy: 2.5), cornerRadius: 5), with: .linearGradient(
            Gradient(colors: [.fsBrand, Color(light: 0x5fc2b6, dark: 0x5fc2b6)]),
            startPoint: CGPoint(x: 0, y: body.minY), endPoint: CGPoint(x: 0, y: body.maxY)))
        screenCtx.fill(Path(ellipseIn: CGRect(x: -2.2, y: -18.2, width: 4.4, height: 4.4)), with: .color(.fsAccent))

        // done: a tick beside the mat
        if f.insole > 0.6 {
            let tp = CGPoint(x: mat.maxX + 6, y: mat.minY + 16)
            var tick = ctx
            tick.opacity = (f.insole - 0.6) / 0.4
            tick.addFilter(.shadow(color: Color.fsOK.opacity(0.4), radius: 6, x: 0, y: 2))
            tick.fill(Path(ellipseIn: CGRect(x: tp.x - 14, y: tp.y - 14, width: 28, height: 28)), with: .color(.fsOK))
            var t = Path()
            t.move(to: CGPoint(x: tp.x - 6, y: tp.y)); t.addLine(to: CGPoint(x: tp.x - 2, y: tp.y + 4)); t.addLine(to: CGPoint(x: tp.x + 6, y: tp.y - 5))
            ctx.opacity = 1
            var mark = ctx
            mark.opacity = (f.insole - 0.6) / 0.4
            mark.stroke(t, with: .color(.white), style: StrokeStyle(lineWidth: 2.6, lineCap: .round, lineJoin: .round))
        }
    }

    private func hexagon(_ c: CGPoint, r: CGFloat) -> Path {
        var p = Path()
        for k in 0..<6 {
            let a = CGFloat(Double(k) * Double.pi / 3 + Double.pi / 6)
            let q = CGPoint(x: c.x + r * cos(a), y: c.y + r * sin(a))
            k == 0 ? p.move(to: q) : p.addLine(to: q)
        }
        p.closeSubpath()
        return p
    }
}

#Preview { OrbitScene().padding().background(Color.fsBackground) }
