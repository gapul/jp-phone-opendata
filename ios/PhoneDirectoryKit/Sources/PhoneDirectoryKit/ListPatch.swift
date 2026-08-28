import Foundation

/// Applies a published difference between two releases of a list.
///
/// A monthly refresh changes a small part of a large table, and both sides are
/// sorted by number, so the publisher ships removals and upserts rather than the
/// whole file again. See `scripts/list_format.py` for the layout.
public enum ListPatch {
    public enum Failure: Error {
        case notAPatch
        case unsupportedVersion(UInt32)
        case truncated
    }

    static let magic = Array("JPCP".utf8)
    private static let headerSize = 16

    /// Rewrites `base` with the patch applied, into `destination`.
    ///
    /// Both inputs are ascending, so this is a linear merge: no sorting, and no
    /// need to hold the whole table as objects.
    public static func apply(patch data: Data, to base: PhoneList, destination: URL) throws {
        guard data.count >= headerSize, Array(data.prefix(4)) == magic else {
            throw Failure.notAPatch
        }

        let version = data.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 4, as: UInt32.self) }
        guard version == 1 else { throw Failure.unsupportedVersion(version) }

        let removeCount = Int(data.withUnsafeBytes {
            $0.loadUnaligned(fromByteOffset: 8, as: UInt32.self)
        })
        let upsertCount = Int(data.withUnsafeBytes {
            $0.loadUnaligned(fromByteOffset: 12, as: UInt32.self)
        })

        let removalsAt = headerSize
        let numbersAt = removalsAt + removeCount * 8
        let offsetsAt = numbersAt + upsertCount * 8
        let labelsAt = offsetsAt + (upsertCount + 1) * 4
        guard data.count >= labelsAt else { throw Failure.truncated }

        var merged: [(number: Int64, label: String)] = []
        merged.reserveCapacity(base.count + upsertCount)

        try data.withUnsafeBytes { raw in
            guard let pointer = raw.baseAddress else { throw Failure.truncated }
            let removals = pointer.advanced(by: removalsAt).assumingMemoryBound(to: Int64.self)
            let numbers = pointer.advanced(by: numbersAt).assumingMemoryBound(to: Int64.self)
            let bounds = pointer.advanced(by: offsetsAt).assumingMemoryBound(to: UInt32.self)
            let labels = pointer.advanced(by: labelsAt).assumingMemoryBound(to: UInt8.self)

            func upsertLabel(_ index: Int) -> String {
                let start = Int(bounds[index])
                let end = Int(bounds[index + 1])
                guard end > start else { return "" }
                return String(
                    decoding: UnsafeBufferPointer(start: labels + start, count: end - start),
                    as: UTF8.self
                )
            }

            var baseAt = 0
            var upsertAt = 0
            var removeAt = 0

            while baseAt < base.count || upsertAt < upsertCount {
                let fromBase = baseAt < base.count ? base.number(at: baseAt) : Int64.max
                let fromUpsert = upsertAt < upsertCount ? numbers[upsertAt] : Int64.max

                if fromUpsert <= fromBase {
                    // An upsert replaces the base entry with the same number.
                    if fromBase == fromUpsert { baseAt += 1 }
                    merged.append((fromUpsert, upsertLabel(upsertAt)))
                    upsertAt += 1
                    continue
                }

                // Removals are ascending too, so advance past anything behind us.
                while removeAt < removeCount && removals[removeAt] < fromBase {
                    removeAt += 1
                }
                if removeAt < removeCount && removals[removeAt] == fromBase {
                    removeAt += 1
                } else {
                    merged.append((fromBase, base.label(at: baseAt)))
                }
                baseAt += 1
            }
        }

        try PhoneListPacker.write(merged, to: destination)
    }
}
