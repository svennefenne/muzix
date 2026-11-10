package io.github.svennefenne.muzix

import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.text.Html
import android.util.Xml
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONArray
import org.json.JSONObject
import org.xmlpull.v1.XmlPullParser
import java.net.URLEncoder
import java.time.Instant
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/**
 * Podcasts and radio kept on the phone while there's no server (step 6 in docs/app-plan.md), in the
 * server's own requests and answers (backend/muzix/api/podcasts.py, radio.py): podcasts found through
 * Apple's directory and read from their feeds here, stations from radio-browser. At a later sign-in to
 * a server they move into the account there (moveTo), and are gone from here.
 */
class LocalShows(context: Context) {
    private val db: SQLiteDatabase = Helper(context).writableDatabase
    private val web = OkHttpClient.Builder().callTimeout(20, TimeUnit.SECONDS).followRedirects(true).build()

    /** Whether there's anything here to move into an account. */
    fun any(): Boolean = count("SELECT count(*) FROM feeds WHERE subscribed = 1") + count("SELECT count(*) FROM stations") > 0

    fun handle(method: String, path: String, q: Map<String, String>, body: String): LocalApi.Answer? {
        val p = path.trimEnd('/').split('/').drop(2)        // "/api/podcasts/3" → [podcasts, 3]
        val b = runCatching { JSONObject(body.ifEmpty { "{}" }) }.getOrDefault(JSONObject())
        return try {
            when (p.firstOrNull()) {
                "podcasts" -> podcasts(method, p, q, b)
                "radio" -> radio(method, p, q, b)
                else -> null
            }
        } catch (e: java.io.IOException) {
            LocalApi.Answer.Json(502, JSONObject().put("detail", "Couldn't reach it: ${e.message}"))
        }
    }

    private fun ok(body: Any) = LocalApi.Answer.Json(200, body)
    private fun missing(what: String) = LocalApi.Answer.Json(404, JSONObject().put("detail", "No such $what"))

    // ------------------------------------------------------------ podcasts

    private fun podcasts(method: String, p: List<String>, q: Map<String, String>, b: JSONObject): LocalApi.Answer {
        val id = p.getOrNull(1)?.toLongOrNull()
        val ep = p.getOrNull(2)?.toLongOrNull()
        return when {
            p.size == 1 && method == "GET" -> ok(feeds("WHERE subscribed = 1 ORDER BY title COLLATE NOCASE"))
            p.size == 1 && method == "POST" -> ok(JSONObject().put("id", read(b.optString("url"), subscribe = true)))
            p.getOrNull(1) == "open" -> ok(JSONObject().put("id", read(b.optString("url"), subscribe = false)))
            p.getOrNull(1) == "latest" -> ok(episodes("WHERE f.subscribed = 1 ORDER BY e.published DESC LIMIT ${q["limit"] ?: "40"}"))
            p.getOrNull(1) == "continue" -> ok(episodes("WHERE g.finished = 0 AND g.position >= 5 AND (coalesce(e.duration, 0) = 0 OR g.position < e.duration - 15) " +
                "ORDER BY g.updated_at DESC LIMIT ${q["limit"] ?: "10"}"))
            p.getOrNull(1) == "search" -> ok(itunes("https://itunes.apple.com/search?media=podcast&limit=30&term=" + enc(q["q"].orEmpty())))
            p.getOrNull(1) == "genres" -> ok(JSONArray(GENRES.map { (i, n) -> JSONObject().put("id", i).put("name", n) }))
            p.getOrNull(1) == "top" -> ok(top(q["genre"]?.toIntOrNull()))
            p.getOrNull(1) == "refresh" -> { refresh(); ok(JSONObject().put("job_id", 0)) }
            p.getOrNull(1) == "episodes" && p.getOrNull(2) == "restore" -> {
                val list = b.optJSONArray("episodes") ?: JSONArray()
                for (i in 0 until list.length()) list.getJSONObject(i).let { x ->
                    if (x.optBoolean("started")) db.execSQL("UPDATE progress SET position = ?, finished = 0 WHERE episode_id = ?", arrayOf<Any>(x.optDouble("position"), x.optLong("id")))
                    else db.execSQL("DELETE FROM progress WHERE episode_id = ?", arrayOf<Any>(x.optLong("id")))
                }
                ok(JSONObject().put("ok", true))
            }
            p.getOrNull(1) == "episodes" && ep != null -> episode(method, ep, p.getOrNull(3), q, b)
            id == null -> missing("podcast")
            p.size == 2 && method == "GET" -> feed(id, q)
            p.size == 2 && method == "DELETE" -> { db.execSQL("UPDATE feeds SET subscribed = 0 WHERE id = ?", arrayOf<Any>(id)); ok(JSONObject().put("ok", true)) }
            p.getOrNull(2) == "subscription" -> {
                if (b.has("autoplay")) db.execSQL("UPDATE feeds SET autoplay = ? WHERE id = ?", arrayOf<Any>(if (b.optBoolean("autoplay")) 1 else 0, id))
                ok(JSONObject().put("ok", true))
            }
            else -> missing("podcast page")
        }
    }

    private fun feedJson(c: Cursor) = JSONObject().put("id", c.long("id")).put("url", c.str("url")).put("title", c.str("title").ifEmpty { c.str("url") })
        .put("author", c.str("author")).put("description", c.str("description")).put("image", c.str("image")).put("link", c.str("link"))
        .put("categories", runCatching { JSONArray(c.str("categories")) }.getOrDefault(JSONArray())).put("error", c.str("error"))
        .put("subscribed", c.int("subscribed") == 1).put("auto_download", false).put("autoplay", c.int("autoplay") == 1)
        .put("unplayed", count("SELECT count(*) FROM episodes e LEFT JOIN progress g ON g.episode_id = e.id WHERE e.feed_id = ${c.long("id")} AND coalesce(g.finished, 0) = 0"))
        .put("new", false).put("last_checked", iso(c.long("last_checked")))

    private fun feeds(where: String) = JSONArray().apply { db.rawQuery("SELECT * FROM feeds $where", null).use { c -> while (c.moveToNext()) put(feedJson(c)) } }

    private fun episodeJson(c: Cursor) = JSONObject().put("id", c.long("id")).put("feed_id", c.long("feed_id")).put("title", c.str("title"))
        .put("description", c.str("description")).put("published", iso(c.long("published"))).put("duration", c.double("duration"))
        .put("image", c.str("image").ifEmpty { c.str("feed_image") }).put("downloaded", false)
        .put("position", c.double("position")).put("finished", c.int("finished") == 1).put("new", false)
        .put("stream", "/api/podcasts/episodes/${c.long("id")}/stream").put("feed_title", c.str("feed_title"))

    private fun episodes(rest: String, args: Array<String> = emptyArray()) = JSONArray().apply {
        db.rawQuery("SELECT e.*, f.title feed_title, f.image feed_image, coalesce(g.position, 0) position, coalesce(g.finished, 0) finished " +
            "FROM episodes e JOIN feeds f ON f.id = e.feed_id LEFT JOIN progress g ON g.episode_id = e.id $rest", args)
            .use { c -> while (c.moveToNext()) put(episodeJson(c)) }
    }

    private fun feed(id: Long, q: Map<String, String>): LocalApi.Answer {
        val f = db.rawQuery("SELECT * FROM feeds WHERE id = ?", arrayOf(id.toString())).use { c -> if (c.moveToFirst()) feedJson(c) else null } ?: return missing("podcast")
        val oldest = q["order"] == "oldest"
        val hide = if (q["hide_finished"] == "true") "AND coalesce(g.finished, 0) = 0" else ""
        val dir = if (oldest) "ASC" else "DESC"
        val list = episodes("WHERE e.feed_id = ? $hide ORDER BY e.published IS NULL, e.published $dir, e.id $dir LIMIT ${(q["limit"]?.toIntOrNull() ?: 200).coerceIn(1, 5000)}", arrayOf(id.toString()))
        return ok(f.put("total", count("SELECT count(*) FROM episodes WHERE feed_id = $id"))
            .put("finished", count("SELECT count(*) FROM episodes e JOIN progress g ON g.episode_id = e.id WHERE e.feed_id = $id AND g.finished = 1"))
            .put("episodes", list))
    }

    private fun episode(method: String, id: Long, what: String?, q: Map<String, String>, b: JSONObject): LocalApi.Answer {
        val e = episodes("WHERE e.id = ?", arrayOf(id.toString())).optJSONObject(0) ?: return missing("episode")
        return when (what) {
            null -> {
                val feed = db.rawQuery("SELECT * FROM feeds WHERE id = ?", arrayOf(e.getLong("feed_id").toString())).use { c -> c.moveToFirst(); feedJson(c) }
                ok(e.put("notes", notes(e.optString("description"))).put("feed", JSONObject().put("id", feed.get("id")).put("title", feed.get("title"))
                    .put("author", feed.get("author")).put("image", feed.get("image"))))
            }
            "stream" -> LocalApi.Answer.Redirect(db.rawQuery("SELECT audio_url FROM episodes WHERE id = ?", arrayOf(id.toString())).use { c -> c.moveToFirst(); c.getString(0) })
            "progress" -> {
                db.execSQL("INSERT OR REPLACE INTO progress(episode_id, position, finished, updated_at) VALUES (?, ?, ?, ?)",
                    arrayOf<Any>(id, b.optDouble("position", 0.0), if (b.optBoolean("finished")) 1 else 0, System.currentTimeMillis()))
                ok(JSONObject().put("ok", true))
            }
            "download" -> ok(JSONObject().put("job_id", 0))
            "next" -> ok(JSONObject().put("next", next(e, q["order"] == "oldest") ?: JSONObject.NULL))
            "finish-older" -> {
                val published = db.rawQuery("SELECT published FROM episodes WHERE id = ?", arrayOf(id.toString())).use { c -> c.moveToFirst(); c.getLong(0) }
                if (published == 0L) return LocalApi.Answer.Json(400, JSONObject().put("detail", "This episode has no date to go by"))
                val before = JSONArray()
                db.rawQuery("SELECT e.id, e.duration, g.position, g.episode_id FROM episodes e LEFT JOIN progress g ON g.episode_id = e.id " +
                    "WHERE e.feed_id = ? AND e.published > 0 AND (e.published < ? OR (e.published = ? AND e.id < ?)) AND coalesce(g.finished, 0) = 0",
                    arrayOf(e.getLong("feed_id").toString(), published.toString(), published.toString(), id.toString())).use { c ->
                    while (c.moveToNext()) {
                        before.put(JSONObject().put("id", c.getLong(0)).put("position", c.getDouble(2)).put("started", !c.isNull(3)))
                        db.execSQL("INSERT OR REPLACE INTO progress(episode_id, position, finished, updated_at) VALUES (?, ?, 1, ?)",
                            arrayOf<Any>(c.getLong(0), c.getDouble(1), System.currentTimeMillis()))
                    }
                }
                ok(JSONObject().put("marked", before.length()).put("before", before))
            }
            else -> missing("episode page")
        }
    }

    /** The next one not heard to the end, in the page's order, else the nearest the other way (autoplay on). */
    private fun next(e: JSONObject, oldest: Boolean): JSONObject? {
        val feed = e.getLong("feed_id")
        if (count("SELECT autoplay FROM feeds WHERE id = $feed") != 1) return null
        val published = db.rawQuery("SELECT published FROM episodes WHERE id = ?", arrayOf(e.getLong("id").toString())).use { c -> c.moveToFirst(); c.getLong(0) }
        fun after(old: Boolean): JSONObject? = episodes("WHERE e.feed_id = $feed AND coalesce(g.finished, 0) = 0 AND e.id != ${e.getLong("id")} AND " +
            (if (old) "e.published >= $published ORDER BY e.published ASC, e.id ASC" else "e.published <= $published ORDER BY e.published DESC, e.id DESC") + " LIMIT 1").optJSONObject(0)
        return after(oldest) ?: after(!oldest)
    }

    /** Show notes as safe HTML: the description's text, in paragraphs (no markup from the feed comes through). */
    private fun notes(text: String): String {
        val plain = Html.fromHtml(text, Html.FROM_HTML_MODE_COMPACT).toString().trim()
        return plain.split(Regex("\n\\s*\n")).joinToString("") { "<p>" + Html.escapeHtml(it).replace("\n", "<br>") + "</p>" }
    }

    /** A feed read now (subscribed to or only opened): its episodes kept. The podcast's id. */
    fun read(url: String, subscribe: Boolean): Long {
        require(url.startsWith("http://") || url.startsWith("https://")) { "That isn't a feed's address" }
        val xml = get(url)
        val parser = Xml.newPullParser().apply { setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, false); setInput(xml.reader()) }
        val ch = HashMap<String, String>()
        val items = mutableListOf<HashMap<String, String>>()
        var item: HashMap<String, String>? = null
        val cats = JSONArray()
        while (parser.next() != XmlPullParser.END_DOCUMENT) {
            if (parser.eventType == XmlPullParser.START_TAG) {
                val tag = parser.name
                val into = item ?: ch
                when (tag) {
                    "item" -> item = HashMap()
                    "enclosure" -> into["audio"] = parser.getAttributeValue(null, "url").orEmpty()
                    "itunes:image" -> into["image"] = parser.getAttributeValue(null, "href").orEmpty()
                    "itunes:category" -> if (item == null) parser.getAttributeValue(null, "text")?.let { cats.put(it) }
                    "url" -> if (item == null && parser.depth == 4) into["image"] = into["image"] ?: parser.nextText().trim()
                    "title", "guid", "pubDate", "description", "itunes:author", "itunes:duration", "link", "itunes:summary", "content:encoded" ->
                        if (!(tag == "link" && into.containsKey("link"))) into[tag] = runCatching { parser.nextText() }.getOrDefault("").trim()
                }
            } else if (parser.eventType == XmlPullParser.END_TAG && parser.name == "item") {
                item?.let(items::add)
                item = null
            }
        }
        db.execSQL("INSERT OR IGNORE INTO feeds(url) VALUES (?)", arrayOf<Any>(url))
        val id = db.rawQuery("SELECT id FROM feeds WHERE url = ?", arrayOf(url)).use { c -> c.moveToFirst(); c.getLong(0) }
        db.execSQL("UPDATE feeds SET title = ?, author = ?, description = ?, image = ?, link = ?, categories = ?, error = '', last_checked = ? WHERE id = ?",
            arrayOf<Any>(ch["title"].orEmpty(), ch["itunes:author"].orEmpty(), ch["description"] ?: ch["itunes:summary"].orEmpty(),
                ch["image"].orEmpty(), ch["link"].orEmpty(), cats.toString(), System.currentTimeMillis(), id))
        if (subscribe) db.execSQL("UPDATE feeds SET subscribed = 1, autoplay = 1, subscribed_at = ? WHERE id = ? AND subscribed = 0", arrayOf<Any>(System.currentTimeMillis(), id))
        for (it in items) {
            val audio = it["audio"].orEmpty().ifEmpty { continue }
            db.execSQL("INSERT OR IGNORE INTO episodes(feed_id, guid, title, description, published, duration, image, audio_url, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                arrayOf<Any>(id, it["guid"] ?: audio, it["title"].orEmpty(), it["content:encoded"] ?: it["description"] ?: it["itunes:summary"].orEmpty(),
                    date(it["pubDate"]), seconds(it["itunes:duration"]), it["image"].orEmpty(), audio, System.currentTimeMillis()))
        }
        return id
    }

    /** The subscribed podcasts read again (on refresh, and when this phone's library opens). */
    fun refresh() {
        val urls = mutableListOf<String>()
        db.rawQuery("SELECT url FROM feeds WHERE subscribed = 1", null).use { c -> while (c.moveToNext()) urls.add(c.getString(0)) }
        for (u in urls) runCatching { read(u, subscribe = false) }.onFailure { e ->
            db.execSQL("UPDATE feeds SET error = ? WHERE url = ?", arrayOf<Any>(e.message.orEmpty().take(500), u))
        }
    }

    private fun itunes(url: String): JSONArray {
        val out = JSONArray()
        val results = JSONObject(get(url)).optJSONArray("results") ?: return out
        for (i in 0 until results.length()) results.getJSONObject(i).let { x ->
            if (x.optString("feedUrl").isNotEmpty()) out.put(JSONObject().put("title", x.optString("collectionName")).put("author", x.optString("artistName"))
                .put("url", x.optString("feedUrl")).put("image", x.optString("artworkUrl600").ifEmpty { x.optString("artworkUrl100") })
                .put("genre", x.optString("primaryGenreName")))
        }
        return out
    }

    private fun top(genre: Int?): JSONArray {
        val country = java.util.Locale.getDefault().country.lowercase().ifEmpty { "us" }
        val ids = if (genre != null) {
            val entries = JSONObject(get("https://itunes.apple.com/$country/rss/toppodcasts/limit=50/genre=$genre/json")).optJSONObject("feed")?.optJSONArray("entry") ?: JSONArray()
            (0 until entries.length()).map { entries.getJSONObject(it).getJSONObject("id").getJSONObject("attributes").getString("im:id") }
        } else {
            val results = JSONObject(get("https://rss.marketingtools.apple.com/api/v2/$country/podcasts/top/30/podcasts.json")).optJSONObject("feed")?.optJSONArray("results") ?: JSONArray()
            (0 until results.length()).map { results.getJSONObject(it).getString("id") }
        }
        return if (ids.isEmpty()) JSONArray() else itunes("https://itunes.apple.com/lookup?entity=podcast&id=" + ids.joinToString(","))
    }

    // ------------------------------------------------------------ radio

    private fun radio(method: String, p: List<String>, q: Map<String, String>, b: JSONObject): LocalApi.Answer = when (p.getOrNull(1)) {
        "search" -> ok(stations(rb("/json/stations/search?limit=${(q["limit"]?.toIntOrNull() ?: 60).coerceAtMost(200)}&hidebroken=true&order=clickcount&reverse=true" +
            (q["q"]?.takeIf { it.isNotEmpty() }?.let { "&name=" + enc(it) } ?: "") + (q["tag"]?.takeIf { it.isNotEmpty() }?.let { "&tag=" + enc(it) } ?: "") +
            (q["country"]?.takeIf { it.isNotEmpty() }?.let { "&countrycode=" + enc(it) } ?: ""))))
        "top" -> ok(JSONObject().put("top", stations(rb("/json/stations/topclick/40?hidebroken=true"))))
        "tags" -> ok(JSONArray().apply {
            val t = JSONArray(rb("/json/tags?order=stationcount&reverse=true&limit=80&hidebroken=true"))
            for (i in 0 until t.length()) t.getJSONObject(i).let { put(JSONObject().put("name", it.optString("name")).put("stations", it.optInt("stationcount"))) }
        })
        "stations" -> when {
            method == "POST" -> {
                db.execSQL("INSERT INTO stations(uuid, name, url, homepage, favicon, tags, country, codec, bitrate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    arrayOf<Any>(b.optString("uuid"), b.optString("name"), b.optString("url"), b.optString("homepage"), b.optString("favicon"),
                        b.optString("tags"), b.optString("country"), b.optString("codec"), b.optInt("bitrate")))
                ok(saved().let { it.getJSONObject(it.length() - 1) })
            }
            method == "DELETE" -> { db.execSQL("DELETE FROM stations WHERE id = ?", arrayOf<Any>(p.getOrNull(2)?.toLongOrNull() ?: -1)); ok(JSONObject().put("ok", true)) }
            else -> ok(saved())
        }
        "play" -> LocalApi.Answer.Redirect(q["url"].orEmpty())
        "history" -> ok(JSONArray())
        "nowplaying" -> ok(JSONObject().put("title", "").put("since", 0))
        else -> missing("radio page")
    }

    private fun saved() = JSONArray().apply {
        db.rawQuery("SELECT * FROM stations ORDER BY id", null).use { c ->
            while (c.moveToNext()) put(JSONObject().put("id", c.long("id")).put("uuid", c.str("uuid")).put("name", c.str("name")).put("url", c.str("url"))
                .put("homepage", c.str("homepage")).put("favicon", c.str("favicon")).put("tags", c.str("tags")).put("country", c.str("country"))
                .put("codec", c.str("codec")).put("bitrate", c.int("bitrate")))
        }
    }

    private fun stations(json: String) = JSONArray().apply {
        val a = JSONArray(json)
        for (i in 0 until a.length()) a.getJSONObject(i).let { s ->
            put(JSONObject().put("uuid", s.optString("stationuuid")).put("name", s.optString("name").trim()).put("url", s.optString("url_resolved").ifEmpty { s.optString("url") })
                .put("homepage", s.optString("homepage")).put("favicon", s.optString("favicon")).put("tags", s.optString("tags")).put("country", s.optString("country"))
                .put("countrycode", s.optString("countrycode")).put("codec", s.optString("codec")).put("bitrate", s.optInt("bitrate"))
                .put("votes", s.optInt("votes")).put("hls", s.optInt("hls") == 1))
        }
    }

    private fun rb(path: String): String {
        var last: Exception? = null
        for (host in listOf("de1", "fi1", "nl1").shuffled()) {
            try { return get("https://$host.api.radio-browser.info$path") } catch (e: Exception) { last = e }
        }
        throw java.io.IOException("The radio directory isn't answering (${last?.message})")
    }

    // ------------------------------------------------------------ into the account at a later sign-in

    /** What's kept here moved into the account on `server` (signed in with `cookie`): each thing the
     * server takes is gone from here, so nothing moves twice. How many moved. */
    fun moveTo(server: String, cookie: String): Int {
        var moved = 0
        val json = "application/json".toMediaType()
        fun post(path: String, body: JSONObject) = web.newCall(Request.Builder().url(server + path).header("Cookie", cookie)
            .header("User-Agent", PlaybackService.USER_AGENT).post(body.toString().toRequestBody(json)).build()).execute().use { it.isSuccessful }
        val feeds = mutableListOf<Pair<Long, String>>()
        db.rawQuery("SELECT id, url FROM feeds WHERE subscribed = 1", null).use { c -> while (c.moveToNext()) feeds.add(c.getLong(0) to c.getString(1)) }
        for ((id, url) in feeds) if (runCatching { post("/api/podcasts", JSONObject().put("url", url)) }.getOrDefault(false)) {
            db.execSQL("UPDATE feeds SET subscribed = 0 WHERE id = ?", arrayOf<Any>(id))
            moved++
        }
        val list = saved()
        for (i in 0 until list.length()) list.getJSONObject(i).let { s ->
            val body = JSONObject()
            for (k in listOf("name", "url", "uuid", "homepage", "favicon", "tags", "country", "codec", "bitrate")) body.put(k, s.opt(k))
            if (runCatching { post("/api/radio/stations", body) }.getOrDefault(false)) {
                db.execSQL("DELETE FROM stations WHERE id = ?", arrayOf<Any>(s.getLong("id")))
                moved++
            }
        }
        return moved
    }

    // ------------------------------------------------------------ small things

    private fun get(url: String): String = web.newCall(Request.Builder().url(url).header("User-Agent", PlaybackService.USER_AGENT).build()).execute().use {
        if (!it.isSuccessful) throw java.io.IOException("HTTP ${it.code}")
        it.body?.string().orEmpty()
    }

    private fun count(sql: String) = db.rawQuery(sql, null).use { if (it.moveToFirst()) it.getInt(0) else 0 }
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
    private fun iso(ms: Long): Any = if (ms > 0) Instant.ofEpochMilli(ms).toString() else JSONObject.NULL

    private fun date(s: String?): Long = s?.let { runCatching { ZonedDateTime.parse(it.trim(), DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() }.getOrNull() } ?: 0L

    private fun seconds(s: String?): Double {
        val parts = s?.trim()?.split(':')?.mapNotNull { it.toDoubleOrNull() } ?: return 0.0
        return parts.fold(0.0) { acc, x -> acc * 60 + x }
    }

    private fun Cursor.idx(name: String) = getColumnIndex(name)
    private fun Cursor.str(name: String) = idx(name).let { if (it < 0 || isNull(it)) "" else getString(it) }
    private fun Cursor.long(name: String) = idx(name).let { if (it < 0 || isNull(it)) 0L else getLong(it) }
    private fun Cursor.int(name: String) = idx(name).let { if (it < 0 || isNull(it)) 0 else getInt(it) }
    private fun Cursor.double(name: String) = idx(name).let { if (it < 0 || isNull(it)) 0.0 else getDouble(it) }

    private class Helper(context: Context) : SQLiteOpenHelper(context, "local-shows.db", null, 1) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL("CREATE TABLE feeds(id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT DEFAULT '', author TEXT DEFAULT '', description TEXT DEFAULT '', " +
                "image TEXT DEFAULT '', link TEXT DEFAULT '', categories TEXT DEFAULT '[]', error TEXT DEFAULT '', last_checked INTEGER DEFAULT 0, " +
                "subscribed INTEGER DEFAULT 0, autoplay INTEGER DEFAULT 1, subscribed_at INTEGER DEFAULT 0)")
            db.execSQL("CREATE TABLE episodes(id INTEGER PRIMARY KEY, feed_id INTEGER, guid TEXT, title TEXT, description TEXT, published INTEGER, " +
                "duration REAL, image TEXT, audio_url TEXT, added_at INTEGER, UNIQUE(feed_id, guid))")
            db.execSQL("CREATE TABLE progress(episode_id INTEGER PRIMARY KEY, position REAL, finished INTEGER, updated_at INTEGER)")
            db.execSQL("CREATE TABLE stations(id INTEGER PRIMARY KEY, uuid TEXT, name TEXT, url TEXT, homepage TEXT, favicon TEXT, tags TEXT, country TEXT, codec TEXT, bitrate INTEGER)")
        }

        override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {}
    }

    companion object {
        // Apple Podcasts' categories, for browsing (as the server has them)
        private val GENRES = listOf(1301 to "Arts", 1321 to "Business", 1303 to "Comedy", 1304 to "Education", 1483 to "Fiction",
            1511 to "Government", 1512 to "Health & Fitness", 1487 to "History", 1305 to "Kids & Family", 1502 to "Leisure",
            1310 to "Music", 1489 to "News", 1314 to "Religion & Spirituality", 1533 to "Science", 1324 to "Society & Culture",
            1545 to "Sports", 1318 to "Technology", 1488 to "True Crime", 1309 to "TV & Film")
    }
}
