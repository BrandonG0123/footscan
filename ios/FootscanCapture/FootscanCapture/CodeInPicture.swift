// A studio connect code read from a picture: a screenshot or photo of the code the studio shows, for when this
// phone's camera can't see that screen (the studio shown on this same phone through a remote-desktop app, say).
// Read on the phone with Core Image; the picture isn't kept or sent anywhere, and choosing it from the photo
// picker needs no permission (the picker runs outside the app and hands over only the picture chosen).
import CoreImage

enum CodeInPicture {
    /// Every QR code's text in the picture, a Footscan studio code first. Slow on a big photo: call it off the main
    /// thread (`codes(inPicture:)`).
    nonisolated static func codes(in image: CIImage) -> [String] {
        let detector = CIDetector(ofType: CIDetectorTypeQRCode, context: nil,
                                  options: [CIDetectorAccuracy: CIDetectorAccuracyHigh])
        let texts = (detector?.features(in: image) ?? []).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        let isStudio = { (t: String) in t.lowercased().hasPrefix("footscan-capture:") }
        return texts.filter(isStudio) + texts.filter { !isStudio($0) }
    }

    /// The codes in a picture file's bytes, read off the main thread; nil if the bytes aren't a picture.
    nonisolated static func codes(inPicture data: Data) async -> [String]? {
        await Task.detached(priority: .userInitiated) {
            CIImage(data: data).map { CodeInPicture.codes(in: $0) }
        }.value
    }

    /// Said when a picture holds no code at all.
    static let noneFound = "No code found in that picture. Take a screenshot with the whole code showing, then choose it again."

    /// Said once connected from a picture: the code in it holds the studio's key, and a screenshot stays in Photos
    /// (and in iCloud Photos, if that's on) until it's deleted.
    static let deleteIt = "Now delete that screenshot from Photos: the code in it holds the studio's key."
}
