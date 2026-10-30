package io.github.svennefenne.muzix

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.cast.CastPlayer
import androidx.media3.cast.RemoteCastPlayer
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.DeviceInfo
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DataSourceBitmapLoader
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.CacheBitmapLoader
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/**
 * Plays the queue the web interface hands over, in a foreground service: it goes on with the
 * screen off, moves on to the next song by itself, and shows the lock screen and notification
 * player that headsets, Bluetooth and cars talk to, and it hands the queue to a Cast speaker
 * when one is chosen. Requests to the Muzix server carry the login cookie; requests elsewhere
 * (a radio station's logo) don't, and a speaker gets signed links instead. Away from wifi the
 * next songs are downloaded ahead, and a dropped connection is waited out (Buffering.kt).
 */
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null
    private var precache: Precache? = null

    override fun onCreate() {
        super.onCreate()
        val http = DefaultHttpDataSource.Factory()
            .setUserAgent(USER_AGENT)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(120_000)          // a chip tune is rendered before its first byte
            .setAllowCrossProtocolRedirects(true)
        val signedIn = ResolvingDataSource.Factory(http) { spec ->
            if (Server.cookie.isNotEmpty() && Server.owns(spec.uri)) spec.withAdditionalHeaders(mapOf("Cookie" to Server.cookie))
            else spec
        }
        val data = DefaultDataSource.Factory(this, signedIn)
        // the player reads what was downloaded ahead, and streams the rest
        val cache = AudioCache.get(this)
        val reading = CacheDataSource.Factory().setCache(cache).setUpstreamDataSourceFactory(signedIn)
            .setCacheWriteDataSinkFactory(null).setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        val writing = CacheDataSource.Factory().setCache(cache).setUpstreamDataSourceFactory(signedIn)
        val local = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(this, reading))
                .setLoadErrorHandlingPolicy(PatientLoading()))
            // a long buffer rides out a weak mobile connection (an audiobook, which isn't downloaded ahead)
            .setLoadControl(DefaultLoadControl.Builder().setBufferDurationsMs(30_000, 300_000, 1_500, 3_000)
                .setTargetBufferBytes(32 shl 20).build())
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
            .setHandleAudioBecomingNoisy(true)  // headphones out: pause
            .setWakeMode(C.WAKE_MODE_NETWORK)   // the screen off doesn't stop the download
            .build()
        // the queue moves to a Google Cast speaker and back (the Cast button, or the notification's output switcher)
        val speaker = RemoteCastPlayer.Builder(this).setMediaItemConverter(CastItems()).build()
        val player = CastPlayer.Builder(this).setLocalPlayer(local).setRemotePlayer(speaker).build()
        precache = Precache(this, local, cache, writing).also { it.start() }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        session = MediaSession.Builder(this, player)
            .setSessionActivity(open)
            .setBitmapLoader(CacheBitmapLoader(DataSourceBitmapLoader.Builder(this).setDataSourceFactory(data).build()))
            .setCallback(object : MediaSession.Callback {
                // items come from the web view's controller without their address; it travels in the request
                override fun onAddMediaItems(session: MediaSession, controller: MediaSession.ControllerInfo,
                                             items: MutableList<MediaItem>): ListenableFuture<MutableList<MediaItem>> =
                    Futures.immediateFuture(items.map { it.buildUpon().setUri(it.requestMetadata.mediaUri).build() }.toMutableList())
            })
            .build()
        setMediaNotificationProvider(DefaultMediaNotificationProvider.Builder(this).build().apply {
            setSmallIcon(R.drawable.ic_stat_muzix)
        })
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    /** The app's card closed in the recent apps: the phone stops playing (going Home or Back
     * keeps the task, and the music). A speaker plays on by itself; the phone only lets go of it. */
    override fun onTaskRemoved(rootIntent: Intent?) {
        if (session?.player?.deviceInfo?.playbackType == DeviceInfo.PLAYBACK_TYPE_REMOTE) stopSelf()
        else pauseAllPlayersAndStopSelf()
    }

    override fun onDestroy() {
        precache?.stop()
        precache = null
        session?.run {
            player.release()
            release()
        }
        session = null
        super.onDestroy()
    }

    companion object {
        const val USER_AGENT = "MuzixApp/${BuildConfig.VERSION_NAME} (Android)"
    }
}
