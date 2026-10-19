package com.orizonx.client.actions

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ActionsStateTest {
    private val full = """
        {"v":1,
         "clock":{"epoch_ms":1760185920000,"utc_offset_min":120},
         "battery":{"available":true,"percent":76,"charging":true},
         "audio":{"available":true,"volume":0.42,"muted":false},
         "media":{"available":true},
         "brightness":{"available":true,"value":0.70},
         "wifi":{"available":true,"on":true,"ssid":"Maison"},
         "bluetooth":{"available":true,"on":true,"connected":["Casque","Souris"]},
         "airplane":{"available":true,"on":false},
         "usb":[{"drive":"E:","label":"KINGSTON","free_bytes":12884901888,"total_bytes":31914983424}],
         "notice":{"code":"usb_busy","drive":"E:"}}
    """.trimIndent()

    private fun parse(text: String) = ActionsState.parse(JSONObject(text))

    @Test
    fun fullStateIsParsed() {
        val s = parse(full)
        assertEquals(ClockState(1760185920000L, 120), s.clock)
        assertEquals(BatteryState(76, true), s.battery)
        assertEquals(AudioState(0.42f, false), s.audio)
        assertTrue(s.mediaAvailable)
        assertEquals(BrightnessState(0.70f), s.brightness)
        assertEquals(WifiState(true, "Maison"), s.wifi)
        assertEquals(BluetoothState(true, listOf("Casque", "Souris")), s.bluetooth)
        assertEquals(AirplaneState(false), s.airplane)
        assertEquals(listOf(UsbDrive("E:", "KINGSTON", 12884901888L, 31914983424L)), s.usb)
        assertEquals(Notice("usb_busy", "E:"), s.notice)
    }

    @Test
    fun emptyObjectGivesAnEmptyState() {
        assertEquals(ActionsState(), parse("{}"))
    }

    @Test
    fun unavailableSectionsAreNull() {
        val s = parse(
            """{"battery":{"available":false},"audio":{"available":false,"volume":0.5},"media":{"available":false},
               "brightness":{"available":false},"wifi":{"available":false,"on":true},
               "bluetooth":{"available":false},"airplane":{"available":false}}""",
        )
        assertNull(s.battery)
        assertNull(s.audio)
        assertFalse(s.mediaAvailable)
        assertNull(s.brightness)
        assertNull(s.wifi)
        assertNull(s.bluetooth)
        assertNull(s.airplane)
    }

    @Test
    fun sectionWithoutAvailableFlagIsHidden() {
        assertNull(parse("""{"audio":{"volume":0.5,"muted":false}}""").audio)
    }

    @Test
    fun missingMandatoryFieldsHideTheSection() {
        val s = parse(
            """{"clock":{"utc_offset_min":60},"battery":{"available":true,"charging":true},
               "audio":{"available":true,"muted":true},"brightness":{"available":true}}""",
        )
        assertNull(s.clock)
        assertNull(s.battery)
        assertNull(s.audio)
        assertNull(s.brightness)
    }

    @Test
    fun optionalFieldsDefault() {
        val s = parse(
            """{"clock":{"epoch_ms":5},"wifi":{"available":true},"bluetooth":{"available":true,"on":true},
               "audio":{"available":true,"volume":0.1}}""",
        )
        assertEquals(ClockState(5L, 0), s.clock)
        assertEquals(WifiState(false, null), s.wifi)
        assertEquals(BluetoothState(true, emptyList()), s.bluetooth)
        assertEquals(AudioState(0.1f, false), s.audio)
    }

    @Test
    fun valuesAreClampedAndInvalidOnesIgnored() {
        val s = parse(
            """{"audio":{"available":true,"volume":3.5},"brightness":{"available":true,"value":-1},
               "battery":{"available":true,"percent":255,"charging":false}}""",
        )
        assertEquals(1f, s.audio!!.volume, 0f)
        assertEquals(0f, s.brightness!!.value, 0f)
        assertNull(s.battery) // 255 = unknown on Windows
    }

    @Test
    fun nullAndBlankSsidMeansNoSsid() {
        assertNull(parse("""{"wifi":{"available":true,"on":true,"ssid":null}}""").wifi!!.ssid)
        assertNull(parse("""{"wifi":{"available":true,"on":true,"ssid":""}}""").wifi!!.ssid)
    }

    @Test
    fun wrongTypesDoNotThrow() {
        val s = parse("""{"clock":5,"battery":"x","usb":{"a":1},"notice":[],"bluetooth":{"available":true,"connected":"Casque"}}""")
        assertNull(s.clock)
        assertNull(s.battery)
        assertTrue(s.usb.isEmpty())
        assertNull(s.notice)
        assertEquals(emptyList<String>(), s.bluetooth!!.connected)
    }

    @Test
    fun usbListKeepsOrderAndSkipsEntriesWithoutDrive() {
        val s = parse(
            """{"usb":[{"drive":"E:","label":"A","free_bytes":1,"total_bytes":2},
                        {"label":"no letter"},
                        42,
                        {"drive":"F:"}]}""",
        )
        assertEquals(listOf(UsbDrive("E:", "A", 1L, 2L), UsbDrive("F:", "", null, null)), s.usb)
    }

    @Test
    fun emptyUsbList() {
        assertTrue(parse("""{"usb":[]}""").usb.isEmpty())
    }

    @Test
    fun noticeWithoutDriveAndWithoutCode() {
        assertEquals(Notice("action_failed", null), parse("""{"notice":{"code":"action_failed"}}""").notice)
        assertNull(parse("""{"notice":{"drive":"E:"}}""").notice)
    }

    @Test
    fun nowPlayingIsParsed() {
        val s = parse(
            """{"now_playing":{"available":true,"app":"Spotify","title":"Song","artist":"Artist","album":"Album",
               "playing":true,"artwork":"0123456789abcdef0123456789abcdef01234567"}}""",
        )
        assertEquals(
            NowPlaying("Spotify", "Song", "Artist", "Album", true, "0123456789abcdef0123456789abcdef01234567"),
            s.nowPlaying,
        )
    }

    @Test
    fun nowPlayingWithoutArtworkOrOptionalTexts() {
        assertEquals(
            NowPlaying("Chrome", "Video", "", "", false, null),
            parse("""{"now_playing":{"available":true,"app":"Chrome","title":"Video","artwork":null}}""").nowPlaying,
        )
        assertNull(parse("""{"now_playing":{"available":true,"artwork":""}}""").nowPlaying!!.artworkId)
    }

    @Test
    fun nowPlayingIsNullWhenAbsentOrUnavailable() {
        assertNull(parse("{}").nowPlaying)
        assertNull(parse("""{"now_playing":{"available":false,"title":"x","playing":true}}""").nowPlaying)
        assertNull(parse("""{"now_playing":{"title":"x"}}""").nowPlaying)
        assertNull(parse("""{"now_playing":"x"}""").nowPlaying)
        assertNull(parse("""{"now_playing":null}""").nowPlaying)
    }

    @Test
    fun nowPlayingNullTextsBecomeEmpty() {
        val n = parse("""{"now_playing":{"available":true,"app":null,"title":null,"artist":null,"album":null}}""").nowPlaying!!
        assertEquals(NowPlaying("", "", "", "", false, null), n)
    }

    @Test
    fun wifiSignalIsParsedClampedAndTolerant() {
        fun signal(raw: String) = parse("""{"wifi":{"available":true,"on":true,"signal":$raw}}""").wifi!!.signal
        assertEquals(72, signal("72"))
        assertEquals(0, signal("0"))
        assertEquals(100, signal("250"))
        assertEquals(0, signal("-5"))
        assertEquals(58, signal("57.6"))
        assertEquals(40, signal("\"40\""))
        assertNull(signal("null"))
        assertNull(signal("\"strong\""))
        assertNull(signal("true"))
        assertNull(signal("[]"))
        assertNull(parse("""{"wifi":{"available":true,"on":true}}""").wifi!!.signal)
    }

    @Test
    fun contextIsParsed() {
        val s = parse(
            """{"context":{"available":true,"app":"PowerPoint","profile":"powerpoint","buttons":[
                {"id":"ppt.prev","icon":"arrow_left","label":"Précédent"},
                {"id":"ppt.next","icon":"arrow_right","label":"Suivant"}]}}""",
        )
        assertEquals(
            ContextBar(
                "PowerPoint", "powerpoint",
                listOf(ContextButton("ppt.prev", "arrow_left", "Précédent"), ContextButton("ppt.next", "arrow_right", "Suivant")),
            ),
            s.context,
        )
    }

    @Test
    fun contextAbsentOrUnavailableIsNull() {
        assertNull(parse("{}").context)
        assertNull(parse("""{"context":{"available":false,"app":"X","profile":"x","buttons":[{"id":"a","icon":"copy","label":"A"}]}}""").context)
        assertNull(parse("""{"context":{"app":"X","profile":"x","buttons":[{"id":"a","icon":"copy","label":"A"}]}}""").context)
        assertNull(parse("""{"context":null}""").context)
        assertNull(parse("""{"context":{"available":true,"app":"X","profile":"x"}}""").context)
        assertNull(parse("""{"context":{"available":true,"app":"X","profile":"x","buttons":[]}}""").context)
    }

    @Test
    fun contextKeepsAtMostEightButtons() {
        val buttons = (1..11).joinToString(",") { """{"id":"b$it","icon":"copy","label":"B$it"}""" }
        val s = parse("""{"context":{"available":true,"app":"X","profile":"x","buttons":[$buttons]}}""")
        assertEquals((1..8).map { "b$it" }, s.context!!.buttons.map { it.id })
    }

    @Test
    fun contextIsTolerantToBadButtons() {
        val s = parse(
            """{"context":{"available":true,"app":null,"buttons":[
                {"icon":"copy","label":"no id"}, 5, null, {"id":"","icon":"copy"},
                {"id":"ok","icon":"no_such_icon","label":"Ok"}, {"id":"bare"}]}}""",
        )
        val c = s.context!!
        assertEquals("", c.app)
        assertEquals("", c.profile)
        assertEquals(listOf(ContextButton("ok", "no_such_icon", "Ok"), ContextButton("bare", "", "")), c.buttons)
    }

    private fun page(id: String, vararg ids: String): String =
        """{"id":"$id","label":"L-$id","buttons":[${ids.joinToString(",") { """{"id":"$it","icon":"copy","label":"B$it"}""" }}]}"""

    private fun pagesJson(vararg pages: String, buttons: String = """{"id":"top","icon":"copy","label":"Top"}"""): String =
        """{"context":{"available":true,"app":"Illustrator","profile":"illustrator","buttons":[$buttons],"pages":[${pages.joinToString(",")}]}}"""

    @Test
    fun contextWithoutPagesIsOneMainPageOfTheButtons() {
        val c = parse(
            """{"context":{"available":true,"app":"X","profile":"x","buttons":[{"id":"a","icon":"copy","label":"A"}]}}""",
        ).context!!
        assertEquals(1, c.pages.size)
        assertEquals(listOf("a"), c.pages[0].buttons.map { it.id })
        assertEquals(c.buttons, c.pages[0].buttons)
    }

    @Test
    fun contextWithEmptyPagesFallsBackToTheButtons() {
        val c = parse(
            """{"context":{"available":true,"app":"X","profile":"x","pages":[],"buttons":[{"id":"a","icon":"copy","label":"A"}]}}""",
        ).context!!
        assertEquals(1, c.pages.size)
        assertEquals(listOf("a"), c.pages[0].buttons.map { it.id })
    }

    @Test
    fun contextPagesAreParsedWithIdLabelAndButtons() {
        val c = parse(pagesJson(page("tools", "t1", "t2"), page("edit", "e1"))).context!!
        assertEquals(listOf("tools", "edit"), c.pages.map { it.id })
        assertEquals(listOf("L-tools", "L-edit"), c.pages.map { it.label })
        assertEquals(listOf("t1", "t2"), c.pages[0].buttons.map { it.id })
        assertEquals(ContextButton("e1", "copy", "Be1"), c.pages[1].buttons[0])
        // `buttons` is page 1, whatever the legacy top-level list says.
        assertEquals(c.pages[0].buttons, c.buttons)
    }

    @Test
    fun contextKeepsAtMostFourPages() {
        val c = parse(pagesJson(*(1..5).map { page("p$it", "b$it") }.toTypedArray())).context!!
        assertEquals(listOf("p1", "p2", "p3", "p4"), c.pages.map { it.id })
    }

    @Test
    fun contextDropsEmptyPages() {
        val c = parse(pagesJson(page("a", "a1"), page("empty"), """{"id":"nobtn"}""", page("c", "c1"))).context!!
        assertEquals(listOf("a", "c"), c.pages.map { it.id })
    }

    @Test
    fun contextKeepsAtMostEightButtonsPerPage() {
        val c = parse(pagesJson(page("a", *(1..9).map { "b$it" }.toTypedArray()))).context!!
        assertEquals((1..8).map { "b$it" }, c.pages[0].buttons.map { it.id })
    }

    @Test
    fun contextWithOnlyEmptyPagesIsNull() {
        assertNull(parse(pagesJson(page("a"), page("b"))).context)
    }

    private fun iconJson(icon: String): String =
        """{"context":{"available":true,"app":"X","profile":"x","icon":$icon,"buttons":[{"id":"a","icon":"copy","label":"A"}]}}"""

    @Test
    fun contextIconIsParsed() {
        assertEquals("0123456789abcdef0123456789abcdef01234567", parse(iconJson("\"0123456789abcdef0123456789abcdef01234567\"")).context!!.icon)
    }

    @Test
    fun contextIconAbsentNullOrNotAStringIsNull() {
        assertNull(parse("""{"context":{"available":true,"app":"X","profile":"x","buttons":[{"id":"a","icon":"copy","label":"A"}]}}""").context!!.icon)
        assertNull(parse(iconJson("null")).context!!.icon)
        assertNull(parse(iconJson("5")).context!!.icon)
        assertNull(parse(iconJson("true")).context!!.icon)
        assertNull(parse(iconJson("{}")).context!!.icon)
        assertNull(parse(iconJson("[\"x\"]")).context!!.icon)
        assertNull(parse(iconJson("\"\"")).context!!.icon)
        assertNull(parse(iconJson("\"  \"")).context!!.icon)
    }

    @Test
    fun contextIconSurvivesPages() {
        val c = parse(
            """{"context":{"available":true,"app":"Illustrator","profile":"illustrator","icon":"abc",
                "buttons":[],"pages":[{"id":"tools","label":"Tools","buttons":[{"id":"t","icon":"pen","label":"T"}]}]}}""",
        ).context!!
        assertEquals("abc", c.icon)
        assertEquals(listOf("tools"), c.pages.map { it.id })
    }

    private fun tabsJson(count: Int, pageExtra: String = ""): String {
        val buttons = (1..count).joinToString(",") { """{"id":"tab.$it","icon":"tab","label":"Tab $it","active":${it == 2}}""" }
        return """{"context":{"available":true,"app":"Chrome","profile":"browser","buttons":[],
            "pages":[{"id":"tabs","label":"Tabs",$pageExtra"buttons":[$buttons]}]}}"""
    }

    @Test
    fun scrollPageKeepsUpToTwentyFourButtons() {
        val page = parse(tabsJson(30, "\"scroll\":true,")).context!!.pages[0]
        assertEquals(true, page.scroll)
        assertEquals((1..24).map { "tab.$it" }, page.buttons.map { it.id })
    }

    @Test
    fun otherPagesStillKeepEightButtons() {
        val page = parse(tabsJson(24)).context!!.pages[0]
        assertEquals(false, page.scroll)
        assertEquals((1..8).map { "tab.$it" }, page.buttons.map { it.id })
        val explicitFalse = parse(tabsJson(24, "\"scroll\":false,")).context!!.pages[0]
        assertEquals(8, explicitFalse.buttons.size)
    }

    @Test
    fun scrollFlagIsTolerant() {
        for (raw in listOf("\"scroll\":null,", "\"scroll\":\"true\",", "\"scroll\":1,", "\"scroll\":{},", "")) {
            assertEquals(raw, false, parse(tabsJson(3, raw)).context!!.pages[0].scroll)
        }
    }

    @Test
    fun activeFlagIsParsedAndTolerant() {
        val buttons = parse(tabsJson(3, "\"scroll\":true,")).context!!.pages[0].buttons
        assertEquals(listOf(false, true, false), buttons.map { it.active })
        assertEquals(ContextButton("tab.2", "tab", "Tab 2", active = true), buttons[1])
        val c = parse(
            """{"context":{"available":true,"app":"X","profile":"x","buttons":[
                {"id":"a","icon":"copy","label":"A"},{"id":"b","icon":"copy","label":"B","active":null},
                {"id":"c","icon":"copy","label":"C","active":"true"},{"id":"d","icon":"copy","label":"D","active":1},
                {"id":"e","icon":"copy","label":"E","active":true}]}}""",
        ).context!!
        assertEquals(listOf(false, false, false, false, true), c.buttons.map { it.active })
    }

    @Test
    fun legacyButtonsListIsStillLimitedToEight() {
        val buttons = (1..12).joinToString(",") { """{"id":"b$it","icon":"copy","label":"B$it"}""" }
        val c = parse("""{"context":{"available":true,"app":"X","profile":"x","buttons":[$buttons]}}""").context!!
        assertEquals(8, c.buttons.size)
        assertEquals(false, c.pages[0].scroll)
    }

    @Test
    fun keyboardSectionIsParsed() {
        assertEquals(
            KeyboardInfo(com.orizonx.client.keyboard.KeyboardLayoutId.AZERTY),
            parse("""{"keyboard":{"available":true,"layout":"azerty"}}""").keyboard,
        )
        assertEquals(
            KeyboardInfo(com.orizonx.client.keyboard.KeyboardLayoutId.QWERTY),
            parse("""{"keyboard":{"available":true,"layout":"qwerty"}}""").keyboard,
        )
    }

    @Test
    fun keyboardAbsentOrUnavailableIsNull() {
        assertNull(parse("{}").keyboard)
        assertNull(parse("""{"keyboard":null}""").keyboard)
        assertNull(parse("""{"keyboard":{"available":false,"layout":"azerty"}}""").keyboard)
        assertNull(parse("""{"keyboard":{"layout":"azerty"}}""").keyboard)
    }

    @Test
    fun unknownOrMissingKeyboardLayoutIsQwerty() {
        val qwerty = com.orizonx.client.keyboard.KeyboardLayoutId.QWERTY
        assertEquals(qwerty, parse("""{"keyboard":{"available":true,"layout":"dvorak"}}""").keyboard!!.layout)
        assertEquals(qwerty, parse("""{"keyboard":{"available":true}}""").keyboard!!.layout)
        assertEquals(qwerty, parse("""{"keyboard":{"available":true,"layout":null}}""").keyboard!!.layout)
        assertEquals(qwerty, parse("""{"keyboard":{"available":true,"layout":5}}""").keyboard!!.layout)
    }

    @Test
    fun trackpadSectionIsParsed() {
        assertEquals(true, parse("""{"trackpad":{"available":true}}""").trackpad)
        assertEquals(false, parse("{}").trackpad)
        assertEquals(false, parse("""{"trackpad":null}""").trackpad)
        assertEquals(false, parse("""{"trackpad":{"available":false}}""").trackpad)
        assertEquals(false, parse("""{"trackpad":{}}""").trackpad)
    }

    @Test
    fun gamepadSectionIsParsed() {
        assertEquals(GamepadInfo(true), parse("""{"gamepad":{"available":true}}""").gamepad)
        assertEquals(
            GamepadInfo(false, GamepadProblem.DRIVER_MISSING),
            parse("""{"gamepad":{"available":false,"reason":"driver_missing"}}""").gamepad,
        )
        assertEquals(GamepadInfo(false, GamepadProblem.ERROR), parse("""{"gamepad":{"available":false,"reason":"error"}}""").gamepad)
    }

    @Test
    fun gamepadAbsentIsNullAndOddReasonsAreErrors() {
        assertNull(parse("{}").gamepad)
        assertNull(parse("""{"gamepad":null}""").gamepad)
        assertNull(parse("""{"gamepad":"yes"}""").gamepad)
        assertEquals(GamepadInfo(false, GamepadProblem.ERROR), parse("""{"gamepad":{"available":false}}""").gamepad)
        assertEquals(GamepadInfo(false, GamepadProblem.ERROR), parse("""{"gamepad":{"available":false,"reason":5}}""").gamepad)
        assertEquals(GamepadInfo(false, GamepadProblem.ERROR), parse("""{"gamepad":{"available":false,"reason":"other"}}""").gamepad)
        assertEquals(GamepadInfo(false, GamepadProblem.ERROR), parse("""{"gamepad":{"available":"true"}}""").gamepad)
        assertEquals(GamepadInfo(false, GamepadProblem.ERROR), parse("""{"gamepad":{}}""").gamepad)
    }

    @Test
    fun nowPlayingCoverIdStillParsed() {
        val n = parse(
            """{"now_playing":{"available":true,"app":"Spotify","title":"T","playing":true,"artwork":"0123456789abcdef0123456789abcdef01234567"}}""",
        ).nowPlaying!!
        assertEquals("0123456789abcdef0123456789abcdef01234567", n.artworkId)
    }

    @Test
    fun usbKindDefaultsToStick() {
        val s = parse(
            """{"usb":[{"drive":"E:","kind":"stick"},{"drive":"F:","kind":"disk"},{"drive":"G:"},
                        {"drive":"H:","kind":"weird"},{"drive":"I:","kind":null},{"drive":"J:","kind":5},
                        {"drive":"K:","kind":"DISK"}]}""",
        )
        assertEquals(
            listOf(UsbKind.STICK, UsbKind.DISK, UsbKind.STICK, UsbKind.STICK, UsbKind.STICK, UsbKind.STICK, UsbKind.DISK),
            s.usb.map { it.kind },
        )
    }
}
