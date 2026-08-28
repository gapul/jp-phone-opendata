import Foundation

/// Turns a plain text list into the packed layout the extension reads, so a list
/// anyone can author in a text editor ends up in the same format as generated ones.
public enum PhoneListPacker {
    /// Parses a list body into ascending, deduplicated entries.
    ///
    /// Lines are `number,label`. A line starting with `-` suppresses the number
    /// instead, the way an ad blocker's exception rule cancels a match — that
    /// entry is stored with an empty label. `#` and `!` start a comment.
    ///
    /// Accepts both national (`03-1234-5678`) and E.164 (`+81 3 1234 5678`)
    /// notation, matching the normalisation in `scripts/jp_phone.py`.
    public static func parse(_ text: String) -> [(number: Int64, label: String)] {
        var seen: [Int64: String] = [:]

        for line in text.split(whereSeparator: \.isNewline) {
            var trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty || trimmed.hasPrefix("#") || trimmed.hasPrefix("!") { continue }

            let isSuppression = trimmed.hasPrefix("-")
            if isSuppression { trimmed = String(trimmed.dropFirst()) }

            let fields = trimmed.split(separator: ",", maxSplits: 1, omittingEmptySubsequences: false)
            guard let number = normalize(String(fields[0])) else { continue }

            let label: String
            if isSuppression {
                label = ""
            } else {
                guard fields.count == 2 else { continue }
                label = fields[1]
                    .trimmingCharacters(in: .whitespaces)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
                if label.isEmpty { continue }
            }

            // First occurrence wins, mirroring how earlier lists win at merge time.
            if seen[number] == nil { seen[number] = label }
        }

        return seen.keys.sorted().map { ($0, seen[$0]!) }
    }

    public static func normalize(_ raw: String) -> Int64? {
        let digits = raw.filter(\.isNumber).unicodeScalars.compactMap { scalar -> Character? in
            // Fold the full-width digits Japanese sources mix in.
            if scalar.value >= 0xFF10 && scalar.value <= 0xFF19 {
                return Character(UnicodeScalar(scalar.value - 0xFEE0)!)
            }
            return ("0"..."9").contains(Character(scalar)) ? Character(scalar) : nil
        }
        let text = String(digits)
        guard !text.isEmpty else { return nil }

        let e164: String
        if text.hasPrefix("810") {
            // Country code plus a retained national trunk prefix.
            e164 = "81" + text.dropFirst(3)
        } else if text.hasPrefix("81") {
            e164 = text
        } else if text.hasPrefix("0") {
            e164 = "81" + text.dropFirst()
        } else {
            return nil
        }

        // 81 + 9 or 10 national digits.
        guard e164.count == 11 || e164.count == 12 else { return nil }
        let national = e164.dropFirst(2)
        // No Japanese national number starts with 0 once the trunk prefix is gone.
        guard let first = national.first, first != "0" else { return nil }
        // Ten digits only occur for mobile (70/80/90), IP phones (50), M2M (20)
        // and 0800 toll-free; geographic numbers are always nine.
        let leading = String(national.prefix(2))
        if national.count == 10, !["70", "80", "90", "50", "20"].contains(leading) {
            return nil
        }
        // And the reverse: those ranges are always ten digits, so a nine-digit
        // one has a digit missing rather than being a landline.
        if national.count == 9, ["50", "60", "70", "80", "90"].contains(leading) {
            return nil
        }
        return Int64(e164)
    }

    public static func write(_ entries: [(number: Int64, label: String)], to url: URL) throws {
        var numbers = Data()
        var offsets = Data()
        var labels = Data()

        var cursor = UInt32(0)
        withUnsafeBytes(of: cursor.littleEndian) { offsets.append(contentsOf: $0) }
        for entry in entries {
            withUnsafeBytes(of: entry.number.littleEndian) { numbers.append(contentsOf: $0) }
            let encoded = Data(entry.label.utf8)
            labels.append(encoded)
            cursor += UInt32(encoded.count)
            withUnsafeBytes(of: cursor.littleEndian) { offsets.append(contentsOf: $0) }
        }

        var file = Data(PhoneList.magic)
        withUnsafeBytes(of: UInt32(1).littleEndian) { file.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt32(entries.count).littleEndian) { file.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt32(0).littleEndian) { file.append(contentsOf: $0) }
        file.append(numbers)
        file.append(offsets)
        file.append(labels)

        try file.write(to: url, options: .atomic)
    }
}
