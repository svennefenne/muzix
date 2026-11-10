package io.github.svennefenne.muzix

import android.content.Context
import android.net.Uri
import java.net.InetAddress

/**
 * The Muzix server the app shows, kept between runs: its addresses (scheme, host and port, no path),
 * the one at home on the local network and the outside one (the server's public address), and the
 * version of its API (whether the app's own web interface fits it: WebUi.kt). The app uses the
 * address at home while it answers, and the outside one otherwise.
 */
object Server {
    private const val PREFS = "muzix"
    private const val KEY = "server"        // the address in use
    private const val HOME = "home"
    private const val AWAY = "away"
    private const val API = "api"

    /** The address in use and the login cookie, for the player's requests (which don't go through the web view). */
    @Volatile var address = ""
    @Volatile var cookie = ""
    @Volatile var api = -1      // -1: not known yet
    @Volatile var home = ""
    @Volatile var away = ""

    fun saved(context: Context): String? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        api = prefs.getInt(API, -1)
        val last = prefs.getString(KEY, null)
        // an app from before it knew two addresses: the one it has is one of them
        home = prefs.getString(HOME, null) ?: last?.takeIf(::local) ?: ""
        away = prefs.getString(AWAY, null) ?: last?.takeUnless(::local) ?: ""
        return last
    }

    /** A server connected to from `typed`, which tells its outside address (`outside`, may be empty). */
    fun connected(context: Context, typed: String, outside: String) {
        home = if (local(typed)) typed else ""
        away = normalize(outside)?.takeIf { it != typed } ?: if (local(typed)) "" else typed
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(HOME, home).putString(AWAY, away).apply()
    }

    /** The address in use, and its API's version. */
    fun save(context: Context, address: String, api: Int) {
        this.address = address
        this.api = api
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, address).putInt(API, api).apply()
    }

    /** The library the app shows: the server's, or this phone's music (LocalLibrary). */
    @Volatile var local = false

    fun library(context: Context): String = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("library", "server")!!

    fun setLibrary(context: Context, which: String) {
        local = which == "local"
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("library", which).apply()
    }

    /** The server's address last used (also while the library is this phone's: the account is there). */
    fun last(context: Context): String = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null).orEmpty()

    /** Where to look for the server, the one at home first. */
    fun addresses(): List<String> = listOf(home, away).filter { it.isNotEmpty() }.distinct()

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

    /** Whether `uri` is on the server (at either address), so it may carry the login cookie. */
    fun owns(uri: Uri): Boolean = uri.host != null && origin(uri).let { it == address || it == home || it == away } && address.isNotEmpty()

    /** `uri` on the server's address in use: a song queued at home plays on from outside, and back. */
    fun current(uri: Uri): Uri {
        if (!owns(uri) || origin(uri) == address) return uri
        val now = Uri.parse(address)
        return uri.buildUpon().scheme(now.scheme).encodedAuthority(now.encodedAuthority).build()
    }

    /** An address on the local network: a private or link-local IP, or a name that only means something there. */
    private fun local(address: String): Boolean {
        val host = Uri.parse(address).host ?: return false
        if (!host.contains('.') || host.endsWith(".local") || host.endsWith(".lan") || host.endsWith(".home.arpa")) return true
        if (!host.all { it.isDigit() || it == '.' || it == ':' || it in 'a'..'f' || it in 'A'..'F' }) return false
        return runCatching { InetAddress.getByName(host) }.getOrNull()
            ?.let { it.isSiteLocalAddress || it.isLinkLocalAddress || it.isLoopbackAddress } ?: false
    }
}
