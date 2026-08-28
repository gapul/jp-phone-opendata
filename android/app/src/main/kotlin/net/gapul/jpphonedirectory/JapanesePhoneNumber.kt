package net.gapul.jpphonedirectory

/**
 * The same rules as `scripts/jp_phone.py` and `PhoneListPacker.normalize`.
 *
 * Kept in step with those deliberately: a number the harvester stored one way
 * and the dialer looks up another way simply never matches, and nothing reports
 * an error when that happens.
 */
object JapanesePhoneNumber {
    fun normalize(raw: String): Long? {
        val digits = buildString {
            for (character in raw) {
                when (character) {
                    // Japanese sources mix in full-width digits.
                    in '０'..'９' -> append(character - 0xFEE0)
                    in '0'..'9' -> append(character)
                }
            }
        }
        if (digits.isEmpty()) return null

        val e164 = when {
            // Country code plus a retained national trunk prefix.
            digits.startsWith("810") -> "81" + digits.substring(3)
            digits.startsWith("81") -> digits
            digits.startsWith("0") -> "81" + digits.substring(1)
            else -> return null
        }

        // 81 + 9 or 10 national digits.
        if (e164.length != 11 && e164.length != 12) return null
        val national = e164.substring(2)
        // No Japanese national number starts with 0 once the trunk prefix is gone.
        if (national.startsWith("0")) return null
        // Ten digits only occur for mobile (70/80/90), IP phones (50), M2M (20)
        // and 0800 toll-free; geographic numbers are always nine.
        val leading = national.take(2)
        if (national.length == 10 && leading !in setOf("70", "80", "90", "50", "20")) {
            return null
        }
        // And the reverse: those ranges are always ten digits, so a nine-digit
        // one has a digit missing rather than being a landline.
        if (national.length == 9 && leading in setOf("50", "60", "70", "80", "90")) {
            return null
        }
        return e164.toLongOrNull()
    }
}
