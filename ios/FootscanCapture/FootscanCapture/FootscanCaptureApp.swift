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
            RootView()
                .environment(studio)
                .environment(settings)
                .environment(library)
                .tint(.fsBrand)
        }
    }
}
