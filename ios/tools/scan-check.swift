// Run the phone's own scan check (ScanCheck.swift, the same file the app
// builds) on models on the Mac: to see what it says about real scans before
// changing a threshold, and to look at a scan someone sent.
//
//   swiftc -O ios/FootscanCapture/FootscanCapture/ScanCheck.swift ios/tools/scan-check.swift -o /tmp/scan-check
//   /tmp/scan-check sole_up data/captures/*/original.obj
//   /tmp/scan-check calibration|shoe_insole <model.obj>...
//
// One line of JSON per model: what it measured, and what it would tell the
// person (scan_again: the app holds the scan back and says scan again).
import Foundation

@main
struct ScanCheckTool {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count >= 3, let kind = ScanCheck.Kind(rawValue: args[1]) else {
            FileHandle.standardError.write("usage: scan-check sole_up|calibration|shoe_insole <model.obj>...\n".data(using: .utf8)!)
            exit(2)
        }
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        for path in args[2...] {
            let started = Date()
            var line: [String: AnyEncodable] = ["model": AnyEncodable(path)]
            do {
                let report = try ScanCheck.run(obj: URL(fileURLWithPath: path), kind: kind)
                line["measures"] = AnyEncodable(report.measures)
                line["scan_again"] = AnyEncodable(report.findings.filter(\.scanAgain).map(\.code))
                line["notes"] = AnyEncodable(report.findings.filter { !$0.scanAgain }.map(\.code))
                line["said"] = AnyEncodable(report.findings.map(\.detail))
            } catch {
                line["error"] = AnyEncodable(error.localizedDescription)
            }
            line["seconds"] = AnyEncodable((Date().timeIntervalSince(started) * 10).rounded() / 10)
            print(String(decoding: try enc.encode(line), as: UTF8.self))
        }
    }
}

struct AnyEncodable: Encodable {
    let encodeTo: (Encoder) throws -> Void
    init<T: Encodable>(_ value: T) { encodeTo = value.encode }
    func encode(to encoder: Encoder) throws { try encodeTo(encoder) }
}
