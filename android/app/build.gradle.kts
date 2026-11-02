plugins {
    id("com.android.application")
}

val serverUrl: String = providers.gradleProperty("tylonServerUrl").getOrElse("https://")

android {
    namespace = "zw.co.tylonerp"
    compileSdk = 35

    defaultConfig {
        applicationId = "zw.co.tylonerp"
        minSdk = 24          // Android 7.0
        targetSdk = 35       // Android 15
        versionCode = 1
        versionName = "1.0.0"
        buildConfigField("String", "SERVER_URL", "\"$serverUrl\"")
        manifestPlaceholders["usesCleartext"] = "false"
    }

    buildTypes {
        debug {
            // Lets a debug build talk to a server on your computer over plain http (for example http://10.0.2.2:8080).
            manifestPlaceholders["usesCleartext"] = "true"
        }
        release {
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
