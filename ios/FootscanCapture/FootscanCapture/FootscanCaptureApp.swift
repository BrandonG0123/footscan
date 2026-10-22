// footscan capture: a test app for LiDAR scanning on iPhone Pro.
//
// Step 1 of moving footscan to the iPhone: before building a whole app, find
// out how accurate LiDAR capture really is. Scan the printed calibration
// object (and your feet), send the models to the studio, and run them
// through the same accuracy study as the photo scans.
//
// Not a medical device. It measures; it designs and treats nothing.
import SwiftUI

@main
struct FootscanCaptureApp: App {
    @State private var studio = StudioConnection()
    @State private var settings = AppSettings()
    @State private var library = ScanLibrary()

    var body: some Scene {
        WindowGroup {
            #if DEBUG
            // Development only: `-previewPrep right-sole` (a launch argument) opens that kind's get-ready
            // sheet straight away, so it can be checked on a simulator, which can't otherwise reach it.
            if let raw = UserDefaults.standard.string(forKey: "previewPrep"), let subject = Subject(rawValue: raw) {
                PrepSheet(subject: subject, mustTick: true) {}
            } else {
                root
            }
            #else
            root
            #endif
        }
    }

    private var root: some View {
        RootView()
            .environment(studio)
            .environment(settings)
            .environment(library)
            .tint(.fsBrand)
    }
}
