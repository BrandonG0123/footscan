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
        case .shoeInsole: ("shoe_insole", nil)
        case .rightSole, .leftSole, .rightSoleFlat, .leftSoleFlat: ("nwb_relaxed", side)
        case .rightPrint, .leftPrint, .rightFoot, .leftFoot: ("swb", side)
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
                        Image(systemName: failure == PhotoPageWords.pageStopped ? "memorychip" : "wifi.exclamationmark")
                            .font(.largeTitle).foregroundStyle(Color.fsWarn)
                        Text(failure).multilineTextAlignment(.center).foregroundStyle(Color.fsMuted)
                        // the page again, from the start, without going back to the home screen
                        Button("Try again") {
                            self.failure = nil
                            loading = true
                            handle.open(url)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .padding(30)
                    .background(Color.fsBackground)
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

enum StudioPage {
    /// What the studio's capture page may use: the camera, and only the studio's own page (never another site's,
    /// and never the microphone). Asked by WebKit each time the page wants the camera. "The studio's own page"
    /// means the same scheme, host and port as the studio link: another program on the same computer (a different
    /// port) is another site.
    static func mediaDecision(scheme: String, host: String, port: Int, studio: URL,
                              type: WKMediaCaptureType) -> WKPermissionDecision {
        guard type == .camera, let studioScheme = studio.scheme?.lowercased(), studioScheme == "https",
              scheme.lowercased() == studioScheme, host.lowercased() == studio.host()?.lowercased(),
              portOrDefault(port, scheme: studioScheme) == portOrDefault(studio.port ?? 0, scheme: studioScheme)
        else { return .deny }
        return .grant
    }

    /// WebKit gives 0 for a page on its scheme's default port; a URL gives no port at all.
    private static func portOrDefault(_ port: Int, scheme: String) -> Int {
        port != 0 ? port : (scheme == "https" ? 443 : 80)
    }
}

/// What the Photos + mat screen says when the studio's page can't be shown.
enum PhotoPageWords {
    static func unreachable(_ studio: String) -> String {
        "Couldn't reach the studio at \(studio). Check Footscan is running on the studio computer and this phone can reach "
            + "it (same Wi-Fi, or Tailscale on); if its address changed, reconnect with its code."
    }

    static let pageStopped = "The studio's page stopped: iOS ended it, which it does when the phone is short of memory. "
        + "Photos already saved to the studio are kept there; any not yet saved are gone. Close other apps, then try again."

    static func certificateChanged(_ studio: String) -> String {
        "The studio at \(studio) answered with a different certificate from the one this phone paired with. If you "
            + "set the studio up again, show its connect code and scan it again."
    }

    /// A cancel (NSURLErrorCancelled, or WebKit's "frame load interrupted" when a link goes to Safari instead),
    /// rather than a load that failed.
    static func isCancel(_ error: Error) -> Bool {
        let e = error as NSError
        return (e.domain == NSURLErrorDomain && e.code == NSURLErrorCancelled)
            || (e.domain == "WebKitErrorDomain" && e.code == 102)
    }

    /// What to say when a load of the studio's page ends with `error`, or nil for nothing. A refused certificate also
    /// ends as a cancel, so it's checked first. Any other cancel is the view's own once the page has shown (the
    /// page is still there behind it); before that, nothing would be on screen, so it's said as unreachable.
    static func failure(_ error: Error, pageShown: Bool, pinRefused: Bool, studio: String) -> String? {
        if pinRefused { return certificateChanged(studio) }
        if isCancel(error) && pageShown { return nil }
        return unreachable(studio)
    }
}

/// Lets the SwiftUI side ask the page about its state.
@MainActor
final class WebHandle {
    weak var webView: WKWebView?

    /// Load the page again from the start (after it couldn't be reached, or stopped).
    func open(_ url: URL) { webView?.load(URLRequest(url: url)) }

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
            let answer = PinnedTrust.decide(challenge, fingerprint: parent.link.fingerprint)
            if answer.0 == .cancelAuthenticationChallenge { pinRefused = true } // WebKit then reports a cancel
            return answer
        }

        /// The studio's page has loaded at least once: a cancel after that is the view's own (a link sent to Safari, a
        /// navigation refused), and the page is still there behind it.
        private var pageShown = false
        /// The studio answered with a certificate other than the pinned one.
        private var pinRefused = false

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

        // WebKit's own name for this question (async form). An earlier spelling, requestMediaCapturePermissionFor
        // ... async, matched nothing, so WebKit never asked it: it fell back to asking the person each time the
        // page opened, and this rule (the camera for the studio only, never the microphone) wasn't applied.
        func webView(_ webView: WKWebView, decideMediaCapturePermissionsFor origin: WKSecurityOrigin,
                     initiatedBy frame: WKFrameInfo, type: WKMediaCaptureType) async -> WKPermissionDecision {
            StudioPage.mediaDecision(scheme: origin.`protocol`, host: origin.host, port: origin.port,
                                     studio: parent.link.url, type: type)
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
            pageShown = true
            pinRefused = false
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            failed(error)
        }

        // the page started loading, then the connection went (a Wi-Fi drop partway)
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            failed(error)
        }

        private func failed(_ error: Error) {
            let studio = StudioConnection.describe(parent.link.url)
            let said = PhotoPageWords.failure(error, pageShown: pageShown, pinRefused: pinRefused, studio: studio)
            pinRefused = false
            // nothing to say (the view's own cancel with the page still there): leave loading to the newer navigation
            guard let said else { return }
            parent.loading = false
            parent.failure = said
        }

        // iOS ended the page's process (it does that to a camera page when the phone is short of memory): the page
        // is blank and its photos not yet saved are gone
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            parent.loading = false
            parent.failure = PhotoPageWords.pageStopped
        }
    }
}
