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

/// How a send is going, in the words the home card and the scan's page use.
enum SendingWords {
    /// `percent`: of the model sent so far (nil before the upload itself starts: finding the studio, making its capture).
    static func chip(_ percent: Int?) -> String {
        guard let percent else { return "Sending" }
        return percent < 100 ? "Sending \(percent)%" : "Studio checking"
    }

    static func detail(_ percent: Int?, calibration: Bool) -> String {
        guard let percent else { return calibration ? "Sending, and measuring its accuracy…" : "Sending…" }
        if percent < 100 { return "Sending the model… \(percent)%" }
        // every byte is there; the studio answers once it has read the model (and scored it, for the calibration object)
        return calibration ? "All sent. The studio is measuring its accuracy…" : "All sent. The studio is checking it…"
    }
}

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
    /// While a scan is sending: the whole percent of its model sent so far (absent until its upload starts). At 100
    /// the studio has all of it and is reading it (and scoring it, for the calibration object) before it answers.
    private(set) var uploaded: [URL: Int] = [:]
    /// Which send of each scan is the current one, so a report from a send that has ended can't land on the next.
    private var sendRun: [URL: Int] = [:]
    private var sendRuns = 0
    /// Bumped when a scan's files or record change, so views re-read them.
    private(set) var version = 0
    /// Model builds cut off because the app left the screen (iOS doesn't lend the graphics chip to an app in the
    /// background): started again by themselves once it's back in front (`resumeInterrupted`).
    private(set) var interrupted: Set<URL> = []
    /// A capture (3D or Photos + mat) fills the screen: cut-off builds wait for it to close rather than start a
    /// model build on the graphics chip beside a live capture.
    var captureOnScreen = false
    /// How many times each scan's build has been started again that way, this run: a build that keeps failing
    /// stops being retried and shows its own error instead.
    private var resumes: [URL: Int] = [:]
    /// Builds started by `resumeInterrupted` (not by a tap), while they run: a tap starts the count again.
    private var autoResuming: Set<URL> = []
    nonisolated static let maxResumes = 3
    nonisolated static let interruptedMessage = "The model stopped building when Footscan left the screen. It starts again by itself when you come back to the app, or tap Try again."
    /// A failure that reaches the app this soon after it came back to the front still counts as caused by leaving.
    nonisolated static let backGrace: TimeInterval = 15

    /// Start a cut-off build again by itself? Only if the failure came while the app was away from the screen, or
    /// within `backGrace` seconds of it coming back (a failure later than that, on screen, is a real one, and
    /// shows its own error), and not more than `maxResumes` times.
    /// Whether a cut-off build may start again now: the app in front, and no capture on screen.
    nonisolated static func mayResume(appActive: Bool, captureOnScreen: Bool) -> Bool { appActive && !captureOnScreen }

    nonisolated static func shouldResume(awayNow: Bool, secondsSinceBack: TimeInterval?, resumesSoFar: Int) -> Bool {
        let causedByLeaving = awayNow || (secondsSinceBack.map { $0 <= backGrace } ?? false)
        return causedByLeaving && resumesSoFar < maxResumes
    }

    init() {
        reload()
        // nothing is building yet: working files a build cut off last time left behind can go
        for scan in scans { ModelBuilder.clearLeftovers(in: scan.folder) }
    }

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
        interrupted.remove(scan.folder)
        resumes[scan.folder] = nil
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
        interrupted = []
        resumes = [:]
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
        interrupted.remove(scan.folder)
        if !autoResuming.contains(scan.folder) { resumes[scan.folder] = nil } // started by a tap: a fresh count
        work[scan.folder] = .building(0)
        let release = KeepAlive.work("Building a 3D model")
        defer { release() }
        // a build the app leaves the screen during usually fails there: when it was away and came back is noted,
        // so such a failure is started again on return (and a later, real one isn't)
        let away = AwayFromScreen()
        let tokens = [
            NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification,
                                                   object: nil, queue: .main) { _ in away.left() },
            NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification,
                                                   object: nil, queue: .main) { _ in away.cameBack() },
        ]
        defer { tokens.forEach(NotificationCenter.default.removeObserver) }
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
            let awayNow = away.isAway || UIApplication.shared.applicationState == .background
            let sinceBack = away.backAt.map { Date().timeIntervalSince($0) }
            if Self.shouldResume(awayNow: awayNow, secondsSinceBack: sinceBack, resumesSoFar: resumes[scan.folder, default: 0]) {
                interrupted.insert(scan.folder)
                problems[scan.folder] = Self.interruptedMessage
                // the builder's own words stay in the record (Details' Last problem): if the app is closed before
                // the restart, or the failure was a real one after all, the reason isn't lost
            } else {
                problems[scan.folder] = message
            }
        } else {
            resumes[scan.folder] = nil
            await makeThumbnail(scan)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        }
        reload()
    }

    /// Builds cut off by the app leaving the screen: start each again, oldest first, picking up from the working
    /// data Object Capture kept (its Checkpoint folder). Call when the app is back in front.
    func resumeInterrupted(settings: AppSettings, studio: StudioConnection) async {
        // a call while a pass runs (a resumed build that failed again just after a return) is kept for the end of
        // that pass, not dropped: otherwise it waits for the next time the app leaves and comes back
        guard !resumingInterrupted else { resumeAgain = true; return }
        resumingInterrupted = true
        defer { resumingInterrupted = false }
        repeat {
            resumeAgain = false
            for scan in scans.reversed() where interrupted.contains(scan.folder) {
                // left the screen again, or a capture opened: the rest wait (for the next return, or for the capture
                // to close), without using up a try
                guard Self.mayResume(appActive: UIApplication.shared.applicationState == .active,
                                     captureOnScreen: captureOnScreen) else { break }
                if scan.hasOBJ || scan.photoCount == 0 {
                    // built by other means meanwhile, or nothing left to build from: nothing to say it will restart
                    interrupted.remove(scan.folder)
                    if problems[scan.folder] == Self.interruptedMessage { problems[scan.folder] = nil }
                    continue
                }
                guard work[scan.folder] == nil else { continue } // busy: stays waiting for the next return
                interrupted.remove(scan.folder)
                resumes[scan.folder, default: 0] += 1
                autoResuming.insert(scan.folder)
                await finish(scan, settings: settings, studio: studio)
                autoResuming.remove(scan.folder)
            }
        } while resumeAgain && UIApplication.shared.applicationState == .active
    }
    private var resumingInterrupted = false
    private var resumeAgain = false

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
        sendRuns += 1
        let run = sendRuns
        sendRun[scan.folder] = run
        let release = KeepAlive.work("Sending a scan")
        defer { work[scan.folder] = nil; uploaded[scan.folder] = nil; sendRun[scan.folder] = nil; reload(); release() }
        let reuse = record.reusableCapture(at: client.link)
        let studioID = PendingCapture.identity(of: client.link), loadKg = record.loadKg
        do {
            let folder = scan.folder
            let sent = try await client.upload(scan, record: record, into: reuse, created: { id in
                // kept as soon as the studio makes it: whatever happens next (a drop, a refusal, the app ended), the
                // next try finishes this capture rather than leaving it empty and making another
                guard var latest = scan.record else { return }
                latest.pendingCapture = PendingCapture(id: id, studio: studioID, loadKg: loadKg)
                scan.save(latest)
            }, progress: { [weak self] percent in
                // only this send's own reports (one still queued when it ended changes nothing, even if the scan is
                // sending again by then)
                guard let self, self.sendRun[folder] == run else { return }
                self.uploaded[folder] = percent
            })
            record.pendingCapture = nil
            record.studioCaptureID = sent.captureID
            record.studioHost = sent.link.host
            studio.remember(sent.link)
            record.sentAt = Date()
            record.studioAccuracy = sent.accuracy
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        } catch StudioClient.Failure.incomplete(let missing, let advice) {
            record.pendingCapture = nil // the studio removed the capture it made for this upload
            record.retake = missing
            record.retakeAdvice = advice.isEmpty ? nil : advice
            scan.save(record)
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        } catch {
            // a refusal sending into a capture an earlier try made: don't keep going back to it (the next try makes a
            // new one). A drop keeps it, as does a refusal of a capture made on this try (it's tried once more). So
            // does a fault of the studio's own (HTTP 500 and up) or of the phone's (reading the model): going back to
            // the same capture is right then, and dropping it would leave it empty in the studio.
            var refused = false
            if case StudioClient.Failure.refused = error { refused = true }
            if refused, let reuse, var latest = scan.record, latest.pendingCapture?.id == reuse {
                latest.pendingCapture = nil
                scan.save(latest)
            }
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

    // MARK: room on the phone

    /// The working data (Checkpoint folder) that can go: Object Capture keeps it to speed up building a model, so
    /// once a scan's model and its studio copy are built it does nothing. Never a scan still being worked on.
    /// Runs anywhere: it only looks at files.
    nonisolated static func workingDataToRemove(_ scans: [Scan]) -> [URL] {
        let fm = FileManager.default
        return scans.filter { $0.hasModel && $0.hasOBJ }.map(\.checkpoint).filter { folder in
            !((try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil))?.isEmpty ?? true)
        }
    }

    /// Empty these folders: what's in them goes, the folders themselves stay. Runs anywhere.
    nonisolated static func empty(_ folders: [URL]) {
        let fm = FileManager.default
        for folder in folders {
            for item in (try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [] {
                try? fm.removeItem(at: item)
            }
        }
    }

    /// Removing working data now: Settings' button waits for it.
    private(set) var removingWorkingData = false

    /// Empty the Checkpoint folders of built models (`workingDataToRemove`). The photos and models stay. -> false
    /// when refused because something is building, checking or sending (or a removal is already running).
    @discardableResult
    func removeWorkingData() async -> Bool {
        guard !busy, !removingWorkingData else { return false }
        removingWorkingData = true
        defer { removingWorkingData = false; reload() }
        let folders = Self.workingDataToRemove(scans)
        await Task.detached(priority: .utility) { Self.empty(folders) }.value
        return true
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

/// While a model builds: whether the app went away from the screen (into the background), and when it last came
/// back from there. Changed only on the main queue. Control Center, a notification or a call banner make the app
/// inactive for a moment but leave it on screen, with the GPU it builds on: coming back from those isn't a return.
final class AwayFromScreen: @unchecked Sendable {
    private(set) var backAt: Date?
    private(set) var isAway = false
    func left() { isAway = true; backAt = nil }
    func cameBack(at now: Date = Date()) {
        guard isAway else { return } // only active again after being inactive: it never left
        isAway = false
        backAt = now
    }
}
