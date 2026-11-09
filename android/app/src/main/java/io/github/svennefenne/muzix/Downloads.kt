package io.github.svennefenne.muzix

import android.app.Notification
import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.cache.CacheKeyFactory
import androidx.media3.datasource.cache.NoOpCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.offline.Download
import androidx.media3.exoplayer.offline.DownloadManager
import androidx.media3.exoplayer.offline.DownloadNotificationHelper
import androidx.media3.exoplayer.offline.DownloadRequest
import androidx.media3.exoplayer.offline.DownloadService
import androidx.media3.exoplayer.scheduler.Requirements
import androidx.media3.exoplayer.scheduler.Scheduler
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * What's downloaded to the phone: albums, playlists, audiobooks, episodes and the liked songs, each a
 * collection the page hands over (frontend/src/downloads.ts) with its songs, the page's data and its
 * cover. The songs go into a cache of their own that nothing empties (Media3's downloader, in
 * [DownloadsService]); the player reads it first, by the song's address on the server without the host
 * or the quality, so a song plays from the phone at home, outside and offline alike. Offline, the
 * pages' data and covers are the app's answers to the page (MainActivity, WebUi).
 */
object Downloads {
    private const val CHANNEL = "downloads"
    private var manager: DownloadManager? = null
    private var cache: SimpleCache? = null
    private lateinit var dir: File
    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient()
    /** Collections by id ("album:12"): {id, kind, title, subtitle, art, path, pages: {api path: data}, items: [keys]}. */
    private val collections = LinkedHashMap<String, JSONObject>()
    @Volatile var offline = false
    /** The page's answer to everything downloaded, when it changes (PlayerBridge sends it on). */
    var onChange: (() -> Unit)? = null

    @Synchronized
    fun init(context: Context) {
        if (manager != null) return
        val app = context.applicationContext
        dir = File(app.filesDir, "downloads").apply { mkdirs() }
        runCatching { JSONObject(File(dir, "collections.json").readText()) }.getOrNull()?.let { all ->
            all.keys().forEach { collections[it] = all.getJSONObject(it) }
        }
        val db = StandaloneDatabaseProvider(app)
        val c = SimpleCache(File(dir, "audio"), NoOpCacheEvictor(), db)
        cache = c
        val signedIn = ResolvingDataSource.Factory(DefaultHttpDataSource.Factory().setUserAgent(PlaybackService.USER_AGENT)
            .setConnectTimeoutMs(15_000).setReadTimeoutMs(120_000)) { spec ->
            if (!Server.owns(spec.uri)) spec
            else spec.withUri(Server.current(spec.uri)).let { if (Server.cookie.isEmpty()) it else it.withAdditionalHeaders(mapOf("Cookie" to Server.cookie)) }
        }
        manager = DownloadManager(app, db, c, signedIn, Executors.newFixedThreadPool(2)).apply {
            maxParallelDownloads = 2
            addListener(object : DownloadManager.Listener {
                override fun onDownloadChanged(m: DownloadManager, d: Download, e: Exception?) = changed()
                override fun onDownloadRemoved(m: DownloadManager, d: Download) = changed()
            })
        }
    }

    fun manager(context: Context): DownloadManager {
        init(context)
        return manager!!
    }

    fun cache(context: Context): SimpleCache {
        init(context)
        return cache!!
    }

    /** A song's place in the downloads: its address on the server, without the host or the quality (a
     * stream started part-way, with ?t=, is another thing and isn't looked for). */
    val keys = CacheKeyFactory { spec: DataSpec -> key(spec.uri) }

    private fun key(uri: Uri): String =
        if (uri.path?.startsWith("/api/") == true && uri.getQueryParameter("t") == null) "muzix:${uri.path}" else uri.toString()

    // ------------------------------------------------------------ what the page asks

    /** A collection to have on the phone (again: the liked songs change), its songs downloaded now. */
    fun add(context: Context, c: JSONObject, wifiOnly: Boolean) {
        init(context)
        val id = c.optString("id").takeIf { it.isNotEmpty() } ?: return
        val items = c.optJSONArray("items") ?: JSONArray()
        val record = JSONObject(c.toString()).apply {
            remove("items")
            put("items", JSONArray((0 until items.length()).map { items.getJSONObject(it).optString("key") }))
        }
        val before = synchronized(collections) { collections.put(id, record) }
        save()
        wifiOnly(context, wifiOnly)
        for (i in 0 until items.length()) {
            val it = items.getJSONObject(i)
            val url = Uri.parse(it.optString("url"))
            val req = DownloadRequest.Builder(it.optString("key"), url).setCustomCacheKey(key(url))
                .setData(it.toString().toByteArray()).build()
            DownloadService.sendAddDownload(context, DownloadsService::class.java, req, false)
        }
        // songs gone from it (a song no longer liked) go, unless another collection has them
        before?.optJSONArray("items")?.let { old -> forget(context, (0 until old.length()).map { old.getString(it) }) }
        c.optString("art").takeIf { it.isNotEmpty() }?.let { art -> thread { keepArt(art) } }
        changed()
    }

    /** Downloads wait for wifi, or take mobile data too (the device's setting). */
    fun wifiOnly(context: Context, on: Boolean) {
        val want = if (on) Requirements.NETWORK_UNMETERED else Requirements.NETWORK
        if (manager(context).requirements.requirements == want) return
        DownloadService.sendSetRequirements(context, DownloadsService::class.java, Requirements(want), false)
    }

    fun remove(context: Context, id: String) {
        init(context)
        val gone = synchronized(collections) { collections.remove(id) } ?: return
        save()
        val keys = gone.optJSONArray("items") ?: JSONArray()
        forget(context, (0 until keys.length()).map { keys.getString(it) })
        changed()
    }

    private fun forget(context: Context, keys: List<String>) {
        val kept = synchronized(collections) {
            collections.values.flatMap { c -> c.optJSONArray("items")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList() }.toSet()
        }
        for (k in keys.filter { it !in kept }) DownloadService.sendRemoveDownload(context, DownloadsService::class.java, k, false)
    }

    /** Everything downloaded, for the page: each collection with how far it has come and its size. */
    fun list(): JSONArray {
        val m = manager ?: return JSONArray()
        val all = synchronized(collections) { collections.values.toList() }
        return JSONArray(all.map { c ->
            val keys = c.optJSONArray("items")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()
            val got = keys.mapNotNull { runCatching { m.downloadIndex.getDownload(it) }.getOrNull() }
            JSONObject().put("id", c.optString("id")).put("kind", c.optString("kind")).put("title", c.optString("title"))
                .put("subtitle", c.optString("subtitle")).put("art", c.optString("art")).put("path", c.optString("path"))
                .put("total", keys.size).put("done", got.count { it.state == Download.STATE_COMPLETED })
                .put("failed", got.count { it.state == Download.STATE_FAILED })
                .put("bytes", got.sumOf { it.bytesDownloaded })
        })
    }

    // ------------------------------------------------------------ offline, the pages from the phone

    /** The page's sign-in state, kept so the app opens offline; and the API's answers for what's downloaded. */
    fun keepState(state: JSONObject) {
        File(dir, "state.json").writeText(state.toString())
    }

    /** The answer to a GET of the API while the server can't be reached, or null. */
    fun answer(path: String): Pair<String, ByteArray>? {
        if (!::dir.isInitialized) return null
        if (path == "/api/auth/state") {
            val state = runCatching { JSONObject(File(dir, "state.json").readText()) }.getOrNull() ?: return null
            return "application/json" to state.put("offline", true).toString().toByteArray()
        }
        if (path.startsWith("/api/art/")) {
            val f = artFile(path.substringBefore('?'))
            return if (f.exists()) "image/jpeg" to f.readBytes() else null
        }
        val page = synchronized(collections) {
            collections.values.firstNotNullOfOrNull { it.optJSONObject("pages")?.let { p -> p.opt(path) ?: p.opt(path.substringBefore('?')) } }
        }
        return page?.let { "application/json" to it.toString().toByteArray() }
    }

    private fun keepArt(art: String) {
        val path = art.substringBefore('?')
        val f = artFile(path)
        if (f.exists() || Server.address.isEmpty()) return
        runCatching {
            val req = Request.Builder().url(Server.address + art).header("User-Agent", PlaybackService.USER_AGENT)
                .apply { if (Server.cookie.isNotEmpty()) header("Cookie", Server.cookie) }.build()
            http.newCall(req).execute().use { r -> if (r.isSuccessful) r.body?.bytes()?.let(f::writeBytes) }
        }
    }

    private fun artFile(path: String): File {
        val name = MessageDigest.getInstance("SHA-256").digest(path.toByteArray()).joinToString("") { "%02x".format(it) }.take(24)
        return File(File(dir, "art").apply { mkdirs() }, name)
    }

    private fun save() {
        val all = synchronized(collections) { JSONObject().apply { collections.forEach { (k, v) -> put(k, v) } } }
        File(dir, "collections.json").writeText(all.toString())
    }

    private fun changed() {
        main.removeCallbacks(tell)
        main.postDelayed(tell, 500)
    }

    private val tell = Runnable { onChange?.invoke() }

    fun notification(context: Context, downloads: List<Download>): Notification =
        DownloadNotificationHelper(context, CHANNEL).buildProgressNotification(context, R.drawable.ic_stat_muzix, null,
            context.getString(R.string.downloading_music), downloads, 0)

    const val CHANNEL_ID = CHANNEL
}

/** Downloads in the background, with a notification while it does (Media3's DownloadService). */
class DownloadsService : DownloadService(7, DEFAULT_FOREGROUND_NOTIFICATION_UPDATE_INTERVAL,
    Downloads.CHANNEL_ID, R.string.downloads, 0) {
    override fun getDownloadManager(): DownloadManager = Downloads.manager(this)

    override fun getScheduler(): Scheduler? = null

    override fun getForegroundNotification(downloads: MutableList<Download>, notMetRequirements: Int): Notification =
        Downloads.notification(this, downloads)
}
