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
    /// Scans whose last send failed because the studio didn't answer (offer Reconnect).
    private(set) var unreachable: Set<URL> = []
    /// Bumped when a scan's files or record change, so views re-read them.
    private(set) var version = 0

    init() { reload() }

    func reload() {
        scans = ScanStore.all()
        version += 1
    }

    /// Is anything still building, converting or sending?
    var busy: Bool { !work.isEmpty }

    /// Deleting waits for the scan's work to finish: the model build and the
    /// upload carry on in the background and need its files until they're done.
    func delete(_ scan: Scan) {
        guard work[scan.folder] == nil else { return }
        ScanStore.delete(scan)
        work[scan.folder] = nil
        problems[scan.folder] = nil
        reload()
    }

    func deleteAll() {
        guard !busy else { return }
        for s in scans { ScanStore.delete(s) }
        work = [:]
        problems = [:]
        reload()
    }

    // MARK: after a capture

    /// Build the model, then send it if that's what the settings say.
    func finish(_ scan: Scan, settings: AppSettings, studio: StudioConnection) async {
        if !scan.hasModel { await build(scan) } else if !scan.hasOBJ { await convert(scan) }
        guard scan.hasOBJ, settings.autoSend, studio.client != nil, let rec = scan.record,
              rec.studioCaptureID == nil, rec.retake == nil, !rec.subject.needsScale || rec.loadKg != nil else { return }
        await send(scan, studio: studio)
    }

    /// With "send automatically" on and a studio connected: send every
    /// finished scan that hasn't gone yet (scans built while away from the
    /// studio, or whose send failed). Foot scans still wait for their scale
    /// reading. One at a time, oldest first.
    func sendWaiting(settings: AppSettings, studio: StudioConnection) async {
        guard settings.autoSend, studio.client != nil, !sendingWaiting else { return }
        sendingWaiting = true
        defer { sendingWaiting = false }
        for scan in scans.reversed() {
            // checked before every upload: switching "send automatically" off stops the queue
            guard settings.autoSend else { break }
            guard studio.client != nil, work[scan.folder] == nil, scan.hasOBJ, let rec = scan.record,
                  rec.studioCaptureID == nil, rec.retake == nil, !rec.subject.needsScale || rec.loadKg != nil else { continue }
            await send(scan, studio: studio)
            // the studio isn't answering: don't try every other scan against it too
            if unreachable.contains(scan.folder) { break }
        }
    }
    private var sendingWaiting = false

    func build(_ scan: Scan) async {
        guard work[scan.folder] == nil else { return }
        problems[scan.folder] = nil
        work[scan.folder] = .building(0)
        let release = KeepAlive.work("Building a 3D model")
        defer { release() }
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

    /// The model was built but its studio copy (OBJ) wasn't made: make just that.
    func convert(_ scan: Scan) async {
        guard work[scan.folder] == nil, scan.hasModel else { return }
        problems[scan.folder] = nil
        work[scan.folder] = .converting
        let release = KeepAlive.work("Saving a model copy")
        defer { release() }
        let usdz = scan.usdz, obj = scan.obj
        let failure = await Task.detached(priority: .userInitiated) { () -> String? in
            do { try ModelBuilder.exportOBJ(from: usdz, to: obj); return nil } catch { return error.localizedDescription }
        }.value
        work[scan.folder] = nil
        if let failure { problems[scan.folder] = "Couldn't save the copy for the studio: \(failure)" }
        await makeThumbnail(scan)
        reload()
    }

    func send(_ scan: Scan, studio: StudioConnection, loadKg: Double? = nil) async {
        // a scan the studio found incomplete would only be refused again
        guard let client = studio.client, var record = scan.record, record.retake == nil, work[scan.folder] == nil else { return }
        if let loadKg { record.loadKg = loadKg; scan.save(record) }
        problems[scan.folder] = nil
        unreachable.remove(scan.folder)
        work[scan.folder] = .sending
        let release = KeepAlive.work("Sending a scan")
        defer { work[scan.folder] = nil; reload(); release() }
        do {
            let sent = try await client.upload(scan, record: record)
            record.studioCaptureID = sent.captureID
            record.studioHost = client.link.host
            record.sentAt = Date()
            record.studioAccuracy = sent.accuracy
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        } catch StudioClient.Failure.incomplete(let missing) {
            record.retake = missing
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        } catch {
            problems[scan.folder] = error.localizedDescription
            if (error as? StudioClient.Failure)?.isUnreachable == true { unreachable.insert(scan.folder) }
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

    /// Bytes used by these scan folders (photos, working data, models).
    /// Runs anywhere: call it off the main thread, it walks every file.
    nonisolated static func bytes(in folders: [URL]) -> Int64 {
        var total: Int64 = 0
        let fm = FileManager.default
        for folder in folders {
            guard let e = fm.enumerator(at: folder, includingPropertiesForKeys: [.fileSizeKey]) else { continue }
            for case let url as URL in e {
                total += Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
            }
        }
        return total
    }
}
