package io.github.svennefenne.muzix

import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.ContextThemeWrapper
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.webkit.CookieManager
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
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.addCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
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
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * The Muzix app: the server's own web interface in a web view, as it looks in a browser, with
 * the app's player behind it (PlaybackService, through PlayerBridge). The first time, and
 * whenever the server can't be reached, it asks for the server's address.
 */
class MainActivity : ComponentActivity() {
    private lateinit var root: FrameLayout
    private lateinit var bridge: PlayerBridge
    private var web: WebView? = null
    private var server = ""
    private var picked: ValueCallback<Array<Uri>>? = null
    private val pickFiles = registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
        picked?.onReceiveValue(uris.toTypedArray())
        picked = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
        if (saved == null) showConnect("", null) else showWeb(saved)
    }

    override fun onResume() {
        super.onResume()
        bridge.inView(true)
    }

    override fun onPause() {
        bridge.inView(false)
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onDestroy() {
        bridge.release()
        web?.destroy()
        super.onDestroy()
    }

    /** Commands from the page that aren't for the player. */
    private fun command(t: String, m: JSONObject) {
        when (t) {
            "server" -> showConnect(server, null)
            "cast" -> chooseSpeaker()
            "bars" -> runCatching { Color.parseColor(m.optString("color")) }.getOrNull()?.let(::bars)
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

    // ------------------------------------------------------------ the server's address

    private fun showConnect(current: String, problem: String?) {
        dropWeb()
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
                    val failed = check(address)
                    runOnUiThread {
                        go.isEnabled = true
                        connecting = false
                        if (failed == null) {
                            Server.save(this, address)
                            showWeb(address)
                        } else {
                            note.text = failed
                        }
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

    /** Null when `address` answers like a Muzix server, otherwise what went wrong. */
    private fun check(address: String): String? = try {
        val conn = URL("$address/api/health").openConnection() as HttpURLConnection
        conn.connectTimeout = 8_000
        conn.readTimeout = 8_000
        conn.setRequestProperty("User-Agent", PlaybackService.USER_AGENT)
        try {
            val body = conn.inputStream.bufferedReader().readText()
            if (conn.responseCode == 200 && JSONObject(body).optBoolean("ok")) null
            else "That address answers, but not as a Muzix server"
        } finally {
            conn.disconnect()
        }
    } catch (e: Exception) {
        "Couldn't reach $address (${e.javaClass.simpleName}: ${e.message})"
    }

    // ------------------------------------------------------------ the web interface

    @SuppressLint("SetJavaScriptEnabled")
    private fun showWeb(address: String) {
        if (Server.address.isNotEmpty() && Server.address != address) bridge.clear()
        server = address
        Server.address = address
        dropWeb()
        val w = WebView(this)
        w.setBackgroundColor(BG)
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
                    bridge.onMessage(data, reply)
                }
            }
        }
        w.webViewClient = object : WebViewClient() {
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
                Server.cookie = CookieManager.getInstance().getCookie(server) ?: ""
            }

            /** Android ended the page to free memory: load it again; the player kept playing. */
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
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
        }
        root.addView(w, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        web = w
        w.loadUrl(address)
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
