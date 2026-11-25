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
            // built beside the scan under a working name and moved into place whole once done: a build cut off
            // while writing (the app ended) never leaves a half-written model.usdz that counts as a model
            let fm = FileManager.default
            let staged = scan.folder.appending(path: "model-building.usdz")
            try? fm.removeItem(at: staged)
            defer { try? fm.removeItem(at: staged) }
            let session = try PhotogrammetrySession(input: scan.images, configuration: config)
            try session.process(requests: [.modelFile(url: staged)])
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
            try Self.putInPlace(staged, at: scan.usdz)
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
    ///
    /// Written in a working folder beside it and moved into place whole: model.obj is what says a scan is ready to
    /// send, so a half-written one (the app ended partway) must never exist. A failed export leaves what was there.
    nonisolated static func exportOBJ(from usdz: URL, to obj: URL) throws {
        let asset = MDLAsset(url: usdz)
        guard asset.count > 0 else { throw ExportError.empty }
        let fm = FileManager.default
        let folder = obj.deletingLastPathComponent()
        let work = folder.appending(path: ".obj-export", directoryHint: .isDirectory)
        try? fm.removeItem(at: work)
        try fm.createDirectory(at: work, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: work) }
        let staged = work.appending(path: obj.lastPathComponent)
        try asset.export(to: staged)
        guard fm.fileExists(atPath: staged.path()) else { throw ExportError.empty }
        // anything the export wrote beside it (a material file the OBJ names) first, the OBJ itself last
        for file in try fm.contentsOfDirectory(at: work, includingPropertiesForKeys: nil)
        where file.lastPathComponent != obj.lastPathComponent {
            try putInPlace(file, at: folder.appending(path: file.lastPathComponent))
        }
        try putInPlace(staged, at: obj)
    }

    /// Move a finished file to where it belongs, replacing what's there, in one step (a rename on the same disk).
    nonisolated static func putInPlace(_ file: URL, at destination: URL) throws {
        let fm = FileManager.default
        if fm.fileExists(atPath: destination.path()) {
            _ = try fm.replaceItemAt(destination, withItemAt: file)
        } else {
            try fm.moveItem(at: file, to: destination)
        }
    }

    enum ExportError: LocalizedError {
        case empty
        var errorDescription: String? { "The model file came out empty." }
    }
}
