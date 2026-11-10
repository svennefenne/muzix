package io.github.svennefenne.muzix

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.graphics.Color
import android.net.Uri
import android.net.ConnectivityManager
import android.net.Network
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.ContextThemeWrapper
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.webkit.CookieManager
import android.webkit.JsResult
import android.webkit.RenderProcessGoneDetail
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.addCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.graphics.ColorUtils
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.mediarouter.app.MediaRouteChooserDialog
import androidx.mediarouter.app.MediaRouteControllerDialog
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.google.android.gms.cast.framework.CastContext
import com.google.android.gms.cast.framework.CastState
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * The Muzix app: the web interface in a web view, as it looks in a browser, with the app's player
 * behind it (PlaybackService, through PlayerBridge). The interface is the app's own (WebUi.kt),
 * served on the server's address; a server whose API it doesn't know shows its own. The first time
 * it asks for the server's address. It installs a newer version of itself when the page's user menu
 * offers one.
 */
class MainActivity : ComponentActivity() {
    private lateinit var root: FrameLayout
    private lateinit var bridge: PlayerBridge
    private var web: WebView? = null
    private var server = ""
    private var picked: ValueCallback<Array<Uri>>? = null
    // this phone's music (step 5): its folders, read by the app, served by its own little server
    private val library by lazy { LocalLibrary(applicationContext) }
    private val pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { tree ->
        if (tree != null) {
            library.addFolder(tree)
            openLocal(firstRead = true)
        }
    }
    private val pickFiles = registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
        picked?.onReceiveValue(uris.toTypedArray())
        picked = null
    }
    private val main = Handler(Looper.getMainLooper())
    // the page is on an address the server isn't at any more (it moved while the app was out of view): the page it was on
    private var stale: String? = null
    private val networks = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = soon()
        override fun onLost(network: Network) = soon()
    }
    // an update downloaded while Android still had to allow installing from this app
    private var waiting: File? = null
    private var downloading = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Crashes.install(this)
        // a debug build's page can be inspected from a computer (chrome://inspect)
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        root = FrameLayout(this).apply { setBackgroundColor(BG) }
        setContentView(root)
        bars(BG)
        // the page stays clear of the status and navigation bars (and the keyboard)
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }
        bridge = PlayerBridge(this, { t, m -> command(t, m) }, ::castState)
        bridge.connect()
        watchSpeakers()
        onBackPressedDispatcher.addCallback(this) {
            val w = web
            if (w != null && w.canGoBack()) w.goBack() else moveTaskToBack(true)   // the music goes on
        }
        val saved = Server.saved(this)
        // no server yet, or this phone's library chosen: this phone's music (a folder for it asked for first)
        if (saved == null || Server.library(this) == "local") showLocal() else showWeb(saved)
        soon()          // with no network at all, nothing below calls
        // the network changes (wifi at home, mobile data outside): the address that answers (it runs once at the start, too)
        getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(networks)
    }

    override fun onStart() {
        super.onStart()
        bridge.visible(true)
        stale?.let { showWeb(Server.address, it) }
    }

    override fun onStop() {
        bridge.visible(false)
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        bridge.inView(true)
        // back from allowing installs from this app: the update it downloaded
        waiting?.let { if (packageManager.canRequestPackageInstalls()) install(it) }
    }

    override fun onPause() {
        bridge.inView(false)
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onDestroy() {
        runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(networks) }
        main.removeCallbacks(choose)
        bridge.release()
        web?.destroy()
        super.onDestroy()
    }

    /** Commands from the page that aren't for the player. */
    private fun command(t: String, m: JSONObject) {
        when (t) {
            "server" -> showConnect(if (Server.local) Server.last(this) else server, null)
            "library" -> useLibrary(m.optString("which"))
            "folder" -> pickFolder.launch(null)
            "cast" -> chooseSpeaker()
            "bars" -> runCatching { Color.parseColor(m.optString("color")) }.getOrNull()?.let(::bars)
            "update" -> update(m.optString("url"))
            // the server's web version in the browser (its admin pages: the app has none)
            "open" -> Uri.parse(m.optString("url")).takeIf { it.scheme in setOf("http", "https") }?.let {
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, it)) }
            }
        }
    }

    /** The status and navigation bars in the page's background colour, with icons that show on it. */
    private fun bars(color: Int) {
        root.setBackgroundColor(color)
        val light = ColorUtils.calculateLuminance(color) > 0.5
        val style = if (light) SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT) else SystemBarStyle.dark(Color.TRANSPARENT)
        enableEdgeToEdge(style, style)
    }

    // ------------------------------------------------------------ Google Cast speakers

    /** Cast is there on phones with Google Play services; elsewhere the page shows no Cast button. */
    private fun cast(then: (CastContext) -> Unit) {
        runCatching {
            CastContext.getSharedInstance(this, ContextCompat.getMainExecutor(this)).addOnSuccessListener(then)
        }
    }

    private fun watchSpeakers() = cast { it.addCastStateListener { castState() } }

    /** Tells the page whether speakers are around, and which one plays. */
    private fun castState() = cast { ctx ->
        val state = when (ctx.castState) {
            CastState.CONNECTED -> "connected"
            CastState.CONNECTING -> "connecting"
            CastState.NOT_CONNECTED -> "available"
            else -> "unavailable"
        }
        val device = ctx.sessionManager.currentCastSession?.castDevice?.friendlyName ?: ""
        bridge.send(JSONObject().put("t", "cast").put("state", state).put("device", device))
    }

    /** The speaker picker; while casting, the speaker's own dialog (volume, Stop casting). */
    private fun chooseSpeaker() = cast { ctx ->
        val themed = ContextThemeWrapper(this, androidx.appcompat.R.style.Theme_AppCompat_NoActionBar)
        if (ctx.castState == CastState.CONNECTED) {
            MediaRouteControllerDialog(themed).show()
        } else {
            MediaRouteChooserDialog(themed).apply { ctx.mergedSelector?.let { routeSelector = it } }.show()
        }
    }

    // ------------------------------------------------------------ updating itself

    /** A newer version of the app (Update in the page's user menu): downloaded, then Android's installer. */
    private fun update(url: String) {
        val uri = Uri.parse(url)
        if (!released(uri) || downloading) return
        downloading = true
        Toast.makeText(this, R.string.downloading, Toast.LENGTH_SHORT).show()
        thread {
            val file = File(cacheDir, "updates/update.apk")
            val failed = try {
                file.parentFile?.mkdirs()
                val conn = URL(uri.toString()).openConnection() as HttpURLConnection
                conn.connectTimeout = 15_000
                conn.readTimeout = 60_000
                conn.setRequestProperty("User-Agent", PlaybackService.USER_AGENT)
                try {
                    if (conn.responseCode != 200) "HTTP ${conn.responseCode}" else {
                        conn.inputStream.use { input -> file.outputStream().use { input.copyTo(it) } }
                        null
                    }
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                e.message ?: e.javaClass.simpleName
            }
            runOnUiThread {
                downloading = false
                if (failed == null) install(file) else Toast.makeText(this, getString(R.string.download_failed, failed), Toast.LENGTH_LONG).show()
            }
        }
    }

    /** One of the app's releases on GitHub (the server says which is the newest: backend/muzix/api/android.py). */
    private fun released(uri: Uri) = uri.scheme == "https" && uri.host == "github.com" &&
        uri.path?.matches(Regex("/[\\w.-]+/[\\w.-]+/releases/download/[\\w.-]+/[\\w.-]+\\.apk")) == true

    private fun install(file: File) {
        // the first time, Android asks to allow installing from this app (then onResume goes on)
        if (!packageManager.canRequestPackageInstalls()) {
            waiting = file
            runCatching { startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName"))) }
            return
        }
        waiting = null
        val apk = FileProvider.getUriForFile(this, "$packageName.files", file)
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(apk, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    // ------------------------------------------------------------ the server's address

    private fun showConnect(current: String, problem: String?) {
        dropWeb()
        server = ""
        bars(BG)
        val pad = dp(24)
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(pad, pad, pad, pad)
        }
        box.addView(ImageView(this).apply { setImageResource(R.drawable.logo) },
            LinearLayout.LayoutParams(dp(80), dp(60)).apply { bottomMargin = dp(20) })
        box.addView(TextView(this).apply {
            text = getString(R.string.app_name)
            setTextColor(TEXT)
            textSize = 28f
            letterSpacing = 0.08f
            gravity = Gravity.CENTER
        })
        box.addView(TextView(this).apply {
            text = "Your Muzix server's address"
            setTextColor(DIM)
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(0, dp(18), 0, dp(8))
        })
        val field = EditText(this).apply {
            setText(current)
            hint = "muzix.example.com"
            setHintTextColor(FAINT)
            setTextColor(TEXT)
            textSize = 17f
            isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
        }
        box.addView(field, LinearLayout.LayoutParams(dp(320), LinearLayout.LayoutParams.WRAP_CONTENT))
        val note = TextView(this).apply {
            text = problem ?: ""
            setTextColor(ERROR)
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, dp(10), 0, dp(10))
        }
        box.addView(note, LinearLayout.LayoutParams(dp(320), LinearLayout.LayoutParams.WRAP_CONTENT))
        val go = Button(this).apply {
            text = "Connect"
            setTextColor(ON_PRIMARY)
            setBackgroundColor(PRIMARY)
        }
        box.addView(go, LinearLayout.LayoutParams(dp(320), dp(48)))
        // or no server: this phone's music, from the folders picked
        val here = Button(this).apply {
            text = if (library.folders().isEmpty()) "Play this phone's music" else "This phone's music"
            setTextColor(TEXT)
            setBackgroundColor(Color.TRANSPARENT)
            setOnClickListener { showLocal() }
        }
        box.addView(here, LinearLayout.LayoutParams(dp(320), dp(48)).apply { topMargin = dp(12) })
        if (library.folders().isNotEmpty()) {
            box.addView(TextView(this).apply {
                text = "Its folders: " + library.folders().joinToString(", ") { LocalLibrary.name(it) }
                setTextColor(DIM)
                textSize = 13f
                gravity = Gravity.CENTER
            }, LinearLayout.LayoutParams(dp(320), LinearLayout.LayoutParams.WRAP_CONTENT))
            box.addView(Button(this).apply {
                text = "Add a folder"
                setTextColor(DIM)
                setBackgroundColor(Color.TRANSPARENT)
                setOnClickListener { pickFolder.launch(null) }
            }, LinearLayout.LayoutParams(dp(320), dp(44)))
        }
        var connecting = false
        val connect = connect@{
            if (connecting) return@connect          // the keyboard's Go and Enter can both fire
            val address = Server.normalize(field.text.toString())
            if (address == null) {
                note.text = "That isn't a web address"
            } else {
                note.text = "Connecting…"
                go.isEnabled = false
                connecting = true
                thread {
                    val answer = check(address)
                    runOnUiThread {
                        go.isEnabled = true
                        connecting = false
                        answer.onSuccess { (api, outside) ->
                            if (address !in Server.addresses() || Server.local) bridge.clear()     // another library: the queue's links are gone
                            closeLocal()
                            Server.setLibrary(this, "server")
                            Server.connected(this, address, outside)
                            Server.save(this, address, api)
                            showWeb(address)
                        }.onFailure { note.text = it.message }
                    }
                }
            }
        }
        go.setOnClickListener { connect() }
        field.setOnEditorActionListener { _, action, event ->
            val enter = event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN
            if (action == EditorInfo.IME_ACTION_GO || enter) connect()
            true
        }
        root.addView(box, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    }

    /** The version of the API `address` answers with as a Muzix server (0: from before versions) and the
     * server's outside address, or what went wrong. */
    private fun check(address: String, wait: Int = 8_000): Result<Pair<Int, String>> = try {
        val conn = URL("$address/api/health").openConnection() as HttpURLConnection
        conn.connectTimeout = wait
        conn.readTimeout = wait
        conn.setRequestProperty("User-Agent", PlaybackService.USER_AGENT)
        try {
            val body = runCatching { JSONObject(conn.inputStream.bufferedReader().readText()) }.getOrNull()
            if (conn.responseCode == 200 && body?.optBoolean("ok") == true) Result.success(body.optInt("api", 0) to body.optString("address"))
            else Result.failure(Exception("That address answers, but not as a Muzix server"))
        } finally {
            conn.disconnect()
        }
    } catch (e: Exception) {
        Result.failure(Exception("Couldn't reach $address (${e.javaClass.simpleName}: ${e.message})"))
    }

    // ------------------------------------------------------------ this phone's music

    /** This phone's library, and with no folder for it yet, the question which one. */
    private fun showLocal() {
        openLocal(firstRead = false)
        if (library.folders().isEmpty()) askFolder()
    }

    /** No folder with music yet: picked first thing. Without one, podcasts and radio play (and the
     * user menu's "Add a music folder" asks again). */
    private fun askFolder() {
        AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
            .setTitle("Where's your music?")
            .setMessage("Pick the folder on this phone that has your music. The app only reads it.\n\nWithout one, podcasts and radio still play.")
            .setPositiveButton("Choose a folder") { _, _ -> pickFolder.launch(null) }
            .setNegativeButton("Not now", null)
            .setNeutralButton("Use a Muzix server") { _, _ -> showConnect(Server.last(this), null) }
            .show()
    }

    /** This phone's library: its little server started, its folders read (the first time before it shows). */
    private fun openLocal(firstRead: Boolean) {
        if (!Server.local) bridge.clear()          // the server's queue's links are gone
        Server.setLibrary(this, "local")
        val api = LocalApi(this, library)
        // the same port each time if it's free (the page keeps its settings by its address)
        val srv = LocalServer.running ?: run {
            val port = getSharedPreferences("muzix", MODE_PRIVATE).getInt("local_port", 0)
            // no read timeout: the Connect socket waits quietly for what the other devices do
            try {
                LocalServer(applicationContext, api, port).also { it.start(0, true) }
            } catch (e: java.io.IOException) {
                LocalServer(applicationContext, api, 0).also { it.start(0, true) }
            }
        }.also { LocalServer.running = it }
        getSharedPreferences("muzix", MODE_PRIVATE).edit().putInt("local_port", srv.listeningPort).apply()
        // the account stays the server's, while there's one
        srv.server = Server.last(this).takeIf { Server.addresses().isNotEmpty() }.orEmpty()
        api.withServer = srv.server.isNotEmpty()
        Server.address = srv.origin
        Server.cookie = "${LocalServer.COOKIE}=${srv.secret}"
        CookieManager.getInstance().setCookie(srv.origin, "${LocalServer.COOKIE}=${srv.secret}; Path=/; HttpOnly")
        if (!api.withServer) thread { runCatching { api.shows.refresh() } }       // this phone's podcasts: their new episodes
        // no folder yet: podcasts and radio, and nothing to read
        if (library.folders().isNotEmpty() && (firstRead || library.db.compileStatement("SELECT count(*) FROM tracks").simpleQueryForLong() == 0L)) {
            showConnect("", "Reading this phone's music…")
            thread {
                val n = runCatching { library.scan() }.getOrDefault(0)
                runOnUiThread { if (Server.local) showWeb(srv.origin).also { if (n == 0) Toast.makeText(this, "No songs found in those folders", Toast.LENGTH_LONG).show() } }
            }
        } else {
            showWeb(srv.origin)
            thread { runCatching { library.scan() } }       // what changed since, read in the background
        }
    }

    /** The user menu's switch: this phone's music (its folders, picked the first time), or the server's again
     * (its address screen, if there's none yet). */
    private fun useLibrary(which: String) {
        if (which == "local") {
            if (!Server.local) showLocal()
            return
        }
        if (!Server.local) return
        val last = Server.last(this)
        if (last.isEmpty() || Server.addresses().isEmpty()) return showConnect("", null)
        bridge.clear()          // this phone's queue's links are gone
        closeLocal()
        Server.setLibrary(this, "server")
        showWeb(last)
        soon()                  // the address that answers now
    }

    /** Signed in to a server: the podcasts and stations this phone kept with no server move into the account (step 6). */
    private var moving = false
    private var movedFor = ""          // the login it was last done for

    private fun moveShows() {
        val cookie = Server.cookie
        if (Server.local || moving || !cookie.contains("muzix_session=") || cookie == movedFor) return
        moving = true
        movedFor = cookie
        val address = server
        thread {
            val shows = LocalShows(applicationContext)
            val n = if (shows.any()) runCatching { shows.moveTo(address, cookie) }.getOrDefault(0) else 0
            runOnUiThread {
                moving = false
                if (n > 0) {
                    Toast.makeText(this, "Moved $n podcasts and stations into your account", Toast.LENGTH_LONG).show()
                    web?.reload()
                }
            }
        }
    }

    private fun closeLocal() {
        LocalServer.running?.stop()
        LocalServer.running = null
        Server.local = false
    }

    /** With this phone's library on: the server's address that answers, for the account's parts. */
    private fun pickAccount() = thread {
        val found = Server.addresses().firstOrNull { a -> check(a, if (a == Server.home && Server.away.isNotEmpty()) 2_500 else 8_000).isSuccess }
        if (found != null) LocalServer.running?.server = found
    }

    // ------------------------------------------------------------ at home and away

    private fun soon() {
        main.removeCallbacks(choose)
        main.postDelayed(choose, 1_500)      // a new network settles first
    }

    /** The server's address that answers, the one at home first (it answers quickly, or not at all), and
     * its API's version (the server may have been updated): the page moves there, or to the interface that fits. */
    private val choose = Runnable {
        if (server.isEmpty()) return@Runnable
        if (Server.local) {
            pickAccount()
            return@Runnable
        }
        thread {
            val found = Server.addresses().firstNotNullOfOrNull { a ->
                check(a, if (a == Server.home && Server.away.isNotEmpty()) 2_500 else 8_000).getOrNull()?.let { a to it.first }
            }
            runOnUiThread {
                offline(found == null)
                if (found != null) use(found.first, found.second)
            }
        }
    }

    /** The server can't be reached (or can again): offline, the page shows what's downloaded. */
    private fun offline(on: Boolean) {
        if (Downloads.offline == on) return
        Downloads.offline = on
        bridge.sendDownloads()
    }

    private fun use(address: String, api: Int) {
        if (server.isEmpty()) return            // the address screen is showing
        val moved = address != server
        val refit = WebUi.fits(api) != WebUi.fits(Server.api)
        if (moved) carryLogin(server, address)
        Server.save(this, address, api)        // the player's next requests go there at once
        if (!moved && !refit) return
        // the same page, at the new address
        val page = web?.url?.let(Uri::parse)?.takeIf { Server.origin(it) == server }
            ?.let { (it.encodedPath ?: "") + (it.encodedQuery?.let { q -> "?$q" } ?: "") } ?: ""
        if (bridge.shown) showWeb(address, page) else stale = page
    }

    /** The login, from one of the server's addresses to the other: the same device, signed in at both. */
    private fun carryLogin(from: String, to: String) {
        val cookies = CookieManager.getInstance()
        val token = cookies.getCookie(from)?.split(';')?.map { it.trim() }?.firstOrNull { it.startsWith("muzix_session=") } ?: return
        if (cookies.getCookie(to)?.contains(token) == true) return
        val secure = if (to.startsWith("https:")) "; Secure" else ""
        cookies.setCookie(to, "$token; Path=/; Max-Age=${60 * 86400}; HttpOnly; SameSite=Lax$secure")
        cookies.flush()
    }

    // ------------------------------------------------------------ the web interface

    @SuppressLint("SetJavaScriptEnabled")
    private fun showWeb(address: String, page: String = "") {
        stale = null
        server = address
        Server.address = address
        // the app's web interface, or the server's own (this phone's library serves the app's itself)
        val own = !Server.local && WebUi.fits(Server.api)
        WebUi.why(Server.api)?.let { Toast.makeText(this, it, Toast.LENGTH_LONG).show() }
        dropWeb()
        val w = WebView(this)
        w.setBackgroundColor(BG)
        // the page stays awake with the screen off, as long as the app is (it plays): it's one of
        // the account's devices, which the others see and control (Muzix Connect)
        w.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false)
        w.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            userAgentString = "$userAgentString ${PlaybackService.USER_AGENT}"
        }
        CookieManager.getInstance().setAcceptCookie(true)
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            // only the server's own pages get the player
            WebViewCompat.addWebMessageListener(w, "MuzixApp", setOf(address)) { _, message, _, isMainFrame, reply ->
                val data = message.data
                if (isMainFrame && data != null) {
                    Server.cookie = CookieManager.getInstance().getCookie(address) ?: ""
                    if (!Server.local && Server.cookie != movedFor) moveShows()     // signed in now, inside the page
                    bridge.onMessage(data, reply)
                }
            }
        }
        w.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                if (!own || request.method != "GET" || Server.origin(request.url) != address) return null
                // offline, what's downloaded answers for the server (Downloads.kt)
                if (Downloads.offline && request.url.path?.startsWith("/api/") == true) {
                    return Downloads.answer(request.url.encodedPath + (request.url.encodedQuery?.let { "?$it" } ?: ""))
                        ?.let { (type, body) -> WebResourceResponse(type, "utf-8", body.inputStream()) }
                        ?: WebResourceResponse("application/json", "utf-8", 503, "Offline", emptyMap(),
                            """{"detail":"Not downloaded: this needs the server"}""".byteInputStream())
                }
                return runCatching { WebUi.response(this@MainActivity, request.url) }.getOrNull()
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.scheme in setOf("http", "https") && Server.origin(url) == server) return false
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, url)) }   // other sites open in the browser
                return true
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) showConnect(server, "Couldn't reach $server (${error.description})")
            }

            override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
                if (request.isForMainFrame && response.statusCode >= 500) {
                    showConnect(server, "$server answered with an error (${response.statusCode})")
                }
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (!Server.local) Server.cookie = CookieManager.getInstance().getCookie(server) ?: ""
                moveShows()
                Crashes.report(this@MainActivity)
            }

            /** The page's process crashed, or Android ended it to free memory: load it again; the player kept playing. */
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                Crashes.pageGone(detail.didCrash(), detail.rendererPriorityAtExit())
                if (view == web) showWeb(server)
                return true
            }
        }
        w.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                picked?.onReceiveValue(null)
                picked = callback
                val type = params.acceptTypes.firstOrNull { it.contains("/") } ?: "*/*"
                pickFiles.launch(type)
                return true
            }

            // the page's questions as the app's own, not under "The page at http://127.0.0.1 says"
            override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean {
                AlertDialog.Builder(this@MainActivity, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                    .setMessage(message)
                    .setPositiveButton(android.R.string.ok) { _, _ -> result.confirm() }
                    .setNegativeButton(android.R.string.cancel) { _, _ -> result.cancel() }
                    .setOnCancelListener { result.cancel() }
                    .show()
                return true
            }
        }
        root.addView(w, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        web = w
        w.loadUrl(address + page)
    }

    /** The web view and whatever else is on screen, gone (the web view destroyed, not just hidden). */
    private fun dropWeb() {
        web?.let {
            root.removeView(it)
            it.destroy()
        }
        web = null
        root.removeAllViews()
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private companion object {
        val BG = Color.parseColor("#0a1020")
        val TEXT = Color.parseColor("#f1e7d0")
        val DIM = Color.parseColor("#aca69b")
        val FAINT = Color.parseColor("#87847f")
        val PRIMARY = Color.parseColor("#f2a93b")
        val ON_PRIMARY = Color.parseColor("#0b0b0f")
        val ERROR = Color.parseColor("#ef5350")
    }
}
