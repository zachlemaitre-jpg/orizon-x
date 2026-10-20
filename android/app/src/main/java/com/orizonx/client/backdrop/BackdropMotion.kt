package com.orizonx.client.backdrop

import kotlin.math.PI
import kotlin.math.sin

/**
 * The slow drift of the dark grey patches behind the app, without Android: where each patch is and how big at time `t`
 * (seconds). Each centre follows its own Lissajous path (different periods on x and y), the radius breathes a little.
 * Everything is a plain sine of `t`, so it is smooth, bounded, and periodic.
 *
 * Positions are fractions of the width and height of the screen; radii are fractions of its larger side.
 */
object BackdropMotion {
    /** One patch: base centre ([baseX], [baseY]), radius [baseRadius], and how it moves. */
    data class Patch(
        val argb: Long,
        val baseX: Float,
        val baseY: Float,
        val baseRadius: Float,
        val ampX: Float,
        val ampY: Float,
        val periodX: Float,
        val periodY: Float,
        val phaseX: Float,
        val phaseY: Float,
        val periodRadius: Float,
        val phaseRadius: Float,
    )

    /** Radius breathing: plus or minus this fraction of the base radius. */
    const val BREATH = 0.05f

    /** Uneven on purpose: different sizes, greys and places, so the glass panels catch different light across the screen. */
    val PATCHES: List<Patch> = listOf(
        Patch(0xFF26262A, 0.12f, 0.18f, 0.62f, 0.10f, 0.08f, 41f, 29f, 0.0f, 1.3f, 37f, 0.4f),
        Patch(0xFF1C1C1F, 0.86f, 0.30f, 0.50f, 0.09f, 0.12f, 53f, 34f, 2.1f, 0.5f, 43f, 1.9f),
        Patch(0xFF141416, 0.40f, 0.82f, 0.70f, 0.12f, 0.09f, 47f, 59f, 4.0f, 2.6f, 31f, 3.3f),
        Patch(0xFF1C1C1F, 0.92f, 0.88f, 0.44f, 0.08f, 0.10f, 26f, 38f, 1.0f, 3.9f, 49f, 5.1f),
        Patch(0xFF202024, 0.58f, 0.40f, 0.34f, 0.11f, 0.11f, 33f, 57f, 5.2f, 0.9f, 27f, 2.2f),
    )

    private const val TWO_PI = (2.0 * PI).toFloat()

    fun x(patch: Patch, t: Float): Float = patch.baseX + patch.ampX * sin(TWO_PI * t / patch.periodX + patch.phaseX)

    fun y(patch: Patch, t: Float): Float = patch.baseY + patch.ampY * sin(TWO_PI * t / patch.periodY + patch.phaseY)

    fun radius(patch: Patch, t: Float): Float =
        patch.baseRadius * (1f + BREATH * sin(TWO_PI * t / patch.periodRadius + patch.phaseRadius))
}
