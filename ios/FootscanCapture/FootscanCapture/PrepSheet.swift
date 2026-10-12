// "Get ready", before the first scan of each kind. Tick each thing as it's
// done; after that kind has been scanned once, this is skipped (and stays
// one tap away as Tips, without the ticking).
import SwiftUI

extension Subject {
    var symbol: String {
        switch self {
        case .calibration: "cube.fill"
        case .rightFoot: "shoeprints.fill"
        case .leftFoot: "shoeprints.fill"
        case .other: "sparkles"
        }
    }

    /// What to have ready before scanning this.
    var checklist: [(String, String)] {
        switch self {
        case .calibration: [
            ("Printed at 100%", "Matte, light-coloured filament; no supports."),
            ("On a plain, matte table", "With room to walk all the way round it."),
            ("Bright, even light", "No harsh shadows or shiny reflections."),
        ]
        case .rightFoot, .leftFoot: [
            ("The paper mat is taped flat", "On a hard floor, with sheet 1 (the heel end) toward the chair."),
            ("Foot bare, trousers rolled up", "Past the ankle, so the whole foot shows."),
            ("Sitting, foot flat on the mat", "Lower leg straight down. The foot stays completely still."),
            ("Someone else holds the phone", "It's much easier for them to walk round you."),
            ("A scale reading, if you can", "Bathroom scale under the foot: the studio records the load with the scan."),
        ]
        case .other: [
            ("Something matte with some texture", "A shoe, a patterned mug, a book. Shiny or plain white things come out patchy."),
            ("Room to walk all the way round", "On a table or the floor, in even light."),
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
                            .scaleEffect(x: subject == .leftFoot ? -1 : 1)
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

    private func row(_ i: Int, _ item: (String, String)) -> some View {
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
                    Image(systemName: "lightbulb.fill").font(.title3).foregroundStyle(Color.fsBrand).frame(width: 28)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.0).font(.headline).foregroundStyle(Color.fsInk)
                    Text(item.1).font(.subheadline).foregroundStyle(Color.fsMuted).fixedSize(horizontal: false, vertical: true)
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
