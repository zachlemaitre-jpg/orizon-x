import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Seule source de version : host-prototype/version.py (__version__ = "X.Y.Z"). versionCode = X*10000 + Y*100 + Z.
val versionFile = rootProject.file("../host-prototype/version.py")
val versionMatch = Regex("""__version__\s*=\s*["'](\d+)\.(\d+)\.(\d+)["']""").find(versionFile.readText())
    ?: throw GradleException("__version__ introuvable (X.Y.Z attendu) dans ${versionFile.path}")
val (verMajor, verMinor, verPatch) = versionMatch.destructured
val appVersionName = "$verMajor.$verMinor.$verPatch"
val appVersionCode = verMajor.toInt() * 10000 + verMinor.toInt() * 100 + verPatch.toInt()

// Signature release : keystore.properties vit hors du dépôt (ORIZONX_SIGNING_DIR, sinon %USERPROFILE%\OrizonX-signing).
// Les secrets ne sont lus qu'au moment du build et ne sont jamais affichés.
val signingDir: File = System.getenv("ORIZONX_SIGNING_DIR")?.takeIf { it.isNotBlank() }?.let { File(it) }
    ?: File(System.getProperty("user.home"), "OrizonX-signing")
val signingProps = File(signingDir, "keystore.properties")

android {
    namespace = "com.orizonx.client"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.orizonx.client"
        minSdk = 30
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
    }

    signingConfigs {
        create("release") {
            if (signingProps.isFile) {
                val props = Properties().apply { signingProps.inputStream().use { load(it) } }
                storeFile = signingDir.resolve(props.getProperty("storeFile", ""))
                storePassword = props.getProperty("storePassword")
                keyAlias = props.getProperty("keyAlias")
                keyPassword = props.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests.all {
            it.systemProperty("tabx.vectors", rootProject.file("../protocol/test-vectors.json").absolutePath)
            it.systemProperty("orizonx.version.file", versionFile.absolutePath)
        }
    }
}

// Seules les tâches release exigent la clé : debug et tests n'en ont pas besoin.
gradle.taskGraph.whenReady {
    val needsKey = allTasks.any { it.project == project && it.name.contains("Release") }
    if (needsKey && !signingProps.isFile) {
        throw GradleException(
            "Signature release impossible : $signingProps est introuvable. " +
                "Crée ce fichier (storeFile, storePassword, keyAlias, keyPassword) ou pointe ORIZONX_SIGNING_DIR vers le dossier qui le contient.",
        )
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
