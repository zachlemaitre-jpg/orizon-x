package com.orizonx.client.keyboard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KeyboardStateTest {
    private var now = 0L
    private val kb = KeyboardState { now }
    private val layout = KeyLayouts.of(KeyboardLayoutId.AZERTY)
    private val a = layout.key(0x10, false)!! // a
    private val z = layout.key(0x11, false)!! // z
    private val shift = layout.key(0x2A, false)!!
    private val ctrl = layout.key(0x1D, false)!!
    private val altGr = layout.key(0x38, true)!!
    private val caps = layout.key(0x3A, false)!!
    private val win = layout.key(0x5B, true)!!
    private val d = layout.key(0x20, false)!! // d

    private fun down(k: KeySpec) = KeyEvent(k.sc, k.ext, true)
    private fun up(k: KeySpec) = KeyEvent(k.sc, k.ext, false)

    @Test
    fun winTappedAloneIsPressedAndReleasedLikeARealKeyboard() {
        // A tap on Win opens Start; it never stays latched (it would hold Win down on the PC).
        assertEquals(listOf(down(win)), kb.touchDown(1, win))
        now = 80
        assertEquals(listOf(up(win)), kb.touchUp(1))
        now = 200
        assertEquals(listOf(down(win)), kb.touchDown(2, win))
        now = 260
        assertEquals(listOf(up(win)), kb.touchUp(2))
        assertEquals(listOf(down(a)), kb.touchDown(3, a))
        assertEquals(listOf(up(a)), kb.touchUp(3))
    }

    @Test
    fun winHeldWithAnotherFingerMakesAShortcut() {
        assertEquals(listOf(down(win)), kb.touchDown(1, win))
        assertEquals(listOf(down(d)), kb.touchDown(2, d))
        assertEquals(listOf(up(d)), kb.touchUp(2))
        assertEquals(listOf(up(win)), kb.touchUp(1))
    }

    @Test
    fun simpleKeyIsDownThenUp() {
        assertEquals(listOf(down(a)), kb.touchDown(1, a))
        now = 80
        assertEquals(listOf(up(a)), kb.touchUp(1))
    }

    @Test
    fun noRepeatBeforeHalfASecond() {
        kb.touchDown(1, a)
        now = 499
        assertTrue(kb.tick().isEmpty())
    }

    @Test
    fun repeatStartsAfter500msAndThenEvery33ms() {
        kb.touchDown(1, a)
        now = 500
        assertEquals(listOf(down(a)), kb.tick())
        now = 520
        assertTrue(kb.tick().isEmpty())
        now = 533
        assertEquals(listOf(down(a)), kb.tick())
        now = 566
        assertEquals(listOf(down(a)), kb.tick())
        assertEquals(listOf(up(a)), kb.touchUp(1))
        now = 700
        assertTrue(kb.tick().isEmpty())
    }

    @Test
    fun onlyTheKeyPressedLastRepeats() {
        kb.touchDown(1, a)
        now = 100
        kb.touchDown(2, z)
        now = 700
        assertEquals(listOf(down(z)), kb.tick())
        kb.touchUp(2)
        // a was pressed 700 ms ago: it takes over.
        assertEquals(listOf(down(a)), kb.tick())
    }

    @Test
    fun capsLockAndModifiersDoNotRepeat() {
        kb.touchDown(1, caps)
        now = 2000
        assertTrue(kb.tick().isEmpty())
        kb.touchUp(1)
        kb.touchDown(2, shift)
        now = 4000
        assertTrue(kb.tick().isEmpty())
    }

    @Test
    fun capsLockIsAnOrdinaryKey() {
        assertEquals(listOf(down(caps)), kb.touchDown(1, caps))
        assertEquals(listOf(up(caps)), kb.touchUp(1))
    }

    @Test
    fun chordHeldWithTwoFingersReleasesTheModifierWithItsFinger() {
        assertEquals(listOf(down(ctrl)), kb.touchDown(1, ctrl))
        now = 50
        assertEquals(listOf(down(a)), kb.touchDown(2, a))
        now = 100
        assertEquals(listOf(up(a)), kb.touchUp(2))
        now = 150
        assertEquals(listOf(up(ctrl)), kb.touchUp(1))
        assertTrue(kb.visuals().isEmpty())
    }

    @Test
    fun modifierReleasedBeforeTheKeyStillGoesUp() {
        kb.touchDown(1, shift)
        kb.touchDown(2, a)
        assertEquals(listOf(up(shift)), kb.touchUp(1))
        assertEquals(listOf(up(a)), kb.touchUp(2))
    }

    @Test
    fun tapOnAModifierLatchesItUntilTheNextKeyIsReleased() {
        assertEquals(listOf(down(shift)), kb.touchDown(1, shift))
        now = 80
        assertTrue(kb.touchUp(1).isEmpty())
        assertEquals(KeyVisual.LATCHED, kb.visuals()[shift.id])
        now = 1000
        assertEquals(listOf(down(a)), kb.touchDown(2, a))
        assertEquals(KeyVisual.LATCHED, kb.visuals()[shift.id])
        now = 1100
        assertEquals(listOf(up(a), up(shift)), kb.touchUp(2))
        assertTrue(kb.visuals().isEmpty())
        // The latch is gone: the next key is alone.
        assertEquals(listOf(down(z)), kb.touchDown(3, z))
        assertEquals(listOf(up(z)), kb.touchUp(3))
    }

    @Test
    fun latchStaysWhileAKeyHeldBeforeItIsReleased() {
        kb.touchDown(1, a)
        now = 100
        kb.touchDown(2, shift)
        now = 150
        kb.touchUp(2) // latched after a went down
        now = 200
        assertEquals(listOf(up(a)), kb.touchUp(1)) // a is older than the latch: the latch stays
        assertEquals(KeyVisual.LATCHED, kb.visuals()[shift.id])
        now = 300
        kb.touchDown(3, z)
        assertEquals(listOf(up(z), up(shift)), kb.touchUp(3))
    }

    @Test
    fun severalLatchesAreAllReleasedAfterTheKey() {
        kb.touchDown(1, ctrl)
        kb.touchUp(1)
        now = 500
        kb.touchDown(2, shift)
        kb.touchUp(2)
        now = 1000
        kb.touchDown(3, a)
        assertEquals(listOf(up(a), up(shift), up(ctrl)), kb.touchUp(3))
    }

    @Test
    fun doubleTapLocksTheModifier() {
        kb.touchDown(1, shift)
        now = 60
        kb.touchUp(1)
        now = 200 // 140 ms after the first tap's release
        assertTrue(kb.touchDown(2, shift).isEmpty())
        assertTrue(kb.touchUp(2).isEmpty())
        assertEquals(KeyVisual.LOCKED, kb.visuals()[shift.id])
        // The lock survives keys.
        now = 2000
        kb.touchDown(3, a)
        assertEquals(listOf(up(a)), kb.touchUp(3))
        assertEquals(KeyVisual.LOCKED, kb.visuals()[shift.id])
    }

    @Test
    fun tapOnALockedModifierUnlocksIt() {
        kb.touchDown(1, shift)
        now = 60
        kb.touchUp(1)
        now = 200
        kb.touchDown(2, shift)
        kb.touchUp(2)
        now = 5000
        assertEquals(listOf(up(shift)), kb.touchDown(3, shift))
        assertTrue(kb.touchUp(3).isEmpty())
        assertTrue(kb.visuals().isEmpty())
    }

    @Test
    fun slowSecondTapReleasesTheLatchInsteadOfLocking() {
        kb.touchDown(1, shift)
        now = 60
        kb.touchUp(1)
        now = 60 + KeyboardState.DOUBLE_TAP_MS
        assertEquals(listOf(up(shift)), kb.touchDown(2, shift))
        assertTrue(kb.touchUp(2).isEmpty())
        assertTrue(kb.visuals().isEmpty())
    }

    @Test
    fun differentModifiersDoNotMakeADoubleTap() {
        kb.touchDown(1, shift)
        now = 40
        kb.touchUp(1)
        now = 100
        assertEquals(listOf(down(ctrl)), kb.touchDown(2, ctrl))
        kb.touchUp(2)
        assertEquals(KeyVisual.LATCHED, kb.visuals()[shift.id])
        assertEquals(KeyVisual.LATCHED, kb.visuals()[ctrl.id])
    }

    @Test
    fun leftAndRightAltAreDifferentKeys() {
        val alt = layout.key(0x38, false)!!
        assertEquals(listOf(down(alt)), kb.touchDown(1, alt))
        assertEquals(listOf(down(altGr)), kb.touchDown(2, altGr))
        assertEquals(KeyVisual.PRESSED, kb.visuals()[alt.id])
        assertEquals(KeyVisual.PRESSED, kb.visuals()[altGr.id])
    }

    @Test
    fun multiTouchFollowsEachFinger() {
        assertEquals(listOf(down(a)), kb.touchDown(1, a))
        assertEquals(listOf(down(z)), kb.touchDown(2, z))
        assertEquals(setOf(a.id, z.id), kb.visuals().keys)
        assertEquals(listOf(up(a)), kb.touchUp(1))
        assertEquals(listOf(up(z)), kb.touchUp(2))
    }

    @Test
    fun secondFingerOnTheSameKeyIsIgnored() {
        assertEquals(listOf(down(a)), kb.touchDown(1, a))
        assertTrue(kb.touchDown(2, a).isEmpty())
        assertTrue(kb.touchUp(2).isEmpty())
        assertEquals(listOf(up(a)), kb.touchUp(1))
    }

    @Test
    fun unknownPointerUpIsIgnored() {
        assertTrue(kb.touchUp(99).isEmpty())
    }

    @Test
    fun releaseAllPutsEverythingUpAndForgets() {
        kb.touchDown(1, a)
        kb.touchDown(2, ctrl)
        now = 100
        kb.touchDown(3, shift)
        kb.touchUp(3) // latched
        now = 150
        val events = kb.releaseAll()
        assertEquals(setOf(up(a), up(ctrl), up(shift)), events.toSet())
        assertEquals(3, events.size)
        assertTrue(kb.visuals().isEmpty())
        assertTrue(kb.touchUp(1).isEmpty())
    }

    @Test
    fun resetSendsNothing() {
        kb.touchDown(1, a)
        kb.reset()
        assertTrue(kb.visuals().isEmpty())
        assertTrue(kb.tick().isEmpty())
    }
}
