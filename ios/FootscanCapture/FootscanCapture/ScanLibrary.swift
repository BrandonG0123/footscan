// Every scan on the phone, and what's happening to each one.
//
// One place runs the steps after a capture, so they carry on whichever
// screen is showing: build the 3D model, make a thumbnail, check the model
// (ScanCheck: a scan the phone can already tell is no good says "scan
// again" there and then), and (with a studio connected and "send
// automatically" on) send it. Home cards and the
// scan's own page both read the progress from here.
import Foundation
import SwiftUI
import UIKit

@MainActor
@Observable
final class ScanLibrary {
    enum Work: Equatable {
        case building(Double), converting, checking, sending
    }

    private(set) var scans: [Scan] = []
    private(set) var work: [URL: Work] = [:]
    private(set) var problems: [URL: String] = [:]
    /// Scans whose last send failed because the studio didn't answer, or dropped midway (sent again later).
    private(set) var unreachable: Set<URL> = []
    /// Of those, the ones where no address answered at all (offer Reconnect: scan the studio's code again).
    private(set) var reconnect: Set<URL> = []
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

    /// Give a scan a name, or take its name away (an empty one). Not while something is running on it: the build and
    /// the send save its record when they end, from the copy they started with, which would drop the name.
    @discardableResult func rename(_ scan: Scan, to typed: String) -> Bool {
        guard work[scan.folder] == nil, var record = scan.record else { return false }
        record.name = ScanRecord.cleanName(typed)
        scan.save(record)
        reload()
        return true
    }

    func deleteAll() {
        guard !busy else { return }
        for s in scans { ScanStore.delete(s) }
        work = [:]
        problems = [:]
        reload()
    }

    // MARK: after a capture

    /// Build the model, check it, then send it if that's what the settings say and the check found nothing
    /// that means scanning again.
    func finish(_ scan: Scan, settings: AppSettings, studio: StudioConnection) async {
        if !scan.hasModel { await build(scan) } else if !scan.hasOBJ { await convert(scan) }
        // the scan's page may have started the check already: wait for it rather than skip it
        while work[scan.folder] == .checking { try? await Task.sleep(for: .milliseconds(100)) }
        await check(scan)
        guard scan.hasOBJ, settings.autoSend, studio.client != nil, let rec = scan.record, readyToSend(rec) else { return }
        await send(scan, studio: studio)
    }

    /// Not sent yet, not refused by the studio, checked by the phone (if it's a kind the phone checks) and not
    /// held back by it, and with its scale reading if it needs one.
    private func readyToSend(_ rec: ScanRecord) -> Bool {
        let checked = rec.subject.checkKind == nil || rec.phoneCheck?.version == ScanCheck.version
        return rec.studioCaptureID == nil && rec.retake == nil && checked && !rec.heldByPhoneCheck
            && (!rec.subject.needsScale || rec.loadKg != nil)
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
            guard studio.client != nil, work[scan.folder] == nil, scan.hasOBJ else { continue }
            // a scan made before the phone checked models is checked before it goes
            await check(scan)
            // and again after the check, which can take a while: switched off or disconnected meanwhile, it stops
            guard settings.autoSend else { break }
            guard studio.client != nil, let rec = scan.record, readyToSend(rec) else { continue }
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

    /// Look at the model the phone built (ScanCheck), once per version of the check, and keep what it found in
    /// the scan's record. Only scans not sent yet, of the kinds the phone checks.
    func check(_ scan: Scan) async {
        guard work[scan.folder] == nil, scan.hasOBJ, let rec = scan.record, rec.studioCaptureID == nil, rec.retake == nil,
              let kind = rec.subject.checkKind, rec.phoneCheck?.version != ScanCheck.version else { return }
        work[scan.folder] = .checking
        let obj = scan.obj
        let found = await Task.detached(priority: .userInitiated) { () -> PhoneCheck in
            do {
                let report = try ScanCheck.run(obj: obj, kind: kind)
                return PhoneCheck(version: ScanCheck.version, findings: report.findings, measures: report.measures)
            } catch {
                return PhoneCheck(version: ScanCheck.version, findings: [], measures: [:], error: error.localizedDescription)
            }
        }.value
        work[scan.folder] = nil
        // read again: the record may have changed while the check ran (a scale reading typed in)
        if var latest = scan.record {
            var found = found
            // someone already chose Send anyway: a newer check doesn't take that back
            found.sentAnyway = latest.phoneCheck?.sentAnyway
            latest.phoneCheck = found
            scan.save(latest)
            if latest.heldByPhoneCheck { UINotificationFeedbackGenerator().notificationOccurred(.error) }
        }
        reload()
    }

    /// The phone's check said scan again, and the person chose to send it anyway: the studio still checks it.
    func sendAnyway(_ scan: Scan, studio: StudioConnection, loadKg: Double? = nil) async {
        guard var rec = scan.record, rec.phoneCheck != nil, work[scan.folder] == nil else { return }
        rec.phoneCheck?.sentAnyway = Date()
        scan.save(rec)
        await send(scan, studio: studio, loadKg: loadKg)
    }

    func send(_ scan: Scan, studio: StudioConnection, loadKg: Double? = nil) async {
        // a scan the studio found incomplete would only be refused again; one the phone's check held back goes
        // only through Send anyway
        guard let client = studio.client, var record = scan.record, record.retake == nil, !record.heldByPhoneCheck,
              work[scan.folder] == nil else { return }
        if let loadKg { record.loadKg = loadKg; scan.save(record) }
        problems[scan.folder] = nil
        unreachable.remove(scan.folder)
        reconnect.remove(scan.folder)
        work[scan.folder] = .sending
        let release = KeepAlive.work("Sending a scan")
        defer { work[scan.folder] = nil; reload(); release() }
        do {
            let sent = try await client.upload(scan, record: record)
            record.studioCaptureID = sent.captureID
            record.studioHost = sent.link.host
            studio.remember(sent.link)
            record.sentAt = Date()
            record.studioAccuracy = sent.accuracy
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        } catch StudioClient.Failure.incomplete(let missing, let advice) {
            record.retake = missing
            record.retakeAdvice = advice.isEmpty ? nil : advice
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        } catch {
            problems[scan.folder] = error.localizedDescription
            if (error as? StudioClient.Failure)?.isUnreachable == true { unreachable.insert(scan.folder) }
            if (error as? StudioClient.Failure)?.offersReconnect == true { reconnect.insert(scan.folder) }
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
