package io.github.svennefenne.muzix

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import androidx.webkit.JavaScriptReplyProxy
import org.json.JSONArray
import org.json.JSONObject

/**
 * The web interface's way to the player. The page (frontend/src/player/app.ts) sends JSON
 * messages: the queue to play, and play, pause, seek, skip. The bridge answers with what plays
 * and where it is: on every change, and twice a second while the app is in view (every five
 * seconds behind the lock screen, enough for play counts and resume points).
 */
class PlayerBridge(private val context: Context, private val onCommand: (String, JSONObject) -> Unit) : Player.Listener {
    private var controller: MediaController? = null
    private var reply: JavaScriptReplyProxy? = null
    private val waiting = ArrayDeque<JSONObject>()
    private val main = Handler(Looper.getMainLooper())
    private var inView = true
    private var failures = 0                 // songs in a row that wouldn't play
    private val tick = object : Runnable {
        override fun run() {
            sendState()
            main.postDelayed(this, if (inView) 500L else 5_000L)
        }
    }

    fun connect() {
        val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
        val future = MediaController.Builder(context, token).buildAsync()
        future.addListener({
            val c = future.get()
            c.addListener(this)
            controller = c
            while (waiting.isNotEmpty()) handle(waiting.removeFirst())
            ticking(c.isPlaying)
        }, ContextCompat.getMainExecutor(context))
    }

    fun release() {
        main.removeCallbacks(tick)
        controller?.release()
        controller = null
    }

    /** Another server: its queue's links don't work any more. */
    fun clear() {
        controller?.run {
            stop()
            clearMediaItems()
        }
    }

    fun inView(visible: Boolean) {
        inView = visible
        if (visible) sendState()
    }

    /** A message from the page; `proxy` is how to answer that page. */
    fun onMessage(data: String, proxy: JavaScriptReplyProxy) {
        reply = proxy
        val msg = runCatching { JSONObject(data) }.getOrNull() ?: return
        if (controller == null) waiting.addLast(msg) else handle(msg)
    }

    private fun handle(m: JSONObject) {
        val c = controller ?: return
        when (val t = m.optString("t")) {
            "hello" -> send(JSONObject().put("t", "hello").put("version", PlaybackService.USER_AGENT)
                .put("queue", JSONArray((0 until c.mediaItemCount).map { c.getMediaItemAt(it).carried() }))
                .put("index", c.currentMediaItemIndex).put("state", state(c)))
            "load" -> {
                val items = m.getJSONArray("items").let { a -> (0 until a.length()).map { item(a.getJSONObject(it)) } }
                c.setMediaItems(items, m.optInt("index"), (m.optDouble("position", 0.0) * 1000).toLong())
                c.prepare()
                c.playWhenReady = m.optBoolean("play", true)
            }
            "upcoming" -> {
                // everything after the current song, replaced
                val items = m.getJSONArray("items").let { a -> (0 until a.length()).map { item(a.getJSONObject(it)) } }
                val at = c.currentMediaItemIndex
                if (at + 1 < c.mediaItemCount) c.removeMediaItems(at + 1, c.mediaItemCount)
                c.addMediaItems(items)
            }
            "play" -> {
                if (c.playbackState == Player.STATE_IDLE) c.prepare()
                c.play()
            }
            "pause" -> c.pause()
            "seek" -> c.seekTo(((m.optDouble("position") - offset(c.currentMediaItem)) * 1000).toLong().coerceAtLeast(0))
            "jump" -> {
                val key = m.optString("key")
                val index = (0 until c.mediaItemCount).firstOrNull { c.getMediaItemAt(it).mediaId == key } ?: return
                c.seekTo(index, 0)
                if (c.playbackState == Player.STATE_IDLE) c.prepare()
                c.play()
            }
            "repeat" -> c.repeatMode = when (m.optString("mode")) {
                "all" -> Player.REPEAT_MODE_ALL
                "one" -> Player.REPEAT_MODE_ONE
                else -> Player.REPEAT_MODE_OFF
            }
            "volume" -> c.volume = m.optDouble("value", 1.0).toFloat().coerceIn(0f, 1f)
            "speed" -> c.setPlaybackSpeed(m.optDouble("value", 1.0).toFloat().coerceIn(0.25f, 4f))
            "meta" -> {
                // a radio station's current song, for the lock screen
                val cur = c.currentMediaItem ?: return
                val md = cur.mediaMetadata.buildUpon().setTitle(m.optString("title")).setArtist(m.optString("artist")).build()
                c.replaceMediaItem(c.currentMediaItemIndex, cur.buildUpon().setMediaMetadata(md).build())
            }
            "stop" -> {
                c.stop()
                c.clearMediaItems()
            }
            else -> onCommand(t, m)
        }
    }

    /** A queue entry from the page: key, url, title, artist, album, art, duration, offset, and the page's own record. */
    private fun item(o: JSONObject): MediaItem {
        val url = Uri.parse(o.getString("url"))
        val extras = Bundle().apply {
            putDouble("offset", o.optDouble("offset", 0.0))
            putDouble("duration", o.optDouble("duration", 0.0))
            putString("muzix", o.optString("muzix"))
        }
        val md = MediaMetadata.Builder()
            .setTitle(o.optString("title"))
            .setArtist(o.optString("artist").ifEmpty { null })
            .setAlbumTitle(o.optString("album").ifEmpty { null })
            .setArtworkUri(o.optString("art").ifEmpty { null }?.let(Uri::parse))
            .setIsPlayable(true)
            .setIsBrowsable(false)
            .setExtras(extras)
            .build()
        return MediaItem.Builder()
            .setMediaId(o.getString("key"))
            .setUri(url)
            .setRequestMetadata(MediaItem.RequestMetadata.Builder().setMediaUri(url).build())
            .setMediaMetadata(md)
            .build()
    }

    private fun MediaItem.carried(): String = mediaMetadata.extras?.getString("muzix") ?: ""

    private fun offset(it: MediaItem?) = it?.mediaMetadata?.extras?.getDouble("offset") ?: 0.0

    private fun state(c: MediaController): JSONObject {
        val cur = c.currentMediaItem
        val known = if (c.duration != C.TIME_UNSET) c.duration / 1000.0 else 0.0
        return JSONObject()
            .put("t", "state")
            .put("key", cur?.mediaId ?: "")
            .put("position", offset(cur) + c.currentPosition / 1000.0)
            .put("duration", cur?.mediaMetadata?.extras?.getDouble("duration")?.takeIf { it > 0 } ?: known)
            .put("playing", c.playWhenReady && c.playbackState != Player.STATE_ENDED)
            .put("buffering", c.playWhenReady && c.playbackState == Player.STATE_BUFFERING)
            .put("seekable", c.isCurrentMediaItemSeekable)
            .put("ended", c.playbackState == Player.STATE_ENDED)
            .put("left", c.mediaItemCount - c.currentMediaItemIndex - 1)
    }

    private fun sendState() {
        controller?.let { send(state(it)) }
    }

    private fun send(msg: JSONObject) {
        runCatching { reply?.postMessage(msg.toString()) }
    }

    private fun ticking(on: Boolean) {
        main.removeCallbacks(tick)
        if (on) main.post(tick)
    }

    // ------------------------------------------------------------ the player's side

    override fun onMediaItemTransition(item: MediaItem?, reason: Int) {
        if (item == null) return
        send(JSONObject().put("t", "item").put("key", item.mediaId).put("offset", offset(item)).put("muzix", item.carried()))
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        if (isPlaying) failures = 0
        ticking(isPlaying)
        sendState()
    }

    override fun onPlaybackStateChanged(playbackState: Int) = sendState()

    override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) = sendState()

    /** A song that won't play is skipped here, so the queue goes on with the screen off; after
     * three in a row (the server is down, say) it stops trying. */
    override fun onPlayerError(error: PlaybackException) {
        val c = controller ?: return
        val cur = c.currentMediaItem
        send(JSONObject().put("t", "error").put("key", cur?.mediaId ?: "")
            .put("title", cur?.mediaMetadata?.title?.toString() ?: "").put("message", "${error.errorCodeName}: ${error.message}"))
        if (++failures < 3 && c.hasNextMediaItem()) {
            c.seekToNextMediaItem()
            c.prepare()
            c.play()
        }
    }
}
