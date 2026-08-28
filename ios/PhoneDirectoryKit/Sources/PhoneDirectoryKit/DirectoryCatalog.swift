import Foundation

/// One subscribed list of numbers, in the spirit of an ad blocker's filter lists.
///
/// Nothing ships with the app: every list is fetched from a URL and stored in the
/// shared App Group, where the extension can read it.
public struct PhoneListDescriptor: Codable, Identifiable, Equatable {
    public var id: String
    public var title: String
    public var filename: String
    public var entryCount: Int
    /// Mean confidence, when the publisher scores its rows.
    public var confidence: Double?
    public var sourceURL: String
    /// Publisher's stamp for the copy held locally; compared against the
    /// catalogue to decide whether a refresh is due.
    public var updatedAt: String?
    public var isEnabled: Bool

    public init(id: String, title: String, filename: String, entryCount: Int,
                confidence: Double?, sourceURL: String, updatedAt: String?, isEnabled: Bool) {
        self.id = id
        self.title = title
        self.filename = filename
        self.entryCount = entryCount
        self.confidence = confidence
        self.sourceURL = sourceURL
        self.updatedAt = updatedAt
        self.isEnabled = isEnabled
    }
}

/// A published difference between the previous release of a list and this one.
///
/// Only one hop back is offered: a subscriber further behind than that fetches
/// the whole list, which is simpler than keeping a chain of patches around.
public struct ListPatchRef: Codable, Equatable {
    /// The `updatedAt` this patch expects the local copy to be at.
    public var from: String
    public var url: String
    public var byteCount: Int
}

/// A list offered by the built-in catalogue.
public struct RemoteList: Codable, Identifiable, Equatable {
    public var id: String
    public var title: String
    public var filename: String
    public var entryCount: Int
    public var confidence: Double?
    public var byteCount: Int
    public var url: String
    public var updatedAt: String?
    public var patch: ListPatchRef?
    /// ISO 3166-1 alpha-2. The catalogue covers every country Overture has
    /// numbers for, which is far too many to show as one flat list.
    public var country: String?
}

/// The user's subscriptions and their priority order.
///
/// Order matters: when the same number appears in several enabled lists, the
/// earliest one supplies the label.
public struct DirectoryCatalog: Codable {
    public var lists: [PhoneListDescriptor] = []

    public static let appGroupIdentifier = "group.net.gapul.JPPhoneDirectory"

    /// Suggested lists, shown so the app is not an empty box on first launch.
    /// They are only offers — nothing is installed until the user picks one.
    public static let suggestionsURL = URL(
        string: "https://github.com/gapul/jp-phone-opendata/releases/latest/download/catalog.json"
    )!

    private static let filename = "catalog.json"

    public init(lists: [PhoneListDescriptor] = []) {
        self.lists = lists
    }

    public static var containerURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier)
    }

    private static var catalogURL: URL? {
        containerURL?.appendingPathComponent(filename)
    }

    public static func load() -> DirectoryCatalog {
        guard let url = catalogURL,
              let data = try? Data(contentsOf: url),
              let saved = try? JSONDecoder().decode(DirectoryCatalog.self, from: data)
        else { return DirectoryCatalog() }
        return saved
    }

    public func save() throws {
        guard let url = Self.catalogURL else { return }
        try JSONEncoder().encode(self).write(to: url, options: .atomic)
    }

    /// Places a newly subscribed list where its priority makes sense.
    ///
    /// Appending would make priority mean "the order you happened to tap", which
    /// is wrong twice over: a list added by hand is almost always a correction
    /// meant to override the bulk ones, and installing the suggestions in a
    /// different order than they are listed would silently invert their quality
    /// ranking. So an unscored list goes to the top, and a scored one sits above
    /// the first list it outranks.
    public mutating func insert(_ descriptor: PhoneListDescriptor) {
        lists.removeAll { $0.id == descriptor.id }
        guard let confidence = descriptor.confidence else {
            lists.insert(descriptor, at: 0)
            return
        }
        let at = lists.firstIndex { ($0.confidence ?? .greatestFiniteMagnitude) < confidence }
        lists.insert(descriptor, at: at ?? lists.count)
    }

    public static func fileURL(for list: PhoneListDescriptor) -> URL? {
        containerURL?.appendingPathComponent(list.filename)
    }

    /// Opens every enabled list, skipping any that will not load so one bad
    /// import cannot take the whole directory down.
    public static func openEnabled(_ onFailure: (String, Error?) -> Void = { _, _ in }) -> [PhoneList] {
        var opened: [PhoneList] = []
        for descriptor in load().lists where descriptor.isEnabled {
            guard let url = fileURL(for: descriptor) else {
                onFailure(descriptor.id, nil)
                continue
            }
            do {
                opened.append(try PhoneList(url: url))
            } catch {
                onFailure(descriptor.id, error)
            }
        }
        return opened
    }
}
