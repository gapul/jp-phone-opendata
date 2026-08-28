import XCTest
@testable import PhoneDirectoryKit

final class DirectoryMergeTests: XCTestCase {
    private var scratch: URL!

    override func setUpWithError() throws {
        scratch = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: scratch)
    }

    /// Builds a list the same way an imported text file would be built.
    private func list(_ body: String) throws -> PhoneList {
        let url = scratch.appendingPathComponent("\(UUID().uuidString).bin")
        try PhoneListPacker.write(PhoneListPacker.parse(body), to: url)
        return try PhoneList(url: url)
    }

    private func merged(_ lists: [PhoneList]) -> [(Int64, String)] {
        var output: [(Int64, String)] = []
        DirectoryMerge.merge(lists) { output.append(($0, $1)) }
        return output
    }

    func testMergeIsAscendingAcrossLists() throws {
        let first = try list("03-1000-0001,A\n03-1000-0003,C")
        let second = try list("03-1000-0002,B\n03-1000-0004,D")

        let result = merged([first, second])

        XCTAssertEqual(result.map(\.1), ["A", "B", "C", "D"])
        XCTAssertEqual(result.map(\.0), result.map(\.0).sorted())
    }

    func testEarlierListWinsOnConflict() throws {
        let preferred = try list("03-1000-0001,Correct")
        let fallback = try list("03-1000-0001,Wrong\n03-1000-0002,Other")

        let result = merged([preferred, fallback])

        // The duplicate is emitted once, and by the higher-priority list.
        XCTAssertEqual(result.map(\.1), ["Correct", "Other"])
    }

    func testSuppressionRemovesANameALowerListWouldSupply() throws {
        let corrections = try list("-03-1000-0001")
        let bulk = try list("03-1000-0001,Stale Name\n03-1000-0002,Kept")

        let result = merged([corrections, bulk])

        XCTAssertEqual(result.map(\.1), ["Kept"])
    }

    func testSuppressionOnlyWinsFromAHigherPriorityList() throws {
        let bulk = try list("03-1000-0001,Wanted")
        let corrections = try list("-03-1000-0001")

        // The suppression sits below, so it does not apply.
        XCTAssertEqual(merged([bulk, corrections]).map(\.1), ["Wanted"])
    }

    func testNormalisationAcceptsTheNotationsTheFeedsUse() {
        XCTAssertEqual(PhoneListPacker.normalize("03-1234-5678"), 81_312_345_678)
        XCTAssertEqual(PhoneListPacker.normalize("+81 3 1234 5678"), 81_312_345_678)
        XCTAssertEqual(PhoneListPacker.normalize("+81 03-1234-5678"), 81_312_345_678)
        XCTAssertEqual(PhoneListPacker.normalize("０３－１２３４－５６７８"), 81_312_345_678)
        XCTAssertEqual(PhoneListPacker.normalize("090-1234-5678"), 819_012_345_678)
        XCTAssertNil(PhoneListPacker.normalize("+1 202 555 0100"))
        XCTAssertNil(PhoneListPacker.normalize("098-485-71117"))
        XCTAssertNil(PhoneListPacker.normalize(""))
    }

    func testCommentsAndBlankLinesAreIgnored() throws {
        let parsed = PhoneListPacker.parse("""
        # a comment
        ! another
        03-1000-0001,Kept

        """)
        XCTAssertEqual(parsed.count, 1)
        XCTAssertEqual(parsed.first?.label, "Kept")
    }
}

final class CatalogOrderTests: XCTestCase {
    private func descriptor(_ id: String, _ confidence: Double?) -> PhoneListDescriptor {
        PhoneListDescriptor(id: id, title: id, filename: "\(id).bin", entryCount: 1,
                            confidence: confidence, sourceURL: "https://example.com/\(id)",
                            updatedAt: nil, isEnabled: true)
    }

    func testScoredListsLandInQualityOrderWhateverTheInstallOrder() {
        var catalog = DirectoryCatalog()
        // Deliberately installed worst-first.
        catalog.insert(descriptor("low", 0.77))
        catalog.insert(descriptor("high", 0.98))
        catalog.insert(descriptor("mid", 0.90))

        XCTAssertEqual(catalog.lists.map(\.id), ["high", "mid", "low"])
    }

    func testAHandMadeListOverridesEverything() {
        var catalog = DirectoryCatalog()
        catalog.insert(descriptor("bulk", 0.82))
        catalog.insert(descriptor("corrections", nil))

        XCTAssertEqual(catalog.lists.first?.id, "corrections")
    }

    func testReinstallingReplacesRatherThanDuplicates() {
        var catalog = DirectoryCatalog()
        catalog.insert(descriptor("a", 0.90))
        catalog.insert(descriptor("a", 0.90))

        XCTAssertEqual(catalog.lists.count, 1)
    }
}

final class MergedCountTests: XCTestCase {
    private var scratch: URL!

    override func setUpWithError() throws {
        scratch = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: scratch)
    }

    private func list(_ body: String) throws -> PhoneList {
        let url = scratch.appendingPathComponent("\(UUID().uuidString).bin")
        try PhoneListPacker.write(PhoneListPacker.parse(body), to: url)
        return try PhoneList(url: url)
    }

    func testOverlapIsCountedOnce() throws {
        let first = try list("03-1000-0001,A\n03-1000-0002,B")
        let second = try list("03-1000-0002,B again\n03-1000-0003,C")

        // Summing the lists would say four.
        XCTAssertEqual(DirectoryMerge.mergedCount([first, second]), 3)
    }

    func testSuppressedEntriesAreNotCounted() throws {
        let corrections = try list("-03-1000-0001")
        let bulk = try list("03-1000-0001,Hidden\n03-1000-0002,Shown")

        XCTAssertEqual(DirectoryMerge.mergedCount([corrections, bulk]), 1)
    }

    func testCountMatchesWhatTheMergeEmits() throws {
        let first = try list("03-1000-0001,A\n03-1000-0004,D")
        let second = try list("-03-1000-0004\n03-1000-0002,B")
        let third = try list("03-1000-0002,dup\n03-1000-0003,C")

        var emitted = 0
        DirectoryMerge.merge([first, second, third]) { _, _ in emitted += 1 }
        XCTAssertEqual(DirectoryMerge.mergedCount([first, second, third]), emitted)
    }
}

/// The random-access path an Android directory provider would use, proven here
/// so the Kotlin port is a transcription rather than a fresh design.
final class LookupTests: XCTestCase {
    private var scratch: URL!

    override func setUpWithError() throws {
        scratch = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: scratch)
    }

    private func list(_ body: String) throws -> PhoneList {
        let url = scratch.appendingPathComponent("\(UUID().uuidString).bin")
        try PhoneListPacker.write(PhoneListPacker.parse(body), to: url)
        return try PhoneList(url: url)
    }

    func testFindsEveryEntryAndNothingElse() throws {
        let entries = (0..<500).map { (number: Int64(81_300_000_000 + $0 * 7), label: "n\($0)") }
        let url = scratch.appendingPathComponent("big.bin")
        try PhoneListPacker.write(entries, to: url)
        let list = try PhoneList(url: url)

        for entry in entries {
            XCTAssertEqual(list.lookup(entry.number), entry.label)
            // The gaps between the seeded numbers must miss.
            XCTAssertNil(list.lookup(entry.number + 1))
        }
    }

    func testEmptyAndBoundaryCases() throws {
        let empty = try list("# nothing here")
        XCTAssertNil(empty.lookup(81_312_345_678))

        let one = try list("03-1234-5678,Only")
        XCTAssertEqual(one.lookup(81_312_345_678), "Only")
        XCTAssertNil(one.lookup(81_312_345_677))
        XCTAssertNil(one.lookup(81_312_345_679))
    }

    func testLookupAgreesWithTheMerge() throws {
        let corrections = try list("-03-1000-0002")
        let preferred = try list("03-1000-0001,Right")
        let bulk = try list("03-1000-0001,Wrong\n03-1000-0002,Hidden\n03-1000-0003,Kept")
        let lists = [corrections, preferred, bulk]

        var merged: [Int64: String] = [:]
        DirectoryMerge.merge(lists) { merged[$0] = $1 }

        for number in Int64(81_310_000_000)...Int64(81_310_000_004) {
            XCTAssertEqual(DirectoryMerge.lookup(number, in: lists), merged[number],
                           "disagreed on \(number)")
        }
    }
}
