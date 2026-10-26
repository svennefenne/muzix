package io.github.svennefenne.muzix

import android.net.Uri
import android.os.Bundle
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import com.google.android.gms.cast.MediaInfo
import com.google.android.gms.cast.MediaQueueItem
import androidx.media3.cast.MediaItemConverter
import org.json.JSONObject
import com.google.android.gms.cast.MediaMetadata as CastMetadata

/**
 * Queue entries as the page describes them (frontend/src/player/app.ts):
 * {key, url, title, artist, album, art, duration, offset, muzix, cast, castMime, live},
 * turned into the players' MediaItems. The page's own description travels along, so a
 * speaker can be given its version of the entry.
 */
object Items {
    fun fromJson(o: JSONObject): MediaItem {
        val url = Uri.parse(o.getString("url"))
        val extras = Bundle().apply {
            putDouble("offset", o.optDouble("offset", 0.0))
            putDouble("duration", o.optDouble("duration", 0.0))
            putString("muzix", o.optString("muzix"))
            putString("json", o.toString())
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

    fun json(item: MediaItem): JSONObject =
        runCatching { JSONObject(item.mediaMetadata.extras?.getString("json") ?: "") }.getOrElse { JSONObject() }
}

/**
 * What a Cast speaker gets of an entry: its signed link (the speaker has no login cookie), the
 * type of what it will receive, and words only: title, artist and album, never a picture.
 * The custom data is shaped like the web player's (frontend/src/player/cast.ts), so Muzix in a
 * browser can pick up the speaker's queue too.
 */
class CastItems : MediaItemConverter {
    override fun toMediaQueueItem(mediaItem: MediaItem): MediaQueueItem {
        val o = Items.json(mediaItem)
        val live = o.optBoolean("live")
        val md = CastMetadata(if (live) CastMetadata.MEDIA_TYPE_GENERIC else CastMetadata.MEDIA_TYPE_MUSIC_TRACK).apply {
            putString(CastMetadata.KEY_TITLE, o.optString("title"))
            putString(if (live) CastMetadata.KEY_SUBTITLE else CastMetadata.KEY_ARTIST, o.optString("artist"))
            if (!live && o.optString("album").isNotEmpty()) putString(CastMetadata.KEY_ALBUM_TITLE, o.optString("album"))
        }
        val offset = o.optDouble("offset", 0.0)
        val carried = JSONObject().put("offset", offset).put("app", o)
        runCatching { carried.put("muzix", JSONObject(o.optString("muzix"))) }
        val info = MediaInfo.Builder(o.optString("cast").ifEmpty { mediaItem.localConfiguration?.uri.toString() })
            .setStreamType(if (live) MediaInfo.STREAM_TYPE_LIVE else MediaInfo.STREAM_TYPE_BUFFERED)
            .setContentType(o.optString("castMime").ifEmpty { "audio/flac" })
            .setMetadata(md)
            .setCustomData(carried)
            .apply {
                val d = o.optDouble("duration", 0.0)
                if (!live && d > 0 && offset == 0.0) setStreamDuration((d * 1000).toLong())
            }
            .build()
        return MediaQueueItem.Builder(info).setAutoplay(true).setPreloadTime(15.0).build()
    }

    override fun toMediaItem(mediaQueueItem: MediaQueueItem): MediaItem {
        val app = mediaQueueItem.media?.customData?.optJSONObject("app") ?: JSONObject().put("key", "").put("url", "")
        return Items.fromJson(app)
    }
}
