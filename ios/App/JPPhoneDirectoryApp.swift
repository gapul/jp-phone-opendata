import CallKit
import PhoneDirectoryKit
import SwiftUI

@main
struct JPPhoneDirectoryApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                ContentView()
            }
        }
    }
}

struct ContentView: View {
    @State private var model = DirectoryModel()
    @State private var isShowingAdd = false
    @State private var newListURL = ""

    var body: some View {
        // Required to derive bindings from an @Observable model held in @State.
        @Bindable var model = model

        return List {
            Section {
                LabeledContent("Extension", value: model.status)
                LabeledContent("Numbers", value: model.registeredCountText)
            } footer: {
                if model.isOverBudget {
                    Text("That is more than iOS reliably accepts. If the reload fails, "
                         + "turn off the largest list first.")
                    .foregroundStyle(.orange)
                } else {
                    Text("Enable under Settings › Apps › Phone › Call Blocking & Identification. "
                         + "Counts are before duplicates between lists are removed.")
                }
            }

            if model.catalog.lists.isEmpty {
                Section {
                    Text("No lists yet. Pick one below, or add any URL with ✚.")
                        .foregroundStyle(.secondary)
                }
            } else {
                Section {
                    ForEach($model.catalog.lists) { $list in
                        Toggle(isOn: $list.isEnabled) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(list.title)
                                Text(subtitle(for: list))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .onMove { model.catalog.lists.move(fromOffsets: $0, toOffset: $1) }
                    .onDelete { model.remove(at: $0) }
                } header: {
                    Text("Subscribed")
                } footer: {
                    Text("When a number appears in several lists, the one nearest the top "
                         + "supplies the name. A list can also blank a number out, which is "
                         + "how a correction list overrides a larger one. Drag to reorder.")
                }
            }

            if !model.visibleSuggestions.isEmpty {
                Section {
                    ForEach(model.visibleSuggestions) { remote in
                        Button {
                            Task { await model.install(remote) }
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(remote.title)
                                    Text(subtitle(for: remote))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                if model.busy.contains(remote.id) {
                                    ProgressView()
                                } else {
                                    Image(systemName: "arrow.down.circle")
                                }
                            }
                        }
                        .disabled(model.busy.contains(remote.id))
                    }
                } header: {
                    HStack {
                        Text(model.showsEveryRegion ? "Suggested" : "Suggested for \(model.regionName)")
                        Spacer()
                        Button(model.showsEveryRegion ? "This region" : "All regions") {
                            model.showsEveryRegion.toggle()
                        }
                        .font(.caption)
                        .textCase(nil)
                    }
                } footer: {
                    Text("Open data lists published alongside this app. Nothing is downloaded "
                         + "until you choose it. Subscribed lists refresh themselves when the "
                         + "publisher posts a newer copy.")
                }
            }

            Section {
                Button(model.isReloading ? "Applying…" : "Apply changes") {
                    Task { await model.apply() }
                }
                .disabled(model.isReloading || model.catalog.lists.isEmpty)
            }
        }
        .navigationTitle("JP Phone Directory")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) { EditButton() }
            ToolbarItem(placement: .topBarTrailing) {
                Button { isShowingAdd = true } label: { Image(systemName: "plus") }
            }
        }
        .refreshable { await model.refresh() }
        .task { await model.refresh() }
        // Recount whenever the selection or its order changes: overlap between
        // lists is large enough that summing them is not a usable answer.
        .task(id: model.selectionSignature) { await model.recount() }
        .alert("Add list", isPresented: $isShowingAdd) {
            TextField("https://example.com/list.csv", text: $newListURL)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
            Button("Cancel", role: .cancel) {}
            Button("Add") {
                let url = newListURL
                newListURL = ""
                Task { await model.add(from: url) }
            }
        } message: {
            Text("A packed list, or text with one number,label per line. "
                 + "Prefix a line with - to blank that number out instead.")
        }
    }

    // Confidence is deliberately not shown. It still decides where a new list
    // lands, but the numbers are not on one scale — Overture's are real per-record
    // averages while the scraped sources carry a flat prior — so putting them side
    // by side would imply a precision that is not there.
    private func subtitle(for list: PhoneListDescriptor) -> String {
        "\(list.entryCount.formatted()) numbers"
    }

    private func subtitle(for remote: RemoteList) -> String {
        "\(remote.entryCount.formatted()) numbers · "
            + ByteCountFormatter.string(fromByteCount: Int64(remote.byteCount), countStyle: .file)
    }
}

@Observable
final class DirectoryModel {
    private static let extensionIdentifier = "net.gapul.JPPhoneDirectory.CallDirectory"

    /// Above roughly this many entries, Call Directory loads start failing on
    /// current devices. A warning rather than a hard cap, since the real ceiling
    /// depends on the device and on how long the labels are.
    private static let practicalCeiling = 1_500_000

    var catalog = DirectoryCatalog()
    var suggestions: [RemoteList] = []
    /// The catalogue spans every country, so it is filtered to this phone's own
    /// region unless the user asks otherwise.
    var showsEveryRegion = false
    var busy: Set<String> = []
    var status = "Checking…"
    var isReloading = false

    /// Merged total, once counted. Until then the sum of the lists, which is an
    /// upper bound because it counts numbers carried by several lists twice.
    var registeredCount: Int?

    private var upperBound: Int {
        catalog.lists.filter(\.isEnabled).reduce(0) { $0 + $1.entryCount }
    }

    var registeredCountText: String {
        guard let registeredCount else { return "\(upperBound.formatted()) or fewer" }
        return registeredCount.formatted()
    }

    /// Changes when the enabled set or its order does, which is exactly when the
    /// merged total can move.
    var selectionSignature: String {
        catalog.lists.filter(\.isEnabled).map(\.filename).joined(separator: "|")
    }

    var isOverBudget: Bool { (registeredCount ?? upperBound) > Self.practicalCeiling }

    private var region: String { Locale.current.region?.identifier ?? "" }

    var regionName: String {
        Locale.current.localizedString(forRegionCode: region) ?? region
    }

    var visibleSuggestions: [RemoteList] {
        guard !showsEveryRegion, !region.isEmpty else { return suggestions }
        // A list with no country is one somebody added by hand; never hide it.
        return suggestions.filter { $0.country == nil || $0.country == region }
    }

    func recount() async {
        let counted = await Task.detached(priority: .utility) {
            DirectoryMerge.mergedCount(DirectoryCatalog.openEnabled())
        }.value
        registeredCount = counted
    }

    func refresh() async {
        catalog = DirectoryCatalog.load()
        await refreshStatus()

        guard let remote = try? await ListInstaller.fetchSuggestions() else { return }
        // Subscribing means tracking the publisher, so stale copies are replaced
        // without asking; only lists the user already chose are touched.
        let (refreshed, updated) = await ListInstaller.applyUpdates(to: catalog, from: remote)
        if updated > 0 {
            catalog = refreshed
            try? catalog.save()
            status = "Updated \(updated) list\(updated == 1 ? "" : "s") — apply to load them"
        }
        let installed = Set(catalog.lists.map(\.id))
        suggestions = remote.filter { !installed.contains($0.id) }
    }

    private func refreshStatus() async {
        do {
            let enabled = try await CXCallDirectoryManager.sharedInstance
                .enabledStatusForExtension(withIdentifier: Self.extensionIdentifier)
            switch enabled {
            case .enabled: status = "Enabled"
            case .disabled: status = "Off — turn it on in Settings"
            case .unknown: status = "Unknown"
            @unknown default: status = "Unknown"
            }
        } catch {
            status = error.localizedDescription
        }
    }

    func install(_ remote: RemoteList) async {
        busy.insert(remote.id)
        defer { busy.remove(remote.id) }
        await add { try await ListInstaller.install(remote) }
        suggestions.removeAll { $0.id == remote.id }
    }

    func add(from urlString: String) async {
        guard let url = URL(string: urlString), url.scheme != nil else {
            status = "Not a usable URL"
            return
        }
        await add { try await ListInstaller.install(from: url) }
    }

    private func add(_ install: () async throws -> PhoneListDescriptor) async {
        do {
            let descriptor = try await install()
            // Re-adding a list replaces it rather than registering it twice.
            if let existing = catalog.lists.firstIndex(where: { $0.id == descriptor.id }) {
                remove(at: IndexSet(integer: existing))
            }
            catalog.insert(descriptor)
            try catalog.save()
            status = "Added \(descriptor.entryCount.formatted()) numbers"
        } catch {
            status = "Failed: \(error.localizedDescription)"
        }
    }

    /// Saves the selection, then asks iOS to re-run the extension against it.
    func apply() async {
        isReloading = true
        defer { isReloading = false }
        do {
            try catalog.save()
            try await CXCallDirectoryManager.sharedInstance
                .reloadExtension(withIdentifier: Self.extensionIdentifier)
            status = "Applied"
        } catch {
            status = "Failed: \(error.localizedDescription)"
        }
        await refreshStatus()
    }

    func remove(at offsets: IndexSet) {
        for index in offsets {
            if let url = DirectoryCatalog.fileURL(for: catalog.lists[index]) {
                try? FileManager.default.removeItem(at: url)
            }
        }
        catalog.lists.remove(atOffsets: offsets)
        try? catalog.save()
    }
}
