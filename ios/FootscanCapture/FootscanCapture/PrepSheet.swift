// "Get ready", before the first scan of each kind. Tick each thing as it's
// done; after that kind has been scanned once, this is skipped (and stays
// one tap away as Tips, without the ticking).
import RealityKit
import SwiftUI

extension Subject {
    var symbol: String {
        switch self {
        case .rightSole, .leftSole: "shoeprints.fill"
        case .rightPrint, .leftPrint: "shippingbox.fill"
        case .calibration: "cube.fill"
        case .rightFoot, .leftFoot: "figure.seated.side.right"
        case .other: "sparkles"
        }
    }

    /// What to have ready before scanning this: (symbol, title, detail).
    var checklist: [(String, String, String)] {
        switch self {
        case .rightSole, .leftSole: [
            ("bed.double.fill", "Lie face down, knee bent", "On a bed or sofa. Bend this knee so the sole faces the ceiling, and let the foot hang relaxed: don't point or pull back the toes."),
            ("shoeprints.fill", "Bare foot, or a thin snug sock", "Nothing loose or thick. A sock with a pattern can help the scan; it adds its thickness to the shape."),
            ("person.2.fill", "Someone else holds the phone", "They scan from above: slowly over the whole sole, then down both sides. The sole is what matters."),
            ("figure.yoga", "Keep the foot still", "Rest your chin on your hands and breathe slowly. If the foot sways, the scan blurs."),
        ]
        case .rightPrint, .leftPrint: [
            ("shippingbox.fill", "A foam impression box", "Sold for orthotic casting. One block per foot; a clinician or athletic trainer may have them."),
            ("figure.seated.side.right", "Seated, press straight down", "Knee over the ankle. Push the foot down until the heel and toes are sunk in, then lift it straight up without rocking."),
            ("table.furniture.fill", "Box on a table, in even light", "With room to walk all the way round. The phone must see into the print from every side."),
            ("ruler.fill", "Calipers ready (optional)", "Measure how deep the heel print is; the studio reports the scan's depth, so you can compare."),
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
                            Text(mustTick ? "Before your first scan" : "Tips").font(.subheadline.weight(.semibold)).foregroundStyle(Color.fsMuted)
                            Text(subject.label).font(.system(.title2, design: .rounded, weight: .bold))
                        }
                    }
                    .padding(.bottom, 4)
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
