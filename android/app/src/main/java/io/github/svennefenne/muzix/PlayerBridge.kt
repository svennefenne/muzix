package io.github.svennefenne.muzix

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.core.content.ContextCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import androidx.webkit.JavaScriptReplyProxy
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.roundToInt

/**
 * The web interface's way to the player. The page (frontend/src/player/app.ts) sends JSON
 * messages: the queue to play, and play, pause, seek, skip. The bridge answers with what plays
 * and where it is: on every change, and twice a second while the app is in view (every five
 * seconds behind the lock screen, for when the page is awake there; episodes' and audiobooks'
 * places don't wait for it, the app saves them itself: Progress.kt).
 *
 * The bridge works the service's player itself, as it's in this process. A MediaController
 * guesses what a change does until the player has made it, and Media3 crashes the app when a
 * late update from the player meets such a guess (a new queue started just as the old one moved
 * on: androidx/media#3239). The controller is kept to bind the service, which keeps it running.
 */
class PlayerBridge(
    private val context: Context,
    private val onCommand: (String, JSONObject) -> Unit,
    private val onHello: () -> Unit,
) : Player.Listener {
    private var controller: MediaController? = null   // keeps the service bound
    private var player: Player? = null
    private var reply: JavaScriptReplyProxy? = null
    private val waiting = ArrayDeque<JSONObject>()
    private val main = Handler(Looper.getMainLooper())
    private var inView = true
    private var failures = 0                 // songs in a row that wouldn't play
    private val audio = context.getSystemService(AudioManager::class.java)
    /** The account's other devices, out of view (the page frozen): the app keeps the connection itself. */
    private val link = ConnectLink(audio, { player }, ::send)
    /** Autoplay while the page is frozen: the songs (or a podcast's episodes) run out, the app finds more itself. */
    private val autoplay = Autoplay({ player }, { link.entry(it) }, ::send)

    /** The phone's media volume changed (its buttons, or another device): the page hears of it, and
     * so do the account's other devices (their volume slider shows the phone's). */
    private val volumeSeen = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            if (i.getIntExtra("android.media.EXTRA_VOLUME_STREAM_TYPE", -1) == AudioManager.STREAM_MUSIC) sendVolume()
        }
    }
    /** The visualizer's spectrum (Spectrum.kt), 30 times a second while the page shows and the music plays. */
    private val spectrum = object : Runnable {
        override fun run() {
            val bands = Spectrum.bands
            if (bands != null && System.currentTimeMillis() - Spectrum.when_ < 300) {
                send(JSONObject().put("t", "spectrum").put("bands", android.util.Base64.encodeToString(bands, android.util.Base64.NO_WRAP)))
            }
            main.postDelayed(this, 33L)
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            sendState()
            main.postDelayed(this, if (inView) 500L else 5_000L)
        }
    }

    /** Everything downloaded, and whether the server can't be reached, for the page. */
    fun sendDownloads() = send(JSONObject().put("t", "downloads").put("list", Downloads.list()).put("offline", Downloads.offline))

    fun connect() {
        Downloads.init(context)
        Downloads.onChange = ::sendDownloads
        val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
        val future = MediaController.Builder(context, token).buildAsync()
        future.addListener({
            val c = future.get()
            controller = c
            player = (PlaybackService.player ?: c).also {
                it.addListener(this)
                it.addListener(autoplay)
            }
            Progress.onSaved = { key -> send(JSONObject().put("t", "saved").put("key", key)) }
            while (waiting.isNotEmpty()) handleSafely(waiting.removeFirst())
            ticking(c.isPlaying)
        }, ContextCompat.getMainExecutor(context))
        ContextCompat.registerReceiver(context, volumeSeen, IntentFilter("android.media.VOLUME_CHANGED_ACTION"),
            ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    fun release() {
        Downloads.onChange = null
        link.stop()
        Progress.onSaved = null
        runCatching { context.unregisterReceiver(volumeSeen) }
        main.removeCallbacks(tick)
        player?.removeListener(this)
        player?.removeListener(autoplay)
        player = null
        controller?.release()
        controller = null
    }

    /** Another server: its queue's links don't work any more. */
    fun clear() {
        player?.run {
            stop()
            clearMediaItems()
        }
    }

    /** The page out of view (it freezes after a while) or back: the device's connection is the app's meanwhile. */
    fun visible(on: Boolean) {
        shown = on
        if (on) link.stop() else link.start()
        autoplay.away(!on)
    }

    /** Whether the app is on screen (started), so its page can be reloaded now. */
    var shown = false
        private set

    fun inView(visible: Boolean) {
        inView = visible
        ticking(player?.isPlaying == true)
        if (visible) sendState()
    }

    /** A message from the page; `proxy` is how to answer that page. */
    fun onMessage(data: String, proxy: JavaScriptReplyProxy) {
        reply = proxy
        val msg = runCatching { JSONObject(data) }.getOrNull() ?: return
        if (player == null) waiting.addLast(msg) else handleSafely(msg)
    }

    /** A message that fails goes to the server's log: thrown back into the web view, it would end the app. */
    private fun handleSafely(m: JSONObject) {
        try {
            handle(m)
        } catch (e: Exception) {
            Crashes.caught("bridge", "The page's \"${m.optString("t")}\" failed", e)
        }
    }

    private fun handle(m: JSONObject) {
        val c = player ?: return
        when (val t = m.optString("t")) {
            "hello" -> send(JSONObject().put("t", "hello").put("version", PlaybackService.USER_AGENT).put("saves", true).put("updates", true)
                .put("downloads", Downloads.list()).put("offline", Downloads.offline)
                .put("device", deviceName()).put("volume", mediaVolume()).put("library", if (Server.local) "local" else "server")
                .put("queue", JSONArray((0 until c.mediaItemCount).map { c.getMediaItemAt(it).carried() }))
                .put("index", c.currentMediaItemIndex).put("state", state(c))).also { onHello() }
            "load" -> {
                val items = m.getJSONArray("items").let { a -> (0 until a.length()).map { Items.fromJson(a.getJSONObject(it)) } }
                c.setMediaItems(items, m.optInt("index"), (m.optDouble("position", 0.0) * 1000).toLong())
                c.prepare()
                c.playWhenReady = m.optBoolean("play", true)
            }
            "device" -> link.device = m.optJSONObject("hello")
            "prefs" -> {
                link.quality = m.optString("quality", "original")
                link.radioBuffer = m.optInt("radioBuffer")
                autoplay.on = m.optBoolean("autoplay")
                autoplay.oldest = m.optJSONArray("oldest")?.let { a -> (0 until a.length()).map { a.optInt(it) }.toSet() } ?: emptySet()
                if (m.has("downloadWifi")) Downloads.wifiOnly(context, m.optBoolean("downloadWifi"))
            }
            "upcoming" -> {
                // everything after the current song, replaced
                val items = m.getJSONArray("items").let { a -> (0 until a.length()).map { Items.fromJson(a.getJSONObject(it)) } }
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
                Progress.asked = key            // from its start, as the page asks
                c.seekTo(index, 0)
                if (c.playbackState == Player.STATE_IDLE) c.prepare()
                c.play()
            }
            "repeat" -> c.repeatMode = when (m.optString("mode")) {
                "all" -> Player.REPEAT_MODE_ALL
                "one" -> Player.REPEAT_MODE_ONE
                else -> Player.REPEAT_MODE_OFF
            }
            // the phone's media volume, as the page (another device, through it) sets it; muted, the player is silent
            "volume" -> {
                val muted = m.optBoolean("muted")
                c.volume = if (muted) 0f else 1f
                if (!muted && m.has("level")) {
                    val max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                    audio.setStreamVolume(AudioManager.STREAM_MUSIC, (m.optDouble("level").coerceIn(0.0, 1.0) * max).roundToInt(), 0)
                }
            }
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
            // downloads (Downloads.kt): a collection to have on the phone, or not any more; the page's
            // sign-in state, for opening offline
            "download" -> m.optJSONObject("collection")?.let { Downloads.add(context, it, m.optBoolean("wifiOnly")) }
            "undownload" -> Downloads.remove(context, m.optString("id"))
            "signedIn" -> m.optJSONObject("state")?.let { runCatching { Downloads.keepState(it) } }
            else -> onCommand(t, m)
        }
    }

    /** The phone's media volume, 0 to 1. */
    private fun mediaVolume(): Double =
        audio.getStreamVolume(AudioManager.STREAM_MUSIC).toDouble() / audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)

    private fun sendVolume() = send(JSONObject().put("t", "volume").put("value", mediaVolume()).put("muted", player?.volume == 0f))

    /** The phone's name as its owner set it (Settings → About phone), for the other devices. */
    private fun deviceName(): String =
        Settings.Global.getString(context.contentResolver, "device_name")?.takeIf { it.isNotBlank() }
            ?: "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}"

    private fun MediaItem.carried(): String = mediaMetadata.extras?.getString("muzix") ?: ""

    private fun offset(it: MediaItem?) = it?.mediaMetadata?.extras?.getDouble("offset") ?: 0.0

    private fun state(c: Player): JSONObject {
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
        player?.let { send(state(it)) }
    }

    /** A message for the page. */
    fun send(msg: JSONObject) {
        runCatching { reply?.postMessage(msg.toString()) }
    }

    private fun ticking(on: Boolean) {
        main.removeCallbacks(tick)
        main.removeCallbacks(spectrum)
        if (on) main.post(tick)
        if (on && inView) main.post(spectrum)
        Spectrum.wanted = on && inView
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
        val c = player ?: return
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
