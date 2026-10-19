package com.orizonx.client.keyboard

/** A key going down or up on the PC, by scan code (spec section 3). */
data class KeyEvent(val sc: Int, val ext: Boolean, val down: Boolean)

/** How a key is drawn: finger on it, one-shot latch (light fill), or lock (light fill plus border). */
enum class KeyVisual { UP, PRESSED, LATCHED, LOCKED }

/**
 * The behaviour of the on-screen keyboard, without Android: touches in, [KeyEvent]s to send out.
 *
 * - A normal key goes down with the finger and up with it; held longer than [REPEAT_DELAY_MS] it sends another `down`
 *   every [REPEAT_INTERVAL_MS] (call [tick] often), like a real keyboard, for the key pressed last.
 * - A modifier goes down with the finger. If another normal key was pressed meanwhile it goes up with the finger (a chord
 *   held with two fingers). If not, it stays down as a one-shot latch, released after the next normal key pressed
 *   afterwards goes up. A second tap within [DOUBLE_TAP_MS] of that tap locks it; any later tap on a latched or locked
 *   modifier releases it.
 * - Every finger ([touchDown]'s `pointer`) follows its own key, so several keys can be down at once.
 *
 * [clock] returns milliseconds and is injectable. Not thread-safe: call it from one thread (the UI).
 */
class KeyboardState(private val clock: () -> Long) {
    private class Touch(val key: KeySpec, val downAt: Long, val seq: Int, val consumed: Boolean = false) {
        var used = false
        var lastRepeat = -1L
    }

    private class Latch(val key: KeySpec, val seq: Int, val tappedAt: Long)

    private val touches = LinkedHashMap<Long, Touch>()
    private val latched = LinkedHashMap<Int, Latch>()
    private val locked = LinkedHashMap<Int, KeySpec>()
    private var seq = 0

    private fun down(key: KeySpec) = KeyEvent(key.sc, key.ext, true)
    private fun up(key: KeySpec) = KeyEvent(key.sc, key.ext, false)

    fun touchDown(pointer: Long, key: KeySpec): List<KeyEvent> {
        val now = clock()
        val s = ++seq
        // The same physical key already held by another finger: nothing more to send.
        if (touches.values.any { it.key.id == key.id && !it.consumed }) {
            touches[pointer] = Touch(key, now, s, consumed = true)
            return emptyList()
        }
        if (!key.modifier) {
            for (t in touches.values) if (t.key.modifier && !t.consumed) t.used = true
            touches[pointer] = Touch(key, now, s)
            return listOf(down(key))
        }
        locked.remove(key.id)?.let {
            touches[pointer] = Touch(key, now, s, consumed = true)
            return listOf(up(key))
        }
        latched.remove(key.id)?.let { latch ->
            touches[pointer] = Touch(key, now, s, consumed = true)
            if (now - latch.tappedAt < DOUBLE_TAP_MS) {
                locked[key.id] = key
                return emptyList()
            }
            return listOf(up(key))
        }
        touches[pointer] = Touch(key, now, s)
        return listOf(down(key))
    }

    fun touchUp(pointer: Long): List<KeyEvent> {
        val touch = touches.remove(pointer) ?: return emptyList()
        if (touch.consumed) return emptyList()
        val key = touch.key
        if (key.modifier) {
            if (touch.used) return listOf(up(key))
            latched[key.id] = Latch(key, ++seq, clock())
            return emptyList()
        }
        val out = mutableListOf(up(key))
        // One-shot latches made before this key went down end with it.
        val ended = latched.values.filter { it.seq < touch.seq }
        for (latch in ended.asReversed()) {
            latched.remove(latch.key.id)
            out += up(latch.key)
        }
        return out
    }

    /** Auto-repeat: a `down` for the key pressed last, once held [REPEAT_DELAY_MS], then at most every [REPEAT_INTERVAL_MS]. */
    fun tick(): List<KeyEvent> {
        val now = clock()
        val touch = touches.values.lastOrNull { !it.consumed && !it.key.modifier } ?: return emptyList()
        if (!touch.key.repeat || now - touch.downAt < REPEAT_DELAY_MS) return emptyList()
        if (touch.lastRepeat >= 0 && now - touch.lastRepeat < REPEAT_INTERVAL_MS) return emptyList()
        touch.lastRepeat = now
        return listOf(down(touch.key))
    }

    /** Events that put every key down on the PC back up (fingers, latches, locks), then forget everything. */
    fun releaseAll(): List<KeyEvent> {
        val out = mutableListOf<KeyEvent>()
        val keys = LinkedHashMap<Int, KeySpec>()
        for (t in touches.values) if (!t.consumed) keys[t.key.id] = t.key
        for (l in latched.values) keys[l.key.id] = l.key
        for (k in locked.values) keys[k.id] = k
        for (k in keys.values.reversed()) out += up(k)
        reset()
        return out
    }

    /** Forget everything without sending anything (the PC releases its keys itself, e.g. on `keyboard.release`). */
    fun reset() {
        touches.clear()
        latched.clear()
        locked.clear()
    }

    /** Visual state by key id ([KeySpec.id]); keys not in the map are [KeyVisual.UP]. */
    fun visuals(): Map<Int, KeyVisual> {
        val map = HashMap<Int, KeyVisual>()
        for (t in touches.values) map[t.key.id] = KeyVisual.PRESSED
        for (l in latched.values) map.putIfAbsent(l.key.id, KeyVisual.LATCHED)
        for (k in locked.values) map[k.id] = KeyVisual.LOCKED
        return map
    }

    companion object {
        const val REPEAT_DELAY_MS = 500L
        const val REPEAT_INTERVAL_MS = 33L
        const val DOUBLE_TAP_MS = 300L
    }
}
