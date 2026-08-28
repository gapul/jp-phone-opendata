import XCTest
@testable import PhoneDirectoryKit

final class ListPatchTests: XCTestCase {
    private var scratch: URL!

    override func setUpWithError() throws {
        scratch = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: scratch)
    }

    private func write(_ entries: [(Int64, String)]) throws -> PhoneList {
        let url = scratch.appendingPathComponent("\(UUID().uuidString).bin")
        try PhoneListPacker.write(entries.map { (number: $0.0, label: $0.1) }, to: url)
        return try PhoneList(url: url)
    }

    /// Builds a patch the way `scripts/list_format.py` does.
    private func patch(removals: [Int64], upserts: [(Int64, String)]) -> Data {
        var data = Data(ListPatch.magic)
        for value in [UInt32(1), UInt32(removals.count), UInt32(upserts.count)] {
            withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) }
        }
        for number in removals {
            withUnsafeBytes(of: number.littleEndian) { data.append(contentsOf: $0) }
        }
        for (number, _) in upserts {
            withUnsafeBytes(of: number.littleEndian) { data.append(contentsOf: $0) }
        }
        var labels = Data()
        var cursor = UInt32(0)
        withUnsafeBytes(of: cursor.littleEndian) { data.append(contentsOf: $0) }
        for (_, label) in upserts {
            let encoded = Data(label.utf8)
            labels.append(encoded)
            cursor += UInt32(encoded.count)
            withUnsafeBytes(of: cursor.littleEndian) { data.append(contentsOf: $0) }
        }
        data.append(labels)
        return data
    }

    private func contents(of list: PhoneList) -> [(Int64, String)] {
        (0..<list.count).map { (list.number(at: $0), list.label(at: $0)) }
    }

    func testUpsertReplacesAndInsertsInOrder() throws {
        let base = try write([(1, "one"), (3, "three"), (5, "five")])
        let destination = scratch.appendingPathComponent("out.bin")

        try ListPatch.apply(
            patch: patch(removals: [], upserts: [(2, "two"), (3, "THREE")]),
            to: base, destination: destination
        )

        let result = contents(of: try PhoneList(url: destination))
        XCTAssertEqual(result.map(\.0), [1, 2, 3, 5])
        XCTAssertEqual(result.map(\.1), ["one", "two", "THREE", "five"])
    }

    func testRemovalDropsTheEntry() throws {
        let base = try write([(1, "one"), (3, "three"), (5, "five")])
        let destination = scratch.appendingPathComponent("out.bin")

        try ListPatch.apply(
            patch: patch(removals: [3], upserts: []),
            to: base, destination: destination
        )

        XCTAssertEqual(contents(of: try PhoneList(url: destination)).map(\.0), [1, 5])
    }

    func testRemovalAndUpsertTogetherStayAscending() throws {
        let base = try write([(10, "a"), (20, "b"), (30, "c"), (40, "d")])
        let destination = scratch.appendingPathComponent("out.bin")

        try ListPatch.apply(
            patch: patch(removals: [10, 30], upserts: [(25, "new"), (40, "D")]),
            to: base, destination: destination
        )

        let patched = try PhoneList(url: destination)
        XCTAssertTrue(patched.isAscending)
        XCTAssertEqual(contents(of: patched).map(\.0), [20, 25, 40])
        XCTAssertEqual(contents(of: patched).map(\.1), ["b", "new", "D"])
    }

    func testSuppressionSurvivesAPatch() throws {
        let base = try write([(1, "one")])
        let destination = scratch.appendingPathComponent("out.bin")

        // An upsert with an empty label turns an entry into a suppression.
        try ListPatch.apply(
            patch: patch(removals: [], upserts: [(1, "")]),
            to: base, destination: destination
        )

        XCTAssertEqual(contents(of: try PhoneList(url: destination)).map(\.1), [""])
    }

    func testRejectsSomethingThatIsNotAPatch() throws {
        let base = try write([(1, "one")])
        XCTAssertThrowsError(
            try ListPatch.apply(
                patch: Data("not a patch at all".utf8),
                to: base, destination: scratch.appendingPathComponent("out.bin")
            )
        )
    }
}
