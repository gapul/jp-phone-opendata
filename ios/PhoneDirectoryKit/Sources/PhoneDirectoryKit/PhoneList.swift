import Foundation

/// Read-only view over one packed list produced by `scripts/build_calldir_db.py`.
///
/// A Call Directory extension gets a small memory budget, far less than the
/// tables it registers, so nothing is parsed up front: the file is memory-mapped
/// and read in place. `NSData` is used rather than `Data` because its `bytes`
/// pointer stays valid for the object's lifetime, which lets a merge across
/// several lists hold cursors into all of them at once.
///
/// An entry with an empty label is a suppression: it says the number should
/// carry no name at all, overriding anything a lower-priority list offers.
public final class PhoneList {
    public enum Failure: Error {
        case notARecognizedTable
        case unsupportedVersion(UInt32)
        case truncated
    }

    /// magic + version + count + padding that keeps `numbers` 8-byte aligned.
    static let headerSize = 16
    static let magic = Array("JPCD".utf8)

    private let backing: NSData
    private let base: UnsafeRawPointer
    private let numbersOffset: Int
    private let offsetsOffset: Int
    private let labelsOffset: Int

    public let count: Int

    public init(url: URL) throws {
        backing = try NSData(contentsOf: url, options: .mappedIfSafe)
        guard backing.length >= Self.headerSize else { throw Failure.truncated }
        base = UnsafeRawPointer(backing.bytes)

        guard Array(UnsafeRawBufferPointer(start: base, count: 4)) == Self.magic else {
            throw Failure.notARecognizedTable
        }
        let version = base.loadUnaligned(fromByteOffset: 4, as: UInt32.self)
        guard version == 1 else { throw Failure.unsupportedVersion(version) }

        count = Int(base.loadUnaligned(fromByteOffset: 8, as: UInt32.self))
        numbersOffset = Self.headerSize
        offsetsOffset = numbersOffset + count * MemoryLayout<Int64>.size
        labelsOffset = offsetsOffset + (count + 1) * MemoryLayout<UInt32>.size
        guard backing.length >= labelsOffset else { throw Failure.truncated }
    }

    /// Entries are stored ascending, which is also the order CallKit requires.
    public func number(at index: Int) -> Int64 {
        base.loadUnaligned(fromByteOffset: numbersOffset + index * 8, as: Int64.self)
    }

    /// Empty means "suppress this number", not "no name available".
    public func label(at index: Int) -> String {
        let start = Int(base.loadUnaligned(fromByteOffset: offsetsOffset + index * 4, as: UInt32.self))
        let end = Int(base.loadUnaligned(fromByteOffset: offsetsOffset + (index + 1) * 4, as: UInt32.self))
        guard end > start else { return "" }
        let bytes = base.advanced(by: labelsOffset + start).assumingMemoryBound(to: UInt8.self)
        return String(decoding: UnsafeBufferPointer(start: bytes, count: end - start), as: UTF8.self)
    }

    /// Whether this entry suppresses rather than names, without paying to build
    /// the string — counting a merged directory touches every entry, so this is
    /// the difference between a snappy screen and a stalled one.
    public func isSuppression(at index: Int) -> Bool {
        let start = base.loadUnaligned(fromByteOffset: offsetsOffset + index * 4, as: UInt32.self)
        let end = base.loadUnaligned(fromByteOffset: offsetsOffset + (index + 1) * 4, as: UInt32.self)
        return end == start
    }

    /// Finds one number, without walking the table.
    ///
    /// This is the access pattern Android needs: a directory provider is asked
    /// about a single number while the phone is deciding whether to ring, so it
    /// has milliseconds and cannot afford the sequential registration pass iOS
    /// does. The numbers are stored contiguous and ascending, so a binary search
    /// works directly on the mapping. Returns nil when absent, and an empty
    /// string when the entry is a suppression.
    public func lookup(_ number: Int64) -> String? {
        var low = 0
        var high = count - 1
        while low <= high {
            let middle = (low + high) / 2
            let candidate = self.number(at: middle)
            if candidate == number { return label(at: middle) }
            if candidate < number { low = middle + 1 } else { high = middle - 1 }
        }
        return nil
    }

    /// Whether the file really is sorted, which the merge and CallKit both assume.
    /// Worth paying for once on a downloaded list: an unsorted one would fail the
    /// whole registration, not just its own entries.
    public var isAscending: Bool {
        guard count > 1 else { return true }
        var previous = number(at: 0)
        for index in 1..<count {
            let current = number(at: index)
            if current <= previous { return false }
            previous = current
        }
        return true
    }
}
