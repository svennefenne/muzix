package io.github.svennefenne.muzix

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

/**
 * The app's crashes, in the server's log (/api/client-errors, where the page's own errors go). An
 * exception nothing caught is written down as the app goes; the next time the page has loaded (so
 * its login is known) that goes to the server, with why Android ended the app since, as Android
 * keeps it: a crash, a native crash, not responding, and low memory or a kill while it was on
 * screen or its player in the foreground, playing or paused a short while (otherwise that's
 * Android tidying up the background). The page's own process ending
 * is told at once (MainActivity loads the page again, and the player plays on).
 */
object Crashes {
    private const val FILE = "crash.txt"
    private const val PREFS = "muzix"
    private const val SEEN = "exits_seen"     // when the newest one told of was
    private val TOLD = mapOf(
        ApplicationExitInfo.REASON_CRASH to "crash",
        ApplicationExitInfo.REASON_CRASH_NATIVE to "native crash",
        ApplicationExitInfo.REASON_ANR to "not responding",
        ApplicationExitInfo.REASON_LOW_MEMORY to "low memory",
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE to "resource use",
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE to "start failed",
        ApplicationExitInfo.REASON_SIGNALED to "killed",
    )
    private val FAULTS = setOf(ApplicationExitInfo.REASON_CRASH, ApplicationExitInfo.REASON_CRASH_NATIVE,
        ApplicationExitInfo.REASON_ANR, ApplicationExitInfo.REASON_INITIALIZATION_FAILURE)
    private var installed = false
    @Volatile private var reported = false

    /** From here on, an exception nothing caught is written down before the app goes. */
    @Synchronized fun install(context: Context) {
        if (installed) return
        installed = true
        val file = File(context.applicationContext.filesDir, FILE)
        val before = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            runCatching { file.writeText("${stamp(System.currentTimeMillis())} on the thread ${t.name}\n${Log.getStackTraceString(e)}") }
            before?.uncaughtException(t, e)
        }
    }

    /** Once a run, when the page has loaded with its login: what ended the app before, if anything. */
    @Synchronized fun report(context: Context) {
        if (reported || Server.address.isEmpty()) return
        reported = true
        val app = context.applicationContext
        thread(name = "crash-report") {
            val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val file = File(app.filesDir, FILE)
            var stack = if (file.exists()) runCatching { file.readText() }.getOrNull() else null
            val seen = prefs.getLong(SEEN, 0L)
            val exits = runCatching {
                app.getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(app.packageName, 0, 16)
            }.getOrDefault(emptyList()).filter { it.timestamp > seen && it.reason in TOLD && (it.reason in FAULTS || noticed(it.importance)) }
                .sortedBy { it.timestamp }
            for (x in exits) {
                val trace = when (x.reason) {
                    ApplicationExitInfo.REASON_CRASH -> stack.also { stack = null }
                    ApplicationExitInfo.REASON_ANR -> runCatching { x.traceInputStream?.bufferedReader()?.use { it.readText() } }.getOrNull()
                    else -> null
                }
                val what = "${TOLD[x.reason]} at ${stamp(x.timestamp)}: ${x.description ?: "no description"} " +
                    "(${x.processName}, ${importance(x.importance)}, ${x.rss / 1024} MB in memory)"
                if (!send(TOLD.getValue(x.reason), what, trace ?: "")) return@thread retry()
                prefs.edit().putLong(SEEN, x.timestamp).apply()
            }
            stack?.let { if (!send("crash", it.lines().getOrElse(1) { "crash" }, it)) return@thread retry() }
            file.delete()
        }
    }

    /** Not in the server's log (not reachable, or the page isn't signed in yet): told on the next page load. */
    private fun retry() {
        reported = false
    }

    /** An exception the app caught and went on from, for the log. */
    fun caught(kind: String, what: String, e: Exception) {
        Log.w("Muzix", what, e)
        if (Server.address.isEmpty()) return
        thread(name = "crash-report") { send(kind, "$what: $e", Log.getStackTraceString(e)) }
    }

    /** The page's process ended: it crashed, or Android ended it for memory. */
    fun pageGone(crashed: Boolean, priority: Int) {
        if (Server.address.isEmpty()) return
        thread(name = "crash-report") {
            send("page gone", if (crashed) "The page's process crashed" else "Android ended the page's process for memory (priority $priority)", "")
        }
    }

    /** One report to the server's log; whether it got there (the server only logs a signed-in user's). */
    private fun send(kind: String, message: String, stack: String): Boolean = runCatching {
        val conn = URL(Server.address + "/api/client-errors").openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 10_000
            conn.readTimeout = 10_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("User-Agent", PlaybackService.USER_AGENT)
            if (Server.cookie.isNotEmpty()) conn.setRequestProperty("Cookie", Server.cookie)
            val body = JSONObject().put("kind", kind.take(20)).put("message", message.take(1000)).put("stack", stack.take(6000))
                .put("url", "${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}".take(500))
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            conn.responseCode in 200..299 && JSONObject(conn.inputStream.bufferedReader().use { it.readText() }).optBoolean("logged")
        } finally {
            conn.disconnect()
        }
    }.getOrDefault(false)

    /** On screen, or the player's service in the foreground: playing, or paused a short while. */
    private fun noticed(importance: Int) = importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE

    private fun importance(i: Int) = when (i) {
        ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND -> "on screen"
        ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE -> "the player in the foreground: playing, or paused a short while"
        else -> "importance $i"
    }

    private fun stamp(ms: Long) = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(Date(ms))
}
