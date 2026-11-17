package io.github.svennefenne.muzix

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import androidx.media3.common.C
import androidx.media3.common.DeviceInfo
import androidx.media3.common.MediaItem
import androidx.media3.common.Player

/**
 * The sleep timer, which the page sets (frontend/src/player/sleep.ts, through PlayerBridge) and the
 * service runs: the page sleeps with the screen off, the player doesn't. At a time, or when an item
 * (a book's chapter) gets to a place in it or to its end, the phone's sound fades down and the player
 * pauses; then the volume is put back, for the next play. The fade is the phone's own player's: a Cast
 * speaker is only paused. Pausing or playing by hand leaves the timer set; a new one replaces it.
 */
class Sleep(context: Context, private val player: Player, private val local: Player) : Player.Listener {
    private val main = Handler(Looper.getMainLooper())
    /** The phone kept awake while a speaker plays: the phone's own player doesn't then, and the timer would sleep. */
    private val wake = context.getSystemService(PowerManager::class.java)
        .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "muzix:sleep").apply { setReferenceCounted(false) }
    private var at = 0L                  // pause at this time (ms since 1970), or
    private var key: String? = null      // when this item gets
    private var pos: Double? = null      //   here (the page's seconds, as in its "seek"), or to its end
    private var fade = 0L                // ms the volume goes down over, before then
    private var before: Float? = null    // the volume before the fade, while it fades
    private var faded = 0f               // and what the fade last made it
    private val tick = Runnable { check() }

    fun start() = player.addListener(this)

    /** The service ends: the timer with it, the volume as it was. */
    fun stop() {
        clear()
        player.removeListener(this)
        unfade()
    }

    /** The page's "sleep": a time, or an item and the place in it (null: its end); neither turns it off. */
    fun set(at: Long?, key: String?, pos: Double?, fade: Double) {
        clear()
        unfade()
        this.at = at ?: 0L
        this.key = if (at == null) key else null
        this.pos = pos
        this.fade = (fade.coerceAtLeast(0.0) * 1000).toLong()
        check()
    }

    private fun clear() {
        main.removeCallbacks(tick)
        awake(false)
        at = 0L
        key = null
    }

    override fun onEvents(p: Player, events: Player.Events) {
        // the time went by while it was paused (the phone asleep, and the timer with it): Play doesn't pause it again
        if (at > 0 && events.contains(Player.EVENT_PLAY_WHEN_READY_CHANGED) && p.playWhenReady && System.currentTimeMillis() >= at) {
            return slept(pause = false)
        }
        // it plays on or stops, on the phone or a speaker; at an item's place: it was moved, or left (which pauses at once)
        if ((at > 0 || key != null) && events.containsAny(Player.EVENT_MEDIA_ITEM_TRANSITION, Player.EVENT_PLAYBACK_STATE_CHANGED,
                Player.EVENT_IS_PLAYING_CHANGED, Player.EVENT_POSITION_DISCONTINUITY, Player.EVENT_PLAYBACK_PARAMETERS_CHANGED,
                Player.EVENT_TIMELINE_CHANGED, Player.EVENT_DEVICE_INFO_CHANGED)) {
            main.removeCallbacks(tick)
            check()
        }
    }

    /** Paused once the time comes, the volume going down on the way. Looked at again every 250 ms while it fades,
     * else when the fade is due (a minute ahead at most: the clock goes on while the phone sleeps, a handler doesn't);
     * at an item's place only while it plays (it's looked at again when that changes). */
    private fun check() {
        val left = left() ?: return awake(false)
        if (left <= 0) return slept(pause = true)
        val fading = left < fade
        if (fading) fadeTo(left.toFloat() / fade) else unfade()     // unfaded: moved back, out of the fade
        awake(player.isPlaying && player.deviceInfo.playbackType == DeviceInfo.PLAYBACK_TYPE_REMOTE)
        if (at > 0 || player.isPlaying) main.postDelayed(tick, if (fading) left.coerceIn(20, 250) else (left - fade).coerceAtMost(60_000))
    }

    /** Kept awake a while (until the next look, ten minutes at most), or not any more. */
    private fun awake(on: Boolean) {
        if (on) wake.acquire(10 * 60_000L) else if (wake.isHeld) wake.release()
    }

    /** Real ms until it pauses (0 or less: now); null with no timer, or an end not known yet (the next item tells). */
    private fun left(): Long? {
        if (at > 0) return at - System.currentTimeMillis()
        val k = key ?: return null
        val cur = player.currentMediaItem
        if (cur?.mediaId != k || player.playbackState == Player.STATE_ENDED) return 0      // ended, or left: nothing after it plays
        // in the item's own time, as the bridge's "seek": the page's seconds less where its stream started
        val end = pos ?: cur.mediaMetadata.extras?.getDouble("duration")?.takeIf { it > 0 }
        val inItem = end?.let { ((it - offset(cur)) * 1000).toLong() } ?: player.duration.takeIf { it != C.TIME_UNSET } ?: return null
        return ((inItem - player.currentPosition) / player.playbackParameters.speed).toLong()
    }

    /** The volume at `share` (1 down to 0) of the fade: squared, as the ear hears it go. Changed meanwhile (muted,
     * say), it's that volume that fades, and comes back. */
    private fun fadeTo(share: Float) {
        val was = before?.takeIf { local.volume == faded } ?: local.volume
        before = was
        faded = was * share * share
        local.volume = faded
    }

    /** The volume as it was before the fade (unless it was changed meanwhile). */
    private fun unfade() {
        val was = before ?: return
        before = null
        if (local.volume == faded) local.volume = was
    }

    /** Done: paused (unless it was played again after the time went by), the volume back, and the page told. */
    private fun slept(pause: Boolean) {
        clear()
        if (pause) player.pause()
        unfade()
        val tell = onSlept
        if (tell != null) tell() else untold = true
    }

    private fun offset(it: MediaItem) = it.mediaMetadata.extras?.getDouble("offset") ?: 0.0

    companion object {
        /** Told once the timer is done, for the page (PlayerBridge). */
        var onSlept: (() -> Unit)? = null

        /** Done with no page there to tell: the next page hears of it after its hello. */
        var untold = false
    }
}
