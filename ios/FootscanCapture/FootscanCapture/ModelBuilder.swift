// Building the 3D model on the phone, from the photos Object Capture kept.
//
// Apple's PhotogrammetrySession does the reconstruction (on a phone it makes
// the "reduced" level of detail; a Mac can rebuild the same photos in more
// detail, see ios/tools/reconstruct-mac.swift). The model comes out as USDZ,
// in metres with Y pointing up; a copy is saved as OBJ, which the studio's
// Import 3D reads (it converts metres to millimetres).
import Foundation
import ModelIO
import RealityKit

@MainActor
@Observable
final class ModelBuilder {
    enum Phase: Equatable {
        case idle, building(Double), converting, done, failed(String)
    }

    var phase: Phase = .idle

    func build(_ scan: Scan) async {
        guard PhotogrammetrySession.isSupported else {
            phase = .failed("This device can't build 3D models. Copy the Images folder to a Mac and use reconstruct-mac.swift.")
            return
        }
        phase = .building(0)
        let started = Date()
        do {
            var config = PhotogrammetrySession.Configuration()
            config.checkpointDirectory = scan.checkpoint
            let session = try PhotogrammetrySession(input: scan.images, configuration: config)
            try session.process(requests: [.modelFile(url: scan.usdz)])
            outputs: for try await output in session.outputs {
                switch output {
                case .requestProgress(_, let fraction):
                    phase = .building(fraction)
                case .requestError(_, let error):
                    throw error
                case .processingCancelled:
                    throw CancellationError()
                case .processingComplete:
                    break outputs
                default:
                    continue
                }
            }
            phase = .converting
            try Self.exportOBJ(from: scan.usdz, to: scan.obj)
            var rec = scan.record
            rec?.modelBuiltOnPhone = true
            rec?.modelSeconds = Date().timeIntervalSince(started).rounded()
            if let rec { scan.save(rec) }
            phase = .done
        } catch {
            var rec = scan.record
            rec?.error = error.localizedDescription
            if let rec { scan.save(rec) }
            phase = .failed(error.localizedDescription)
        }
    }

    /// USDZ -> OBJ with Model I/O. Geometry only matters for measuring; the
    /// OBJ keeps the model's own units (metres) and axes (Y up).
    nonisolated static func exportOBJ(from usdz: URL, to obj: URL) throws {
        let asset = MDLAsset(url: usdz)
        guard asset.count > 0 else { throw ExportError.empty }
        try? FileManager.default.removeItem(at: obj)
        try asset.export(to: obj)
    }

    enum ExportError: LocalizedError {
        case empty
        var errorDescription: String? { "The model file came out empty." }
    }
}
