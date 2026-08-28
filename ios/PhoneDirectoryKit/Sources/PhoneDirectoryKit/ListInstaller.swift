import Foundation

/// Fetches lists and installs them into the App Group.
///
/// The extension has no network access, so every download happens in the
/// container app; the extension only ever reads files that are already local.
public enum ListInstaller {
    public enum Failure: LocalizedError {
        case noContainer
        case notAscending
        case empty
        case patchUnavailable

        public var errorDescription: String? {
            switch self {
            case .noContainer: "The app group container is unavailable."
            case .notAscending: "That list is not sorted, so iOS would reject it."
            case .empty: "No usable rows in that list."
            case .patchUnavailable: "No usable patch for the copy held here."
            }
        }
    }

    public static func fetchSuggestions() async throws -> [RemoteList] {
        let (data, _) = try await URLSession.shared.data(from: DirectoryCatalog.suggestionsURL)
        return try JSONDecoder().decode([RemoteList].self, from: data)
    }

    public static func install(_ remote: RemoteList) async throws -> PhoneListDescriptor {
        guard let url = URL(string: remote.url) else { throw URLError(.badURL) }
        return try await install(from: url, id: remote.id, title: remote.title,
                                 confidence: remote.confidence, updatedAt: remote.updatedAt)
    }

    /// Installs whatever a URL points at: either a packed table, or a plain text
    /// list that anyone can author in an editor.
    ///
    /// The file is validated before it is published under its final name. The
    /// merge assumes every input is ascending and CallKit rejects the whole
    /// registration if the merged output is not, so one bad list would take down
    /// the entire directory rather than just itself.
    public static func install(
        from url: URL,
        id: String? = nil,
        title: String? = nil,
        confidence: Double? = nil,
        updatedAt: String? = nil
    ) async throws -> PhoneListDescriptor {
        guard let container = DirectoryCatalog.containerURL else { throw Failure.noContainer }

        let (data, _) = try await URLSession.shared.data(from: url)
        let filename = "list-\(UUID().uuidString).bin"
        let staged = container.appendingPathComponent("staged-\(filename)")

        if Array(data.prefix(4)) == PhoneList.magic {
            try data.write(to: staged, options: .atomic)
        } else {
            guard let text = String(data: data, encoding: .utf8) else { throw Failure.empty }
            let entries = PhoneListPacker.parse(text)
            guard !entries.isEmpty else { throw Failure.empty }
            try PhoneListPacker.write(entries, to: staged)
        }

        let list: PhoneList
        do {
            list = try PhoneList(url: staged)
        } catch {
            try? FileManager.default.removeItem(at: staged)
            throw error
        }
        guard list.isAscending else {
            try? FileManager.default.removeItem(at: staged)
            throw Failure.notAscending
        }
        let count = list.count

        let destination = container.appendingPathComponent(filename)
        try FileManager.default.moveItem(at: staged, to: destination)

        return PhoneListDescriptor(
            id: id ?? url.absoluteString,
            title: title ?? url.deletingPathExtension().lastPathComponent,
            filename: filename,
            entryCount: count,
            confidence: confidence,
            sourceURL: url.absoluteString,
            updatedAt: updatedAt,
            isEnabled: true
        )
    }

    /// Brings one list forward using the published difference rather than the
    /// whole table.
    ///
    /// Only taken when the patch is genuinely smaller and starts from exactly the
    /// copy held locally; otherwise the caller falls back to a full download.
    static func patch(
        _ installed: PhoneListDescriptor,
        to remote: RemoteList
    ) async throws -> PhoneListDescriptor {
        guard let container = DirectoryCatalog.containerURL,
              let reference = remote.patch,
              reference.from == installed.updatedAt,
              reference.byteCount < remote.byteCount,
              let url = URL(string: reference.url),
              let base = DirectoryCatalog.fileURL(for: installed)
        else { throw Failure.patchUnavailable }

        let (data, _) = try await URLSession.shared.data(from: url)
        let filename = "list-\(UUID().uuidString).bin"
        let destination = container.appendingPathComponent(filename)
        try ListPatch.apply(patch: data, to: try PhoneList(url: base), destination: destination)

        let rebuilt = try PhoneList(url: destination)
        guard rebuilt.isAscending else {
            try? FileManager.default.removeItem(at: destination)
            throw Failure.notAscending
        }

        var descriptor = installed
        descriptor.filename = filename
        descriptor.entryCount = rebuilt.count
        descriptor.updatedAt = remote.updatedAt
        descriptor.title = remote.title
        descriptor.confidence = remote.confidence
        return descriptor
    }

    /// Re-downloads subscribed lists the catalogue says have moved on.
    ///
    /// A list without an `updatedAt` on either side is left alone: with no way to
    /// tell whether it changed, re-fetching every launch would be pure waste.
    /// Returns the refreshed catalogue and how many lists were replaced.
    public static func applyUpdates(
        to catalog: DirectoryCatalog,
        from suggestions: [RemoteList]
    ) async -> (catalog: DirectoryCatalog, updated: Int) {
        var updated = catalog
        var count = 0

        for (index, installed) in catalog.lists.enumerated() {
            guard let remote = suggestions.first(where: { $0.id == installed.id }),
                  let published = remote.updatedAt,
                  published != installed.updatedAt
            else { continue }

            let replacement: PhoneListDescriptor
            if let patched = try? await patch(installed, to: remote) {
                replacement = patched
            } else if let full = try? await install(remote) {
                replacement = full
            } else {
                continue
            }
            // Keep the user's choices; only the data underneath changes.
            var descriptor = replacement
            descriptor.isEnabled = installed.isEnabled
            if let stale = DirectoryCatalog.fileURL(for: installed) {
                try? FileManager.default.removeItem(at: stale)
            }
            updated.lists[index] = descriptor
            count += 1
        }

        return (updated, count)
    }
}
