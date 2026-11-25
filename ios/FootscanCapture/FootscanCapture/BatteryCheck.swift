// Before a scan: is the battery low? A capture runs the camera (and, for a 3D scan, LiDAR and tracking) for
// minutes, and a 3D scan's model is then built on the phone, which is the heaviest thing the app does. Reads only the battery level and whether the
// phone is charging (no permission; nothing is kept or sent).
import UIKit

enum BatteryCheck {
    /// Under this share of a full battery, unplugged, the app says so before a scan. A judgment, not measured on
    /// this app: how much a scan and its model build take hasn't been timed on a phone yet.
    static let low: Float = 0.2

    /// What to say before a scan, or nil when the battery is fine, charging, or not known (`level` -1, as in the
    /// simulator).
    static func note(level: Float, state: UIDevice.BatteryState) -> String? {
        guard state == .unplugged, level >= 0, level < low else { return nil }
        // to the nearest percent, as the status bar shows it (0.13 is 12.99999 as a Float), but never shown as the
        // line itself or over it
        let percent = min(Int((level * 100).rounded()), Int((low * 100).rounded()) - 1)
        return "Battery at \(percent)%. A scan uses a lot of it (a 3D scan's model is built on the phone too), "
            + "and the phone turning off partway would end the scan. Plug it in if you can."
    }

    /// Start reading the battery. Called when the app starts and left on (it costs next to nothing): straight after
    /// it is switched on, iOS can still report the level and state as unknown, which would skip the note.
    @MainActor static func watch() { UIDevice.current.isBatteryMonitoringEnabled = true }

    /// The phone's own reading, now.
    @MainActor static func now() -> String? {
        watch()
        return note(level: UIDevice.current.batteryLevel, state: UIDevice.current.batteryState)
    }
}
