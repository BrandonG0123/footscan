// Settings: the studio, sending, the safety points, and starting over.
import SwiftUI

/// Pages the App Store requires an app to link to: its privacy policy and a way to get help.
/// The privacy policy is docs/PRIVACY.md in the public repository (tests/test_privacy_manifest.py checks it exists).
enum AppLinks {
    static let privacyPolicy = URL(string: "https://github.com/BrandonG0123/footscan/blob/main/docs/PRIVACY.md")!
    static let support = URL(string: "https://github.com/BrandonG0123/footscan/issues")!
}

struct SettingsView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(StudioConnection.self) private var studio
    @Environment(ScanLibrary.self) private var library
    @Environment(\.dismiss) private var dismiss
    @State private var showStudio = false
    @State private var confirmDeleteAll = false
    @State private var storage: Int64 = 0
    /// Of that, working data no built model needs any more (ScanLibrary.workingDataToRemove).
    @State private var workingData: Int64 = 0
    @State private var confirmRemoveWorking = false
    @State private var removeRefused = false

    var body: some View {
        @Bindable var settings = settings
        NavigationStack {
            List {
                Section {
                    Button { showStudio = true } label: {
                        HStack {
                            Label("Studio", systemImage: "desktopcomputer")
                            Spacer()
                            Text(studio.link?.host ?? "Not connected").foregroundStyle(Color.fsMuted)
                        }
                    }
                    Toggle(isOn: $settings.autoSend) {
                        Label("Send finished scans automatically", systemImage: "paperplane")
                    }
                } footer: {
                    Text("With a studio connected, each model is sent as soon as it's built. Foot scans wait for their scale reading.")
                }

                Section("Safety") {
                    ForEach(Array(OnboardingView.acknowledgments.enumerated()), id: \.offset) { _, ack in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(ack.0).font(.subheadline.weight(.semibold))
                            Text(ack.1).font(.footnote).foregroundStyle(Color.fsMuted)
                        }
                        .padding(.vertical, 2)
                    }
                    if let at = settings.safetyAcknowledgedAt {
                        Text("Agreed \(at.formatted(date: .abbreviated, time: .shortened))").font(.footnote).foregroundStyle(Color.fsMuted)
                    }
                }

                Section {
                    Button { settings.replayIntro(); dismiss() } label: {
                        Label("Show the intro and get-ready lists again", systemImage: "arrow.counterclockwise")
                    }
                }

                Section {
                    LabeledContent("Scans on this phone", value: "\(library.scans.count)")
                    LabeledContent("Space used", value: ByteCountFormatter.string(fromByteCount: storage, countStyle: .file))
                    if workingData > 0 {
                        Button { confirmRemoveWorking = true } label: {
                            LabeledContent {
                                Text(ByteCountFormatter.string(fromByteCount: workingData, countStyle: .file))
                            } label: {
                                Label("Remove working data", systemImage: "externaldrive.badge.minus")
                            }
                        }
                        .disabled(library.busy || library.removingWorkingData)
                    }
                    Button(role: .destructive) { confirmDeleteAll = true } label: {
                        Label("Delete all scans", systemImage: "trash")
                    }
                    .disabled(library.scans.isEmpty || library.busy)
                } header: {
                    Text("Storage")
                } footer: {
                    Text(removeRefused ? "A scan started building or sending, so nothing was removed. Try again once it has finished."
                     : library.busy ? "A scan is still building or sending; delete scans or remove working data once it has finished."
                                  : workingData > 0 ? "Working data is what the phone used while building each model. Once a model is built it isn't needed: removing it keeps every scan's photos and model. Scans already sent stay in the studio."
                                  : "Scans already sent stay in the studio.")
                }

                Section {
                    Link(destination: AppLinks.privacyPolicy) {
                        Label("Privacy policy", systemImage: "hand.raised")
                    }
                    Link(destination: AppLinks.support) {
                        Label("Help and support", systemImage: "questionmark.circle")
                    }
                    LabeledContent("Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?")
                    Text("Footscan measures how accurate iPhone scanning is. It is not a medical device: it designs and treats nothing.")
                        .font(.footnote).foregroundStyle(Color.fsMuted)
                }
            }
            .navigationTitle("Settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $showStudio) { StudioView() }
            .confirmationDialog("Remove the working data of built models?", isPresented: $confirmRemoveWorking, titleVisibility: .visible) {
                Button("Remove \(ByteCountFormatter.string(fromByteCount: workingData, countStyle: .file))", role: .destructive) {
                    Task { removeRefused = !(await library.removeWorkingData()) }
                }
            } message: {
                Text("Every scan keeps its photos and its 3D model, and nothing in the studio changes.")
            }
            .confirmationDialog("Delete every scan on this phone?", isPresented: $confirmDeleteAll, titleVisibility: .visible) {
                Button("Delete all \(library.scans.count)", role: .destructive) {
                    library.deleteAll()
                    storage = 0
                }
            }
            .task(id: library.version) {
                // the build or send that stopped Remove has finished: the footer goes back to saying what's there
                if !library.busy { removeRefused = false }
                let scans = library.scans
                let folders = scans.map(\.folder)
                (storage, workingData) = await Task.detached(priority: .utility) {
                    (ScanLibrary.bytes(in: folders), ScanLibrary.bytes(in: ScanLibrary.workingDataToRemove(scans)))
                }.value
            }
        }
        .tint(.fsBrand)
    }
}
