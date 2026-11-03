// What the app remembers between launches, so things are asked once.
//
// - The intro (with the safety points) is shown on first launch only.
// - Before the first scan of each kind there's a short "get ready" list;
//   once a scan of that kind has been captured, it's skipped (still one tap
//   away as Tips).
// - With a studio connected, finished models are sent automatically.
import Foundation
import RealityKit
import SwiftUI

@MainActor
@Observable
final class AppSettings {
    private let defaults = UserDefaults.standard

    var onboarded: Bool { didSet { defaults.set(onboarded, forKey: "onboarded") } }
    var safetyAcknowledgedAt: Date? { didSet { defaults.set(safetyAcknowledgedAt, forKey: "safetyAcknowledgedAt") } }
    var autoSend: Bool { didSet { defaults.set(autoSend, forKey: "autoSend") } }
    /// The chosen way to scan, on phones that can do both.
    var method: CaptureMethod { didSet { defaults.set(method.rawValue, forKey: "captureMethod") } }
    private(set) var prepared: Set<String> { didSet { defaults.set(Array(prepared), forKey: "preparedSubjects") } }

    init() {
        onboarded = defaults.bool(forKey: "onboarded")
        safetyAcknowledgedAt = defaults.object(forKey: "safetyAcknowledgedAt") as? Date
        autoSend = defaults.object(forKey: "autoSend") as? Bool ?? true
        method = CaptureMethod(rawValue: defaults.string(forKey: "captureMethod") ?? "") ?? .lidar
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

/// Two ways to scan. LiDAR (Apple's 3D capture) on phones that support it;
/// photos on the printed mat on any iPhone (needs the studio, which builds
/// the model).
enum CaptureMethod: String, CaseIterable, Identifiable {
    case lidar, photos
    var id: String { rawValue }
    var label: String { self == .lidar ? "3D capture" : "Photos + mat" }
    var detail: String {
        self == .lidar
            ? "LiDAR measures as it goes; the phone builds the model."
            : "Any iPhone. Uses the printed mat; the studio on your Mac builds the model."
    }

    /// Can this phone do Apple's 3D capture (Object Capture)?
    @MainActor static var lidarAvailable: Bool { ObjectCaptureSession.isSupported }
}
