import java.util.Properties
import javax.inject.Inject

plugins {
    id("com.android.application")
}

// Release signing: the keystore the MUZIX_KEYSTORE* variables name (GitHub Actions), or the one
// ~/.config/muzix-android/keystore.properties names, on a computer that holds the key. Without
// either, release builds are signed with the debug key.
val keyFile = File(System.getProperty("user.home"), ".config/muzix-android/keystore.properties")
val keyProps = Properties().apply { if (keyFile.exists()) keyFile.inputStream().use { load(it) } }
fun signing(env: String, prop: String): String? = System.getenv(env)?.takeIf { it.isNotEmpty() } ?: keyProps.getProperty(prop)
val keystore = signing("MUZIX_KEYSTORE", "storeFile")

// every commit is a newer version to Android: the version code counts them
val commits = providers.exec {
    commandLine("git", "rev-list", "--count", "HEAD")
    isIgnoreExitValue = true
}.standardOutput.asText.map { it.trim().toIntOrNull() ?: 1 }

// the web interface that comes with the app (WebUi.kt): the frontend's build (frontend/ → npm run build),
// without its source maps and the older font files (the web view takes woff2)
abstract class CopyWebUi : DefaultTask() {
    @get:InputDirectory abstract val dist: DirectoryProperty
    @get:OutputDirectory abstract val outputDir: DirectoryProperty
    @get:Inject abstract val files: FileSystemOperations

    @TaskAction
    fun copy() {
        files.sync {
            from(dist) { exclude("**/*.map", "**/*.woff") }
            into(outputDir.dir("web"))
        }
    }
}
val copyWebUi = tasks.register<CopyWebUi>("copyWebUi") {
    dist.set(rootProject.layout.projectDirectory.dir("../frontend/dist"))
}
androidComponents {
    onVariants { it.sources.assets?.addGeneratedSourceDirectory(copyWebUi, CopyWebUi::outputDir) }
}

android {
    namespace = "io.github.svennefenne.muzix"
    compileSdk {
        version = release(36) { minorApiLevel = 1 }
    }

    defaultConfig {
        applicationId = "io.github.svennefenne.muzix"
        minSdk = 29
        targetSdk = 35
        versionCode = commits.get()
        versionName = "0.10.9"
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        if (keystore != null) {
            create("release") {
                storeFile = file(keystore)
                storePassword = signing("MUZIX_KEYSTORE_PASSWORD", "storePassword")
                keyAlias = signing("MUZIX_KEY_ALIAS", "keyAlias")
                keyPassword = signing("MUZIX_KEY_PASSWORD", "keyPassword") ?: storePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.12.4")
    implementation("androidx.webkit:webkit:1.17.1")
    implementation("androidx.media3:media3-exoplayer:1.11.1")
    implementation("androidx.media3:media3-session:1.11.1")
    implementation("androidx.media3:media3-cast:1.11.1")
    // the songs downloaded ahead (Buffering.kt)
    implementation("androidx.media3:media3-datasource:1.11.1")
    implementation("androidx.media3:media3-database:1.11.1")
    // the speaker picker's dialogs
    implementation("androidx.mediarouter:mediarouter:1.8.1")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.fragment:fragment-ktx:1.8.9")
    // the app's own connection to the account's other devices, while its page is frozen (ConnectLink.kt)
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // this phone's library: the app's own little web server on 127.0.0.1 (LocalServer.kt)
    implementation("org.nanohttpd:nanohttpd:2.3.1")
    // and its Muzix Connect socket, passed on to the server
    implementation("org.nanohttpd:nanohttpd-websocket:2.3.1")
}
