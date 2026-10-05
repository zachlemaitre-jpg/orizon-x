package com.orizonx.client.input

import com.orizonx.client.protocol.InputContact
import com.orizonx.client.protocol.Protocol
import com.orizonx.client.protocol.TabletMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InputMapperTest {
    private val w = 1000f
    private val h = 500f
    private val down = Protocol.CONTACT_CONTACT or Protocol.CONTACT_IN_RANGE
    private val canceled = down or Protocol.CONTACT_CANCELED

    private fun mapper() = InputMapper(hudSlopPx = 50f)
    private fun finger(id: Int, x: Float = 100f, y: Float = 100f) = PointerSample(id, Tool.FINGER, x, y)
    private fun touch(vararg contacts: InputContact) = TabletMessage.Input(Protocol.DEVICE_TOUCH, contacts.toList())
    private fun four() = listOf(finger(0), finger(1), finger(2), finger(3))

    @Test
    fun normalizesAndClamps() {
        val out = mapper().process(listOf(finger(0, 500f, 250f), finger(1, -10f, 900f)), w, h, 0)
        assertEquals(listOf(touch(InputContact(0, down, 32768, 32768), InputContact(1, down, 0, 65535))), out.messages)
    }

    @Test
    fun fingerSlotsAreStableAndReused() {
        val m = mapper()
        m.process(listOf(finger(5), finger(7)), w, h, 0)
        assertEquals(listOf(1), m.process(listOf(finger(7)), w, h, 10).messages.single().contacts.map { it.id })
        assertEquals(listOf(0, 1), m.process(listOf(finger(7), finger(9)), w, h, 20).messages.single().contacts.map { it.id })
    }

    @Test
    fun liftingAllFingersSendsEmptyFrame() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        assertEquals(listOf(touch()), m.process(emptyList(), w, h, 10).messages)
    }

    @Test
    fun identicalSnapshotIsNotResent() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        assertTrue(m.process(listOf(finger(0)), w, h, 10).messages.isEmpty())
    }

    @Test
    fun fourthFingerCancelsAndSuppressesUntilAllUp() {
        val m = mapper()
        m.process(listOf(finger(0), finger(1), finger(2)), w, h, 0)
        val cancel = m.process(four(), w, h, 10).messages.single()
        assertEquals(3, cancel.contacts.size)
        assertTrue(cancel.contacts.all { it.flags == canceled })
        assertTrue(m.process(listOf(finger(0, 300f), finger(1)), w, h, 20).messages.isEmpty())
        assertTrue(m.process(emptyList(), w, h, 30).messages.isEmpty())
        assertEquals(1, m.process(listOf(finger(4)), w, h, 40).messages.single().contacts.size)
    }

    @Test
    fun fourFingerHoldTogglesHudOnce() {
        val m = mapper()
        assertFalse(m.process(four(), w, h, 1_000).toggleHud)
        assertEquals(3_000L, m.hudDeadlineMs)
        assertFalse(m.tick(2_999))
        assertTrue(m.tick(3_000))
        assertFalse(m.tick(4_000))
        assertNull(m.hudDeadlineMs)
    }

    @Test
    fun movingAFingerCancelsTheHudGesture() {
        val m = mapper()
        m.process(four(), w, h, 0)
        m.process(listOf(finger(0, 200f), finger(1), finger(2), finger(3)), w, h, 500)
        assertFalse(m.tick(2_000))
    }

    @Test
    fun liftingAFingerCancelsTheHudGesture() {
        val m = mapper()
        m.process(four(), w, h, 0)
        m.process(listOf(finger(0), finger(1), finger(2)), w, h, 500)
        assertFalse(m.tick(2_000))
    }

    @Test
    fun penInRangeCancelsAndIgnoresFingers() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        val pen = PointerSample(0, Tool.PEN, 500f, 250f, inContact = false)
        val out = m.process(listOf(finger(0), pen), w, h, 10).messages
        assertEquals(Protocol.DEVICE_PEN, out[0].device)
        assertEquals(touch(InputContact(0, canceled, 6554, 13107)), out[1])
        assertTrue(m.process(listOf(finger(0, 400f), pen), w, h, 20).messages.isEmpty())
        // le stylet s'éloigne mais la paume reste posée : toujours ignorée
        assertEquals(
            listOf(TabletMessage.Input(Protocol.DEVICE_PEN, emptyList())),
            m.process(listOf(finger(0, 400f)), w, h, 30).messages,
        )
    }

    @Test
    fun penContactConversion() {
        val pen = PointerSample(
            pointerId = 3, tool = Tool.PEN, x = 0f, y = 500f, pressure = 0.5f,
            tiltRad = (Math.PI / 4).toFloat(), orientationRad = (Math.PI / 2).toFloat(), barrel = true,
        )
        val contact = mapper().process(listOf(pen), w, h, 0).messages.single().contacts.single()
        assertEquals(InputContact(0, down or Protocol.CONTACT_BARREL, 0, 65535, 512, 45, 0), contact)
    }

    @Test
    fun hoveringPenHasNoPressure() {
        val pen = PointerSample(0, Tool.PEN, 0f, 0f, pressure = 0.3f, inContact = false)
        val contact = mapper().process(listOf(pen), w, h, 0).messages.single().contacts.single()
        assertEquals(Protocol.CONTACT_IN_RANGE, contact.flags)
        assertEquals(0, contact.pressure)
    }

    @Test
    fun penDuringHoldCancelsTheHudGesture() {
        val m = mapper()
        m.process(four(), w, h, 0)
        m.process(four() + PointerSample(0, Tool.PEN, 500f, 250f, inContact = false), w, h, 500)
        assertNull(m.hudDeadlineMs)
        assertFalse(m.tick(2_000))
    }

    @Test
    fun restingPalmAfterPenLeavesNeverTogglesHud() {
        val m = mapper()
        m.process(four() + PointerSample(0, Tool.PEN, 500f, 250f, inContact = false), w, h, 0)
        m.process(four(), w, h, 100)
        assertFalse(m.tick(2_100))
    }

    @Test
    fun slotFreedInThisFrameIsNotReusedInTheSameFrame() {
        val m = mapper()
        m.process(listOf(finger(5)), w, h, 0)
        assertEquals(listOf(1), m.process(listOf(finger(9, 500f)), w, h, 10).messages.single().contacts.map { it.id })
    }

    @Test
    fun nanValuesNeverCrash() {
        val m = mapper()
        assertTrue(m.process(listOf(finger(0, Float.NaN)), w, h, 0).messages.isEmpty())
        val pen = PointerSample(0, Tool.PEN, 10f, 10f, pressure = Float.NaN, tiltRad = Float.NaN, orientationRad = Float.POSITIVE_INFINITY)
        val c = m.process(listOf(pen), w, h, 10).messages.single().contacts.single()
        assertEquals(Triple(0, 0, 0), Triple(c.pressure, c.tiltX, c.tiltY))
    }

    @Test
    fun reusedPointerIdDisqualifiesTheHudGesture() {
        val m = mapper()
        m.process((0..4).map { finger(it) }, w, h, 0)
        m.process((0..3).map { finger(it) }, w, h, 300)
        m.process((0..3).map { finger(it) } + finger(4, 110f), w, h, 600)
        assertFalse(m.tick(2_000))
    }

    @Test
    fun cancelAllCancelsActiveContactsOnce() {
        val m = mapper()
        m.process(listOf(finger(0)), w, h, 0)
        assertEquals(listOf(touch(InputContact(0, canceled, 6554, 13107))), m.cancelAll())
        assertTrue(m.cancelAll().isEmpty())
    }
}
