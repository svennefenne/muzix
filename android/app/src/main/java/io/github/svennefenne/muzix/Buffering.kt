package io.github.svennefenne.muzix

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Timeline
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.CacheWriter
import androidx.media3.datasource.cache.ContentMetadata
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy
import java.io.File
import java.io.IOException
import java.io.InterruptedIOException
import java.util.Collections
import java.util.concurrent.Executors

/** Songs downloaded ahead of time, kept a while: at most 1 GB, the least recently played go first. */
object AudioCache {
    @Volatile private var cache: SimpleCache? = null

    fun get(context: Context): SimpleCache = cache ?: synchronized(this) {
        cache ?: SimpleCache(File(context.cacheDir, "audio"), LeastRecentlyUsedCacheEvictor(1L shl 30),
            StandaloneDatabaseProvider(context)).also { cache = it }
    }
}

/**
 * A dropped connection (a tunnel, a dead spot) is waited out: the player tries again every few
 * seconds for as long as it takes and plays on from where it stopped, instead of giving up and
 * skipping song after song. A file the server says it can't give isn't waited for.
 */
class PatientLoading : DefaultLoadErrorHandlingPolicy() {
    override fun getRetryDelayMsFor(info: LoadErrorHandlingPolicy.LoadErrorInfo): Long {
        val e = info.exception
        if (e is HttpDataSource.InvalidResponseCodeException && e.responseCode < 500) return C.TIME_UNSET
        return super.getRetryDelayMsFor(info)
    }

    override fun getMinimumLoadableRetryCount(dataType: Int) = Int.MAX_VALUE
}

/**
 * Away from wifi, the song that plays and the next two are downloaded whole into [AudioCache]
 * ahead of time, so a tunnel or a dead spot doesn't stop the music: the player reads them from
 * there. On wifi songs stream as before. This is the only writer of the cache; the player only
 * reads it, so the two never wait for each other.
 */
class Precache(
    context: Context,
    private val player: Player,
    private val cache: SimpleCache,
    private val writing: CacheDataSource.Factory,
) : Player.Listener {
    private val net = context.getSystemService(ConnectivityManager::class.java)
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private var wanted: List<Uri> = emptyList()
    private var busy = false
    private var stopped = false
    private val failed: MutableSet<Uri> = Collections.synchronizedSet(mutableSetOf())
    @Volatile private var writer: CacheWriter? = null
    @Volatile private var writingUri: Uri? = null
    private val network = object : ConnectivityManager.NetworkCallback() {
        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
            main.post { update() }
        }

        override fun onLost(network: Network) {
            main.post { update() }
        }
    }

    fun start() {
        player.addListener(this)
        net.registerDefaultNetworkCallback(network)
        update()
    }

    fun stop() {
        stopped = true
        player.removeListener(this)
        runCatching { net.unregisterNetworkCallback(network) }
        wanted = emptyList()
        writer?.cancel()
        worker.shutdownNow()
    }

    override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) = update()

    override fun onTimelineChanged(timeline: Timeline, reason: Int) = update()

    override fun onPlaybackStateChanged(playbackState: Int) = update()

    /** Away from home: not on wifi (or a cable), or on a wifi that costs (a phone's hotspot). */
    private fun away(): Boolean {
        val caps = net.getNetworkCapabilities(net.activeNetwork) ?: return true
        val home = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        return !home || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    }

    private fun update() {
        wanted = if (away()) upcoming() else emptyList()
        if (writingUri != null && writingUri !in wanted) writer?.cancel()
        pump()
    }

    /** The song that plays and the two after it: not radio, nor an audiobook file hours long. */
    private fun upcoming(): List<Uri> {
        if (player.playbackState == Player.STATE_IDLE || player.currentTimeline.isEmpty) return emptyList()
        val repeat = if (player.repeatMode == Player.REPEAT_MODE_ONE) Player.REPEAT_MODE_OFF else player.repeatMode
        val first = player.currentMediaItemIndex
        val out = mutableListOf<MediaItem>()
        var i = first
        while (i != C.INDEX_UNSET && out.size < 3) {
            out += player.getMediaItemAt(i)
            i = player.currentTimeline.getNextWindowIndex(i, repeat, player.shuffleModeEnabled)
            if (i == first) break
        }
        return out.filter {
            val o = Items.json(it)
            !o.optBoolean("live") && o.optDouble("duration", 0.0) <= 7200
        }.mapNotNull { it.localConfiguration?.uri }
    }

    private fun cached(uri: Uri): Boolean {
        val key = uri.toString()
        val length = ContentMetadata.getContentLength(cache.getContentMetadata(key))
        return length >= 0 && cache.isCached(key, 0, length)
    }

    /** One download at a time, the song that plays first. A dropped connection tries again in a
     * while; a file the server can't give is let be. */
    private fun pump() {
        if (busy || stopped) return
        val uri = wanted.firstOrNull { it !in failed && !cached(it) } ?: return
        busy = true
        worker.execute {
            val w = CacheWriter(writing.createDataSourceForDownloading(), DataSpec(uri), null, null)
            writer = w
            writingUri = uri
            val wait = try {
                w.cache()
                0L
            } catch (e: InterruptedIOException) {
                0L                      // let go of: another song is wanted now
            } catch (e: HttpDataSource.InvalidResponseCodeException) {
                if (e.responseCode < 500) failed += uri
                5_000L
            } catch (e: IOException) {
                5_000L                  // no connection: again in a while
            } finally {
                writer = null
                writingUri = null
            }
            main.postDelayed({
                busy = false
                pump()
            }, wait)
        }
    }
}
