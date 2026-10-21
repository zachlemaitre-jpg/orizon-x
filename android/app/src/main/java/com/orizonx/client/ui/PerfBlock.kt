package com.orizonx.client.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** How many one-second points the graph's width stands for (the PC keeps this many). */
private const val GRAPH_POINTS = 60

/**
 * A performance block: icon, [name] and [value] on top, the [series] graph in the free space, then the [detail] line.
 * The texts keep their size whatever the block's size; only the graph takes the free space. In [compact] mode (a 1x1
 * block) only the icon, the name and the value are shown, centred.
 *
 * [series] are heights in 0..1, oldest first; the series whose index is in [dashed] are drawn with a dashed line.
 * No BoxWithConstraints here: this card may sit in places measured with intrinsic sizes, where it crashes.
 */
@Composable
internal fun PerfCard(
    icon: Int,
    name: String,
    value: String,
    detail: String?,
    series: List<List<Float>>,
    dashed: Set<Int>,
    compact: Boolean,
    modifier: Modifier = Modifier,
) {
    GlassCard(modifier) {
        if (compact) {
            Column(
                Modifier.fillMaxSize(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Picto(icon, 22.dp)
                Spacer(Modifier.height(4.dp))
                PerfText(name, 13.sp, FontWeight.SemiBold, 1f, TextAlign.Center)
                PerfText(value, 16.sp, FontWeight.Normal, 1f, TextAlign.Center)
            }
        } else {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Picto(icon, 22.dp)
                Spacer(Modifier.width(8.dp))
                PerfText(name, 16.sp, FontWeight.SemiBold, 1f, TextAlign.Start, Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                PerfText(value, 16.sp, FontWeight.Normal, 1f, TextAlign.End)
            }
            Spacer(Modifier.height(4.dp))
            PerfGraph(series, dashed, Modifier.weight(1f).fillMaxWidth())
            if (detail != null) {
                Spacer(Modifier.height(4.dp))
                PerfText(detail, 12.sp, FontWeight.Normal, 0.7f, TextAlign.Start, Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
private fun PerfText(text: String, size: androidx.compose.ui.unit.TextUnit, weight: FontWeight, alpha: Float, align: TextAlign, modifier: Modifier = Modifier) {
    BasicText(
        text,
        modifier = modifier,
        style = TextStyle(color = Color.White.copy(alpha = alpha), fontSize = size, fontWeight = weight, textAlign = align),
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

/**
 * The curves of [series] (heights in 0..1, oldest first) on a faint baseline, smoothed with quadratic midpoints. The graph
 * is [GRAPH_POINTS] points wide and the newest point sits at the right edge, so a short history fills in from the right.
 * The first series also gets a soft gradient under it.
 */
@Composable
internal fun PerfGraph(series: List<List<Float>>, dashed: Set<Int>, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val pad = 2.dp.toPx()
        val w = size.width
        val h = size.height
        val top = pad
        val bottom = h - pad
        val span = (bottom - top).coerceAtLeast(1f)
        drawLine(Color.White.copy(alpha = 0.18f), Offset(0f, bottom), Offset(w, bottom), strokeWidth = 1.dp.toPx())
        for ((index, values) in series.withIndex()) {
            if (values.isEmpty()) continue
            val slots = maxOf(GRAPH_POINTS, values.size)
            val step = if (slots > 1) w / (slots - 1) else 0f
            val first = slots - values.size
            val pts = values.mapIndexed { i, v -> Offset((first + i) * step, bottom - v.coerceIn(0f, 1f) * span) }
            val line = Path().apply {
                moveTo(pts[0].x, pts[0].y)
                if (pts.size == 1) {
                    lineTo(w, pts[0].y)
                } else {
                    for (i in 1 until pts.size) {
                        val prev = pts[i - 1]
                        val cur = pts[i]
                        quadraticTo(prev.x, prev.y, (prev.x + cur.x) / 2f, (prev.y + cur.y) / 2f)
                    }
                    lineTo(pts.last().x, pts.last().y)
                }
            }
            if (index == 0 && pts.size > 1) {
                val area = Path().apply {
                    addPath(line)
                    lineTo(pts.last().x, bottom)
                    lineTo(pts[0].x, bottom)
                    close()
                }
                drawPath(area, Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.25f), Color.Transparent), startY = top, endY = bottom))
            }
            drawPath(
                line,
                Color.White,
                style = Stroke(
                    width = 2.dp.toPx(),
                    cap = StrokeCap.Round,
                    join = StrokeJoin.Round,
                    pathEffect = if (index in dashed) PathEffect.dashPathEffect(floatArrayOf(8f, 6f)) else null,
                ),
            )
        }
    }
}
