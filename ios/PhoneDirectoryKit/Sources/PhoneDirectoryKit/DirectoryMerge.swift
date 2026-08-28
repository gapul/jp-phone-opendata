import Foundation

/// Combines several subscribed lists into the single ascending stream CallKit wants.
public enum DirectoryMerge {
    /// Answers a single number the way the merge would, without merging.
    ///
    /// Lists are consulted in priority order and the first hit wins, so this
    /// agrees with `merge` by construction. A suppression stops the search
    /// rather than falling through, otherwise a correction list could never
    /// withdraw a name.
    public static func lookup(_ number: Int64, in lists: [PhoneList]) -> String? {
        for list in lists {
            guard let label = list.lookup(number) else { continue }
            return label.isEmpty ? nil : label
        }
        return nil
    }

    /// How many entries the merge would actually register.
    ///
    /// Summing the lists instead overstates it by however much they overlap,
    /// which is not a rounding error: across the published set it is nearly 9%.
    /// Since that number decides whether the user is warned about the device
    /// ceiling, it has to be the merged one.
    public static func mergedCount(_ lists: [PhoneList]) -> Int {
        var cursors = [Int](repeating: 0, count: lists.count)
        var counted = 0

        while true {
            var winner: Int?
            var smallest = Int64.max
            for (index, list) in lists.enumerated() where cursors[index] < list.count {
                let candidate = list.number(at: cursors[index])
                if candidate < smallest {
                    smallest = candidate
                    winner = index
                }
            }
            guard let winner else { break }

            if !lists[winner].isSuppression(at: cursors[winner]) { counted += 1 }
            for (index, list) in lists.enumerated()
            where cursors[index] < list.count && list.number(at: cursors[index]) == smallest {
                cursors[index] += 1
            }
        }

        return counted
    }

    /// Merges ascending lists into one ascending, duplicate-free stream.
    ///
    /// CallKit rejects the request unless numbers arrive strictly ascending and
    /// without repeats, so a number carried by more than one enabled list is
    /// emitted once, labelled by whichever list comes first.
    ///
    /// A winning entry with an empty label suppresses the number entirely: the
    /// list is saying "show nothing for this", which is how a correction list
    /// removes a wrong name that a larger list below it would otherwise supply.
    /// Without that, priority could only ever replace a name, never withdraw one.
    ///
    /// Returns the number of entries emitted.
    @discardableResult
    public static func merge(_ lists: [PhoneList], emit: (Int64, String) -> Void) -> Int {
        var cursors = [Int](repeating: 0, count: lists.count)
        var emitted = 0

        while true {
            var winner: Int?
            var smallest = Int64.max
            for (index, list) in lists.enumerated() where cursors[index] < list.count {
                let candidate = list.number(at: cursors[index])
                if candidate < smallest {
                    smallest = candidate
                    winner = index
                }
            }
            guard let winner else { break }

            let label = lists[winner].label(at: cursors[winner])
            if !label.isEmpty {
                emit(smallest, label)
                emitted += 1
            }

            // Drop the same number wherever else it appears, suppressed or not.
            for (index, list) in lists.enumerated()
            where cursors[index] < list.count && list.number(at: cursors[index]) == smallest {
                cursors[index] += 1
            }
        }

        return emitted
    }
}
