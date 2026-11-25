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
        // rounded down, so a level under the line never shows as the line itself
        return "Battery at \(Int(level * 100))%. A scan uses a lot of it (a 3D scan's model is built on the phone too), "
            + "and the phone turning off partway would end the scan. Plug it in if you can."
    }

    /// The phone's own reading, now.
    @MainActor static func now() -> String? {
        let device = UIDevice.current
        let wasOn = device.isBatteryMonitoringEnabled
        device.isBatteryMonitoringEnabled = true
        defer { device.isBatteryMonitoringEnabled = wasOn }
        return note(level: device.batteryLevel, state: device.batteryState)
    }
}
