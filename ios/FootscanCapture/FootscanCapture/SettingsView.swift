// Settings: the studio, sending, the safety points, and starting over.
import SwiftUI

struct SettingsView: View {
    @Environment(AppSettings.self) private var settings
    @Environment(StudioConnection.self) private var studio
    @Environment(ScanLibrary.self) private var library
    @Environment(\.dismiss) private var dismiss
    @State private var showStudio = false
    @State private var confirmDeleteAll = false
    @State private var storage: Int64 = 0

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
                    Button(role: .destructive) { confirmDeleteAll = true } label: {
                        Label("Delete all scans", systemImage: "trash")
                    }
                    .disabled(library.scans.isEmpty || library.busy)
                } header: {
                    Text("Storage")
                } footer: {
                    Text(library.busy ? "A scan is still building or sending; delete once it has finished."
                                      : "Scans already sent stay in the studio.")
                }

                Section {
                    LabeledContent("Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?")
                    Text("footscan capture measures how accurate iPhone scanning is. It is not a medical device: it designs and treats nothing.")
                        .font(.footnote).foregroundStyle(Color.fsMuted)
                }
            }
            .navigationTitle("Settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(isPresented: $showStudio) { StudioView() }
            .confirmationDialog("Delete every scan on this phone?", isPresented: $confirmDeleteAll, titleVisibility: .visible) {
                Button("Delete all \(library.scans.count)", role: .destructive) {
                    library.deleteAll()
                    storage = 0
                }
            }
            .task(id: library.version) {
                let folders = library.scans.map(\.folder)
                storage = await Task.detached(priority: .utility) { ScanLibrary.bytes(in: folders) }.value
            }
        }
        .tint(.fsBrand)
    }
}
