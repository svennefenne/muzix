package io.github.svennefenne.muzix

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.DocumentsContract
import android.util.Log
import java.io.File

/**
 * This phone's music (step 5 in docs/app-plan.md): the folders picked with the system's folder picker,
 * read by the app itself (the tags with MediaMetadataRetriever, from the files; not the phone's media
 * index), kept in a database of its own with the likes, playlists and plays of this library. Its pages
 * are served by LocalServer/LocalApi in the server's own shapes. The files are only read, never changed.
 */
class LocalLibrary(private val context: Context) {
    val db: SQLiteDatabase = Helper(context).writableDatabase
    private val prefs = context.getSharedPreferences("muzix-local", Context.MODE_PRIVATE)
    val artDir = File(context.filesDir, "local-art").apply { mkdirs() }
    @Volatile var scanning = false
        private set

    // ------------------------------------------------------------ the folders

    /** The folders picked (tree URIs the app may read on), kept between runs. */
    fun folders(): List<Uri> = prefs.getStringSet("folders", emptySet()).orEmpty().map(Uri::parse).sortedBy { it.toString() }

    fun addFolder(tree: Uri) {
        context.contentResolver.takePersistableUriPermission(tree, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        prefs.edit().putStringSet("folders", folders().map { it.toString() }.toSet() + tree.toString()).apply()
    }

    fun removeFolder(tree: Uri) {
        runCatching { context.contentResolver.releasePersistableUriPermission(tree, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        prefs.edit().putStringSet("folders", folders().map { it.toString() }.toSet() - tree.toString()).apply()
    }

    // ------------------------------------------------------------ reading them

    private data class Doc(val uri: Uri, val name: String, val modified: Long, val size: Long, val folder: String)

    /** The folders read again: new and changed songs read, gone ones dropped, then the albums and artists. */
    @Synchronized
    fun scan(): Int {
        scanning = true
        try {
            val found = mutableListOf<Doc>()
            val covers = HashMap<String, Uri>()        // a folder's own picture (cover.jpg, folder.jpg...)
            for (tree in folders()) {
                runCatching { walk(tree, DocumentsContract.getTreeDocumentId(tree), "", found, covers) }
                    .onFailure { Log.w(TAG, "Couldn't read $tree", it) }
            }
            val known = HashMap<String, Long>()
            db.rawQuery("SELECT uri, modified FROM tracks", null).use { c -> while (c.moveToNext()) known[c.getString(0)] = c.getLong(1) }
            val now = System.currentTimeMillis()
            var read = 0
            for (d in found) {
                if (known[d.uri.toString()] == d.modified) continue
                read(d, now)?.let {
                    db.insertWithOnConflict("tracks", null, it, SQLiteDatabase.CONFLICT_REPLACE)
                    read++
                }
            }
            val there = found.map { it.uri.toString() }.toHashSet()
            for (uri in known.keys - there) db.delete("tracks", "uri = ?", arrayOf(uri))
            group(covers)
            return read
        } finally {
            scanning = false
        }
    }

    private fun walk(tree: Uri, docId: String, path: String, out: MutableList<Doc>, covers: HashMap<String, Uri>) {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId)
        val cols = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_SIZE)
        context.contentResolver.query(children, cols, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.getString(0)
                val name = c.getString(1) ?: continue
                if (name.startsWith(".")) continue
                if (c.getString(2) == DocumentsContract.Document.MIME_TYPE_DIR) {
                    walk(tree, id, "$path/$name", out, covers)
                    continue
                }
                val ext = name.substringAfterLast('.', "").lowercase()
                val uri = DocumentsContract.buildDocumentUriUsingTree(tree, id)
                if (ext in AUDIO) out.add(Doc(uri, name, c.getLong(3), c.getLong(4), "$tree$path"))
                else if (name.substringBeforeLast('.').lowercase() in COVER_NAMES && ext in setOf("jpg", "jpeg", "png")) covers["$tree$path"] = uri
            }
        }
    }

    /** A song's tags, from the file itself. */
    private fun read(d: Doc, now: Long): ContentValues? {
        val mmr = MediaMetadataRetriever()
        return try {
            mmr.setDataSource(context, d.uri)
            fun tag(k: Int) = mmr.extractMetadata(k)?.trim().orEmpty()
            val number = { s: String -> s.substringBefore('/').trim().toIntOrNull() ?: 0 }
            val artist = tag(MediaMetadataRetriever.METADATA_KEY_ARTIST)
            ContentValues().apply {
                put("uri", d.uri.toString())
                put("folder", d.folder)
                put("title", tag(MediaMetadataRetriever.METADATA_KEY_TITLE).ifEmpty { d.name.substringBeforeLast('.') })
                put("artist", artist.ifEmpty { "Unknown artist" })
                put("albumartist", tag(MediaMetadataRetriever.METADATA_KEY_ALBUMARTIST).ifEmpty { artist.ifEmpty { "Unknown artist" } })
                put("album", tag(MediaMetadataRetriever.METADATA_KEY_ALBUM).ifEmpty { d.folder.substringAfterLast('/').ifEmpty { "Unknown album" } })
                put("track_no", number(tag(MediaMetadataRetriever.METADATA_KEY_CD_TRACK_NUMBER)))
                put("disc_no", number(tag(MediaMetadataRetriever.METADATA_KEY_DISC_NUMBER)).coerceAtLeast(1))
                // the year in the tags, else in the folder's name ("Album (2010)"), as the server reads it
                put("year", (tag(MediaMetadataRetriever.METADATA_KEY_YEAR).ifEmpty { tag(MediaMetadataRetriever.METADATA_KEY_DATE) }).take(4).toIntOrNull()
                    ?: Regex("""\((\d{4})\)""").find(Uri.decode(d.folder).substringAfterLast('/'))?.groupValues?.get(1)?.toIntOrNull() ?: 0)
                put("genre", tag(MediaMetadataRetriever.METADATA_KEY_GENRE))
                put("duration", (tag(MediaMetadataRetriever.METADATA_KEY_DURATION).toLongOrNull() ?: 0) / 1000.0)
                put("format", d.name.substringAfterLast('.', "").lowercase())
                put("bitrate", (tag(MediaMetadataRetriever.METADATA_KEY_BITRATE).toIntOrNull() ?: 0) / 1000)
                put("size", d.size)
                put("modified", d.modified)
                put("added_at", now)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Couldn't read ${d.name}: ${e.message}")
            null
        } finally {
            runCatching { mmr.release() }
        }
    }

    /** The albums (by album artist and title) and artists, from the songs; the albums' covers. */
    private fun group(covers: Map<String, Uri>) {
        db.beginTransaction()
        try {
            db.execSQL("INSERT OR IGNORE INTO artists(name) SELECT DISTINCT albumartist FROM tracks")
            db.execSQL("INSERT OR IGNORE INTO artists(name) SELECT DISTINCT artist FROM tracks")
            db.execSQL("UPDATE tracks SET artist_id = (SELECT id FROM artists WHERE name = tracks.artist COLLATE NOCASE)")
            db.execSQL("INSERT OR IGNORE INTO albums(key, title, artist, added_at, folder) SELECT lower(albumartist) || char(0) || lower(album), " +
                "min(album), min(albumartist), min(added_at), min(folder) FROM tracks GROUP BY lower(albumartist), lower(album)")
            db.execSQL("UPDATE tracks SET album_id = (SELECT id FROM albums WHERE key = lower(tracks.albumartist) || char(0) || lower(tracks.album))")
            db.execSQL("DELETE FROM albums WHERE id NOT IN (SELECT DISTINCT album_id FROM tracks WHERE album_id IS NOT NULL)")
            db.execSQL("DELETE FROM artists WHERE id NOT IN (SELECT artist_id FROM tracks UNION SELECT artist_id FROM albums)")
            db.execSQL("UPDATE albums SET artist_id = (SELECT id FROM artists WHERE name = albums.artist COLLATE NOCASE), " +
                "track_count = (SELECT count(*) FROM tracks WHERE album_id = albums.id), " +
                "duration = (SELECT coalesce(sum(duration), 0) FROM tracks WHERE album_id = albums.id), " +
                "year = (SELECT coalesce(max(year), 0) FROM tracks WHERE album_id = albums.id), " +
                "formats = (SELECT group_concat(DISTINCT format) FROM tracks WHERE album_id = albums.id), " +
                "genre = coalesce((SELECT genre FROM tracks WHERE album_id = albums.id AND genre != '' GROUP BY genre ORDER BY count(*) DESC LIMIT 1), '')")
            db.execSQL("UPDATE artists SET genre = coalesce((SELECT genre FROM albums WHERE artist_id = artists.id AND genre != '' GROUP BY genre ORDER BY count(*) DESC LIMIT 1), '')")
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        // the covers the albums don't have yet: the folder's picture, else one in a song's tags
        val missing = mutableListOf<Pair<Long, String>>()
        db.rawQuery("SELECT id, folder FROM albums WHERE art IS NULL OR art = ''", null).use { c ->
            while (c.moveToNext()) missing.add(c.getLong(0) to c.getString(1))
        }
        for ((id, folder) in missing) {
            val bytes = covers[folder]?.let { u -> runCatching { context.contentResolver.openInputStream(u)?.use { it.readBytes() } }.getOrNull() }
                ?: embedded(id)
            val file = File(artDir, "album-$id.jpg")
            if (bytes != null && save(bytes, file)) db.execSQL("UPDATE albums SET art = ? WHERE id = ?", arrayOf<Any>(file.name, id))
        }
    }

    private fun embedded(albumId: Long): ByteArray? {
        db.rawQuery("SELECT uri FROM tracks WHERE album_id = ? ORDER BY disc_no, track_no LIMIT 3", arrayOf(albumId.toString())).use { c ->
            while (c.moveToNext()) {
                val mmr = MediaMetadataRetriever()
                try {
                    mmr.setDataSource(context, Uri.parse(c.getString(0)))
                    mmr.embeddedPicture?.let { return it }
                } catch (_: Exception) {
                } finally {
                    runCatching { mmr.release() }
                }
            }
        }
        return null
    }

    /** A picture kept here, at most 600 pixels on a side. */
    fun save(bytes: ByteArray, file: File): Boolean {
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return false
        val scale = 600f / maxOf(bmp.width, bmp.height)
        val out = if (scale < 1) Bitmap.createScaledBitmap(bmp, (bmp.width * scale).toInt(), (bmp.height * scale).toInt(), true) else bmp
        file.outputStream().use { out.compress(Bitmap.CompressFormat.JPEG, 88, it) }
        return true
    }

    private class Helper(context: Context) : SQLiteOpenHelper(context, "local-library.db", null, 1) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL("CREATE TABLE tracks(id INTEGER PRIMARY KEY, uri TEXT UNIQUE, folder TEXT, title TEXT, artist TEXT, " +
                "albumartist TEXT, album TEXT, album_id INTEGER, artist_id INTEGER, track_no INTEGER, disc_no INTEGER, year INTEGER, " +
                "genre TEXT, duration REAL, format TEXT, bitrate INTEGER, size INTEGER, modified INTEGER, added_at INTEGER)")
            db.execSQL("CREATE TABLE albums(id INTEGER PRIMARY KEY, key TEXT UNIQUE, title TEXT, artist TEXT, artist_id INTEGER, " +
                "year INTEGER DEFAULT 0, genre TEXT DEFAULT '', track_count INTEGER DEFAULT 0, duration REAL DEFAULT 0, " +
                "formats TEXT DEFAULT '', art TEXT, added_at INTEGER, folder TEXT)")
            db.execSQL("CREATE TABLE artists(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE, genre TEXT DEFAULT '', art TEXT)")
            db.execSQL("CREATE TABLE likes(kind TEXT, item_id INTEGER, created_at INTEGER, PRIMARY KEY(kind, item_id))")
            db.execSQL("CREATE TABLE playlists(id INTEGER PRIMARY KEY, name TEXT, description TEXT DEFAULT '', updated_at INTEGER)")
            db.execSQL("CREATE TABLE playlist_items(id INTEGER PRIMARY KEY, playlist_id INTEGER, track_id INTEGER, position INTEGER)")
            db.execSQL("CREATE TABLE plays(track_id INTEGER, played_at INTEGER)")
            db.execSQL("CREATE TABLE recent(kind TEXT, item_id INTEGER, at INTEGER, PRIMARY KEY(kind, item_id))")
            db.execSQL("CREATE INDEX tracks_album ON tracks(album_id)")
            db.execSQL("CREATE INDEX tracks_artist ON tracks(artist_id)")
        }

        override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {}
    }

    companion object {
        private const val TAG = "MuzixLocal"
        val AUDIO = setOf("mp3", "flac", "ogg", "oga", "opus", "m4a", "m4b", "aac", "wav", "mka", "webm", "3gp", "amr", "mid", "midi")
        private val COVER_NAMES = setOf("cover", "folder", "front", "album", "albumart")
    }
}
