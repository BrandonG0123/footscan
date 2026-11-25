// A scan's model, shared under a name that says which scan it is.
//
// Every scan's files are called model.obj and model.usdz on the phone, so three scans AirDropped to the Mac
// arrived as model.obj, model-1.obj and model-2.obj, with nothing to tell which foot each was. Shared from the
// app they're now named after the scan: "Right sole 2026-11-25 0412.obj", or its name if it has one
// ("Sam, left 2026-11-25 0412.obj"). The files on the phone keep their names.
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

    /// The model file `url` of `scan`, named after the scan.
    init(_ url: URL, of scan: Scan) {
        self.url = url
        name = Self.fileName(for: scan.record, ext: url.pathExtension)
    }

    /// "Right sole 2026-11-25 0412.obj": the scan's name (or what it's of), and when it was taken, in this
    /// phone's time zone. Characters a file name can't hold become spaces.
    static func fileName(for record: ScanRecord?, ext: String, timeZone: TimeZone = .current) -> String {
        guard let record else { return "model.\(ext)" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = timeZone
        f.dateFormat = "yyyy-MM-dd HHmm"
        let unsafe = CharacterSet(charactersIn: "/\\:?%*|\"<>").union(.controlCharacters).union(.newlines)
        let heading = record.heading.components(separatedBy: unsafe).joined(separator: " ")
            .split(separator: " ", omittingEmptySubsequences: true).joined(separator: " ")
        let stem = heading.isEmpty ? "Scan" : heading
        return "\(stem) \(f.string(from: record.created)).\(ext)"
    }
}
