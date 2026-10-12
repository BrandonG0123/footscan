// What the app remembers between launches, so things are asked once.
//
// - The intro (with the safety points) is shown on first launch only.
// - Before the first scan of each kind there's a short "get ready" list;
//   once a scan of that kind has been captured, it's skipped (still one tap
//   away as Tips).
// - With a studio connected, finished models are sent automatically.
import Foundation
import SwiftUI

@MainActor
@Observable
final class AppSettings {
    private let defaults = UserDefaults.standard

    var onboarded: Bool { didSet { defaults.set(onboarded, forKey: "onboarded") } }
    var safetyAcknowledgedAt: Date? { didSet { defaults.set(safetyAcknowledgedAt, forKey: "safetyAcknowledgedAt") } }
    var autoSend: Bool { didSet { defaults.set(autoSend, forKey: "autoSend") } }
    private(set) var prepared: Set<String> { didSet { defaults.set(Array(prepared), forKey: "preparedSubjects") } }

    init() {
        onboarded = defaults.bool(forKey: "onboarded")
        safetyAcknowledgedAt = defaults.object(forKey: "safetyAcknowledgedAt") as? Date
        autoSend = defaults.object(forKey: "autoSend") as? Bool ?? true
        prepared = Set(defaults.stringArray(forKey: "preparedSubjects") ?? [])
    }

    func hasPrepared(_ subject: Subject) -> Bool { prepared.contains(subject.rawValue) }
    func markPrepared(_ subject: Subject) { prepared.insert(subject.rawValue) }

    /// Start over: the intro and every "get ready" list come back.
    func replayIntro() {
        onboarded = false
        prepared = []
    }
}
