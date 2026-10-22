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
        versionCode = 5
        versionName = "0.5.3"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Signed with the debug key so the release APK installs directly (sideloading).
            // Publish to a store with your own keystore instead.
            signingConfig = signingConfigs.getByName("debug")
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
    // Offline speech recognition (models are downloaded on demand, after the user agrees).
    implementation("com.alphacephei:vosk-android:0.3.47")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20231013")  // the Android one is only a stub in unit tests
}
