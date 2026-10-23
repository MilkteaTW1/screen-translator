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
        versionCode = 17
        versionName = "0.5.15"
        externalNativeBuild { cmake { arguments += listOf("-DANDROID_STL=c++_static") } }
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
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "x86_64")
            isUniversalApk = false
        }
    }
}

dependencies {
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
