plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.orizonx.client"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.orizonx.client"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }

    testOptions {
        unitTests.all {
            it.systemProperty("tabx.vectors", rootProject.file("../protocol/test-vectors.json").absolutePath)
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.06.01"))
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")

    testImplementation("junit:junit:4.13.2")
    // android.jar ne fournit qu'un bouchon de org.json en test JVM : on embarque la vraie implémentation.
    testImplementation("org.json:json:20240303")
}
