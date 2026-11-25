// Is the camera on for this app? Checked before a scan opens the capture, which can't see without it.
import AVFoundation

/// Whether this app may use the camera, in the three cases the app treats differently.
enum CameraAccess: Equatable {
    /// `off`: turned off for Footscan (its switch in Settings). `blocked`: restricted for the whole phone (Screen Time,
    /// or a school or work phone's management), with no switch for Footscan to turn on.
    case allowed, off, blocked, notAsked

    static let offMessage = "Footscan isn't allowed to use the camera, so it can't scan. Turn it on in Settings > Footscan > Camera."
    static let blockedMessage = "The camera is blocked on this iPhone (by Screen Time, or by whoever manages the phone), so Footscan can't scan. Whoever set that up can allow it."

    /// What to tell the person when the camera can't be used, or nil.
    var message: String? {
        switch self {
        case .off: Self.offMessage
        case .blocked: Self.blockedMessage
        case .allowed, .notAsked: nil
        }
    }

    static func from(_ status: AVAuthorizationStatus) -> CameraAccess {
        switch status {
        case .authorized: .allowed
        case .notDetermined: .notAsked
        case .restricted: .blocked
        default: .off
        }
    }

    static func state() -> CameraAccess { from(AVCaptureDevice.authorizationStatus(for: .video)) }
}
