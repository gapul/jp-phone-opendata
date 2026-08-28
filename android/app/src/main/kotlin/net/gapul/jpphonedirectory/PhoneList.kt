package net.gapul.jpphonedirectory

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel

/**
 * Reads one packed list, the same format the iOS build and `scripts/list_format.py`
 * produce. Layout is documented in `scripts/build_calldir_db.py`.
 *
 * Android asks about a single number while deciding whether to ring, and has
 * milliseconds to answer, so nothing is parsed up front: the file is mapped and
 * binary-searched in place. The numbers are stored contiguous and ascending,
 * which is what makes that possible.
 */
class PhoneList private constructor(
    // Held as ByteBuffer rather than MappedByteBuffer: order() widens the type.
    private val buffer: ByteBuffer,
    val count: Int,
) {
    private val numbersAt = HEADER_SIZE
    private val offsetsAt = numbersAt + count * 8
    private val labelsAt = offsetsAt + (count + 1) * 4

    fun numberAt(index: Int): Long = buffer.getLong(numbersAt + index * 8)

    /** Empty means the entry suppresses the number rather than naming it. */
    fun labelAt(index: Int): String {
        val start = buffer.getInt(offsetsAt + index * 4)
        val end = buffer.getInt(offsetsAt + (index + 1) * 4)
        if (end <= start) return ""
        val bytes = ByteArray(end - start)
        // Duplicate so concurrent lookups do not fight over the position.
        buffer.duplicate().apply { position(labelsAt + start) }.get(bytes)
        return String(bytes, Charsets.UTF_8)
    }

    /** Returns null when absent, and an empty string for a suppression. */
    fun lookup(number: Long): String? {
        var low = 0
        var high = count - 1
        while (low <= high) {
            val middle = (low + high) / 2
            val candidate = numberAt(middle)
            when {
                candidate == number -> return labelAt(middle)
                candidate < number -> low = middle + 1
                else -> high = middle - 1
            }
        }
        return null
    }

    companion object {
        private const val HEADER_SIZE = 16
        private val MAGIC = "JPCD".toByteArray(Charsets.US_ASCII)

        fun open(file: File): PhoneList? {
            if (!file.isFile || file.length() < HEADER_SIZE) return null
            val channel = RandomAccessFile(file, "r").channel
            val buffer = channel.use {
                it.map(FileChannel.MapMode.READ_ONLY, 0, it.size())
            }.order(ByteOrder.LITTLE_ENDIAN)

            val magic = ByteArray(4).also { buffer.duplicate().get(it) }
            if (!magic.contentEquals(MAGIC)) return null
            if (buffer.getInt(4) != 1) return null

            val count = buffer.getInt(8)
            val list = PhoneList(buffer, count)
            return if (buffer.capacity() >= list.labelsAt) list else null
        }
    }
}

/**
 * Consults lists in priority order, first hit wins — the same rule the iOS merge
 * applies, expressed as a lookup because Android never has to enumerate.
 */
object Directory {
    fun lookup(number: Long, lists: List<PhoneList>): String? {
        for (list in lists) {
            val label = list.lookup(number) ?: continue
            return if (label.isEmpty()) null else label
        }
        return null
    }
}
