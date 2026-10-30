// "Get ready", before the first scan of each kind. Tick each thing as it's
// done; after that kind has been scanned once, this is skipped (and stays
// one tap away as Tips, without the ticking). After the studio refused a
// scan, Scan again opens it too, with what to change this time on top.
import RealityKit
import SwiftUI

extension Subject {
    var symbol: String {
        switch self {
        case .rightSole, .leftSole: "shoeprints.fill"
        case .rightSoleFlat, .leftSoleFlat: "bed.double.fill"
        case .rightPrint, .leftPrint: "shippingbox.fill"
        case .shoeInsole: "shoe.fill"
        case .calibration: "cube.fill"
        case .rightFoot, .leftFoot: "figure.seated.side.right"
        case .other: "sparkles"
        }
    }

    /// The checks to make just before tapping Start, shown under the camera while the box is set: the things
    /// that, missed, got real scans refused (docs/scanning-guide.md). Short: they share the screen with it.
    var startChecks: String? {
        switch scanKind {
        case "sole_up": "Check: ball of the foot level, toes relaxed, the box past the toe tips and the heel."
        case "sole_hanging": "Check: the other foot well away, ball of the foot level, toes relaxed."
        case "impression": "Check: the whole foam box inside the box."
        default: nil
        }
    }

    /// What to have ready before scanning this: (symbol, title, detail).
    var checklist: [(String, String, String)] {
        switch self {
        case .rightSole, .leftSole: [
            ("bed.double.fill", "Lie face down", "On a bed or sofa, chin on your hands."),
            ("arrow.up", "Bend this knee, sole up", "Lower leg straight up, sole to the ceiling, ankle relaxed. Don't point the foot or pull the toes back; let the toes lie straight, not curled."),
            ("ruler.fill", "The ball of the foot level", "Your helper lays a book (anything flat and stiff) across the ball of the foot: the big-toe side and the little-toe side should both touch it. If one doesn't, turn the foot gently until it does, then take the book away."),
            ("shoeprints.fill", "Bare foot or a thin sock", "Nothing loose or thick."),
            ("person.2.fill", "A helper scans, two laps", "They circle the foot slowly, phone pointing down at the sole, until the ring is full; then a second lap, closer, over the toes and the back of the heel. You keep still."),
        ]
        case .rightSoleFlat, .leftSoleFlat: [
            ("bed.double.fill", "Lie face down, legs straight", "Feet just past the end of the bed: ankles at the edge, feet hanging relaxed."),
            ("arrow.left.and.right", "The other foot out of the way", "Move the other leg well to the side, a forearm's width between the feet, so only this foot is in the scan."),
            ("ruler.fill", "The ball of the foot level", "Your helper holds a book (anything flat and stiff) across the ball of the foot: the big-toe side and the little-toe side should both touch it. If one doesn't, turn the foot gently until it does, then take the book away."),
            ("shoeprints.fill", "Bare foot or a thin sock", "Nothing loose or thick."),
            ("person.2.fill", "A helper scans from behind", "Slowly from the inner side, round behind the foot, to the outer side. Then again a little higher, and lower."),
            ("leaf.fill", "Stay relaxed", "Your legs rest on the bed, so the foot can stay still. Breathe slowly."),
        ]
        case .rightPrint, .leftPrint: [
            ("shippingbox.fill", "A foam impression box", "Sold for orthotic casting. One block per foot; a clinician or athletic trainer may have them."),
            ("figure.seated.side.right", "Seated, press straight down", "Knee over the ankle. Push the foot down until the heel and toes are sunk in, then lift it straight up without rocking."),
            ("table.furniture.fill", "Box on a table, in even light", "With room to walk all the way round. The phone must see into the print from every side."),
            ("ruler.fill", "Calipers ready (optional)", "Measure how deep the heel print is; the studio reports the scan's depth, so you can compare."),
        ]
        case .shoeInsole: [
            ("shoe.fill", "The insole from the shoe you'll wear", "Pull it out of the shoe. One is enough: the studio fits it to either foot."),
            ("table.furniture.fill", "Flat on a plain, matte table, top side up", "With room to walk all the way round. A dark table if the insole is light, so its edge shows."),
            ("sun.max.fill", "Even light", "No harsh shadows across the edge."),
        ]
        case .calibration: [
            ("printer.fill", "Printed at 100%", "Matte, light-coloured filament; no supports."),
            ("table.furniture.fill", "On a plain, matte table", "With room to walk all the way round it."),
            ("sun.max.fill", "Bright, even light", "No harsh shadows or shiny reflections."),
        ]
        case .rightFoot, .leftFoot: [
            ("doc.on.doc.fill", "The paper mat is taped flat", "On a hard floor, with sheet 1 (the heel end) toward the chair."),
            ("figure.seated.side.right", "Sitting, foot bare and flat on the mat", "Trousers rolled past the ankle, lower leg straight down. The foot stays completely still."),
            ("scalemass.fill", "A bathroom scale under the foot", "You'll type in its reading afterwards: the studio needs it for a seated scan."),
            ("person.2.fill", "Someone else holds the phone", "It's much easier for them to walk round you."),
        ]
        case .other: [
            ("cube.fill", "Something matte with some texture", "A shoe, a patterned mug, a book. Shiny or plain white things come out patchy."),
            ("arrow.trianglehead.2.clockwise.rotate.90", "Room to walk all the way round", "On a table or the floor, in even light."),
        ]
        }
    }
}

struct PrepSheet: View {
    let subject: Subject
    /// First time: everything must be ticked. Later (Tips): just a reminder.
    var mustTick: Bool
    /// Scanning again after the studio refused the last one: what to change, shown first.
    var retake: [RetakeAdvice] = []
    var onStart: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var ticked = Set<Int>()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 14) {
                        Image(systemName: subject.symbol)
                            .font(.system(size: 26, weight: .semibold))
                            .foregroundStyle(Color.fsBrandInk)
                            .frame(width: 56, height: 56)
                            .background(Color.fsBrand, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .scaleEffect(x: subject.isLeft ? -1 : 1)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(mustTick ? "Before your first scan" : retake.isEmpty ? "Tips" : "Scan again").font(.subheadline.weight(.semibold)).foregroundStyle(Color.fsMuted)
                            Text(subject.label).font(.system(.title2, design: .rounded, weight: .bold))
                        }
                    }
                    .padding(.bottom, 4)
                    if !retake.isEmpty {
                        RetakeSteps(advice: retake, heading: "Change this time")
                            .card(padding: 16)
                    }
                    if subject.scanKind == "sole_up" || subject.scanKind == "sole_hanging" {
                        SoleScanAnimation(left: subject.isLeft, pose: subject.scanKind == "sole_up" ? .kneeBent : .legsFlat)
                            .padding(.bottom, 6)
                    }
                    ForEach(Array(subject.checklist.enumerated()), id: \.offset) { i, item in
                        row(i, item)
                            .modifier(StaggeredAppear(index: i))
                    }
                    if mustTick {
                        Text("You'll only see this list before your first \(subject.label.lowercased()) scan.")
                            .font(.footnote).foregroundStyle(Color.fsMuted)
                    }
                }
                .padding(20)
            }
            .background(Color.fsBackground)
            .safeAreaInset(edge: .bottom) {
                Button(mustTick && ticked.count < subject.checklist.count ? "Tick each one when it's ready" : "Start scanning") {
                    onStart()
                    dismiss()
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(mustTick && ticked.count < subject.checklist.count)
                .padding(.horizontal, 20).padding(.vertical, 10)
                .background(.bar)
            }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .sensoryFeedback(.impact(weight: .light), trigger: ticked)
        .sensoryFeedback(.success, trigger: ticked.count == subject.checklist.count)
    }

    private func row(_ i: Int, _ item: (String, String, String)) -> some View {
        Button {
            guard mustTick else { return }
            if ticked.contains(i) { ticked.remove(i) } else { ticked.insert(i) }
        } label: {
            HStack(alignment: .top, spacing: 14) {
                if mustTick {
                    Image(systemName: ticked.contains(i) ? "checkmark.circle.fill" : "circle")
                        .font(.title2)
                        .foregroundStyle(ticked.contains(i) ? Color.fsBrand : Color.fsLine)
                        .contentTransition(.symbolEffect(.replace))
                } else {
                    Image(systemName: item.0).font(.title3).foregroundStyle(Color.fsBrand)
                        .frame(width: 40, height: 40)
                        .background(Color.fsBrandSoft, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.1).font(.headline).foregroundStyle(Color.fsInk)
                    Text(item.2).font(.subheadline).foregroundStyle(Color.fsMuted).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .card(padding: 16)
        }
        .buttonStyle(PressableStyle())
        .disabled(!mustTick)
        .accessibilityAddTraits(ticked.contains(i) ? [.isSelected] : [])
    }
}

/// What to change on the next scan, after the studio refused one: each problem's title, then its steps, numbered.
struct RetakeSteps: View {
    let advice: [RetakeAdvice]
    var heading: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let heading { Text(heading).font(.headline).foregroundStyle(Color.fsInk) }
            ForEach(advice, id: \.self) { a in
                VStack(alignment: .leading, spacing: 8) {
                    Label(a.title, systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Color.fsWarn)
                    ForEach(Array(a.steps.enumerated()), id: \.offset) { i, step in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("\(i + 1)").font(.caption.weight(.bold).monospacedDigit())
                                .foregroundStyle(Color.fsBrandInk)
                                .frame(width: 20, height: 20)
                                .background(Color.fsBrand, in: Circle())
                            Text(step).font(.subheadline).foregroundStyle(Color.fsInk)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
