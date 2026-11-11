package io.github.svennefenne.muzix

import android.content.Context
import android.database.Cursor
import android.net.Uri
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.time.Instant
import java.util.concurrent.TimeUnit

/**
 * This phone's library as the web interface asks for it: the server's own requests and answers
 * (backend/muzix/api/library.py, me.py), from LocalLibrary's database. What only a server has (game
 * music, audiobooks, the Library Network, the admin pages) isn't here; podcasts and radio are the
 * account's, on the server, while there's one (LocalServer passes them on).
 */
class LocalApi(private val context: Context, private val lib: LocalLibrary) {
    sealed class Answer {
        data class Json(val status: Int, val body: Any) : Answer()
        data class Song(val uri: Uri, val mime: String) : Answer()
        data class Picture(val file: File) : Answer()
        data class Redirect(val url: String) : Answer()      // an episode's or a station's own address
    }

    private val db get() = lib.db
    private val store = context.getSharedPreferences("muzix-local", Context.MODE_PRIVATE)
    private val web = OkHttpClient.Builder().callTimeout(10, TimeUnit.SECONDS).build()
    /** Podcasts and radio are the server's while there's one (LocalServer passes them on); else this phone's (step 6). */
    var withServer = false
    val shows = LocalShows(context)

    fun handle(method: String, path: String, q: Map<String, String>, body: String): Answer {
        val p = path.trimEnd('/').split('/').drop(2)     // "/api/albums/3" → [albums, 3]
        val id = p.getOrNull(1)?.toLongOrNull()
        if (!withServer && (path.startsWith("/api/podcasts") || path.startsWith("/api/radio"))) {
            shows.handle(method, path, q, body)?.let { return it }
        }
        return when {
            method == "GET" && path == "/api/health" -> ok(JSONObject().put("ok", true).put("version", "local").put("api", 1))
            method == "GET" && path == "/api/auth/state" -> ok(state())
            method == "GET" && path == "/api/me" -> ok(user())
            method == "PATCH" && path == "/api/me/prefs" -> ok(setPrefs(JSONObject(body.ifEmpty { "{}" })))
            path == "/api/auth/logout" -> ok(JSONObject().put("ok", true))
            path == "/api/client-errors" -> ok(JSONObject().put("ok", true).put("logged", false))
            method == "GET" && path == "/api/home" -> ok(home())
            method == "GET" && path == "/api/genres" -> ok(genres(q["limit"]?.toIntOrNull() ?: 100))
            method == "GET" && path == "/api/sidebar" -> ok(sidebar())
            method == "GET" && path == "/api/albums" -> ok(albums(q))
            method == "GET" && p.size == 2 && p[0] == "albums" && id != null -> album(id)
            method == "GET" && path == "/api/artists" -> ok(artists(q))
            method == "GET" && p.size == 2 && p[0] == "artists" && id != null -> artist(id)
            method == "GET" && path == "/api/letters" -> ok(letters(q))
            method == "GET" && path == "/api/tracks" -> ok(tracksByIds(q["ids"].orEmpty()))
            method == "GET" && path == "/api/random" -> ok(random(q))
            method == "POST" && path == "/api/similar" -> ok(similar(JSONObject(body.ifEmpty { "{}" })))
            method == "GET" && path == "/api/search" -> ok(search(q["q"].orEmpty(), q["limit"]?.toIntOrNull() ?: 20))
            path.startsWith("/api/search/recent") -> recent(method, p, body)
            p.firstOrNull() == "likes" -> likes(method, p)
            p.firstOrNull() == "playlists" -> playlists(method, p, body)
            method == "POST" && path == "/api/plays" -> played(JSONObject(body.ifEmpty { "{}" }).optLong("track_id"))
            method == "GET" && p.size == 2 && p[0] == "stream" && id != null -> stream(id)
            method == "GET" && p.size == 3 && p[0] == "tracks" && p[2] == "lyrics" && id != null -> ok(lyrics(id))
            method == "GET" && p.size >= 3 && p[0] == "art" -> picture(p[1], p[2].toLongOrNull() ?: -1)
            // a Cast speaker's links to this library, played from the phone's address on the wifi (LocalServer)
            method == "GET" && path == "/api/cast/token" -> ok(JSONObject().put("token", LocalServer.CAST_TOKEN).put("expires", System.currentTimeMillis() / 1000 + 86_400))
            method == "GET" && path == "/api/local/folders" -> ok(folders())
            method == "DELETE" && path == "/api/local/folders" -> removeFolder(q["uri"].orEmpty())
            method == "GET" && path in setOf("/api/file-playlists", "/api/vgm/systems", "/api/me/devices") -> ok(JSONArray())
            method == "GET" && path == "/api/android/latest" -> latestApp()
            else -> Answer.Json(404, JSONObject().put("detail", "Not in this phone's library"))
        }
    }

    private fun ok(body: Any) = Answer.Json(200, body)

    // ------------------------------------------------------------ the account (this phone's own)

    private fun state() = JSONObject().put("needs_setup", false).put("setup", false)
        .put("modules", JSONObject().put("vgm", false).put("audiobooks", false).put("network", false)
            .put("podcasts", true).put("radio", true))
        .put("user", user()).put("site_name", "This phone").put("allow_signup", false).put("version", BuildConfig.VERSION_NAME)

    private fun user() = JSONObject().put("id", 1).put("username", "This phone").put("is_admin", false).put("prefs", prefs())

    private fun prefs() = runCatching { JSONObject(store.getString("prefs", "{}")!!) }.getOrDefault(JSONObject())

    private fun setPrefs(changes: JSONObject): JSONObject {
        val p = prefs()
        for (k in changes.keys()) if (changes.isNull(k)) p.remove(k) else p.put(k, changes.get(k))
        store.edit().putString("prefs", p.toString()).apply()
        return p
    }

    // ------------------------------------------------------------ this phone's folders (Settings)

    private fun folders() = JSONArray().apply {
        for (tree in lib.folders()) put(JSONObject().put("uri", tree.toString()).put("name", LocalLibrary.name(tree)).put("songs", lib.songsIn(tree)))
    }

    /** A folder taken out of the library (its files stay where they are). */
    private fun removeFolder(uri: String): Answer {
        val tree = lib.folders().firstOrNull { it.toString() == uri } ?: return Answer.Json(404, JSONObject().put("detail", "Not one of this phone's folders"))
        lib.removeFolder(tree)
        return ok(JSONObject().put("ok", true))
    }

    // ------------------------------------------------------------ shapes (backend/muzix/serial.py)

    private fun liked(kind: String): Set<Long> = buildSet {
        db.rawQuery("SELECT item_id FROM likes WHERE kind = ?", arrayOf(kind)).use { c -> while (c.moveToNext()) add(c.getLong(0)) }
    }

    private fun albumArt(id: Long, art: String?) = if (art.isNullOrEmpty()) JSONObject.NULL else "/api/art/album/$id?v=1"

    private fun albumJson(c: Cursor, lk: Set<Long>): JSONObject {
        val id = c.long("id")
        return JSONObject().put("id", id).put("title", c.str("title")).put("artist", c.str("artist"))
            .put("artist_id", c.long("artist_id")).put("year", c.int("year")).put("genre", c.str("genre")).put("kind", "music")
            .put("track_count", c.int("track_count")).put("duration", c.double("duration"))
            .put("formats", JSONArray(c.str("formats").split(',').filter { it.isNotEmpty() }))
            .put("art", albumArt(id, c.str("art"))).put("added_at", iso(c.long("added_at"))).put("liked", id in lk)
            .put("peer", JSONObject.NULL)
    }

    private fun trackJson(c: Cursor, lk: Set<Long>, art: Map<Long, String?>): JSONObject {
        val id = c.long("id")
        val album = c.long("album_id")
        val format = c.str("format")
        return JSONObject().put("id", id).put("title", c.str("title")).put("artist", c.str("artist"))
            .put("albumartist", c.str("albumartist")).put("album", c.str("album")).put("album_id", album)
            .put("artist_id", c.long("artist_id")).put("track_no", c.int("track_no")).put("disc_no", c.int("disc_no"))
            .put("year", c.int("year")).put("genre", c.str("genre")).put("duration", c.double("duration"))
            .put("format", format).put("kind", "music").put("family", JSONObject.NULL).put("subsong", 0)
            .put("sample_rate", 0).put("bit_depth", 0).put("bitrate", c.int("bitrate"))
            .put("cast_native", format in setOf("mp3", "flac", "m4a", "aac", "ogg", "oga", "opus", "wav", "webm"))
            .put("system", "").put("art", albumArt(album, art[album])).put("stream", "/api/stream/$id")
            .put("liked", id in lk).put("tags", JSONArray())
    }

    private fun artistJson(c: Cursor, lk: Set<Long>, albums: Int?) = JSONObject().put("id", c.long("id"))
        .put("name", c.str("name")).put("genre", c.str("genre")).put("tags", JSONArray())
        .put("art", "/api/art/artist/${c.long("id")}").put("album_count", albums ?: JSONObject.NULL).put("liked", c.long("id") in lk)

    private fun albums(sql: String, args: Array<String> = emptyArray()): JSONArray {
        val lk = liked("album")
        return JSONArray().apply { db.rawQuery(sql, args).use { c -> while (c.moveToNext()) put(albumJson(c, lk)) } }
    }

    private fun tracks(sql: String, args: Array<String> = emptyArray()): MutableList<JSONObject> {
        val lk = liked("track")
        val art = HashMap<Long, String?>()
        db.rawQuery("SELECT id, art FROM albums", null).use { c -> while (c.moveToNext()) art[c.getLong(0)] = c.getString(1) }
        return mutableListOf<JSONObject>().apply { db.rawQuery(sql, args).use { c -> while (c.moveToNext()) add(trackJson(c, lk, art)) } }
    }

    // ------------------------------------------------------------ browsing

    private fun home(): JSONObject {
        val stats = db.rawQuery("SELECT (SELECT count(*) FROM tracks), (SELECT count(*) FROM albums), (SELECT count(*) FROM artists), " +
            "(SELECT coalesce(sum(duration), 0) FROM tracks)", null).use { c -> c.moveToFirst(); listOf(c.getLong(0), c.getLong(1), c.getLong(2), c.getLong(3)) }
        return JSONObject()
            .put("stats", JSONObject().put("tracks", stats[0]).put("albums", stats[1]).put("artists", stats[2])
                .put("vgm_tracks", 0).put("hours", stats[3] / 3600))
            .put("recently_played", albums("SELECT a.* FROM albums a JOIN (SELECT t.album_id, max(p.played_at) m FROM plays p " +
                "JOIN tracks t ON t.id = p.track_id GROUP BY t.album_id) r ON r.album_id = a.id ORDER BY r.m DESC LIMIT 14"))
            .put("recently_added", albums("SELECT * FROM albums ORDER BY added_at DESC, id DESC LIMIT 14"))
            .put("most_played", albums("SELECT a.* FROM albums a JOIN (SELECT t.album_id, count(*) n FROM plays p " +
                "JOIN tracks t ON t.id = p.track_id GROUP BY t.album_id) r ON r.album_id = a.id ORDER BY r.n DESC LIMIT 14"))
            .put("rediscover", albums("SELECT * FROM albums WHERE art IS NOT NULL AND art != '' ORDER BY random() LIMIT 14"))
            .put("vgm", JSONArray()).put("genres", genres(12))
            .put("new_podcasts", JSONArray()).put("new_episodes", JSONArray())
    }

    private fun genres(limit: Int): JSONArray {
        val out = JSONArray()
        db.rawQuery("SELECT genre, count(*), sum(track_count), count(DISTINCT artist_id) FROM albums WHERE genre != '' " +
            "GROUP BY genre ORDER BY count(*) DESC LIMIT ?", arrayOf(limit.toString())).use { c ->
            while (c.moveToNext()) {
                val g = c.getString(0)
                val art = JSONArray()
                db.rawQuery("SELECT id FROM albums WHERE genre = ? AND art IS NOT NULL AND art != '' ORDER BY random() LIMIT 4", arrayOf(g))
                    .use { a -> while (a.moveToNext()) art.put("/api/art/album/${a.getLong(0)}?v=1") }
                out.put(JSONObject().put("name", g).put("albums", c.getInt(1)).put("tracks", c.getInt(2)).put("artists", c.getInt(3)).put("art", art))
            }
        }
        return out
    }

    private fun where(q: Map<String, String>, artists: Boolean = false): Pair<String, Array<String>> {
        val parts = mutableListOf<String>()
        val args = mutableListOf<String>()
        q["genre"]?.takeIf { it.isNotEmpty() }?.let { parts.add("genre = ?"); args.add(it) }
        q["artist_id"]?.toLongOrNull()?.let { parts.add("artist_id = ?"); args.add(it.toString()) }
        if (q["liked_only"] == "true") parts.add("id IN (SELECT item_id FROM likes WHERE kind = '${if (artists) "artist" else "album"}')")
        return (if (parts.isEmpty()) "" else "WHERE " + parts.joinToString(" AND ")) to args.toTypedArray()
    }

    private val albumOrder = mapOf("added" to "added_at DESC", "name" to "title COLLATE NOCASE", "artist" to "artist COLLATE NOCASE, year",
        "year" to "year DESC", "played" to "(SELECT count(*) FROM plays p JOIN tracks t ON t.id = p.track_id WHERE t.album_id = albums.id) DESC")

    private fun albums(q: Map<String, String>): JSONObject {
        if (q["kind"] == "vgm") return JSONObject().put("total", 0).put("items", JSONArray())
        val (w, args) = where(q)
        val total = db.rawQuery("SELECT count(*) FROM albums $w", args).use { it.moveToFirst(); it.getInt(0) }
        val order = albumOrder[q["sort"]] ?: albumOrder.getValue("added")
        return JSONObject().put("total", total).put("items", albums("SELECT * FROM albums $w ORDER BY $order, id LIMIT ? OFFSET ?",
            args + arrayOf(q["limit"] ?: "60", q["offset"] ?: "0")))
    }

    private fun album(id: Long): Answer {
        val a = db.rawQuery("SELECT * FROM albums WHERE id = ?", arrayOf(id.toString())).use { c ->
            if (!c.moveToFirst()) return Answer.Json(404, JSONObject().put("detail", "No such album"))
            albumJson(c, liked("album")).put("folder", "").put("colors", JSONArray()).put("artist_tags", JSONArray())
        }
        a.put("tracks", JSONArray(tracks("SELECT * FROM tracks WHERE album_id = ? ORDER BY disc_no, track_no, title COLLATE NOCASE", arrayOf(id.toString()))))
        a.put("offset", 0)
        a.put("more", albums("SELECT * FROM albums WHERE artist_id = ? AND id != ? ORDER BY year DESC LIMIT 12", arrayOf(a.optLong("artist_id").toString(), id.toString())))
        return ok(a)
    }

    private fun artists(q: Map<String, String>): JSONObject {
        val genre = q["genre"]?.takeIf { it.isNotEmpty() }
        val counts = "SELECT artist_id, count(*) n, max(added_at) added FROM albums ${if (genre != null) "WHERE genre = ?" else ""} GROUP BY artist_id"
        val likedOnly = if (q["liked_only"] == "true") "WHERE artists.id IN (SELECT item_id FROM likes WHERE kind = 'artist')" else ""
        val base = "FROM artists JOIN ($counts) c ON c.artist_id = artists.id $likedOnly"
        val args = listOfNotNull(genre)
        val total = db.rawQuery("SELECT count(*) $base", args.toTypedArray()).use { it.moveToFirst(); it.getInt(0) }
        val order = when (q["sort"]) { "albums" -> "c.n DESC, name COLLATE NOCASE"; "added" -> "c.added DESC"; else -> "name COLLATE NOCASE" }
        val lk = liked("artist")
        val items = JSONArray()
        db.rawQuery("SELECT artists.*, c.n $base ORDER BY $order, artists.id LIMIT ? OFFSET ?",
            (args + listOf(q["limit"] ?: "100", q["offset"] ?: "0")).toTypedArray()).use { c ->
            while (c.moveToNext()) items.put(artistJson(c, lk, c.getInt(c.getColumnIndexOrThrow("n"))))
        }
        return JSONObject().put("total", total).put("items", items)
    }

    private fun artist(id: Long): Answer {
        val a = db.rawQuery("SELECT * FROM artists WHERE id = ?", arrayOf(id.toString())).use { c ->
            if (!c.moveToFirst()) return Answer.Json(404, JSONObject().put("detail", "No such artist"))
            artistJson(c, liked("artist"), null)
        }
        val list = albums("SELECT * FROM albums WHERE artist_id = ? ORDER BY year DESC, title", arrayOf(id.toString()))
        val top = tracks("SELECT t.* FROM tracks t LEFT JOIN (SELECT track_id, count(*) n FROM plays GROUP BY track_id) p ON p.track_id = t.id " +
            "WHERE t.artist_id = ? ORDER BY coalesce(p.n, 0) DESC, random() LIMIT 10", arrayOf(id.toString()))
        return ok(a.put("album_count", list.length()).put("tag_groups", JSONArray()).put("albums", list).put("top_tracks", JSONArray(top)))
    }

    private fun letters(q: Map<String, String>): JSONArray {
        val out = JSONArray()
        val sql = if (q["of"] == "artists") "SELECT name FROM artists WHERE id IN (SELECT artist_id FROM albums) ORDER BY name COLLATE NOCASE, id"
        else "SELECT ${if (q["sort"] == "artist") "artist" else "title"} FROM albums ORDER BY 1 COLLATE NOCASE, id"
        var last = ""
        var i = 0
        db.rawQuery(sql, null).use { c ->
            while (c.moveToNext()) {
                val ch = c.getString(0).orEmpty().trim().take(1).uppercase()
                val letter = if (ch.isNotEmpty() && ch[0] in 'A'..'Z') ch else if (ch.isNotEmpty() && ch[0].isLetter()) "…" else "#"
                if (letter != last) out.put(JSONObject().put("letter", letter).put("offset", i))
                last = letter
                i++
            }
        }
        return out
    }

    private fun tracksByIds(ids: String): JSONArray {
        val want = ids.split(',').mapNotNull { it.trim().toLongOrNull() }.take(1000)
        if (want.isEmpty()) return JSONArray()
        val found = tracks("SELECT * FROM tracks WHERE id IN (${want.joinToString(",")})").associateBy { it.getLong("id") }
        return JSONArray(want.mapNotNull { found[it] })
    }

    private fun random(q: Map<String, String>): JSONArray {
        if (q["kind"] == "vgm") return JSONArray()
        val parts = mutableListOf("1")
        val args = mutableListOf<String>()
        q["genre"]?.takeIf { it.isNotEmpty() }?.let { parts.add("genre = ?"); args.add(it) }
        q["artist_id"]?.toLongOrNull()?.let { parts.add("artist_id = ?"); args.add(it.toString()) }
        q["album_id"]?.toLongOrNull()?.let { parts.add("album_id = ?"); args.add(it.toString()) }
        val n = (q["n"]?.toIntOrNull() ?: 50).coerceIn(1, 500)
        return JSONArray(tracks("SELECT * FROM tracks WHERE ${parts.joinToString(" AND ")} ORDER BY random() LIMIT $n", args.toTypedArray()))
    }

    /** Autoplay: songs in the seeds' genres (else any), not queued and not played lately. */
    private fun similar(b: JSONObject): JSONArray {
        val seeds = b.optJSONArray("seeds")?.let { a -> (0 until a.length()).map { a.optLong(it) } }.orEmpty().take(10)
        val exclude = b.optJSONArray("exclude")?.let { a -> (0 until a.length()).map { a.optLong(it) } }.orEmpty()
        val n = b.optInt("n", 10).coerceIn(1, 50)
        if (seeds.isEmpty()) return JSONArray()
        val skip = (seeds + exclude).joinToString(",")
        val recent = "SELECT track_id FROM plays ORDER BY played_at DESC LIMIT 300"
        val genres = "SELECT DISTINCT genre FROM tracks WHERE id IN (${seeds.joinToString(",")}) AND genre != ''"
        val same = tracks("SELECT * FROM tracks WHERE genre IN ($genres) AND id NOT IN ($skip) AND id NOT IN ($recent) ORDER BY random() LIMIT $n")
        if (same.size >= n) return JSONArray(same)
        val have = (same.map { it.getLong("id") } + seeds + exclude).joinToString(",")
        return JSONArray(same + tracks("SELECT * FROM tracks WHERE id NOT IN ($have) ORDER BY random() LIMIT ${n - same.size}"))
    }

    private fun search(text: String, limit: Int): JSONObject {
        val q = text.trim()
        if (q.isEmpty()) return JSONObject().put("artists", JSONArray()).put("albums", JSONArray()).put("tracks", JSONArray()).put("books", JSONArray())
        val like = "%${q.replace("%", "").replace("_", "")}%"
        val lk = liked("artist")
        val artists = JSONArray()
        db.rawQuery("SELECT * FROM artists WHERE name LIKE ? ORDER BY (name LIKE ?) DESC, name COLLATE NOCASE LIMIT ?",
            arrayOf(like, "$q%", limit.toString())).use { c -> while (c.moveToNext()) artists.put(artistJson(c, lk, null)) }
        return JSONObject().put("artists", artists)
            .put("albums", albums("SELECT * FROM albums WHERE title LIKE ? OR artist LIKE ? ORDER BY (title LIKE ?) DESC, title COLLATE NOCASE LIMIT ?",
                arrayOf(like, like, "$q%", limit.toString())))
            .put("tracks", JSONArray(tracks("SELECT * FROM tracks WHERE title LIKE ? OR artist LIKE ? ORDER BY (title LIKE ?) DESC, title COLLATE NOCASE LIMIT ?",
                arrayOf(like, like, "$q%", limit.toString()))))
            .put("books", JSONArray())
    }

    private fun recent(method: String, p: List<String>, body: String): Answer {
        when (method) {
            "POST" -> JSONObject(body.ifEmpty { "{}" }).let { b ->
                db.execSQL("INSERT OR REPLACE INTO recent(kind, item_id, at) VALUES (?, ?, ?)", arrayOf<Any>(b.optString("kind"), b.optLong("id"), System.currentTimeMillis()))
            }
            "DELETE" -> if (p.size >= 4) db.execSQL("DELETE FROM recent WHERE kind = ? AND item_id = ?", arrayOf<Any>(p[2], p[3].toLongOrNull() ?: -1))
                else db.execSQL("DELETE FROM recent")
            else -> {
                val out = JSONArray()
                db.rawQuery("SELECT kind, item_id FROM recent ORDER BY at DESC LIMIT 12", null).use { c ->
                    while (c.moveToNext()) {
                        val kind = c.getString(0)
                        val id = c.getLong(1).toString()
                        val item: Any? = when (kind) {
                            "album" -> albums("SELECT * FROM albums WHERE id = ?", arrayOf(id)).optJSONObject(0)
                            "track" -> tracks("SELECT * FROM tracks WHERE id = ?", arrayOf(id)).firstOrNull()
                            "artist" -> db.rawQuery("SELECT * FROM artists WHERE id = ?", arrayOf(id)).use { a -> if (a.moveToFirst()) artistJson(a, liked("artist"), null) else null }
                            else -> null
                        }
                        if (item != null) out.put(JSONObject().put("kind", kind).put("item", item))
                    }
                }
                return ok(out)
            }
        }
        return ok(JSONObject().put("ok", true))
    }

    // ------------------------------------------------------------ yours: likes, playlists, plays

    private fun likes(method: String, p: List<String>): Answer {
        if (method == "GET" && p.getOrNull(1) == "tracks") {
            return ok(JSONArray(tracks("SELECT t.* FROM tracks t JOIN likes l ON l.kind = 'track' AND l.item_id = t.id ORDER BY l.created_at DESC")))
        }
        val kind = p.getOrNull(1) ?: return Answer.Json(404, JSONObject())
        val id = p.getOrNull(2)?.toLongOrNull() ?: return Answer.Json(404, JSONObject())
        if (method == "PUT") db.execSQL("INSERT OR IGNORE INTO likes(kind, item_id, created_at) VALUES (?, ?, ?)", arrayOf<Any>(kind, id, System.currentTimeMillis()))
        else db.execSQL("DELETE FROM likes WHERE kind = ? AND item_id = ?", arrayOf<Any>(kind, id))
        return ok(JSONObject().put("liked", method == "PUT"))
    }

    private fun playlistJson(id: Long, withTracks: Boolean): JSONObject? {
        val p = db.rawQuery("SELECT * FROM playlists WHERE id = ?", arrayOf(id.toString())).use { c ->
            if (!c.moveToFirst()) return null
            JSONObject().put("id", id).put("name", c.str("name")).put("description", c.str("description")).put("public", false)
                .put("owner_id", 1).put("updated_at", iso(c.long("updated_at")))
        }
        db.rawQuery("SELECT count(*), coalesce(sum(t.duration), 0) FROM playlist_items i JOIN tracks t ON t.id = i.track_id WHERE i.playlist_id = ?",
            arrayOf(id.toString())).use { c -> c.moveToFirst(); p.put("track_count", c.getInt(0)).put("duration", c.getDouble(1)) }
        val art = JSONArray()
        db.rawQuery("SELECT DISTINCT t.album_id FROM playlist_items i JOIN tracks t ON t.id = i.track_id JOIN albums a ON a.id = t.album_id " +
            "WHERE i.playlist_id = ? AND a.art IS NOT NULL AND a.art != '' ORDER BY i.position LIMIT 4", arrayOf(id.toString()))
            .use { c -> while (c.moveToNext()) art.put("/api/art/album/${c.getLong(0)}?v=1") }
        p.put("art", art)
        if (withTracks) {
            val items = mutableListOf<Long>()
            db.rawQuery("SELECT i.id FROM playlist_items i JOIN tracks t ON t.id = i.track_id WHERE i.playlist_id = ? ORDER BY i.position",
                arrayOf(id.toString())).use { c -> while (c.moveToNext()) items.add(c.getLong(0)) }
            val list = tracks("SELECT t.* FROM playlist_items i JOIN tracks t ON t.id = i.track_id WHERE i.playlist_id = ? ORDER BY i.position", arrayOf(id.toString()))
            p.put("tracks", JSONArray(list.mapIndexed { n, t -> t.put("item_id", items[n]) }))
        }
        return p
    }

    private fun playlists(method: String, p: List<String>, body: String): Answer {
        val id = p.getOrNull(1)?.toLongOrNull()
        val b = runCatching { JSONObject(body.ifEmpty { "{}" }) }.getOrDefault(JSONObject())
        val now = System.currentTimeMillis()
        val missing = Answer.Json(404, JSONObject().put("detail", "No such playlist"))
        return when {
            id == null && method == "GET" -> ok(JSONArray().apply {
                db.rawQuery("SELECT id FROM playlists ORDER BY updated_at DESC", null).use { c -> while (c.moveToNext()) playlistJson(c.getLong(0), false)?.let(::put) }
            })
            id == null && method == "POST" -> {
                db.execSQL("INSERT INTO playlists(name, description, updated_at) VALUES (?, ?, ?)", arrayOf<Any>(b.optString("name", "New playlist"), b.optString("description"), now))
                val new = db.rawQuery("SELECT last_insert_rowid()", null).use { it.moveToFirst(); it.getLong(0) }
                ok(playlistJson(new, false)!!)
            }
            id == null -> missing
            p.size == 2 && method == "GET" -> playlistJson(id, true)?.let(::ok) ?: missing
            p.size == 2 && method == "PATCH" -> {
                db.execSQL("UPDATE playlists SET name = ?, description = ?, updated_at = ? WHERE id = ?", arrayOf<Any>(b.optString("name"), b.optString("description"), now, id))
                playlistJson(id, false)?.let(::ok) ?: missing
            }
            p.size == 2 && method == "DELETE" -> {
                db.execSQL("DELETE FROM playlist_items WHERE playlist_id = ?", arrayOf<Any>(id))
                db.execSQL("DELETE FROM playlists WHERE id = ?", arrayOf<Any>(id))
                ok(JSONObject().put("ok", true))
            }
            p.getOrNull(2) == "tracks" && method == "POST" -> {
                var pos = db.rawQuery("SELECT coalesce(max(position), -1) FROM playlist_items WHERE playlist_id = ?", arrayOf(id.toString())).use { it.moveToFirst(); it.getInt(0) }
                val ids = b.optJSONArray("track_ids") ?: JSONArray()
                for (i in 0 until ids.length()) db.execSQL("INSERT INTO playlist_items(playlist_id, track_id, position) VALUES (?, ?, ?)", arrayOf<Any>(id, ids.getLong(i), ++pos))
                db.execSQL("UPDATE playlists SET updated_at = ? WHERE id = ?", arrayOf<Any>(now, id))
                playlistJson(id, false)?.let(::ok) ?: missing
            }
            p.getOrNull(2) == "items" && method == "DELETE" -> {
                db.execSQL("DELETE FROM playlist_items WHERE playlist_id = ? AND id = ?", arrayOf<Any>(id, p.getOrNull(3)?.toLongOrNull() ?: -1))
                db.execSQL("UPDATE playlists SET updated_at = ? WHERE id = ?", arrayOf<Any>(now, id))
                ok(JSONObject().put("ok", true))
            }
            p.getOrNull(2) == "order" && method == "PUT" -> {
                val items = b.optJSONArray("item_ids") ?: JSONArray()
                for (i in 0 until items.length()) db.execSQL("UPDATE playlist_items SET position = ? WHERE playlist_id = ? AND id = ?", arrayOf<Any>(i, id, items.getLong(i)))
                ok(JSONObject().put("ok", true))
            }
            else -> missing
        }
    }

    private fun played(track: Long): Answer {
        db.execSQL("INSERT INTO plays(track_id, played_at) VALUES (?, ?)", arrayOf<Any>(track, System.currentTimeMillis()))
        return ok(JSONObject().put("ok", true))
    }

    private fun sidebar(): JSONObject {
        val playlists = JSONArray()
        db.rawQuery("SELECT id FROM playlists ORDER BY updated_at DESC", null).use { c ->
            while (c.moveToNext()) playlistJson(c.getLong(0), false)?.let { playlists.put(JSONObject().put("id", it.getLong("id")).put("name", it.getString("name"))
                .put("art", it.getJSONArray("art").opt(0) ?: JSONObject.NULL)) }
        }
        val albums = albums("SELECT * FROM albums WHERE id IN (SELECT item_id FROM likes WHERE kind = 'album') ORDER BY artist COLLATE NOCASE, year")
        val seen = (0 until albums.length()).map { albums.getJSONObject(it).getLong("id") }.toSet()
        val recentAlbums = albums("SELECT a.* FROM albums a JOIN (SELECT t.album_id, max(p.played_at) m FROM plays p JOIN tracks t ON t.id = p.track_id " +
            "GROUP BY t.album_id) r ON r.album_id = a.id ORDER BY r.m DESC LIMIT 30")
        for (i in 0 until recentAlbums.length()) recentAlbums.getJSONObject(i).let { if (it.getLong("id") !in seen) albums.put(it) }
        val artists = JSONArray()
        db.rawQuery("SELECT id, name FROM artists WHERE id IN (SELECT item_id FROM likes WHERE kind = 'artist') ORDER BY name COLLATE NOCASE", null).use { c ->
            while (c.moveToNext()) artists.put(JSONObject().put("id", c.getLong(0)).put("name", c.getString(1)).put("art", "/api/art/artist/${c.getLong(0)}"))
        }
        return JSONObject()
            .put("liked_songs", db.rawQuery("SELECT count(*) FROM likes WHERE kind = 'track'", null).use { it.moveToFirst(); it.getInt(0) })
            .put("playlists", playlists).put("file_playlists", JSONArray())
            .put("albums", JSONArray((0 until albums.length()).map { albums.getJSONObject(it) }.map { a ->
                JSONObject().put("id", a.get("id")).put("title", a.get("title")).put("artist", a.get("artist")).put("year", a.get("year"))
                    .put("kind", "music").put("art", a.get("art")).put("liked", a.get("liked")).put("peer", JSONObject.NULL)
            }))
            .put("games", JSONArray()).put("artists", artists).put("books", JSONArray())
            .put("podcasts", if (withServer) JSONArray() else myPodcasts()).put("stations", if (withServer) JSONArray() else myStations())
    }

    /** The sidebar's podcasts and stations, while they're this phone's. */
    private fun myPodcasts() = JSONArray().apply {
        val list = (shows.handle("GET", "/api/podcasts", emptyMap(), "") as? Answer.Json)?.body as? JSONArray ?: JSONArray()
        for (i in 0 until list.length()) list.getJSONObject(i).let { f ->
            put(JSONObject().put("id", f.get("id")).put("title", f.get("title")).put("author", f.get("author"))
                .put("art", f.optString("image").ifEmpty { null } ?: JSONObject.NULL).put("new", false))
        }
    }

    private fun myStations() = (shows.handle("GET", "/api/radio/stations", emptyMap(), "") as? Answer.Json)?.body as? JSONArray ?: JSONArray()

    // ------------------------------------------------------------ the files, pictures and words

    private fun stream(id: Long): Answer {
        val (uri, format) = db.rawQuery("SELECT uri, format FROM tracks WHERE id = ?", arrayOf(id.toString())).use { c ->
            if (!c.moveToFirst()) return Answer.Json(404, JSONObject().put("detail", "No such track"))
            Uri.parse(c.getString(0)) to c.getString(1)
        }
        return Answer.Song(uri, MIME[format] ?: "application/octet-stream")
    }

    private fun picture(kind: String, id: Long): Answer {
        val none = Answer.Json(404, JSONObject().put("detail", "No picture"))
        if (kind == "album") {
            val name = db.rawQuery("SELECT art FROM albums WHERE id = ?", arrayOf(id.toString())).use { c -> if (c.moveToFirst()) c.getString(0) else null }
            return name?.takeIf { it.isNotEmpty() }?.let { File(lib.artDir, it) }?.takeIf { it.exists() }?.let { Answer.Picture(it) } ?: none
        }
        if (kind != "artist") return none
        // an artist's picture from Deezer, fetched once and kept (an empty file: there's none)
        val file = File(lib.artDir, "artist-$id.jpg")
        if (!file.exists()) {
            val name = db.rawQuery("SELECT name FROM artists WHERE id = ?", arrayOf(id.toString())).use { c -> if (c.moveToFirst()) c.getString(0) else null } ?: return none
            val bytes = runCatching {
                val found = get("https://api.deezer.com/search/artist?limit=1&q=" + URLEncoder.encode(name, "UTF-8"))
                val pic = JSONObject(found).optJSONArray("data")?.optJSONObject(0)?.takeIf { it.optString("name").equals(name, true) }
                    ?.optString("picture_xl")?.takeIf { it.isNotEmpty() && !it.contains("/artist//") }
                pic?.let { u -> web.newCall(Request.Builder().url(u).build()).execute().use { it.body?.bytes() } }
            }.getOrNull()
            if (bytes == null || !lib.save(bytes, file)) file.writeBytes(ByteArray(0))
        }
        return if (file.length() > 0) Answer.Picture(file) else none
    }

    /** A song's words from LRCLIB (synced if it has them), shown only: the files aren't changed. */
    private fun lyrics(id: Long): JSONObject {
        val empty = JSONObject().put("source", JSONObject.NULL).put("synced", false).put("lines", JSONArray()).put("instrumental", false).put("colors", JSONArray())
        val (artist, title, album, duration) = db.rawQuery("SELECT artist, title, album, duration FROM tracks WHERE id = ?", arrayOf(id.toString())).use { c ->
            if (!c.moveToFirst()) return empty
            listOf(c.getString(0), c.getString(1), c.getString(2), c.getDouble(3).toInt().toString())
        }
        val found = runCatching {
            JSONObject(get("https://lrclib.net/api/get?artist_name=${enc(artist)}&track_name=${enc(title)}&album_name=${enc(album)}&duration=$duration"))
        }.getOrNull() ?: return empty
        if (found.optBoolean("instrumental")) return empty.put("source", "lrclib").put("instrumental", true)
        val synced = found.optString("syncedLyrics").takeIf { it.isNotBlank() && it != "null" }
        val lines = JSONArray()
        if (synced != null) {
            val stamp = Regex("""^\[(\d+):(\d+(?:\.\d+)?)]\s*(.*)$""")
            for (l in synced.lines()) stamp.find(l)?.let { m ->
                lines.put(JSONObject().put("t", m.groupValues[1].toInt() * 60 + m.groupValues[2].toDouble()).put("text", m.groupValues[3]))
            }
        } else {
            found.optString("plainLyrics").takeIf { it.isNotBlank() && it != "null" }?.lines()?.forEach { lines.put(JSONObject().put("t", JSONObject.NULL).put("text", it)) }
        }
        if (lines.length() == 0) return empty
        return empty.put("source", "lrclib").put("synced", synced != null).put("lines", lines)
    }

    /** The app's newest version with no server to ask (LocalServer passes it on to one): the highest
     * android-v* release on GitHub with the APK, as backend/muzix/api/android.py answers it. */
    private fun latestApp(): Answer {
        val releases = try {
            JSONArray(get("https://api.github.com/repos/svennefenne/muzix/releases?per_page=30"))
        } catch (e: Exception) {
            return Answer.Json(502, JSONObject().put("detail", "GitHub couldn't be reached to check for updates: try again in a while"))
        }
        fun parts(v: String) = v.split('.').map { it.toIntOrNull() ?: 0 }
        fun higher(a: String, b: String): Boolean {
            val (x, y) = parts(a) to parts(b)
            for (i in 0 until maxOf(x.size, y.size)) if (x.getOrElse(i) { 0 } != y.getOrElse(i) { 0 }) return x.getOrElse(i) { 0 } > y.getOrElse(i) { 0 }
            return false
        }
        var best = JSONObject().put("version", JSONObject.NULL).put("url", JSONObject.NULL)
        for (i in 0 until releases.length()) {
            val r = releases.getJSONObject(i)
            val v = Regex("^android-v(\\d+(?:\\.\\d+)*)$").find(r.optString("tag_name"))?.groupValues?.get(1) ?: continue
            if (r.optBoolean("draft") || r.optBoolean("prerelease")) continue
            val assets = r.optJSONArray("assets") ?: continue
            val apk = (0 until assets.length()).map { assets.getJSONObject(it) }.firstOrNull { it.optString("name") == "muzix-android.apk" } ?: continue
            if (best.isNull("version") || higher(v, best.getString("version"))) {
                best = JSONObject().put("version", v).put("url", apk.optString("browser_download_url"))
            }
        }
        return ok(best)
    }

    private fun get(url: String): String = web.newCall(Request.Builder().url(url).header("User-Agent", PlaybackService.USER_AGENT).build()).execute().use {
        if (!it.isSuccessful) throw java.io.IOException("HTTP ${it.code}")
        it.body?.string().orEmpty()
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private fun iso(ms: Long): Any = if (ms > 0) Instant.ofEpochMilli(ms).toString() else JSONObject.NULL

    private fun Cursor.idx(name: String) = getColumnIndex(name)
    private fun Cursor.str(name: String) = idx(name).let { if (it < 0 || isNull(it)) "" else getString(it) }
    private fun Cursor.long(name: String) = idx(name).let { if (it < 0 || isNull(it)) 0L else getLong(it) }
    private fun Cursor.int(name: String) = idx(name).let { if (it < 0 || isNull(it)) 0 else getInt(it) }
    private fun Cursor.double(name: String) = idx(name).let { if (it < 0 || isNull(it)) 0.0 else getDouble(it) }

    companion object {
        val MIME = mapOf("mp3" to "audio/mpeg", "flac" to "audio/flac", "ogg" to "audio/ogg", "oga" to "audio/ogg", "opus" to "audio/ogg",
            "m4a" to "audio/mp4", "m4b" to "audio/mp4", "aac" to "audio/aac", "wav" to "audio/wav", "mka" to "audio/x-matroska",
            "webm" to "audio/webm", "3gp" to "audio/3gpp", "amr" to "audio/amr", "mid" to "audio/midi", "midi" to "audio/midi")
    }
}
