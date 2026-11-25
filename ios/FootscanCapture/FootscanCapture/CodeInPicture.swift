// A studio connect code read from a picture: a screenshot or photo of the code the studio shows, for when this
// phone's camera can't see that screen (the studio shown on this same phone through a remote-desktop app, say).
// Read on the phone with Core Image; the picture isn't kept or sent anywhere, and choosing it from the photo
// picker needs no permission (the picker runs outside the app and hands over only the picture chosen).
import CoreImage

enum CodeInPicture {
    /// Every QR code's text in the picture, a Footscan studio code first.
    nonisolated static func codes(in image: CIImage) -> [String] {
        let detector = CIDetector(ofType: CIDetectorTypeQRCode, context: nil,
                                  options: [CIDetectorAccuracy: CIDetectorAccuracyHigh])
        let texts = (detector?.features(in: image) ?? []).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        let studio = texts.filter { $0.hasPrefix("footscan-capture:") }
        return studio + texts.filter { !$0.hasPrefix("footscan-capture:") }
    }

    /// Said when a picture holds no code at all.
    static let noneFound = "No code found in that picture. Take a screenshot with the whole code showing, then choose it again."
}
