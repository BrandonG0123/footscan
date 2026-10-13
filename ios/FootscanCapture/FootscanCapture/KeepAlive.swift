// Keeping a scan going: the screen mustn't dim halfway round a foot, and an
// upload shouldn't die because a text came in.
//
// - While anything holds a claim (a capture, a model build, an upload), the
//   screen stays awake.
// - While building or sending, iOS is asked for extra time if the app goes
//   to the background (usually about 30 seconds). Enough to finish an
//   upload; a model build needs the graphics chip, which iOS doesn't lend to
//   background apps, so a build cut off that way shows "Try again".
//
// And before a capture: is there room? Object Capture keeps hundreds of
// megabytes of photos per scan and fails partway through if it runs out.
import Foundation
import UIKit

@MainActor
enum KeepAlive {
    private static var awake = 0
    private static var background: UIBackgroundTaskIdentifier = .invalid
    private static var backgroundHolders = 0

    /// Keep the screen on until the returned function is called (call it exactly once).
    static func screen() -> () -> Void {
        awake += 1
        UIApplication.shared.isIdleTimerDisabled = true
        var released = false
        return {
            guard !released else { return }
            released = true
            awake -= 1
            if awake == 0 { UIApplication.shared.isIdleTimerDisabled = false }
        }
    }

    /// Screen on, plus extra time in the background, for a build or an upload.
    static func work(_ name: String) -> () -> Void {
        let releaseScreen = screen()
        backgroundHolders += 1
        if background == .invalid {
            background = UIApplication.shared.beginBackgroundTask(withName: name) {
                // iOS is out of patience: hand the time back so the app isn't killed.
                Task { @MainActor in endBackground() }
            }
        }
        var released = false
        return {
            guard !released else { return }
            released = true
            releaseScreen()
            backgroundHolders -= 1
            if backgroundHolders == 0 { endBackground() }
        }
    }

    private static func endBackground() {
        guard background != .invalid else { return }
        UIApplication.shared.endBackgroundTask(background)
        background = .invalid
    }
}

enum DiskSpace {
    /// Leave at least this much free before starting a capture.
    static let neededForCapture: Int64 = 1_500_000_000

    /// Bytes free for things the user asked for (what iOS will actually make room for).
    static func available() -> Int64? {
        let home = URL(fileURLWithPath: NSHomeDirectory())
        let values = try? home.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage
    }

    /// A message if there isn't room for a capture, else nil.
    static func captureProblem() -> String? {
        guard let free = available(), free < neededForCapture else { return nil }
        let have = ByteCountFormatter.string(fromByteCount: free, countStyle: .file)
        let need = ByteCountFormatter.string(fromByteCount: neededForCapture, countStyle: .file)
        return "Only \(have) free on this iPhone. A scan needs about \(need): delete some old scans (Settings shows how much they use) or other files, then try again."
    }
}
