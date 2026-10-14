// Photos + mat: the capture that needs no LiDAR.
//
// Any iPhone can scan this way. The studio's own capture page (the same one
// the website uses: printed-mat detection, sharpness and coverage checks,
// "slow down" coaching) runs inside the app and sends the photos straight
// to the studio, where they become a 3D model in real millimetres, scaled
// by the mat's black squares. Then Make insole, as for a LiDAR scan.
//
// It talks only to the connected studio, with the same pinned certificate
// as uploads, and the camera is only offered to that page.
import SwiftUI
import WebKit

extension Subject {
    /// What the studio's capture page calls this kind of scan.
    var studioCondition: (condition: String, foot: String?) {
        switch self {
        case .calibration: ("calibration", nil)
        case .rightFoot: ("swb", "right")
        case .leftFoot: ("swb", "left")
        case .other: ("object", nil)
        }
    }
}

struct PhotoCaptureView: View {
    let subject: Subject
    let link: StudioLink
    let key: String
    var onClose: () -> Void

    @State private var loading = true
    @State private var failure: String?

    private var url: URL {
        var c = URLComponents(url: link.url.appending(path: "studio/capture.html"), resolvingAgainstBaseURL: false)!
        let (condition, foot) = subject.studioCondition
        c.queryItems = [URLQueryItem(name: "key", value: key), URLQueryItem(name: "condition", value: condition),
                        URLQueryItem(name: "session", value: "PHOTO"), URLQueryItem(name: "from", value: "app")]
            + (foot.map { [URLQueryItem(name: "foot", value: $0)] } ?? [])
        return c.url!
    }

    var body: some View {
        NavigationStack {
            ZStack {
                StudioWebView(url: url, link: link, loading: $loading, failure: $failure)
                    .ignoresSafeArea(edges: .bottom)
                if loading && failure == nil { ProgressView("Opening the studio's camera…") }
                if let failure {
                    VStack(spacing: 12) {
                        Image(systemName: "wifi.exclamationmark").font(.largeTitle).foregroundStyle(Color.fsWarn)
                        Text(failure).multilineTextAlignment(.center).foregroundStyle(Color.fsMuted)
                    }
                    .padding(30)
                }
            }
            .navigationTitle("Photos + mat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done", action: onClose) } }
        }
    }
}

/// A web view that trusts only the paired studio, and lets only it use the camera.
private struct StudioWebView: UIViewRepresentable {
    let url: URL
    let link: StudioLink
    @Binding var loading: Bool
    @Binding var failure: String?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true          // the camera preview plays in the page
        config.mediaTypesRequiringUserActionForPlayback = []
        config.websiteDataStore = .nonPersistent()       // the studio key doesn't linger in a cookie jar
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = false
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let parent: StudioWebView
        init(_ parent: StudioWebView) { self.parent = parent }

        private func isStudio(_ host: String?) -> Bool { host == parent.link.url.host() }

        func webView(_ webView: WKWebView, respondTo challenge: URLAuthenticationChallenge) async
            -> (URLSession.AuthChallengeDisposition, URLCredential?) {
            guard isStudio(challenge.protectionSpace.host) else { return (.cancelAuthenticationChallenge, nil) }
            return PinnedTrust.decide(challenge, fingerprint: parent.link.fingerprint)
        }

        // Stay on the studio: anything else opens in Safari instead.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let target = action.request.url else { return .cancel }
            if isStudio(target.host()) || target.scheme == "about" { return .allow }
            await UIApplication.shared.open(target)
            return .cancel
        }

        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType) async -> WKPermissionDecision {
            isStudio(origin.host) && type == .camera ? .grant : .deny
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.loading = false
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            parent.loading = false
            parent.failure = "Couldn't reach the studio at \(parent.link.host). Check Footscan is running on your Mac "
                + "and both are on the same Wi-Fi; if the Mac's address changed, reconnect with its code."
        }
    }
}
