package io.github.svennefenne.muzix

import android.content.Context
import android.net.Uri
import android.webkit.WebResourceResponse

/**
 * The web interface that comes with the app (the frontend's build, in the APK's assets/web), served
 * on the server's own address: the web view's requests there that aren't for the API get the app's
 * files, so the page keeps its links as they are, its login cookie and the Connect socket. A server
 * whose API this interface doesn't know (older, or newer than the app) shows its own, as before.
 */
object WebUi {
    /** The server API versions this interface works with (API_VERSION in backend/muzix/__init__.py). */
    private const val OLDEST_API = 1
    private const val NEWEST_API = 1

    fun fits(api: Int) = api in OLDEST_API..NEWEST_API

    /** Why a server shows its own interface: the app or the server to update; null while its version isn't known. */
    fun why(api: Int): String? = when {
        api < 0 || fits(api) -> null
        api > NEWEST_API -> "The server is newer than this app: update the app (until then, the server's own pages show)"
        else -> "The server is older than this app: update Muzix on the server (until then, its own pages show)"
    }

    @Volatile private var files: Set<String>? = null

    /** The app's answer for `uri` on the server: a file of the build, or the page (index.html) for any
     * other address, as the server answers; null for the API, which the server answers. */
    fun response(context: Context, uri: Uri): WebResourceResponse? {
        val path = uri.path.orEmpty()
        if (path.startsWith("/api/") || path == "/manifest.webmanifest") return null       // the server's own
        val name = path.trimStart('/').takeIf { it in files(context) } ?: "index.html"
        val type = TYPES[name.substringAfterLast('.')] ?: "application/octet-stream"
        val text = type.startsWith("text/") || type == "image/svg+xml"
        return WebResourceResponse(type, if (text) "utf-8" else null, context.assets.open("web/$name")).apply {
            responseHeaders = mapOf("Cache-Control" to "no-cache")
        }
    }

    private fun files(context: Context): Set<String> = files ?: buildSet {
        fun walk(dir: String) {
            for (entry in context.assets.list(dir).orEmpty()) {
                val path = "$dir/$entry"
                if (context.assets.list(path).isNullOrEmpty()) add(path.removePrefix("web/")) else walk(path)
            }
        }
        walk("web")
    }.also { files = it }

    private val TYPES = mapOf(
        "html" to "text/html", "js" to "text/javascript", "css" to "text/css", "svg" to "image/svg+xml",
        "png" to "image/png", "jpg" to "image/jpeg", "webp" to "image/webp", "woff2" to "font/woff2",
        "json" to "application/json", "webmanifest" to "application/manifest+json", "ico" to "image/x-icon",
    )
}
