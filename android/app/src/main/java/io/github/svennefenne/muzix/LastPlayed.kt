package io.github.svennefenne.muzix

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import org.json.JSONArray
import org.json.JSONObject

/**
 * What the phone played last, for the next time the app starts with nothing to play: the songs the
 * player had (as the page described them), which one played and where in it. The page shows them
 * paused there, and Play carries on (frontend/src/player/engine.ts, restoreLast). It's kept here, as
 * the page sleeps with the screen off while the player plays on: saved when the song changes, on
 * pause, every 15 seconds while it plays and when the service ends; a queue cleared is forgotten.
 * It belongs to the library it played from (this phone's, or the server's at either address).
 */
class LastPlayed(private val context: Context, private val player: Player) : Player.Listener {
    private val main = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            save()
            main.postDelayed(this, EVERY)
        }
    }

    fun start() {
        player.addListener(this)
        if (player.isPlaying) main.postDelayed(tick, EVERY)
    }

    fun stop() {
        main.removeCallbacks(tick)
        player.removeListener(this)
        save()
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        main.removeCallbacks(tick)
        if (isPlaying) main.postDelayed(tick, EVERY)
        save()
    }

    override fun onMediaItemTransition(item: MediaItem?, reason: Int) = save()

    override fun onTimelineChanged(timeline: Timeline, reason: Int) {
        if (timeline.isEmpty && reason == Player.TIMELINE_CHANGE_REASON_PLAYLIST_CHANGED) forget(context) else save()
    }

    private fun save() {
        val n = player.mediaItemCount
        val cur = player.currentMediaItem ?: return
        if (n == 0) return
        val offset = cur.mediaMetadata.extras?.getDouble("offset") ?: 0.0
        val last = JSONObject()
            .put("queue", JSONArray((0 until n).map { player.getMediaItemAt(it).mediaMetadata.extras?.getString("muzix") ?: "" }))
            .put("index", player.currentMediaItemIndex)
            .put("position", offset + player.currentPosition / 1000.0)
            .put("at", System.currentTimeMillis())
            .put("library", library())
        prefs(context).edit().putString(KEY, last.toString()).apply()
    }

    companion object {
        private const val KEY = "last"
        private const val EVERY = 15_000L

        private fun prefs(c: Context) = c.getSharedPreferences("muzix-last", Context.MODE_PRIVATE)

        private fun library() = if (Server.local) "local" else "${Server.home}|${Server.away}"

        /** What played last, if it was in the library shown now. */
        fun read(c: Context): JSONObject? = runCatching { JSONObject(prefs(c).getString(KEY, null) ?: return null) }.getOrNull()
            ?.takeIf { it.optString("library") == library() }

        fun forget(c: Context) = prefs(c).edit().remove(KEY).apply()
    }
}
