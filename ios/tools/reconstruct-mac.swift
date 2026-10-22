// Rebuild a phone scan's 3D model on the Mac, in more detail than the phone can.
//
//   swiftc -O ios/tools/reconstruct-mac.swift -o /tmp/reconstruct-mac
//   /tmp/reconstruct-mac <Images folder> <out.usdz> [reduced|medium|full|raw] [Checkpoint folder]
//
// With the scan's Checkpoint folder (the phone's own session data, next to
// Images), the Mac starts from what the phone worked out. Pass a copy: the
// Mac writes into it.
//
// The phone builds the "reduced" level of detail; an Apple-silicon Mac can
// build medium, full or raw from the same photos (they carry the LiDAR depth
// and the phone's positions inside them). Also writes <out>.obj next to it
// for the studio's Import 3D. Compare phone vs Mac with footscan accuracy-mesh.
import Foundation
import ModelIO
import RealityKit

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 3 else { fail("usage: reconstruct-mac <Images folder> <out.usdz> [reduced|medium|full|raw] [Checkpoint folder]") }
let images = URL(fileURLWithPath: args[1], isDirectory: true)
let out = URL(fileURLWithPath: args[2])
let details: [String: PhotogrammetrySession.Request.Detail] = ["reduced": .reduced, "medium": .medium, "full": .full, "raw": .raw]
let detailName = args.count > 3 ? args[3] : "full"
guard let detail = details[detailName] else { fail("detail must be one of: reduced, medium, full, raw") }
guard PhotogrammetrySession.isSupported else { fail("This Mac can't run PhotogrammetrySession (it needs Apple silicon or a capable GPU).") }

let started = Date()
let session: PhotogrammetrySession
do {
    var configuration = PhotogrammetrySession.Configuration()
    if args.count > 4 { configuration.checkpointDirectory = URL(fileURLWithPath: args[4], isDirectory: true) }
    // FOOTSCAN_NO_MASK=1: keep everything the photos show (object masking can cut away a foot's heel where it
    // meets the leg and the bed)
    if ProcessInfo.processInfo.environment["FOOTSCAN_NO_MASK"] == "1" { configuration.isObjectMaskingEnabled = false }
    session = try PhotogrammetrySession(input: images, configuration: configuration)
    try session.process(requests: [.modelFile(url: out, detail: detail)])
} catch {
    fail("couldn't start: \(error.localizedDescription)")
}

let done = DispatchSemaphore(value: 0)
var failure: String?
Task {
    do {
        for try await output in session.outputs {
            switch output {
            case .requestProgress(_, let fraction):
                print(String(format: "\r%3.0f%%", fraction * 100), terminator: "")
                fflush(stdout)
            case .requestError(_, let error):
                failure = error.localizedDescription
            case .processingComplete, .processingCancelled:
                done.signal()
                return
            default:
                continue
            }
        }
    } catch {
        failure = error.localizedDescription
    }
    done.signal()
}
done.wait()
print("")
if let failure { fail("reconstruction failed: \(failure)") }

let obj = out.deletingPathExtension().appendingPathExtension("obj")
let asset = MDLAsset(url: out)
do {
    try? FileManager.default.removeItem(at: obj)
    try asset.export(to: obj)
} catch {
    fail("built \(out.path) but couldn't write the OBJ: \(error.localizedDescription)")
}
print("\(detailName) model: \(out.path) and \(obj.path) (\(Int(Date().timeIntervalSince(started))) s)")
