package com.orizonx.client.actions

import com.orizonx.client.i18n.Lang
import com.orizonx.client.protocol.FrameWriter
import com.orizonx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Test

class ActionMessagesTest {
    private fun wire(json: org.json.JSONObject) =
        String(FrameWriter.encode(TabletMessage.Action(json)).drop(8).toByteArray(), Charsets.UTF_8)

    @Test
    fun sliderValuesAreRoundedAndClamped() {
        assertEquals("""{"id":"volume.set","value":0.333}""", wire(ActionMessages.volumeSet(1f / 3)))
        assertEquals("""{"id":"brightness.set","value":1}""", wire(ActionMessages.brightnessSet(7f)))
        assertEquals("""{"id":"brightness.set","value":0}""", wire(ActionMessages.brightnessSet(-1f)))
    }

    @Test
    fun booleanAndDriveActions() {
        assertEquals("""{"id":"volume.mute","value":true}""", wire(ActionMessages.volumeMute(true)))
        assertEquals("""{"id":"wifi.set","value":false}""", wire(ActionMessages.wifiSet(false)))
        assertEquals("""{"id":"bluetooth.set","value":true}""", wire(ActionMessages.bluetoothSet(true)))
        assertEquals("""{"id":"airplane.set","value":true}""", wire(ActionMessages.airplaneSet(true)))
        assertEquals("""{"id":"usb.open","drive":"E:"}""", wire(ActionMessages.usbOpen("E:")))
        assertEquals("""{"id":"usb.eject","drive":"E:"}""", wire(ActionMessages.usbEject("E:")))
    }

    @Test
    fun contextPress() {
        assertEquals("""{"id":"context.press","button":"ppt.prev"}""", wire(ActionMessages.contextPress("ppt.prev")))
    }

    @Test
    fun claudeWatchAndSidebarActions() {
        assertEquals("""{"id":"claude.watch","open":true}""", wire(ActionMessages.claudeWatch(true)))
        assertEquals("""{"id":"claude.watch","open":false}""", wire(ActionMessages.claudeWatch(false)))
        assertEquals("""{"id":"claude.new"}""", wire(ActionMessages.claudeNew()))
        assertEquals("""{"id":"claude.artifacts"}""", wire(ActionMessages.claudeArtifacts()))
        assertEquals("""{"id":"claude.customize"}""", wire(ActionMessages.claudeCustomize()))
        assertEquals("""{"id":"claude.more"}""", wire(ActionMessages.claudeMore()))
        assertEquals("""{"id":"claude.show_context"}""", wire(ActionMessages.claudeShowContext()))
        assertEquals("""{"id":"claude.show_usage"}""", wire(ActionMessages.claudeShowUsage()))
        assertEquals("""{"id":"claude.open","title":"Fix \"login\" é"}""", wire(ActionMessages.claudeOpen("Fix \"login\" é")))
    }

    @Test
    fun launchOpenAndCompact() {
        assertEquals("""{"id":"launch.open","target":"settings"}""", wire(ActionMessages.launchOpen("settings")))
        assertEquals("""{"id":"launch.open","target":"downloads"}""", wire(ActionMessages.launchOpen("downloads")))
        assertEquals("""{"id":"claude.compact"}""", wire(ActionMessages.claudeCompact()))
    }

    @Test
    fun claudeFocus() {
        assertEquals("""{"id":"claude.focus"}""", wire(ActionMessages.claudeFocus()))
    }

    @Test
    fun contextLang() {
        assertEquals("""{"id":"context.lang","lang":"en"}""", wire(ActionMessages.contextLang(Lang.EN)))
        assertEquals("""{"id":"context.lang","lang":"fr"}""", wire(ActionMessages.contextLang(Lang.FR)))
    }

    @Test
    fun mediaKeys() {
        assertEquals("""{"id":"media.play_pause"}""", wire(ActionMessages.mediaPlayPause()))
        assertEquals("""{"id":"media.next"}""", wire(ActionMessages.mediaNext()))
        assertEquals("""{"id":"media.previous"}""", wire(ActionMessages.mediaPrevious()))
    }
}
