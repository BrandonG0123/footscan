// Is the camera on for this app? Checked before a scan opens the capture, which can't see without it.
import AVFoundation

/// Whether this app may use the camera, in the three cases the app treats differently.
enum CameraAccess: Equatable {
    case allowed, off, notAsked

    static let offMessage = "Footscan isn't allowed to use the camera, so it can't scan. Turn it on in Settings > Footscan > Camera."

    static func from(_ status: AVAuthorizationStatus) -> CameraAccess {
        switch status {
        case .authorized: .allowed
        case .notDetermined: .notAsked
        default: .off  // denied, or restricted (Screen Time, a managed phone)
        }
    }

    static func state() -> CameraAccess { from(AVCaptureDevice.authorizationStatus(for: .video)) }
}
