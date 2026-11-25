// Where scans live on the phone, and what each one records about itself.
//
// Every scan is a folder in the app's Documents, which the Files app and
// Finder (iPhone > Files) can both see:
//
//   Documents/Scans/<what>-<date>/
//     Images/        the photos Object Capture kept (with LiDAR depth inside)
//     Checkpoint/    Object Capture's working data; speeds up the model step
//     model.usdz     the 3D model the phone built (metres, Y up)
//     model.obj      the same model as OBJ, for the studio's Import 3D
//     scan.json      what was scanned, when, on what phone, and how it went
//
// Not a medical device: this is a test app for measuring how accurate LiDAR
// capture is, before deciding whether footscan should use it.
import Foundation
import UIKit

enum Subject: String, CaseIterable, Identifiable, Codable {
    // The bottom of the foot is what the insole is made from, so the scans
    // that show it come first: the sole facing the camera, and the print a
    // foot leaves in a foam box.
    case rightSole = "right-sole"
    case leftSole = "left-sole"
    case rightSoleFlat = "right-sole-legs-flat"
    case leftSoleFlat = "left-sole-legs-flat"
    case rightPrint = "right-foam-print"
    case leftPrint = "left-foam-print"
    // the shoe's own insole, lying flat: the printed insole can take its outline, to fit that shoe
    case shoeInsole = "shoe-insole"
    case calibration = "calibration-object"
    case rightFoot = "right-foot"
    case leftFoot = "left-foot"
    case other = "other"

    var id: String { rawValue }

    /// "right" or "left" for anything of a foot; nil otherwise.
    var side: String? {
        switch self {
        case .rightSole, .rightSoleFlat, .rightPrint, .rightFoot: "right"
        case .leftSole, .leftSoleFlat, .leftPrint, .leftFoot: "left"
        case .shoeInsole, .calibration, .other: nil
        }
    }

    var isFoot: Bool { side != nil }
    var isLeft: Bool { side == "left" }

    /// A foot resting on the floor, seated: the studio needs the bathroom-scale reading under it.
    var needsScale: Bool { self == .rightFoot || self == .leftFoot }

    /// How the studio's Make insole should read the model.
    var scanKind: String? {
        switch self {
        case .rightSole, .leftSole: "sole_up"
        case .rightSoleFlat, .leftSoleFlat: "sole_hanging"
        case .rightPrint, .leftPrint: "impression"
        case .rightFoot, .leftFoot: "foot"
        case .shoeInsole, .calibration, .other: nil
        }
    }

    /// How the phone checks the model it built, before it's sent (ScanCheck); nil: not checked on the phone.
    var checkKind: ScanCheck.Kind? {
        switch self {
        case .rightSole, .leftSole: .soleUp
        case .shoeInsole: .shoeInsole
        case .calibration: .calibration
        default: nil
        }
    }

    /// Sole and foam-print scans use Apple's 3D capture (the printed mat can't go under a raised sole or a foam box).
    var needs3DCapture: Bool {
        switch self {
        case .rightSole, .leftSole, .rightSoleFlat, .leftSoleFlat, .rightPrint, .leftPrint, .shoeInsole: true
        default: false
        }
    }

    /// For the small cards on the home screen.
    var shortLabel: String {
        switch self {
        case .rightSole: "Right sole"
        case .leftSole: "Left sole"
        case .rightSoleFlat: "Legs flat, right"
        case .leftSoleFlat: "Legs flat, left"
        case .rightPrint: "Right foam print"
        case .leftPrint: "Left foam print"
        case .shoeInsole: "Shoe's insole"
        case .calibration: "Calibration"
        case .rightFoot: "Whole right foot"
        case .leftFoot: "Whole left foot"
        case .other: "Anything"
        }
    }

    var label: String {
        switch self {
        case .rightSole: "Right sole"
        case .leftSole: "Left sole"
        case .rightSoleFlat: "Right sole, legs flat"
        case .leftSoleFlat: "Left sole, legs flat"
        case .rightPrint: "Right foam print"
        case .leftPrint: "Left foam print"
        case .shoeInsole: "Your shoe's insole"
        case .calibration: "Calibration object"
        case .rightFoot: "Whole right foot"
        case .leftFoot: "Whole left foot"
        case .other: "Anything else"
        }
    }

    /// One line under the card: what this scan is for.
    var purpose: String {
        switch self {
        case .rightSole, .leftSole: "Sole up, today"
        case .rightSoleFlat, .leftSoleFlat: "Steadier? Compare"
        case .rightPrint, .leftPrint: "Most accurate"
        case .shoeInsole: "Fit to your shoe"
        case .calibration: "Check accuracy"
        case .rightFoot, .leftFoot: "Size, not sole"
        case .other: "Practice"
        }
    }

    var howTo: String {
        switch self {
        case .rightSole, .leftSole:
            "Lie face down on a bed, bend this knee so the sole faces the ceiling, and let the foot relax. Someone else scans the sole from above and round both sides."
        case .rightSoleFlat, .leftSoleFlat:
            "Lie face down on a bed with your legs straight and your feet just past the end, hanging relaxed. Someone else sweeps the phone round behind the foot."
        case .rightPrint, .leftPrint:
            "Press this foot straight down into a foam impression box while seated, lift it straight out, and scan the print from all round, with the box on a table."
        case .shoeInsole:
            "Take the insole out of the shoe you'll wear and lay it flat on a plain, matte table, top side up, with space to walk all the way round. The printed insole takes its outline."
        case .calibration:
            "Put the printed calibration object on a plain, matte table with space to walk all the way round. Even light, no harsh shadows."
        case .rightFoot, .leftFoot:
            "Sit on a chair with this foot bare and flat on the printed mat. Keep the foot completely still. Someone else holds the phone and walks round you."
        case .other:
            "Any object on a table, to get a feel for how capture works. Matte, textured things scan best; shiny or plain white ones (like earbuds) come out patchy."
        }
    }
}

struct ScanRecord: Codable {
    var subject: Subject
    var created: Date
    var device: String
    var systemVersion: String
    var appVersion: String
    var shotsTaken: Int?
    var scanPasses: Int?
    var modelBuiltOnPhone: Bool = false
    var modelSeconds: Double?
    var error: String?
    /// Bathroom-scale reading under the foot (kg): the studio needs it for a loaded (seated) foot scan.
    var loadKg: Double?
    /// Set once it has been sent to the studio.
    var studioCaptureID: String?
    var studioHost: String?
    var sentAt: Date?
    var studioAccuracy: StudioAccuracy?
    /// Set when the studio refused the scan because part of the foot is missing (toes, heel): what's
    /// missing and how to scan again, one line each. Such a scan is never sent again: take a new one.
    var retake: [String]?
    /// With `retake`: what to change on the next scan, as the studio worded it (title and steps per problem).
    /// Missing from records made before the studio sent it, and from studios that don't: see `nextTime`.
    var retakeAdvice: [RetakeAdvice]?
    /// What the phone's own check (ScanCheck) found once the model was built. A scan it says to scan again isn't
    /// sent by itself; it goes only if the person taps Send anyway.
    var phoneCheck: PhoneCheck?
    /// Set when the person stopped the capture partway (the X, then Stop scanning) after photos were taken. The
    /// photos stay, but the home screen doesn't ask for its model to be built: a scan stopped on purpose is
    /// usually one they meant to start again. Its page can still build it.
    var stoppedEarly: Date?
    /// The capture the studio made for this scan on a try whose upload then dropped: the next try sends the model
    /// into it, so a shaky connection doesn't leave the studio one empty capture per try.
    var pendingCapture: PendingCapture?
    var units = "metres, Y up (Apple Object Capture's own frame). The studio's Import 3D converts to millimetres."
    var note = "Footscan LiDAR test capture. Not a medical device."
}

extension ScanRecord {
    /// What to change on the next scan of this kind, if the studio refused this one: its own steps, or for
    /// a refusal that came without them, each line's headline as the title and its "Scan again ..." ending
    /// as the one step (the same fallback as the studio's completeness.retake_advice). If the studio hasn't
    /// refused it, what the phone's own check said to change.
    var nextTime: [RetakeAdvice] {
        if let retakeAdvice, !retakeAdvice.isEmpty { return retakeAdvice }
        if let retake { return retake.map(RetakeAdvice.init(line:)) }
        return phoneCheck?.scanAgain.map { RetakeAdvice(code: $0.code, title: $0.title, steps: $0.steps) } ?? []
    }

    /// The phone's check said scan again, and nobody chose to send it anyway: held back, not sent by itself.
    var heldByPhoneCheck: Bool {
        guard let phoneCheck, phoneCheck.sentAnyway == nil else { return false }
        return !phoneCheck.scanAgain.isEmpty
    }
}

/// A capture the studio made for a scan whose upload then dropped. Sending a model into a capture again replaces
/// the model there, so the next try can finish this one instead of making another.
struct PendingCapture: Codable, Equatable {
    var id: String
    /// Which studio made it (`identity(of:)`): another studio's capture ids mean nothing here.
    var studio: String
    /// The scale reading it was made with (foot scans): a different one now needs a new capture.
    var loadKg: Double?

    /// The same studio whichever address it answers at: its pinned certificate, else (a development build's
    /// public studio) its address.
    static func identity(of link: StudioLink) -> String { link.fingerprint ?? link.host }
}

extension ScanRecord {
    /// The capture an earlier, dropped try made, if it was made at this studio with the same scale reading.
    func reusableCapture(at link: StudioLink) -> String? {
        guard let pendingCapture, pendingCapture.studio == PendingCapture.identity(of: link),
              pendingCapture.loadKg == loadKg else { return nil }
        return pendingCapture.id
    }
}

/// The phone's own check of a scan's model (ScanCheck), as kept in its record.
struct PhoneCheck: Codable {
    /// ScanCheck.version that made it: a scan checked by an older one is checked again, until it's sent.
    var version: Int
    var findings: [ScanCheck.Finding]
    /// What it measured (angles in degrees, lengths in mm), for tuning the check on real scans.
    var measures: [String: Double]
    /// Set if the check couldn't run (the model couldn't be read). Nothing is held back then.
    var error: String?
    /// When the person chose to send it even so.
    var sentAnyway: Date?

    /// The findings that mean the scan won't make a good insole.
    var scanAgain: [ScanCheck.Finding] { findings.filter(\.scanAgain) }
    /// Worth knowing, but the scan can still be used.
    var notes: [ScanCheck.Finding] { findings.filter { !$0.scanAgain } }
}

/// What to change on the next scan after the studio refused one (its completeness.retake_advice): a short
/// title for what went wrong, and the steps to do differently, in the order to do them.
struct RetakeAdvice: Codable, Hashable {
    var code: String
    var title: String
    var steps: [String]

    init(code: String, title: String, steps: [String]) {
        self.code = code; self.title = title; self.steps = steps
    }

    /// From one of the studio's refusal lines alone ("THE TOES ARE MISSING: ... Scan again with ...").
    init(line: String) {
        let head = line.split(separator: ":", maxSplits: 1).first.map(String.init) ?? line
        let lower = head.trimmingCharacters(in: .whitespaces).lowercased()
        let again = line.range(of: "Scan again").map { String(line[$0.lowerBound...]) } ?? "Scan again."
        self.init(code: "other", title: lower.prefix(1).uppercased() + lower.dropFirst(), steps: [again])
    }
}

struct Scan: Identifiable, Hashable {
    let folder: URL
    var id: URL { folder }

    var images: URL { folder.appending(path: "Images", directoryHint: .isDirectory) }
    var checkpoint: URL { folder.appending(path: "Checkpoint", directoryHint: .isDirectory) }
    var usdz: URL { folder.appending(path: "model.usdz") }
    var obj: URL { folder.appending(path: "model.obj") }
    var recordURL: URL { folder.appending(path: "scan.json") }
    var thumbnail: URL { folder.appending(path: "thumb.png") }

    var record: ScanRecord? {
        guard let data = try? Data(contentsOf: recordURL) else { return nil }
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        return try? dec.decode(ScanRecord.self, from: data)
    }

    func save(_ record: ScanRecord) {
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .iso8601
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        try? enc.encode(record).write(to: recordURL, options: .atomic)
    }

    var hasModel: Bool { FileManager.default.fileExists(atPath: usdz.path()) }

    /// What deleting this scan from the phone loses, said in the confirmation before it goes.
    var deleteWarning: String {
        record?.studioCaptureID == nil ? "Its photos and model will be gone." : "The copy in the studio stays."
    }

    /// Photos and no studio copy of the model yet: the home screen asks for it to be finished (built). Not a capture
    /// the person stopped partway, until a model is built from it anyway (then its copy for the studio is owed).
    var waitsToBuild: Bool { photoCount > 0 && !hasOBJ && (record?.stoppedEarly == nil || hasModel) }

    /// Nothing was kept or happened: no photos, no model, no shots counted (a stopped capture's photos may still be
    /// on their way to the folder) and no error saved to explain a failure. A capture cancelled before its first
    /// photo leaves this, and its folder can go.
    var keptNothing: Bool {
        guard photoCount == 0, !hasModel else { return false }
        guard let rec = record else { return true }
        return rec.stoppedEarly == nil && rec.error == nil && (rec.shotsTaken ?? 0) == 0
    }
    var hasOBJ: Bool { FileManager.default.fileExists(atPath: obj.path()) }

    var photoCount: Int {
        (try? FileManager.default.contentsOfDirectory(atPath: images.path()))?
            .filter { !$0.hasPrefix(".") }.count ?? 0
    }
}

enum ScanStore {
    static var root: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appending(path: "Scans", directoryHint: .isDirectory)
    }

    /// A new, empty scan folder for this subject.
    static func create(_ subject: Subject) throws -> Scan {
        let stamp = ISO8601DateFormatter.string(from: Date(), timeZone: .current,
                                                formatOptions: [.withFullDate, .withTime, .withColonSeparatorInTime])
            .replacingOccurrences(of: ":", with: "")
        let scan = Scan(folder: root.appending(path: "\(subject.rawValue)-\(stamp)", directoryHint: .isDirectory))
        for dir in [scan.images, scan.checkpoint] {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        scan.save(ScanRecord(subject: subject, created: Date(), device: deviceModel(),
                             systemVersion: UIDevice.current.systemVersion,
                             appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"))
        return scan
    }

    /// Every scan on the phone (or in `folder`, for tests), newest first.
    static func all(in folder: URL = root) -> [Scan] {
        let urls = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.creationDateKey])) ?? []
        // Newest first, by when each scan was taken (folder names start with
        // the kind of scan, so sorting by name would group them by kind).
        let scans = urls.filter(\.hasDirectoryPath).map { url -> (Scan, Date) in
            let scan = Scan(folder: url)
            let made = scan.record?.created
                ?? (try? url.resourceValues(forKeys: [.creationDateKey]).creationDate)
                ?? .distantPast
            return (scan, made)
        }
        return scans.sorted { $0.1 != $1.1 ? $0.1 > $1.1 : $0.0.folder.lastPathComponent > $1.0.folder.lastPathComponent }
            .map(\.0)
    }

    static func delete(_ scan: Scan) {
        try? FileManager.default.removeItem(at: scan.folder)
    }

    /// A readable name for a hardware model code. Only codes confirmed on a
    /// real device are listed; anything else shows the code itself.
    static func phoneName(_ code: String) -> String {
        ["iPhone18,1": "iPhone 17 Pro"][code] ?? code
    }

    /// The hardware model, e.g. "iPhone18,1", so results can be compared across phones.
    static func deviceModel() -> String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
    }
}
