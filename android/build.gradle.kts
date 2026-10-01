plugins {
    id("com.android.application") version "9.0.1" apply false
    // AGP 9 intègre Kotlin (KGP 2.2.10) : le plugin Compose doit avoir la même version.
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10" apply false
}
