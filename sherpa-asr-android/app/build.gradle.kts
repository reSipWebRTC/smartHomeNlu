plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace   = "com.example.asrapp"
    compileSdk  = 34

    defaultConfig {
        applicationId  = "com.example.asrapp"
        minSdk         = 26
        targetSdk      = 34
        versionCode    = 1
        versionName    = "1.0"

        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
    }

    //composeOptions {
        //kotlinCompilerExtensionVersion = "1.5.11"
        //kotlinCompilerExtensionVersion = "1.5.21"
    //}


    packaging {
        jniLibs.pickFirsts += "**/*.so"
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    //implementation(dir(): 'libs', include: ['*.jar',"*.aar"])
    // sherpa-onnx Android AAR (~15MB)
    //implementation("com.github.k2-fsa:sherpa-onnx:1.10.18")

    implementation(fileTree("libs") { include("*.aar", "*.jar") })
    // Silero VAD
    //implementation("com.github.gkonovalov.android-vad:silero:2.0.9")

    // Compose BOM + Material 3
    implementation(platform("androidx.compose:compose-bom:2024.05.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.7.0")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.0")

    // Navigation Compose
    implementation("androidx.navigation:navigation-compose:2.7.6")

    // Networking: OkHttp
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // JSON: Moshi
    implementation("com.squareup.moshi:moshi:1.15.1")
    implementation("com.squareup.moshi:moshi-kotlin:1.15.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
