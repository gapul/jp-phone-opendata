package net.gapul.jpphonedirectory

import android.app.Activity
import android.os.Bundle
import android.provider.ContactsContract
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.io.File
import java.net.URL
import kotlin.concurrent.thread

/**
 * Minimal container: lists live in `filesDir/lists`, and the provider reads them.
 *
 * Deliberately thin for now. The subscription model, catalogue and incremental
 * updates are already worked out on the iOS side; porting that UI is worth doing
 * only once the directory itself is known to show up on a real call.
 */
class MainActivity : Activity() {
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 96, 48, 48)
        }
        status = TextView(this)
        val url = EditText(this).apply {
            hint = "https://…/places_Microsoft.bin"
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
        }
        val add = Button(this).apply {
            text = "Add list"
            setOnClickListener { install(url.text.toString()) }
        }
        val check = Button(this).apply {
            text = "Look up a number"
            setOnClickListener { lookup(url.text.toString()) }
        }

        root.addView(status)
        root.addView(url)
        root.addView(add)
        root.addView(check)
        setContentView(root)

        refresh()
    }

    private fun listsDirectory(): File =
        File(filesDir, DirectoryProvider.LISTS_DIRECTORY).apply { mkdirs() }

    private fun refresh() {
        val files = listsDirectory().listFiles()?.filter { it.name.endsWith(".bin") }.orEmpty()
        val total = files.sumOf { PhoneList.open(it)?.count ?: 0 }
        status.text = "${files.size} lists, ${total} numbers"
    }

    private fun install(from: String) {
        status.text = "Downloading…"
        thread {
            val message = try {
                val name = from.substringAfterLast('/').ifEmpty { "list.bin" }
                val destination = File(listsDirectory(), name)
                URL(from).openStream().use { input ->
                    destination.outputStream().use { input.copyTo(it) }
                }
                // Reject anything the reader cannot open rather than leaving a
                // broken file for the provider to trip over on a live call.
                if (PhoneList.open(destination) == null) {
                    destination.delete()
                    "Not a usable list"
                } else {
                    // The Contacts Provider caches the directory set.
                    contentResolver.notifyChange(ContactsContract.Directory.CONTENT_URI, null)
                    null
                }
            } catch (error: Exception) {
                "Failed: ${error.message}"
            }
            runOnUiThread {
                if (message != null) status.text = message else refresh()
            }
        }
    }

    /** Answers the same question the dialer will, for checking without a call. */
    private fun lookup(raw: String) {
        val number = JapanesePhoneNumber.normalize(raw)
        if (number == null) {
            status.text = "Not a Japanese number"
            return
        }
        val lists = listsDirectory().listFiles { file -> file.name.endsWith(".bin") }
            ?.sortedBy { it.name }
            ?.mapNotNull { PhoneList.open(it) }
            .orEmpty()
        status.text = Directory.lookup(number, lists) ?: "not found"
    }
}
