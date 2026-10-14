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
    @State private var handle = WebHandle()
    @State private var unsavedPhotos = 0
    @State private var confirmDiscard = false
    @State private var stillSending = false

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
                StudioWebView(url: url, link: link, handle: handle, loading: $loading, failure: $failure)
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
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { Task { await done() } } } }
            .interactiveDismissDisabled()
            .confirmationDialog("Discard \(unsavedPhotos) photo\(unsavedPhotos == 1 ? "" : "s")?", isPresented: $confirmDiscard,
                                titleVisibility: .visible) {
                Button("Discard and close", role: .destructive, action: onClose)
                Button("Keep scanning", role: .cancel) {}
            } message: {
                Text("They haven't been saved to the studio yet. To keep them, tap Save to library first.")
            }
            .alert("Still sending to the studio", isPresented: $stillSending) {
                Button("OK", role: .cancel) {}
            } message: {
                Text("Wait until it says Saved, then close. Closing now would stop the upload.")
            }
        }
    }

    /// Done: close straight away unless that would lose photos or cut off an upload.
    private func done() async {
        guard let state = await handle.captureState() else { return onClose() }
        if state.uploading { stillSending = true }
        else if state.unsaved > 0 { unsavedPhotos = state.unsaved; confirmDiscard = true }
        else { onClose() }
    }
}

/// Lets the SwiftUI side ask the page about its state.
@MainActor
final class WebHandle {
    weak var webView: WKWebView?

    struct State: Decodable { let uploading: Bool; let unsaved: Int }

    func captureState() async -> State? {
        guard let webView,
              let json = try? await webView.evaluateJavaScript(
                  "window.footscanCaptureState ? JSON.stringify(window.footscanCaptureState()) : null") as? String,
              let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(State.self, from: data)
    }
}

/// A web view that trusts only the paired studio, and lets only it use the camera.
private struct StudioWebView: UIViewRepresentable {
    let url: URL
    let link: StudioLink
    let handle: WebHandle
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
        handle.webView = view
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

        // Stay on the studio: anything else opens in Safari instead. And leaving
        // the capture page (a menu link) mustn't lose photos: same rule as Done.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let target = action.request.url else { return .cancel }
            guard isStudio(target.host()) || target.scheme == "about" else {
                await UIApplication.shared.open(target)
                return .cancel
            }
            // Any main-frame page load counts (even reloading this same page); only a jump
            // within the page (#anchor on the same address) keeps the photos.
            func withoutFragment(_ u: URL?) -> String? {
                guard let u, var c = URLComponents(url: u, resolvingAgainstBaseURL: false) else { return nil }
                c.fragment = nil
                return c.string
            }
            let samePageJump = target.fragment != nil && withoutFragment(target) == withoutFragment(webView.url)
            let leavingPage = action.targetFrame?.isMainFrame != false && !samePageJump
            guard leavingPage, let state = await parent.handle.captureState() else { return .allow }
            if state.uploading {
                await Self.tell(webView, "Still sending to the studio. Wait until it says Saved, then go on.")
                return .cancel
            }
            if state.unsaved > 0 {
                let discard = await Self.ask(webView, "Leave this page and discard \(state.unsaved) unsaved photo\(state.unsaved == 1 ? "" : "s")?")
                return discard ? .allow : .cancel
            }
            return .allow
        }

        private static func tell(_ webView: WKWebView, _ message: String) async {
            await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
                let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
                alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in done.resume() })
                guard let top = top(from: webView) else { return done.resume() }
                top.present(alert, animated: true)
            }
        }

        private static func ask(_ webView: WKWebView, _ message: String) async -> Bool {
            await withCheckedContinuation { done in
                let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
                alert.addAction(UIAlertAction(title: "Keep scanning", style: .cancel) { _ in done.resume(returning: false) })
                alert.addAction(UIAlertAction(title: "Discard", style: .destructive) { _ in done.resume(returning: true) })
                guard let top = top(from: webView) else { return done.resume(returning: false) }
                top.present(alert, animated: true)
            }
        }

        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType) async -> WKPermissionDecision {
            isStudio(origin.host) && type == .camera ? .grant : .deny
        }

        // The page's own "Discard N frames?" and messages: shown as native dialogs.
        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo) async -> Bool {
            await Self.ask(webView, message)
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo) async {
            await Self.tell(webView, message)
        }

        private static func top(from view: UIView) -> UIViewController? {
            var vc = view.window?.rootViewController
            while let next = vc?.presentedViewController { vc = next }
            return vc
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
