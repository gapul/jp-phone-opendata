// Host-side check that the Swift reader agrees with the Python writer.
//
// The package's own tests cover the merge on synthetic lists; this one runs the
// reader over the real generated files, which are far larger and are the ones
// that would actually break a device.
//
// Usage:
//   swiftc -O -parse-as-library \
//     ios/PhoneDirectoryKit/Sources/PhoneDirectoryKit/PhoneList.swift \
//     scripts/verify_db.swift -o /tmp/verify_db
//   /tmp/verify_db dist/places_Microsoft.bin

import Foundation

@main
enum VerifyDB {
    static func main() throws {
        let arguments = CommandLine.arguments
        guard arguments.count == 2 else {
            FileHandle.standardError.write(Data("usage: verify_db <list.bin>\n".utf8))
            exit(2)
        }

        let list = try PhoneList(url: URL(fileURLWithPath: arguments[1]))
        print("count: \(list.count)")

        var previous = Int64.min
        var suppressions = 0
        var outOfRange = 0

        for index in 0..<list.count {
            let number = list.number(at: index)
            // CallKit drops the entire request if numbers are not strictly ascending.
            precondition(number > previous, "not ascending at \(index): \(number) <= \(previous)")
            previous = number

            // An empty label is a deliberate suppression, so count rather than reject.
            if list.label(at: index).isEmpty { suppressions += 1 }
            // E.164 allows 8 to 15 digits, country code included. The lists now
            // span 200-odd countries, so nothing narrower than that applies.
            if number < 10_000_000 || number > 999_999_999_999_999 { outOfRange += 1 }
        }

        print("suppressions: \(suppressions)")
        print("out of range: \(outOfRange)")
        if list.count > 0 {
            print("  first: +\(list.number(at: 0)) \(list.label(at: 0))")
            print("  last:  +\(list.number(at: list.count - 1)) \(list.label(at: list.count - 1))")
        }

        precondition(outOfRange == 0, "\(outOfRange) entries are not valid E.164 numbers")
        precondition(list.isAscending, "isAscending disagrees with the walk above")
        print("ok")
    }
}
