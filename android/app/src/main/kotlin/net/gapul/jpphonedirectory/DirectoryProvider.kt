package net.gapul.jpphonedirectory

import android.content.ContentProvider
import android.content.ContentValues
import android.content.UriMatcher
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.provider.ContactsContract
import java.io.File

/**
 * Supplies caller names to the system dialer.
 *
 * Android has no equivalent of iOS's pre-registered Call Directory: the dialer
 * asks the Contacts Provider who a number belongs to, and that forwards the
 * question here. So there is nothing to register and no size ceiling — but the
 * answer has to come back while the phone is deciding whether to ring.
 *
 * Note that `PhoneLookup` does not reach directory providers; the caller has to
 * use `Phone.CONTENT_FILTER_URI` with a `directory=` parameter. Whether a given
 * dialer does that on an incoming call varies, which is the one thing about this
 * approach that cannot be settled by reading the documentation.
 */
class DirectoryProvider : ContentProvider() {
    private val matcher = UriMatcher(UriMatcher.NO_MATCH).apply {
        addURI(AUTHORITY, "directories", DIRECTORIES)
        addURI(AUTHORITY, "data/phones/filter", PHONE_FILTER)
        addURI(AUTHORITY, "data/phones/filter/*", PHONE_FILTER)
    }

    private var lists: List<PhoneList> = emptyList()

    override fun onCreate(): Boolean = true

    /** Opened lazily and cached: the first call after boot pays for the mapping. */
    private fun lists(): List<PhoneList> {
        if (lists.isEmpty()) {
            val directory = File(context?.filesDir, LISTS_DIRECTORY)
            lists = directory.listFiles { file -> file.name.endsWith(".bin") }
                ?.sortedBy { it.name }
                ?.mapNotNull { PhoneList.open(it) }
                ?: emptyList()
        }
        return lists
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = when (matcher.match(uri)) {
        DIRECTORIES -> directories(projection)
        PHONE_FILTER -> phoneFilter(uri, projection)
        else -> null
    }

    /** Announces this directory to the Contacts Provider when it scans. */
    private fun directories(projection: Array<out String>?): Cursor {
        val columns = projection ?: arrayOf(
            ContactsContract.Directory.ACCOUNT_NAME,
            ContactsContract.Directory.ACCOUNT_TYPE,
            ContactsContract.Directory.DISPLAY_NAME,
            ContactsContract.Directory.TYPE_RESOURCE_ID,
            ContactsContract.Directory.EXPORT_SUPPORT,
            ContactsContract.Directory.SHORTCUT_SUPPORT,
            ContactsContract.Directory.PHOTO_SUPPORT,
        )
        val cursor = MatrixCursor(columns)
        cursor.addRow(
            columns.map { column ->
                when (column) {
                    ContactsContract.Directory.ACCOUNT_NAME,
                    ContactsContract.Directory.ACCOUNT_TYPE,
                    ContactsContract.Directory.DISPLAY_NAME -> DISPLAY_NAME
                    ContactsContract.Directory.TYPE_RESOURCE_ID -> R.string.app_name
                    ContactsContract.Directory.EXPORT_SUPPORT ->
                        ContactsContract.Directory.EXPORT_SUPPORT_SAME_ACCOUNT_ONLY
                    ContactsContract.Directory.SHORTCUT_SUPPORT ->
                        ContactsContract.Directory.SHORTCUT_SUPPORT_NONE
                    ContactsContract.Directory.PHOTO_SUPPORT ->
                        ContactsContract.Directory.PHOTO_SUPPORT_NONE
                    else -> null
                }
            }.toTypedArray()
        )
        return cursor
    }

    private fun phoneFilter(uri: Uri, projection: Array<out String>?): Cursor {
        // A directory provider must null-fill columns it does not recognise
        // rather than fail, so that a newer platform asking for more does not
        // break it.
        val columns = projection ?: arrayOf(
            ContactsContract.Contacts._ID,
            ContactsContract.Contacts.DISPLAY_NAME,
        )
        val cursor = MatrixCursor(columns)

        val query = uri.lastPathSegment ?: return cursor
        val number = JapanesePhoneNumber.normalize(query) ?: return cursor
        val label = Directory.lookup(number, lists()) ?: return cursor

        cursor.addRow(
            columns.map { column ->
                when (column) {
                    ContactsContract.Contacts._ID -> 1L
                    ContactsContract.Contacts.DISPLAY_NAME,
                    ContactsContract.Contacts.DISPLAY_NAME_ALTERNATIVE,
                    ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME -> label
                    ContactsContract.CommonDataKinds.Phone.NUMBER -> query
                    ContactsContract.CommonDataKinds.Phone.TYPE ->
                        ContactsContract.CommonDataKinds.Phone.TYPE_WORK
                    else -> null
                }
            }.toTypedArray()
        )
        return cursor
    }

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0

    companion object {
        const val AUTHORITY = "net.gapul.jpphonedirectory.directory"
        const val LISTS_DIRECTORY = "lists"
        private const val DISPLAY_NAME = "JP Phone Directory"
        private const val DIRECTORIES = 1
        private const val PHONE_FILTER = 2
    }
}
