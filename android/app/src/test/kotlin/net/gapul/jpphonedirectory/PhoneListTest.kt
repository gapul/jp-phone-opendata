package net.gapul.jpphonedirectory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class PhoneListTest {
    @get:Rule
    val folder = TemporaryFolder()

    /** Writes the packed format the build scripts produce. */
    private fun write(entries: List<Pair<Long, String>>): File {
        val labels = entries.map { it.second.toByteArray(Charsets.UTF_8) }
        val size = 16 + entries.size * 8 + (entries.size + 1) * 4 + labels.sumOf { it.size }
        val buffer = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("JPCD".toByteArray(Charsets.US_ASCII))
        buffer.putInt(1)
        buffer.putInt(entries.size)
        buffer.putInt(0)
        entries.forEach { buffer.putLong(it.first) }
        var cursor = 0
        buffer.putInt(cursor)
        labels.forEach { cursor += it.size; buffer.putInt(cursor) }
        labels.forEach { buffer.put(it) }

        val file = folder.newFile()
        file.writeBytes(buffer.array())
        return file
    }

    @Test
    fun `finds every entry and nothing between them`() {
        val entries = (0 until 500).map { 81_300_000_000L + it * 7 to "n$it" }
        val list = PhoneList.open(write(entries))!!

        assertEquals(500, list.count)
        entries.forEach { (number, label) ->
            assertEquals(label, list.lookup(number))
            assertNull(list.lookup(number + 1))
        }
    }

    @Test
    fun `reads japanese labels back intact`() {
        val list = PhoneList.open(write(listOf(81_312_345_678L to "渋谷クリニック")))!!
        assertEquals("渋谷クリニック", list.lookup(81_312_345_678L))
    }

    @Test
    fun `rejects a file that is not a packed list`() {
        val file = folder.newFile().apply { writeBytes("not a list at all".toByteArray()) }
        assertNull(PhoneList.open(file))
    }

    @Test
    fun `earlier list wins and a suppression hides the number`() {
        val corrections = PhoneList.open(write(listOf(81_312_345_678L to "")))!!
        val bulk = PhoneList.open(
            write(listOf(81_312_345_678L to "Hidden", 81_398_765_432L to "Shown"))
        )!!

        assertNull(Directory.lookup(81_312_345_678L, listOf(corrections, bulk)))
        assertEquals("Shown", Directory.lookup(81_398_765_432L, listOf(corrections, bulk)))
    }

    @Test
    fun `normalisation matches the harvesters`() {
        assertEquals(81_312_345_678L, JapanesePhoneNumber.normalize("03-1234-5678"))
        assertEquals(81_312_345_678L, JapanesePhoneNumber.normalize("+81 3 1234 5678"))
        assertEquals(81_312_345_678L, JapanesePhoneNumber.normalize("+81 03-1234-5678"))
        assertEquals(81_312_345_678L, JapanesePhoneNumber.normalize("０３－１２３４－５６７８"))
        assertEquals(819_012_345_678L, JapanesePhoneNumber.normalize("090-1234-5678"))
        assertNull(JapanesePhoneNumber.normalize("+1 202 555 0100"))
        assertNull(JapanesePhoneNumber.normalize("098-485-71117"))
        assertNull(JapanesePhoneNumber.normalize(""))
    }
}
