import java.util.Properties

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
        versionName = "0.3.1"
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
    // the speaker picker's dialogs
    implementation("androidx.mediarouter:mediarouter:1.8.1")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.fragment:fragment-ktx:1.8.9")
}
