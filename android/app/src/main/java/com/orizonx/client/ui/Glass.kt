package com.orizonx.client.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.res.painterResource
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
            .background(Color(0x99202024))
            .border(1.dp, edgeBrush(0.45f, 0.15f), PanelShape)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        content = content,
    )
}

/** Large glass button; [selected] adds a stronger fill and a bright edge. [icon] (a drawable id) sits left of the label. */
@Composable
fun GlassButton(text: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier, icon: Int? = null) {
    Box(
        modifier = modifier
            .heightIn(min = 64.dp)
            .clip(CardShape)
            .background(Color.White.copy(alpha = if (selected) 0.28f else 0.08f))
            .border(
                if (selected) 2.dp else 1.dp,
                if (selected) Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.9f), Color.White.copy(alpha = 0.5f)))
                else edgeBrush(0.35f, 0.10f),
                CardShape,
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 24.dp, vertical = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        val alpha = if (selected) 1f else 0.75f
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (icon != null) {
                Image(
                    painterResource(icon),
                    contentDescription = null,
                    modifier = Modifier.size(30.dp),
                    colorFilter = ColorFilter.tint(Color.White.copy(alpha = alpha)),
                )
                Spacer(Modifier.width(10.dp))
            }
            GlassText(
                text,
                size = 20.sp,
                alpha = alpha,
                weight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            )
        }
    }
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
