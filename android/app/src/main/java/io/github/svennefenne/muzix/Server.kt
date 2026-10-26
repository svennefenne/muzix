package io.github.svennefenne.muzix

import android.content.Context
import android.net.Uri

/** The Muzix server the app shows: its address (scheme, host and port, no path), kept between runs. */
object Server {
    private const val PREFS = "muzix"
    private const val KEY = "server"

    /** The server and its login cookie, for the player's requests (which don't go through the web view). */
    @Volatile var address = ""
    @Volatile var cookie = ""

    fun saved(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)

    fun save(context: Context, address: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, address).apply()
    }

    /** "muzix.example.com" → "https://muzix.example.com"; anything after the address is dropped. */
    fun normalize(input: String): String? {
        val text = input.trim().trimEnd('/')
        if (text.isEmpty()) return null
        val uri = Uri.parse(if ("://" in text) text else "https://$text")
        if (uri.scheme !in setOf("http", "https") || uri.host.isNullOrEmpty()) return null
        return origin(uri)
    }

    fun origin(uri: Uri): String {
        val port = if (uri.port != -1) ":${uri.port}" else ""
        return "${uri.scheme}://${uri.host}$port"
    }

    /** Whether `uri` is on the server, so it may carry the login cookie. */
    fun owns(uri: Uri): Boolean = address.isNotEmpty() && uri.host != null && origin(uri) == address
}
