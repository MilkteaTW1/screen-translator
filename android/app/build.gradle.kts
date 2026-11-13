import java.net.URL
import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.milkteatw1.screentranslator"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.milkteatw1.screentranslator"
        minSdk = 26
        targetSdk = 34
        versionCode = 37
        versionName = "0.6.5"
        externalNativeBuild { cmake { arguments += listOf("-DANDROID_STL=c++_static") } }
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }  // one APK that carries both
    }
    // Whisper (whisper.cpp, in src/main/cpp) is built with the NDK for each ABI.
    ndkVersion = "27.0.12077973"
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    // The release key lives outside the repo: its path and passwords come from ~/.gradle/gradle.properties
    // (SCREEN_TRANSLATOR_STORE_FILE, _STORE_PASSWORD, _KEY_ALIAS, _KEY_PASSWORD). Without them the debug key is used,
    // so anyone can still build an APK that installs.
    val storeFile = providers.gradleProperty("SCREEN_TRANSLATOR_STORE_FILE").orNull
    signingConfigs {
        if (storeFile != null) {
            create("release") {
                this.storeFile = file(storeFile)
                storePassword = providers.gradleProperty("SCREEN_TRANSLATOR_STORE_PASSWORD").get()
                keyAlias = providers.gradleProperty("SCREEN_TRANSLATOR_KEY_ALIAS").get()
                keyPassword = providers.gradleProperty("SCREEN_TRANSLATOR_KEY_PASSWORD").get()
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
    // sherpa-onnx brings ~67 MB of native libraries (arm64 + x86_64). Stored uncompressed they would double the APK;
    // compressed they add about 25 MB (the phone unpacks them when installing).
    packaging { jniLibs { useLegacyPackaging = true } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// Fast speech captions use sherpa-onnx (Apache-2.0). Its Android library is ~49 MB, so it is not in the repo: it is
// downloaded once from the official release into app/libs (git-ignored) and checked against this SHA-256.
val sherpaVersion = "2.0.1"
val sherpaSha256 = "a8d09d1d32f3eb8520482c6d3d43fae674681c5b050385967c70a3c2c9bf0ee7"
val sherpaAar = layout.projectDirectory.file("libs/sherpa-onnx-$sherpaVersion.aar").asFile
val downloadSherpa by tasks.registering {
    outputs.file(sherpaAar)
    doLast {
        fun sha(f: File) = MessageDigest.getInstance("SHA-256").digest(f.readBytes()).joinToString("") { "%02x".format(it) }
        if (sherpaAar.isFile && sha(sherpaAar) == sherpaSha256) return@doLast
        sherpaAar.parentFile.mkdirs()
        val part = File(sherpaAar.path + ".part")
        URL("https://github.com/k2-fsa/sherpa-onnx/releases/download/v$sherpaVersion/sherpa-onnx-$sherpaVersion.aar")
            .openStream().use { input -> part.outputStream().use { input.copyTo(it) } }
        check(sha(part) == sherpaSha256) { "sherpa-onnx $sherpaVersion download does not match its checksum" }
        part.renameTo(sherpaAar)
    }
}

dependencies {
    implementation(files(sherpaAar).builtBy(downloadSherpa))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    // On-device OCR: Latin is bundled; Chinese/Japanese/Korean models come from Google Play services on first use
    // (keeps the APK small). Translation language data is downloaded on demand, after the user confirms.
    implementation("com.google.mlkit:text-recognition:16.0.1")
    implementation("com.google.android.gms:play-services-mlkit-text-recognition-chinese:16.0.1")
    implementation("com.google.android.gms:play-services-mlkit-text-recognition-japanese:16.0.1")
    implementation("com.google.android.gms:play-services-mlkit-text-recognition-korean:16.0.1")
    implementation("com.google.mlkit:translate:17.0.3")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20231013")  // the Android one is only a stub in unit tests
}
