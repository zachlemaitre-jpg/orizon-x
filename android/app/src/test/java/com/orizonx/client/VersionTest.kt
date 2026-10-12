package com.orizonx.client

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Test

/** The APK version comes from host-prototype/version.py (single source), read by Gradle. */
class VersionTest {
    @Test
    fun buildVersionMatchesVersionPy() {
        val text = File(checkNotNull(System.getProperty("orizonx.version.file"))).readText()
        val match = Regex("""__version__\s*=\s*["'](\d+)\.(\d+)\.(\d+)["']""").find(text)!!
        val (major, minor, patch) = match.destructured.toList().map { it.toInt() }
        assertEquals("$major.$minor.$patch", BuildConfig.VERSION_NAME)
        assertEquals(major * 10000 + minor * 100 + patch, BuildConfig.VERSION_CODE)
    }
}
