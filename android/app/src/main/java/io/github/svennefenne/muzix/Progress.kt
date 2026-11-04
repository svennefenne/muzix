package io.github.svennefenne.muzix

import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Where episodes and audiobooks got to, saved to the server by the app itself: the page in the
 * web view sleeps while the screen is off, and the player plays on. Saved every 15 seconds while
 * one plays, when it's paused, left or played to its end, and when the service ends (the app's
 * card closed). One the player goes on to by itself, or by the lock screen's next, carries on
 * where it was left: as the page handed it over (frontend/src/player/app.ts), or as left here since.
 */
class Progress(private val player: Player) : Player.Listener {
    private val main = Handler(Looper.getMainLooper())
    private val out = Executors.newSingleThreadExecutor()   // one save after another, so the last one stays
    private var item: MediaItem? = null      // the episode or audiobook part playing
    private var about: JSONObject? = null    // the page's description of it
    private var at = 0.0                     // where it got to, in seconds
    private var saved = 0L
    private val left = HashMap<String, Double>()   // the ones left since the page handed the queue over
    private val tick = object : Runnable {
        override fun run() {
            note()
            if (System.currentTimeMillis() - saved >= EVERY) save(false)
            main.postDelayed(this, 1_000L)
        }
    }

    fun start() {
        player.addListener(this)
        follow(player.currentMediaItem, Player.MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED)
        if (player.isPlaying) main.postDelayed(tick, 1_000L)
    }

    /** The service ends: the place, saved before it goes. */
    fun stop() {
        main.removeCallbacks(tick)
        player.removeListener(this)
        note()
        save(false)
        out.shutdown()
        runCatching { out.awaitTermination(3, TimeUnit.SECONDS) }
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        main.removeCallbacks(tick)
        if (isPlaying) {
            main.postDelayed(tick, 1_000L)
        } else {
            note()
            save(player.playbackState == Player.STATE_ENDED)
        }
    }

    override fun onMediaItemTransition(next: MediaItem?, reason: Int) {
        val was = item
        val end = about?.optDouble("duration", 0.0) ?: 0.0
        if (was != null && was.mediaId != next?.mediaId) {
            // played to its end, or left in its last seconds: heard
            val done = reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO || (end > 0 && at > end - 15)
            left[was.mediaId] = if (done) 0.0 else at
            save(done, told = true)
        }
        follow(next, reason)
    }

    private fun follow(next: MediaItem?, reason: Int) {
        val changed = reason == Player.MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED
        if (changed) left.clear()           // a queue from the page, with its places
        val info = next?.let(::spoken)
        item = if (info != null) next else null
        about = info
        val page = asked == next?.mediaId
        asked = ""
        if (next == null || info == null) return
        val offset = offset(next)
        val resume = left[next.mediaId] ?: Items.json(next).optDouble("resume", 0.0)
        if (!changed && !page && offset == 0.0 && resume > 0.5 && player.currentPosition < 500) {
            player.seekTo((resume * 1000).toLong())
        }
        at = offset + player.currentPosition / 1000.0
    }

    private fun note() {
        val cur = player.currentMediaItem ?: return
        if (cur.mediaId == item?.mediaId) at = offset(cur) + player.currentPosition / 1000.0
    }

    /** The place saved; with `told`, or once heard, the page hears of it too (its lists show it). */
    private fun save(done: Boolean, told: Boolean = false) {
        val info = about ?: return
        val key = item?.mediaId ?: return
        saved = System.currentTimeMillis()
        val server = Server.address
        val cookie = Server.cookie
        if (server.isEmpty()) return
        val end = info.optDouble("duration", 0.0)
        val pos = if (done && end > 0) end else at
        val (path, body) = if (info.optString("kind") == "episode") {
            "/api/podcasts/episodes/${info.optLong("id")}/progress" to JSONObject().put("position", pos).put("finished", done)
        } else {
            val book = info.optLong("bookId").takeIf { it > 0 } ?: return
            "/api/books/$book/progress" to JSONObject()
                .put("position", info.optDouble("partOffset", 0.0) + pos).put("finished", done && lastPart(info))
        }
        out.execute {
            val ok = runCatching {
                val conn = URL(server + path).openConnection() as HttpURLConnection
                try {
                    conn.requestMethod = "PUT"
                    conn.connectTimeout = 10_000
                    conn.readTimeout = 10_000
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/json")
                    conn.setRequestProperty("User-Agent", PlaybackService.USER_AGENT)
                    if (cookie.isNotEmpty()) conn.setRequestProperty("Cookie", cookie)
                    conn.outputStream.use { it.write(body.toString().toByteArray()) }
                    conn.responseCode in 200..299
                } finally {
                    conn.disconnect()
                }
            }.getOrDefault(false)
            if (ok && (told || done)) main.post { onSaved?.invoke(key) }
        }
    }

    /** Whether no later part of the same audiobook is in the queue: its end is the book's. */
    private fun lastPart(info: JSONObject): Boolean {
        val book = info.optLong("bookId")
        val part = info.optDouble("partOffset", 0.0)
        return (0 until player.mediaItemCount).none { i ->
            val o = spoken(player.getMediaItemAt(i))
            o != null && o.optLong("bookId") == book && o.optDouble("partOffset", 0.0) > part
        }
    }

    private fun spoken(it: MediaItem): JSONObject? =
        runCatching { JSONObject(it.mediaMetadata.extras?.getString("muzix") ?: "") }.getOrNull()
            ?.takeIf { o -> o.optString("kind") in SPOKEN }

    private fun offset(it: MediaItem) = it.mediaMetadata.extras?.getDouble("offset") ?: 0.0

    companion object {
        private const val EVERY = 15_000L
        private val SPOKEN = setOf("episode", "book")

        /** The item the page just asked to play from its start (PlayerBridge's jump): it isn't carried on in. */
        @Volatile var asked = ""

        /** Told of each save that left an item or heard it to the end, for the page. */
        var onSaved: ((String) -> Unit)? = null
    }
}
