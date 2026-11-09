package io.github.svennefenne.muzix

import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import java.io.IOException
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject

/**
 * Autoplay while the page is away. Awake, the page keeps the queue going itself: with the last
 * song playing it asks for similar ones, with a podcast's last episode the next one (when that
 * podcast's autoplay is on), and hands them over (frontend/src/player/engine.ts). Out of view a
 * while, Android freezes the page, so once what the player has runs out, nothing would come next
 * until the app is opened again. So out of view, with the last one playing, the app asks the server
 * itself (POST /api/similar, seeded as the page seeds it; GET /api/podcasts/episodes/{id}/next, in
 * the order the podcast's page is sorted) and adds what it gets; back in view, the page is told the
 * queue ("queue") and goes on from there.
 */
class Autoplay(
    private val player: () -> Player?,
    private val entry: (JSONObject) -> JSONObject,
    private val toPage: (JSONObject) -> Unit,
) : Player.Listener {
    private val main = Handler(Looper.getMainLooper())
    private val client = OkHttpClient()
    /** The page's Autoplay setting, sent with its prefs (an older page doesn't: then it's off here). */
    var on = false
    /** The podcasts whose page is sorted oldest first (a serial): their next episode is the one after, not before. */
    var oldest = emptySet<Int>()
    private var away = false
    private var added = false           // songs or episodes added while the page was away: told once it's back
    private var asked = ""              // the one the last search was made at (one search each)

    fun away(out: Boolean) {
        away = out
        if (out) return check()
        val p = player()
        if (added && p != null) {
            added = false
            toPage(JSONObject().put("t", "queue").put("index", p.currentMediaItemIndex)
                .put("queue", JSONArray((0 until p.mediaItemCount).map { p.getMediaItemAt(it).carried()?.toString() ?: "" })))
        }
    }

    override fun onEvents(p: Player, events: Player.Events) {
        if (events.containsAny(Player.EVENT_MEDIA_ITEM_TRANSITION, Player.EVENT_PLAYBACK_STATE_CHANGED, Player.EVENT_TIMELINE_CHANGED)) check()
    }

    /** The last one plays (or has ended), and the page is away: like the page, not while the queue repeats. */
    private fun check() {
        val p = player() ?: return
        val at = p.currentMediaItemIndex
        val cur = p.currentMediaItem ?: return
        if (at < p.mediaItemCount - 1) asked = ""      // more to come: the last one (again, the same album replayed) gets its search
        if (!away || p.repeatMode != Player.REPEAT_MODE_OFF || at != p.mediaItemCount - 1 || cur.mediaId == asked) return
        val info = cur.carried() ?: return
        when (info.optString("kind")) {
            "track" -> if (on) similar(p, at, cur)
            "episode" -> nextEpisode(info, cur)
        }
    }

    /** Songs like the last ones chosen (the Autoplay setting). */
    private fun similar(p: Player, at: Int, cur: MediaItem) {
        asked = cur.mediaId
        val tracks = (0 until p.mediaItemCount).mapNotNull { p.getMediaItemAt(it).carried() }.filter { it.optString("kind") == "track" }
        val played = (0..at).mapNotNull { p.getMediaItemAt(it).carried() }.filter { it.optString("kind") == "track" }
        val chosen = played.filter { !it.optBoolean("auto") }
        val seeds = chosen.ifEmpty { played }.takeLast(5).reversed().map { it.optInt("id") }
        val body = JSONObject().put("seeds", JSONArray(seeds)).put("exclude", JSONArray(tracks.map { it.optInt("id") })).put("n", 10)
        ask(request("/api/similar").post(body.toString().toRequestBody("application/json".toMediaType())).build(), cur) { r ->
            JSONArray(r).let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map(::slim) }
        }
    }

    /** A podcast's next episode: none when its autoplay (switched on its page) is off, or all are heard. */
    private fun nextEpisode(info: JSONObject, cur: MediaItem) {
        asked = cur.mediaId
        val order = if (info.optInt("feedId") in oldest) "oldest" else "newest"
        ask(request("/api/podcasts/episodes/${info.optInt("id")}/next?order=$order").build(), cur) { r ->
            listOfNotNull(JSONObject(r).optJSONObject("next")?.let(::episode))
        }
    }

    private fun request(path: String) = Request.Builder().url(Server.address + path).header("User-Agent", PlaybackService.USER_AGENT)
        .apply { if (Server.cookie.isNotEmpty()) header("Cookie", Server.cookie) }

    /** The server's answer, as the page's queue entries, added after `cur`; no answer, and it's asked again at the next change (the song ending). */
    private fun ask(req: Request, cur: MediaItem, found: (String) -> List<JSONObject>) {
        client.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                main.post { asked = "" }
            }

            override fun onResponse(call: Call, response: Response) {
                val got = response.use { r -> if (r.isSuccessful) runCatching { found(r.body?.string() ?: "") }.getOrNull() else null }
                val token = if (!got.isNullOrEmpty()) castToken() else ""
                main.post { if (got == null) asked = "" else add(got, cur.mediaId, token) }
            }
        })
    }

    /** The token in a speaker's links (it has no login cookie), as the page puts them in: casting goes on too. */
    private fun castToken(): String = runCatching {
        client.newCall(request("/api/cast/token").build()).execute().use { r -> if (r.isSuccessful) JSONObject(r.body?.string() ?: "").optString("token") else "" }
    }.getOrDefault("")

    /** What was found, after the one it was asked at, if that's still the last (the page not back, nothing else
     * played meanwhile); what the queue has already stays out. */
    private fun add(found: List<JSONObject>, after: String, token: String) {
        val p = player() ?: return
        if (!away || p.currentMediaItem?.mediaId != after || p.currentMediaItemIndex != p.mediaItemCount - 1) return
        val queued = (0 until p.mediaItemCount).map { p.getMediaItemAt(it).mediaId }.toSet()
        val items = found.filter { it.optString("key") !in queued }.map { s ->
            val e = entry(s)
            if (token.isNotEmpty()) {
                val cast = Uri.parse(Server.address + s.optString("src")).buildUpon().appendQueryParameter("q", "cast")
                    .appendQueryParameter("ct", token).build().toString()
                val mime = if (s.optString("kind") == "track") MIME[s.optString("format")] ?: "audio/flac" else "audio/mpeg"
                e.put("cast", cast).put("castMime", mime)
            }
            Items.fromJson(e)
        }
        if (items.isEmpty()) return
        val ended = p.playbackState == Player.STATE_ENDED
        p.addMediaItems(items)
        added = true
        if (ended) {
            p.seekTo(p.currentMediaItemIndex + 1, 0)
            p.prepare()
            p.play()
        }
    }

    /** A song as the page puts it in the queue (fromTrack and slim, frontend/src/store/player.ts and player/cast.ts). */
    private fun slim(t: JSONObject): JSONObject = JSONObject()
        .put("key", "track:${t.optInt("id")}").put("kind", "track").put("id", t.optInt("id")).put("title", t.optString("title"))
        .put("artist", t.optString("artist").ifEmpty { t.optString("albumartist") }).put("album", t.optString("album"))
        .put("art", t.opt("art") ?: JSONObject.NULL).put("duration", t.optDouble("duration", 0.0)).put("src", t.optString("stream"))
        .put("albumId", t.opt("album_id") ?: JSONObject.NULL).put("artistId", t.opt("artist_id") ?: JSONObject.NULL)
        .put("format", t.optString("format")).put("castNative", t.optBoolean("cast_native")).put("auto", true)

    /** An episode as the page puts it in the queue (fromEpisode, frontend/src/store/player.ts), its podcast and
     * place kept: the page has them once it's back, and the player goes on from that place (Progress.kt). */
    private fun episode(e: JSONObject): JSONObject = JSONObject()
        .put("key", "episode:${e.optInt("id")}").put("kind", "episode").put("id", e.optInt("id")).put("title", e.optString("title"))
        .put("artist", if (e.isNull("feed_title")) "" else e.optString("feed_title"))
        .put("art", if (e.isNull("image") || e.optString("image").isEmpty()) JSONObject.NULL else e.optString("image"))
        .put("duration", e.optDouble("duration", 0.0)).put("src", e.optString("stream"))
        .put("resume", if (e.optBoolean("finished")) 0.0 else e.optDouble("position", 0.0))
        .put("feedId", e.optInt("feed_id")).put("auto", true)

    private fun MediaItem.carried(): JSONObject? =
        mediaMetadata.extras?.getString("muzix")?.takeIf { it.isNotEmpty() }?.let { runCatching { JSONObject(it) }.getOrNull() }

    companion object {
        /** What a speaker is told a song is, by the file's type (castMime, frontend/src/player/cast.ts). */
        private val MIME = mapOf("mp3" to "audio/mpeg", "flac" to "audio/flac", "m4a" to "audio/mp4", "m4b" to "audio/mp4",
            "aac" to "audio/mp4", "ogg" to "audio/ogg", "oga" to "audio/ogg", "opus" to "audio/ogg", "wav" to "audio/wav")
    }
}
