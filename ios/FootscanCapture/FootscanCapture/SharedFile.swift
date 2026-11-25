// A scan's model, shared under a name that says which scan it is.
//
// Every scan's files are called model.obj and model.usdz on the phone, so three scans AirDropped to the Mac
// arrived as model.obj, model-1.obj and model-2.obj, with nothing to tell which foot each was. Shared from the
// app they're now named after the scan: "Right sole 2026-11-25 041200.obj", or its name if it has one
// ("Sam, left 2026-11-25 041200.obj"), so a scan's name goes wherever the person sends the file. The
// files on the phone keep their names.
import CoreTransferable
import Foundation
import UniformTypeIdentifiers

struct SharedFile: Transferable {
    let url: URL
    let name: String

    static var transferRepresentation: some TransferRepresentation {
        // the type the file is, so the receiving app knows it (Quick Look opens a .usdz, say)
        FileRepresentation(exportedContentType: .usdz) { SentTransferredFile($0.url) }
            .suggestedFileName { $0.name }
            .exportingCondition { $0.url.pathExtension.lowercased() == "usdz" }
        FileRepresentation(exportedContentType: UTType(filenameExtension: "obj") ?? .data) { SentTransferredFile($0.url) }
            .suggestedFileName { $0.name }
            .exportingCondition { $0.url.pathExtension.lowercased() != "usdz" }
    }

    /// The model file `url` of `scan` (whose record is `record`, read once by the caller), named after the scan.
    init(_ url: URL, record: ScanRecord?) {
        self.url = url
        name = Self.fileName(for: record, ext: url.pathExtension)
    }

    /// "Right sole 2026-11-25 041200.obj": the scan's name (or what it's of), and when it was taken, in this
    /// phone's time zone now. Characters a file name can't hold become spaces, and leading dots go (a name
    /// starting with one would make a hidden file on the Mac).
    static func fileName(for record: ScanRecord?, ext: String, timeZone: TimeZone = .current) -> String {
        guard let record else { return "model.\(ext)" }
        let unsafe = CharacterSet(charactersIn: "/\\:?%*|\"<>").union(.controlCharacters).union(.newlines)
        var heading = record.heading.components(separatedBy: unsafe).joined(separator: " ")
            .split(separator: " ", omittingEmptySubsequences: true).joined(separator: " ")
        while heading.hasPrefix(".") { heading.removeFirst() }
        heading = heading.trimmingCharacters(in: .whitespaces)
        // to the second, as the scan folders are, so two quick retakes differ
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let c = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: record.created)
        let stamp = String(format: "%04d-%02d-%02d %02d%02d%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0,
                           c.hour ?? 0, c.minute ?? 0, c.second ?? 0)
        return "\(heading.isEmpty ? "Scan" : heading) \(stamp).\(ext)"
    }
}
