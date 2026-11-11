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

/// Two ways to scan. LiDAR (Apple's 3D capture) on an iPhone or iPad that supports it;
/// photos on the printed mat on any of them (needs the studio, which builds
/// the model).
enum CaptureMethod: String, CaseIterable, Identifiable {
    case lidar, photos
    var id: String { rawValue }
    var label: String { self == .lidar ? "3D capture" : "Photos + mat" }
    var detail: String {
        self == .lidar
            ? "LiDAR measures as it goes; the \(DeviceKind.current.noun) builds the model."
            : "Any iPhone or iPad. Uses the printed mat; your Footscan studio builds the model."
    }

    /// Can this phone or iPad do Apple's 3D capture (Object Capture)?
    @MainActor static var lidarAvailable: Bool { ObjectCaptureSession.isSupported }
}

/// iPhone or iPad, for the words on screen: "this iPad", not "this phone", when that's what's in their hands.
///
/// Apple's 3D capture (Object Capture) runs on the iPhones and iPads that have LiDAR and an A14 chip or later:
/// iPhone 12 Pro onwards (Pro models), and iPad Pro from 2021 (M1) onwards. The 2020 iPad Pro has LiDAR but
/// an A12Z, so it can't; no iPad Air, mini or plain iPad has LiDAR. The app never decides from that list: it
/// asks `ObjectCaptureSession.isSupported` and offers Photos + mat everywhere else.
enum DeviceKind {
    case phone, pad

    /// What this device is. Read once: an app can't move between an iPhone and an iPad.
    static let current: DeviceKind = UIDevice.current.userInterfaceIdiom == .pad ? .pad : .phone

    /// In a sentence: "this phone", "the iPad builds the model".
    var noun: String { self == .pad ? "iPad" : "phone" }
    /// The product: "This iPhone scans with photos", "Finder > iPad > Files".
    var model: String { self == .pad ? "iPad" : "iPhone" }
    /// The 3D capture needs: what to say where it can't run.
    var needsLiDAR: String {
        self == .pad ? "an iPad Pro with LiDAR (2021 or later)" : "an iPhone with LiDAR (a Pro model, 12 Pro or later)"
    }
}
