package io.github.milkteatw1.screentranslator

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdaterTest {
    private fun release(tag: String, prerelease: Boolean = false, vararg assets: String) =
        """{"tag_name":"$tag","prerelease":$prerelease,"draft":false,"assets":[""" +
            assets.joinToString(",") { """{"name":"$it","size":100,"browser_download_url":"https://x/$tag/$it"}""" } + "]}"

    private fun list(vararg r: String) = r.joinToString(",", "[", "]")
    private val arm = listOf("arm64-v8a", "armeabi-v7a")

    @Test fun versionsCompareNumerically() {
        assertTrue(Updater.newer("0.10.0", "0.9.9"))
        assertTrue(Updater.newer("v0.5.0".removePrefix("v"), "0.4.3"))
        assertFalse(Updater.newer("0.5.0", "0.5.0"))
        assertFalse(Updater.newer("0.4.3", "0.5.0"))
    }

    @Test fun offersTheNewerApkForThisPhone() {
        val json = list(release("v0.5.0", false, "ScreenTranslator-Setup-0.5.0.exe", "ScreenTranslator-0.5.0-arm64.apk"))
        val u = Updater.find(json, "0.4.0", arm)!!
        assertEquals("0.5.0", u.version)
        assertEquals("https://x/v0.5.0/ScreenTranslator-0.5.0-arm64.apk", u.url)
    }

    @Test fun nothingWhenUpToDate() {
        assertNull(Updater.find(list(release("v0.5.0", false, "ScreenTranslator-0.5.0-arm64.apk")), "0.5.0", arm))
    }

    @Test fun aWindowsOnlyReleaseDoesNotHideAnOlderOneWithAnApk() {
        val json = list(
            release("v0.5.2", false, "ScreenTranslator-Setup-0.5.2.exe"),
            release("v0.5.1", false, "ScreenTranslator-Setup-0.5.1.exe", "ScreenTranslator-0.5.1-arm64.apk"))
        assertEquals("0.5.1", Updater.find(json, "0.5.0", arm)!!.version)
    }

    @Test fun preReleasesAndOtherArchitecturesAreSkipped() {
        assertNull(Updater.find(list(release("v0.6.0", true, "ScreenTranslator-0.6.0-arm64.apk")), "0.5.0", arm))
        assertNull(Updater.find(list(release("v0.6.0", false, "ScreenTranslator-0.6.0-x86_64.apk")), "0.5.0", arm))
    }

    @Test fun theSingleApkFitsEveryPhone() {
        val json = list(release("v0.5.17", false, "ScreenTranslator-Setup-0.5.17.exe", "ScreenTranslator-0.5.17.apk"))
        assertEquals("https://x/v0.5.17/ScreenTranslator-0.5.17.apk", Updater.find(json, "0.5.16", arm)!!.url)
        assertEquals("0.5.17", Updater.find(json, "0.5.16", listOf("x86_64"))!!.version)
    }

    @Test fun picksTheNewestWhenSeveralQualify() {
        val json = list(
            release("v0.5.1", false, "ScreenTranslator-0.5.1-arm64.apk"),
            release("v0.5.2", false, "ScreenTranslator-0.5.2-arm64.apk"))
        assertEquals("0.5.2", Updater.find(json, "0.5.0", arm)!!.version)
    }

    @Test fun releasesListsEveryUsableVersionNewestFirst() {
        val json = list(
            release("v0.6.1", false, "ScreenTranslator-0.6.1.apk"),
            release("v0.6.3", false, "ScreenTranslator-Setup-0.6.3.exe"),  // no APK: not listed
            release("v0.6.4", false, "ScreenTranslator-0.6.4.apk"),
            release("v0.7.0", true, "ScreenTranslator-0.7.0.apk"),  // pre-release
            release("v0.6.2", false, "ScreenTranslator-0.6.2-arm64.apk"))
        assertEquals(listOf("0.6.4", "0.6.2", "0.6.1"), Updater.releases(json, arm).map { it.version })
        assertEquals("https://x/v0.6.4/ScreenTranslator-0.6.4.apk", Updater.releases(json, arm)[0].url)
        assertEquals(listOf("0.6.4", "0.6.1"), Updater.releases(json, listOf("x86_64")).map { it.version })  // 0.6.2 is arm64 only
    }

    @Test fun releasesOrdersByVersionNotByListPosition() {
        val json = list(release("v0.9.0", false, "ScreenTranslator-0.9.0.apk"), release("v0.10.0", false, "ScreenTranslator-0.10.0.apk"))
        assertEquals(listOf("0.10.0", "0.9.0"), Updater.releases(json, arm).map { it.version })
    }
}
