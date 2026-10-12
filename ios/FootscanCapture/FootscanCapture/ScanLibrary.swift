// Every scan on the phone, and what's happening to each one.
//
// One place runs the steps after a capture, so they carry on whichever
// screen is showing: build the 3D model, make a thumbnail, and (with a
// studio connected and "send automatically" on) send it. Home cards and the
// scan's own page both read the progress from here.
import Foundation
import SwiftUI
import UIKit

@MainActor
@Observable
final class ScanLibrary {
    enum Work: Equatable {
        case building(Double), converting, sending
    }

    private(set) var scans: [Scan] = []
    private(set) var work: [URL: Work] = [:]
    private(set) var problems: [URL: String] = [:]
    /// Bumped when a scan's files or record change, so views re-read them.
    private(set) var version = 0

    init() { reload() }

    func reload() {
        scans = ScanStore.all()
        version += 1
    }

    func delete(_ scan: Scan) {
        ScanStore.delete(scan)
        work[scan.folder] = nil
        problems[scan.folder] = nil
        reload()
    }

    func deleteAll() {
        for s in scans { ScanStore.delete(s) }
        work = [:]
        problems = [:]
        reload()
    }

    // MARK: after a capture

    /// Build the model, then send it if that's what the settings say.
    func finish(_ scan: Scan, settings: AppSettings, studio: StudioConnection) async {
        if !scan.hasModel { await build(scan) }
        guard scan.hasOBJ, settings.autoSend, studio.client != nil, let rec = scan.record,
              rec.studioCaptureID == nil, !rec.subject.isFoot || rec.loadKg != nil else { return }
        await send(scan, studio: studio)
    }

    func build(_ scan: Scan) async {
        guard work[scan.folder] == nil else { return }
        problems[scan.folder] = nil
        work[scan.folder] = .building(0)
        let builder = ModelBuilder()
        let watch = Task { @MainActor in
            while !Task.isCancelled {
                switch builder.phase {
                case .building(let f): work[scan.folder] = .building(f)
                case .converting: work[scan.folder] = .converting
                default: break
                }
                try? await Task.sleep(for: .milliseconds(200))
            }
        }
        await builder.build(scan)
        watch.cancel()
        work[scan.folder] = nil
        if case .failed(let message) = builder.phase {
            problems[scan.folder] = message
        } else {
            await makeThumbnail(scan)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        }
        reload()
    }

    func send(_ scan: Scan, studio: StudioConnection, loadKg: Double? = nil) async {
        guard let client = studio.client, var record = scan.record, work[scan.folder] == nil else { return }
        if let loadKg { record.loadKg = loadKg; scan.save(record) }
        problems[scan.folder] = nil
        work[scan.folder] = .sending
        defer { work[scan.folder] = nil; reload() }
        do {
            let sent = try await client.upload(scan, record: record)
            record.studioCaptureID = sent.captureID
            record.studioHost = client.link.host
            record.sentAt = Date()
            record.studioAccuracy = sent.accuracy
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        } catch {
            problems[scan.folder] = error.localizedDescription
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        }
    }

    /// Save a picture of the model next to it, for the scan cards.
    func makeThumbnail(_ scan: Scan) async {
        guard scan.hasModel else { return }
        let url = scan.usdz, out = scan.thumbnail
        let png = await Task.detached(priority: .utility) {
            ModelScene.snapshot(url, size: CGSize(width: 360, height: 360))?.pngData()
        }.value
        if let png { try? png.write(to: out, options: .atomic) }
    }

    /// Bytes used by every scan (photos, working data, models).
    func storageUsed() -> Int64 {
        var total: Int64 = 0
        let fm = FileManager.default
        for s in scans {
            guard let e = fm.enumerator(at: s.folder, includingPropertiesForKeys: [.fileSizeKey]) else { continue }
            for case let url as URL in e {
                total += Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
            }
        }
        return total
    }
}
