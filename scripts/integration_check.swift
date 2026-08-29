// Exercises the app's own code against the lists that are actually published.
//
// The unit tests cover the rules on synthetic data, and `verify_db` covers the
// generated files. Neither touches the part that breaks in the field: the
// catalogue decoding into the type the app really uses, the URLs in it resolving,
// and the files behind them opening. That is what this walks.
//
// Usage:
//   swiftc -O -parse-as-library \
//     ios/PhoneDirectoryKit/Sources/PhoneDirectoryKit/*.swift \
//     scripts/integration_check.swift -o /tmp/integration_check
//   /tmp/integration_check

import Foundation

@main
enum IntegrationCheck {
    static func main() async throws {
        var failures: [String] = []

        func check(_ name: String, _ condition: Bool, _ detail: @autoclosure () -> String = "") {
            if condition {
                print("  ok   \(name)")
            } else {
                let extra = detail()
                print("  FAIL \(name)\(extra.isEmpty ? "" : ": \(extra)")")
                failures.append(name)
            }
        }

        // 1. The catalogue the app fetches on launch, decoded as the app decodes it.
        print("catalogue")
        let (data, response) = try await URLSession.shared.data(from: DirectoryCatalog.suggestionsURL)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        check("suggestionsURL responds", status == 200, "HTTP \(status)")

        let catalogue = try JSONDecoder().decode([RemoteList].self, from: data)
        check("decodes into RemoteList", !catalogue.isEmpty)
        check("every entry has a country", catalogue.allSatisfy { $0.country != nil })
        check("every entry has a URL", catalogue.allSatisfy { URL(string: $0.url) != nil })
        check("sizes are populated", catalogue.allSatisfy { $0.byteCount > 0 && $0.entryCount > 0 })
        check("stamps parse", catalogue.allSatisfy { $0.updatedAt.map { !$0.isEmpty } ?? false })
        let total = catalogue.reduce(0) { $0 + $1.entryCount }
        print("       \(catalogue.count) lists, \(total) numbers")

        // A subscriber's phone only ever sees its own region.
        let region = Locale.current.region?.identifier ?? "JP"
        let local = catalogue.filter { $0.country == region }
        check("this region is covered (\(region))", !local.isEmpty)

        // 2. Install the smallest few the way the app would, then read them back.
        print("lists")
        let scratch = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: scratch) }

        var opened: [PhoneList] = []
        for remote in catalogue.sorted(by: { $0.byteCount < $1.byteCount }).prefix(4) {
            let destination = scratch.appendingPathComponent(remote.filename)
            let (payload, listResponse) = try await URLSession.shared.data(from: URL(string: remote.url)!)
            let listStatus = (listResponse as? HTTPURLResponse)?.statusCode ?? 0
            check("\(remote.filename) downloads", listStatus == 200, "HTTP \(listStatus)")
            try payload.write(to: destination)

            guard let list = try? PhoneList(url: destination) else {
                check("\(remote.filename) opens", false, "reader rejected it")
                continue
            }
            check("\(remote.filename) opens", true)
            check("\(remote.filename) is ascending", list.isAscending)
            check("\(remote.filename) count matches the catalogue",
                  list.count == remote.entryCount, "\(list.count) vs \(remote.entryCount)")
            opened.append(list)
        }

        // 3. The merge, and the lookup that has to agree with it.
        print("merge")
        var merged: [Int64: String] = [:]
        let emitted = DirectoryMerge.merge(opened) { merged[$0] = $1 }
        check("merge emits something", emitted > 0)
        check("mergedCount agrees with merge",
              DirectoryMerge.mergedCount(opened) == emitted,
              "\(DirectoryMerge.mergedCount(opened)) vs \(emitted)")

        var ascending = true
        var previous = Int64.min
        for number in merged.keys.sorted() {
            if number <= previous { ascending = false; break }
            previous = number
        }
        check("merged output is strictly ascending", ascending)

        // Random-access lookup is the Android path; it must answer identically.
        let sample = merged.keys.sorted().prefix(200)
        let disagreements = sample.filter { DirectoryMerge.lookup($0, in: opened) != merged[$0] }
        check("lookup agrees with merge on \(sample.count) numbers", disagreements.isEmpty,
              "\(disagreements.count) disagreed")

        // 4. A hand-written list, the way someone subscribing by URL would supply it.
        print("text list")
        let authored = """
        # correction list
        03-1234-5678,Example Clinic
        -0120-000-000
        """
        let entries = PhoneListPacker.parse(authored)
        let authoredURL = scratch.appendingPathComponent("authored.bin")
        try PhoneListPacker.write(entries, to: authoredURL)
        let authoredList = try PhoneList(url: authoredURL)
        check("packs and reopens", authoredList.count == 2)
        check("suppression survives the round trip",
              authoredList.lookup(81_120_000_000) == "")
        check("a suppression on top hides a name below",
              DirectoryMerge.lookup(81_312_345_678, in: [authoredList]) == "Example Clinic")

        print("")
        if failures.isEmpty {
            print("all checks passed")
        } else {
            print("\(failures.count) failed: \(failures.joined(separator: ", "))")
            exit(1)
        }
    }
}
