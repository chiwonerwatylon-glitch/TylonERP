plugins {
    id("com.android.application")
}

val serverUrl: String = providers.gradleProperty("tylonServerUrl").getOrElse("https://")

// Release signing. CI passes your own key through environment variables (GitHub secrets, see README: Signing).
// Without them the build uses the sideload key in this folder, so every APK the workflow publishes can update the
// one already on a phone. Anyone with this repository can sign with that key: set your own before handing the app
// out widely or publishing it to a store.
val keystoreFile: String = System.getenv("TYLON_KEYSTORE") ?: rootProject.file("sideload.keystore").path
val keystorePassword: String = System.getenv("TYLON_KEYSTORE_PASSWORD") ?: "tylonerp-sideload"
val keyAliasName: String = System.getenv("TYLON_KEY_ALIAS") ?: "tylonerp"
val keyPasswordValue: String = System.getenv("TYLON_KEY_PASSWORD") ?: keystorePassword
val buildNumber: Int = providers.gradleProperty("tylonVersionCode").orNull?.toIntOrNull() ?: 2

android {
    namespace = "zw.co.tylonerp"
    compileSdk = 35

    defaultConfig {
        applicationId = "zw.co.tylonerp"
        minSdk = 24          // Android 7.0
        targetSdk = 35       // Android 15
        versionCode = buildNumber
        versionName = "2.0.$buildNumber"
        buildConfigField("String", "SERVER_URL", "\"$serverUrl\"")
        manifestPlaceholders["usesCleartext"] = "false"
    }

    signingConfigs {
        create("release") {
            storeFile = file(keystoreFile)
            storePassword = keystorePassword
            keyAlias = keyAliasName
            keyPassword = keyPasswordValue
        }
    }

    buildTypes {
        debug {
            // Lets a debug build talk to a server on your computer over plain http (for example http://10.0.2.2:8080).
            manifestPlaceholders["usesCleartext"] = "true"
        }
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    lint {
        abortOnError = false
    }
}
