package io.github.svennefenne.muzix

import android.media.AudioManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

/**
 * The app as one of the account's devices (Muzix Connect, backend/muzix/api/connect.py) while its
 * page can't be: out of view a few minutes, Android's web view freezes the page, which then
 * neither tells what plays nor hears the other devices. So while the app is out of view this keeps
 * the device's connection itself, under the page's id: it tells what the player plays and does what
 * the others ask (play, pause, skip, seek, volume, a new queue). Back in view, the page connects
 * again and takes over (frontend/src/player/connect.ts); it hears what changed meanwhile.
 */
class ConnectLink(private val audio: AudioManager, private val player: () -> Player?, private val toPage: (JSONObject) -> Unit) :
    Player.Listener {
    private val main = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder().pingInterval(25, TimeUnit.SECONDS).build()
    private var ws: WebSocket? = null
    private var wanted = false
    private var retry = 0
    private var sentQueue = -1          // the queue's version the others have
    private var queueVersion = 0
    /** The page's own device (its hello) and its sound settings, for when it's frozen. */
    var device: JSONObject? = null
    var quality = "original"
    var radioBuffer = 0
    /** A queue came from another device while the page was away: it's told once it's back. */
    private var changed = false
    private val beat = object : Runnable {
        override fun run() {
            if (player()?.isPlaying == true) publish()
            main.postDelayed(this, 10_000L)
        }
    }

    /** Out of view: this keeps the device's connection. */
    fun start() {
        val dev = device ?: return
        if (wanted || Server.address.isEmpty() || dev.optString("id").isEmpty()) return
        wanted = true
        player()?.addListener(this)
        open()
        main.postDelayed(beat, 10_000L)
    }

    /** Back in view: the page takes over; what changed meanwhile, told to it. */
    fun stop() {
        if (!wanted) return
        wanted = false
        main.removeCallbacks(beat)
        player()?.removeListener(this)
        ws?.close(1000, "the page is back")
        ws = null
        val p = player()
        if (changed && p != null) {
            changed = false
            toPage(JSONObject().put("t", "queue").put("index", p.currentMediaItemIndex)
                .put("queue", JSONArray((0 until p.mediaItemCount).map { carried(p.getMediaItemAt(it)) ?: "" })))
        }
    }

    private fun open() {
        val url = Server.address.replaceFirst("http", "ws") + "/api/connect"
        val req = Request.Builder().url(url).header("User-Agent", PlaybackService.USER_AGENT)
            .apply { if (Server.cookie.isNotEmpty()) header("Cookie", Server.cookie) }.build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                main.post {
                    if (ws !== webSocket) return@post
                    retry = 0
                    sentQueue = -1
                    webSocket.send(device.toString())
                    publish()
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                main.post { if (ws === webSocket) runCatching { onMessage(JSONObject(text)) } }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = again(webSocket)

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = again(webSocket)
        })
    }

    private fun again(webSocket: WebSocket) {
        main.post {
            if (ws !== webSocket || !wanted) return@post
            ws = null
            val wait = listOf(1, 2, 5, 10, 30)[retry.coerceAtMost(4)]
            retry++
            main.postDelayed({ if (wanted && ws == null) open() }, wait * 1000L)
        }
    }

    // ------------------------------------------------------------ what plays, for the others

    override fun onTimelineChanged(timeline: androidx.media3.common.Timeline, reason: Int) {
        queueVersion++
    }

    override fun onEvents(p: Player, events: Player.Events) {
        if (events.containsAny(Player.EVENT_MEDIA_ITEM_TRANSITION, Player.EVENT_IS_PLAYING_CHANGED,
                Player.EVENT_PLAYBACK_STATE_CHANGED, Player.EVENT_TIMELINE_CHANGED, Player.EVENT_POSITION_DISCONTINUITY,
                Player.EVENT_REPEAT_MODE_CHANGED, Player.EVENT_VOLUME_CHANGED)) publish()
    }

    private fun publish() {
        val p = player() ?: return
        val socket = ws ?: return
        if (p.mediaItemCount == 0 || p.currentMediaItemIndex < 0) return
        val cur = p.currentMediaItem
        val extras = cur?.mediaMetadata?.extras
        val known = if (p.duration != C.TIME_UNSET) p.duration / 1000.0 else 0.0
        val st = JSONObject()
            .put("index", p.currentMediaItemIndex)
            .put("position", (extras?.getDouble("offset") ?: 0.0) + p.currentPosition / 1000.0)
            .put("duration", extras?.getDouble("duration")?.takeIf { it > 0 } ?: known)
            .put("playing", p.playWhenReady && p.playbackState != Player.STATE_ENDED && p.playbackState != Player.STATE_IDLE)
            .put("buffering", p.playWhenReady && p.playbackState == Player.STATE_BUFFERING)
            .put("shuffle", false)
            .put("repeat", when (p.repeatMode) { Player.REPEAT_MODE_ALL -> "all"; Player.REPEAT_MODE_ONE -> "one"; else -> "off" })
            .put("volume", mediaVolume())
            .put("muted", p.volume == 0f)
        if (sentQueue != queueVersion) {
            st.put("queue", JSONArray((0 until p.mediaItemCount).mapNotNull { carried(p.getMediaItemAt(it))?.let(::JSONObject) }))
            sentQueue = queueVersion
        }
        socket.send(JSONObject().put("t", "state").put("state", st).toString())
    }

    // ------------------------------------------------------------ what the others ask

    private fun onMessage(m: JSONObject) {
        val p = player() ?: return
        when (m.optString("t")) {
            "command" -> command(p, m)
            "takeover" -> m.optJSONObject("state")?.let { st ->
                load(p, st.optJSONArray("queue") ?: return, st.optInt("index"), st.optDouble("position", 0.0), m.optBoolean("play", true))
            }
            "yield" -> {
                p.stop()
                p.clearMediaItems()
            }
        }
    }

    private fun command(p: Player, m: JSONObject) {
        when (m.optString("cmd")) {
            "play" -> {
                if (p.playbackState == Player.STATE_IDLE) p.prepare()
                p.play()
            }
            "pause" -> p.pause()
            "next" -> if (p.hasNextMediaItem()) p.seekToNextMediaItem()
            "prev" -> if ((p.currentPosition > 4_000 && !m.optBoolean("always")) || !p.hasPreviousMediaItem()) p.seekTo(0)
                else p.seekToPreviousMediaItem()
            "seek" -> {
                val offset = p.currentMediaItem?.mediaMetadata?.extras?.getDouble("offset") ?: 0.0
                if (p.isCurrentMediaItemSeekable) p.seekTo(((m.optDouble("position") - offset) * 1000).toLong().coerceAtLeast(0))
            }
            "jump" -> {
                val key = m.optString("key")
                val i = (0 until p.mediaItemCount).firstOrNull { p.getMediaItemAt(it).mediaId == key } ?: return
                p.seekTo(i, 0)
                p.play()
            }
            "volume" -> {
                val muted = m.optBoolean("muted")
                p.volume = if (muted) 0f else 1f
                if (!muted) {
                    val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                    audio.setStreamVolume(AudioManager.STREAM_MUSIC, (m.optDouble("volume").coerceIn(0.0, 1.0) * max).roundToInt(), 0)
                }
            }
            "repeat" -> p.repeatMode = when (m.optString("mode")) {
                "all" -> Player.REPEAT_MODE_ALL
                "one" -> Player.REPEAT_MODE_ONE
                else -> Player.REPEAT_MODE_OFF
            }
            "load" -> load(p, m.optJSONArray("queue") ?: return, m.optInt("index"), m.optDouble("position", 0.0), m.optBoolean("play", true))
            "queue" -> {
                // the queue changed there: what comes after what plays here, replaced
                val queue = m.optJSONArray("queue") ?: return
                val key = p.currentMediaItem?.mediaId
                val at = (0 until queue.length()).firstOrNull { queue.optJSONObject(it)?.optString("key") == key } ?: return
                if (p.currentMediaItemIndex + 1 < p.mediaItemCount) p.removeMediaItems(p.currentMediaItemIndex + 1, p.mediaItemCount)
                p.addMediaItems(items(queue, at + 1, 0.0))
                changed = true
            }
            "stop" -> {
                p.stop()
                p.clearMediaItems()
            }
        }
    }

    /** A queue from another device, played here from `index`, `at` seconds in. */
    private fun load(p: Player, queue: JSONArray, index: Int, at: Double, play: Boolean) {
        val first = queue.optJSONObject(index) ?: return
        val direct = direct(first)
        val list = items(queue, index, if (direct) 0.0 else at)
        if (list.isEmpty()) return
        Progress.asked = list[0].mediaId
        p.setMediaItems(list, 0, if (direct) (at * 1000).toLong() else 0L)
        p.prepare()
        p.playWhenReady = play
        changed = true
    }

    /** The playable entries from `from` on, as the page would hand them over (frontend/src/player/app.ts). */
    private fun items(queue: JSONArray, from: Int, startAt: Double): List<MediaItem> =
        (from until queue.length()).mapNotNull { queue.optJSONObject(it) }.take(WINDOW)
            .mapIndexed { i, it -> Items.fromJson(entry(it, if (i == 0) startAt else 0.0)) }

    /** An entry from another device (or autoplay) as the page would hand it over, in this phone's sound quality. */
    fun entry(it: JSONObject, from: Double = 0.0): JSONObject {
        val radio = it.optString("kind") == "radio"
        val url = Uri.parse(Server.address + it.optString("src")).buildUpon().apply {
            if (radio) { if (radioBuffer > 0) appendQueryParameter("buffer", radioBuffer.toString()) }
            else if (quality != "original") appendQueryParameter("q", quality)
            if (from > 0.5) appendQueryParameter("t", "%.1f".format(java.util.Locale.ROOT, from))
        }.build().toString()
        val art = it.optString("art").takeIf { a -> a.isNotEmpty() && a != "null" }?.let { a ->
            val sized = if (a.startsWith("/api/art/")) a + (if ("?" in a) "&" else "?") + "s=600" else a
            if (sized.startsWith("/")) Server.address + sized else sized
        } ?: ""
        return JSONObject().put("key", it.optString("key")).put("url", url).put("title", it.optString("title"))
            .put("artist", it.optString("artist")).put("album", it.optString("album")).put("art", art)
            .put("duration", if (radio) 0.0 else it.optDouble("duration", 0.0)).put("offset", from)
            .put("resume", it.optDouble("resume", 0.0)).put("muzix", it.toString()).put("live", radio)
    }

    /** Whether the app gets the file as it is (and seeks in it) or a converted stream started at a time. */
    private fun direct(it: JSONObject): Boolean {
        val kind = it.optString("kind")
        if (kind == "episode") return true
        if (quality != "original" || kind == "radio") return false
        return if (it.has("castNative")) it.optBoolean("castNative") else kind == "book"
    }

    private fun carried(it: MediaItem): String? = it.mediaMetadata.extras?.getString("muzix")?.takeIf { s -> s.isNotEmpty() }

    private fun mediaVolume(): Double =
        audio.getStreamVolume(AudioManager.STREAM_MUSIC).toDouble() / audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)

    companion object {
        private const val WINDOW = 100      // entries handed to the player at a time, as the page does
    }
}
