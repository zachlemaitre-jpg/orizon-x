package com.orizonx.client.actions

import org.junit.Assert.assertEquals
import org.junit.Test

class ActionsIconsTest {
    @Test
    fun mutedAlwaysShowsMute() {
        assertEquals(VolumeIcon.MUTE, ActionsIcons.volume(0.9f, muted = true))
        assertEquals(VolumeIcon.MUTE, ActionsIcons.volume(0f, muted = true))
    }

    @Test
    fun volumeThresholds() {
        assertEquals(VolumeIcon.LOW, ActionsIcons.volume(0f, false))
        assertEquals(VolumeIcon.LOW, ActionsIcons.volume(0.33f, false))
        assertEquals(VolumeIcon.MEDIUM, ActionsIcons.volume(0.34f, false))
        assertEquals(VolumeIcon.MEDIUM, ActionsIcons.volume(0.66f, false))
        assertEquals(VolumeIcon.HIGH, ActionsIcons.volume(0.67f, false))
        assertEquals(VolumeIcon.HIGH, ActionsIcons.volume(1f, false))
    }

    @Test
    fun volumeFollowsTheDisplayedPercentage() {
        // 33.6 % is shown as "34 %": the icon must agree.
        assertEquals(VolumeIcon.MEDIUM, ActionsIcons.volume(0.336f, false))
        assertEquals(VolumeIcon.LOW, ActionsIcons.volume(0.334f, false))
    }

    @Test
    fun brightnessThresholds() {
        assertEquals(BrightnessIcon.NONE, ActionsIcons.brightness(0f))
        assertEquals(BrightnessIcon.NONE, ActionsIcons.brightness(0.004f))
        assertEquals(BrightnessIcon.LOW, ActionsIcons.brightness(0.01f))
        assertEquals(BrightnessIcon.LOW, ActionsIcons.brightness(0.33f))
        assertEquals(BrightnessIcon.MEDIUM, ActionsIcons.brightness(0.34f))
        assertEquals(BrightnessIcon.MEDIUM, ActionsIcons.brightness(0.66f))
        assertEquals(BrightnessIcon.HIGH, ActionsIcons.brightness(0.67f))
        assertEquals(BrightnessIcon.HIGH, ActionsIcons.brightness(1f))
    }

    @Test
    fun valuesOutsideTheRangeAreClamped() {
        assertEquals(VolumeIcon.HIGH, ActionsIcons.volume(7f, false))
        assertEquals(VolumeIcon.LOW, ActionsIcons.volume(-1f, false))
        assertEquals(BrightnessIcon.NONE, ActionsIcons.brightness(-1f))
    }

    @Test
    fun wifiBySignal() {
        assertEquals(WifiIcon.STRONG, ActionsIcons.wifi(true, 100))
        assertEquals(WifiIcon.STRONG, ActionsIcons.wifi(true, 67))
        assertEquals(WifiIcon.MEDIUM, ActionsIcons.wifi(true, 66))
        assertEquals(WifiIcon.MEDIUM, ActionsIcons.wifi(true, 34))
        assertEquals(WifiIcon.WEAK, ActionsIcons.wifi(true, 33))
        assertEquals(WifiIcon.WEAK, ActionsIcons.wifi(true, 0))
    }

    @Test
    fun wifiOnButNotConnectedIsWeak() {
        assertEquals(WifiIcon.WEAK, ActionsIcons.wifi(true, null))
    }

    @Test
    fun wifiOffIsStrongWhateverTheSignal() {
        assertEquals(WifiIcon.STRONG, ActionsIcons.wifi(false, null))
        assertEquals(WifiIcon.STRONG, ActionsIcons.wifi(false, 10))
    }
}
