package com.orizonx.client.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orizonx.client.R

/** Police du titre « Orizon X » (MAZAGLA), réservée à la marque. */
val BrandFont = FontFamily(Font(R.font.mazagla))

private val CardShape = RoundedCornerShape(20.dp)
private val PanelShape = RoundedCornerShape(14.dp)

private fun edgeBrush(top: Float, bottom: Float) =
    Brush.verticalGradient(listOf(Color.White.copy(alpha = top), Color.White.copy(alpha = bottom)))

/** Frosted glass: translucent fill and light edge. Place it over a blurred, colourful background. */
@Composable
fun GlassCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .clip(CardShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, edgeBrush(0.45f, 0.12f), CardShape)
            .padding(24.dp),
        content = content,
    )
}

/** Simulated glass for overlays above the video: no blur (it would force GPU composition and add latency). */
@Composable
fun GlassPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .clip(PanelShape)
            .background(Color(0x8C141428))
            .border(1.dp, edgeBrush(0.45f, 0.15f), PanelShape)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        content = content,
    )
}

@Composable
fun GlassText(
    text: String,
    size: TextUnit = 14.sp,
    alpha: Float = 1f,
    mono: Boolean = false,
    weight: FontWeight = FontWeight.Normal,
    color: Color = Color.White,
    align: TextAlign? = null,
) {
    BasicText(
        text = text,
        style = TextStyle(
            color = color.copy(alpha = alpha),
            fontSize = size,
            fontFamily = if (mono) FontFamily.Monospace else FontFamily.Default,
            fontWeight = weight,
            textAlign = align ?: TextAlign.Unspecified,
        ),
    )
}
