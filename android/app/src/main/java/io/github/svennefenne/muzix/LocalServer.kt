package io.github.svennefenne.muzix

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Log
import android.webkit.CookieManager
import fi.iki.elonen.NanoHTTPD
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.FileInputStream
import java.net.Inet4Address
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.TimeUnit

/**
 * The app's own little web server for this phone's library, on 127.0.0.1: the web interface that comes
 * with the app (WebUi.kt's files), and this phone's library as the server's requests (LocalApi). With a
 * server too, what's the account's stays the server's (podcasts, radio, the account's devices), passed
 * on with the app's login there. Only the app may use it (other apps can reach 127.0.0.1): the web view
 * and the player carry a secret, new for each run. A Cast speaker gets the songs from the phone's address
 * on the wifi instead, by their signed links only (forSpeakers).
 */
class LocalServer(private val context: Context, private val api: LocalApi, port: Int) : NanoHTTPD("127.0.0.1", port) {
    val secret: String = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(24).also { SecureRandom().nextBytes(it) })
    val origin get() = "http://127.0.0.1:$listeningPort"
    /** The server whose account this is, if there's one: what's the account's goes there. */
    @Volatile var server = ""
    private val http = OkHttpClient.Builder().readTimeout(0, TimeUnit.MILLISECONDS).build()

    override fun serve(session: IHTTPSession): Response {
        val path = session.uri
        if (!path.startsWith("/api/")) return page(path)
        if (!allowed(session)) return newFixedLengthResponse(Response.Status.FORBIDDEN, MIME_PLAINTEXT, "Only the Muzix app may use this")
        val method = session.method.name
        val body = if (method in setOf("POST", "PUT", "PATCH")) read(session) else ""
        return try {
            if (server.isNotEmpty() && ACCOUNT.any { path.startsWith(it) }) return account(session, method, body)
            val query = session.parameters.mapValues { it.value.firstOrNull().orEmpty() }
            val a = api.handle(method, path, query, body)
            // the sidebar's podcasts and stations are the account's
            if (path == "/api/sidebar" && a is LocalApi.Answer.Json && a.body is JSONObject) return json(a.status, mergeSidebar(a.body))
            answer(session, a)
        } catch (e: Exception) {
            Log.w("MuzixLocal", "$method $path failed", e)
            json(500, JSONObject().put("detail", e.message ?: e.javaClass.simpleName))
        }
    }

    private fun allowed(s: IHTTPSession): Boolean {
        val cookie = s.headers["cookie"].orEmpty().split(';').map { it.trim() }.firstOrNull { it.startsWith("$COOKIE=") }?.substringAfter('=')
        return (cookie ?: s.headers[HEADER]) == secret
    }

    private fun read(s: IHTTPSession): String {
        val n = s.headers["content-length"]?.toIntOrNull() ?: return ""
        val buf = ByteArray(n)
        var at = 0
        while (at < n) {
            val got = s.inputStream.read(buf, at, n - at)
            if (got < 0) break
            at += got
        }
        return String(buf, 0, at, Charsets.UTF_8)
    }

    /** The interface's files, and its page (index.html) for every other address, as the server answers. */
    private fun page(path: String): Response {
        val files = context.assets
        val name = path.trimStart('/').takeIf { it.isNotEmpty() && !it.contains("..") && runCatching { files.open("web/$it").close() }.isSuccess } ?: "index.html"
        val type = WEB_TYPES[name.substringAfterLast('.')] ?: "application/octet-stream"
        return newChunkedResponse(Response.Status.OK, type, files.open("web/$name")).apply { addHeader("Cache-Control", "no-cache") }
    }

    private fun json(status: Int, body: Any): Response =
        newFixedLengthResponse(Response.Status.lookup(status) ?: Response.Status.INTERNAL_ERROR, "application/json", body.toString())

    private fun answer(s: IHTTPSession, a: LocalApi.Answer): Response = when (a) {
        is LocalApi.Answer.Json -> json(a.status, a.body)
        is LocalApi.Answer.Picture -> newFixedLengthResponse(Response.Status.OK, "image/jpeg", FileInputStream(a.file), a.file.length())
            .apply { addHeader("Cache-Control", "max-age=86400") }
        is LocalApi.Answer.Song -> song(s, a)
        is LocalApi.Answer.Redirect -> newFixedLengthResponse(Response.Status.REDIRECT, MIME_PLAINTEXT, "").apply { addHeader("Location", a.url) }
    }

    /** A song's file, from where it is (the folder the app may read), a range of it when asked. */
    private fun song(s: IHTTPSession, a: LocalApi.Answer.Song): Response {
        val fd = context.contentResolver.openAssetFileDescriptor(a.uri, "r") ?: return json(404, JSONObject().put("detail", "Gone"))
        val size = fd.length.takeIf { it >= 0 } ?: fd.parcelFileDescriptor.statSize
        val range = Regex("""bytes=(\d*)-(\d*)""").find(s.headers["range"].orEmpty())
        val input = FileInputStream(fd.fileDescriptor)
        input.channel.position(fd.startOffset)
        if (range == null || size <= 0) {
            return newFixedLengthResponse(Response.Status.OK, a.mime, input, size).apply { addHeader("Accept-Ranges", "bytes") }
        }
        val from = range.groupValues[1].toLongOrNull() ?: 0L
        val to = (range.groupValues[2].toLongOrNull() ?: (size - 1)).coerceAtMost(size - 1)
        if (from >= size) return newFixedLengthResponse(Response.Status.RANGE_NOT_SATISFIABLE, MIME_PLAINTEXT, "")
        input.channel.position(fd.startOffset + from)
        return newFixedLengthResponse(Response.Status.PARTIAL_CONTENT, a.mime, input, to - from + 1).apply {
            addHeader("Accept-Ranges", "bytes")
            addHeader("Content-Range", "bytes $from-$to/$size")
        }
    }

    // ------------------------------------------------------------ Cast speakers on the wifi

    private var lan: NanoHTTPD? = null

    /** Where a Cast speaker gets this library: the phone's address on the wifi (listened on from the first
     * time, again when the address changes), or "" with no wifi. */
    @Synchronized
    fun forSpeakers(): String {
        val ip = wifiAddress() ?: return ""
        lan?.let { if (it.hostname == ip && it.isAlive) return "http://$ip:${it.listeningPort}" else it.stop() }
        val srv = object : NanoHTTPD(ip, 0) {
            override fun serve(session: IHTTPSession): Response = speaker(session)
        }
        srv.start(SOCKET_READ_TIMEOUT, true)
        lan = srv
        Log.i("MuzixLocal", "Cast speakers get this phone's music from http://$ip:${srv.listeningPort}")
        return "http://$ip:${srv.listeningPort}"
    }

    /** What a speaker may have: the audio, by its signed links (the account's episodes and stations passed on
     * to the server with the app's login), nothing else of the library. */
    private fun speaker(s: IHTTPSession): Response {
        val path = s.uri
        val signed = SPEAKER.matches(path) && s.parameters["ct"]?.firstOrNull() == CAST_TOKEN
        if (!signed || (s.method != Method.GET && s.method != Method.HEAD)) {
            return newFixedLengthResponse(Response.Status.FORBIDDEN, MIME_PLAINTEXT, "Not for speakers")
        }
        return try {
            if (server.isNotEmpty() && ACCOUNT.any { path.startsWith(it) }) return account(s, "GET", "")
            answer(s, api.handle("GET", path, s.parameters.mapValues { it.value.firstOrNull().orEmpty() }, ""))
        } catch (e: Exception) {
            Log.w("MuzixLocal", "A speaker's $path failed", e)
            newFixedLengthResponse(Response.Status.INTERNAL_ERROR, MIME_PLAINTEXT, "")
        }
    }

    private fun wifiAddress(): String? {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
        @Suppress("DEPRECATION")
        return cm.allNetworks.firstNotNullOfOrNull { n ->
            val caps = cm.getNetworkCapabilities(n)
            if (caps == null || !(caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))) null
            else cm.getLinkProperties(n)?.linkAddresses?.map { it.address }?.firstOrNull { it is Inet4Address && it.isSiteLocalAddress }?.hostAddress
        }
    }

    override fun stop() {
        lan?.stop()
        super.stop()
    }

    // ------------------------------------------------------------ the account's, on the server

    private fun account(s: IHTTPSession, method: String, body: String): Response {
        val url = server + s.uri + (s.queryParameterString?.let { "?$it" } ?: "")
        val req = Request.Builder().url(url).header("User-Agent", PlaybackService.USER_AGENT)
            .apply { CookieManager.getInstance().getCookie(server)?.let { header("Cookie", it) } }
            .apply { s.headers["range"]?.let { header("Range", it) } }
            .method(method, if (method in setOf("POST", "PUT", "PATCH")) body.toRequestBody((s.headers["content-type"] ?: "application/json").toMediaTypeOrNull()) else null)
            .build()
        return try {
            val r = http.newCall(req).execute()
            val type = r.header("Content-Type") ?: "application/octet-stream"
            val stream = r.body?.byteStream() ?: return newFixedLengthResponse(Response.Status.lookup(r.code) ?: Response.Status.OK, type, "")
            newChunkedResponse(Response.Status.lookup(r.code) ?: Response.Status.OK, type, stream).apply {
                listOf("Content-Range", "Accept-Ranges", "Cache-Control").forEach { h -> r.header(h)?.let { addHeader(h, it) } }
            }
        } catch (e: Exception) {
            json(502, JSONObject().put("detail", "The server can't be reached"))
        }
    }

    /** The account's part of a page that's mostly this phone's: the sidebar's podcasts and stations. */
    fun mergeSidebar(local: JSONObject): JSONObject = runCatching {
        if (server.isEmpty()) return local
        val req = Request.Builder().url("$server/api/sidebar").header("User-Agent", PlaybackService.USER_AGENT)
            .apply { CookieManager.getInstance().getCookie(server)?.let { header("Cookie", it) } }.build()
        http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) return local
            val theirs = JSONObject(r.body?.string().orEmpty())
            local.put("podcasts", theirs.optJSONArray("podcasts") ?: JSONArray()).put("stations", theirs.optJSONArray("stations") ?: JSONArray())
        }
    }.getOrDefault(local)

    companion object {
        /** The one running, for as long as the app's process lives (the player plays from it in the background). */
        @Volatile var running: LocalServer? = null
        const val COOKIE = "muzix_local"
        const val HEADER = "x-muzix-local"
        /** The signature in a Cast speaker's links to this library (GET /api/cast/token, LocalApi): new for each run. */
        val CAST_TOKEN: String = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(18).also { SecureRandom().nextBytes(it) })
        private val SPEAKER = Regex("/api/(stream/\\d+|podcasts/episodes/\\d+/stream|radio/play)")

        /** A link for a Cast speaker: one to this library (127.0.0.1, which the speaker can't reach) on the
         * phone's address on the wifi; any other as it is. */
        fun speakerLink(url: String): String {
            val srv = running ?: return url
            if (!url.startsWith(srv.origin + "/")) return url
            val lan = srv.forSpeakers().ifEmpty { return url }
            return lan + url.substring(srv.origin.length)
        }
        // the account's, on the server, even while the library is this phone's (docs/app-plan.md)
        val ACCOUNT = arrayOf("/api/podcasts", "/api/radio", "/api/me/devices")
        private val WEB_TYPES = mapOf("html" to "text/html", "js" to "text/javascript", "css" to "text/css", "svg" to "image/svg+xml",
            "png" to "image/png", "woff2" to "font/woff2", "json" to "application/json", "ico" to "image/x-icon")
    }
}
