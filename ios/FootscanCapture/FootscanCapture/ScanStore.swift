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
    case calibration = "calibration-object"
    case rightFoot = "right-foot"
    case leftFoot = "left-foot"
    case other = "other"

    var id: String { rawValue }

    var isFoot: Bool { self == .rightFoot || self == .leftFoot }

    /// For the small cards on the home screen.
    var shortLabel: String {
        switch self {
        case .calibration: "Calibration"
        case .rightFoot: "Right foot"
        case .leftFoot: "Left foot"
        case .other: "Anything"
        }
    }

    var label: String {
        switch self {
        case .calibration: "Calibration object"
        case .rightFoot: "Right foot"
        case .leftFoot: "Left foot"
        case .other: "Anything else"
        }
    }

    var howTo: String {
        switch self {
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
    var units = "metres, Y up (Apple Object Capture's own frame). The studio's Import 3D converts to millimetres."
    var note = "Footscan LiDAR test capture. Not a medical device."
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
