package com.orizonx.client.claude

import com.orizonx.client.i18n.Lang
import org.junit.Assert.assertEquals
import org.junit.Test

class ClaudeFormatTest {
    private val now = 1_800_000_000L

    private fun age(secondsAgo: Long, lang: Lang) = ClaudeFormat.age(now - secondsAgo, now, lang)

    @Test
    fun ageInEnglish() {
        assertEquals("just now", age(0, Lang.EN))
        assertEquals("just now", age(59, Lang.EN))
        assertEquals("1 min", age(60, Lang.EN))
        assertEquals("3 min", age(3 * 60 + 20, Lang.EN))
        assertEquals("59 min", age(59 * 60 + 59, Lang.EN))
        assertEquals("1 h", age(3_600, Lang.EN))
        assertEquals("2 h", age(2 * 3_600 + 1_800, Lang.EN))
        assertEquals("23 h", age(86_399, Lang.EN))
        assertEquals("yesterday", age(86_400, Lang.EN))
        assertEquals("yesterday", age(172_799, Lang.EN))
        assertEquals("2 d", age(172_800, Lang.EN))
        assertEquals("12 d", age(12 * 86_400L + 5, Lang.EN))
    }

    @Test
    fun ageInFrench() {
        assertEquals("à l'instant", age(10, Lang.FR))
        assertEquals("3 min", age(200, Lang.FR))
        assertEquals("2 h", age(2 * 3_600, Lang.FR))
        assertEquals("hier", age(90_000, Lang.FR))
        assertEquals("5 j", age(5 * 86_400L, Lang.FR))
    }

    @Test
    fun ageOfTheFutureOrUnknownIsHandled() {
        assertEquals("just now", ClaudeFormat.age(now + 30, now, Lang.EN)) // the PC clock is a little ahead
        assertEquals("just now", ClaudeFormat.age(now + 5_000, now, Lang.EN))
    }

    @Test
    fun tokensBelowAThousandAreExact() {
        assertEquals("0", ClaudeFormat.tokens(0, Lang.EN))
        assertEquals("842", ClaudeFormat.tokens(842, Lang.EN))
        assertEquals("999", ClaudeFormat.tokens(999, Lang.FR))
    }

    @Test
    fun tokensInThousandsAreRoundedToTheNearestK() {
        assertEquals("1 k", ClaudeFormat.tokens(1_000, Lang.EN))
        assertEquals("1 k", ClaudeFormat.tokens(1_499, Lang.EN))
        assertEquals("2 k", ClaudeFormat.tokens(1_500, Lang.EN))
        assertEquals("561 k", ClaudeFormat.tokens(561_234, Lang.EN))
        assertEquals("561 k", ClaudeFormat.tokens(561_234, Lang.FR))
        assertEquals("999 k", ClaudeFormat.tokens(999_499, Lang.EN))
    }

    @Test
    fun tokensInMillionsUseTheLanguagesDecimalSeparator() {
        assertEquals("1.2 M", ClaudeFormat.tokens(1_234_567, Lang.EN))
        assertEquals("1,2 M", ClaudeFormat.tokens(1_234_567, Lang.FR))
        assertEquals("1.0 M", ClaudeFormat.tokens(1_000_000, Lang.EN))
        assertEquals("1.0 M", ClaudeFormat.tokens(999_600, Lang.EN)) // rounds up to a million, not "1000 k"
        assertEquals("12.5 M", ClaudeFormat.tokens(12_500_000, Lang.EN))
        assertEquals("12,5 M", ClaudeFormat.tokens(12_500_000, Lang.FR))
    }

    @Test
    fun negativeTokensAreZero() {
        assertEquals("0", ClaudeFormat.tokens(-5, Lang.EN))
    }
}
