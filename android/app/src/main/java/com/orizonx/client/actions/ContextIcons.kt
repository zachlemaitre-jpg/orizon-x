package com.orizonx.client.actions

import com.orizonx.client.R

/**
 * Maps the icon names sent by the PC in the `context` section (spec section 5) to the `ctx_<name>` vector drawables.
 * An unknown or blank name gives the neutral dot, so a newer PC never breaks an older APK.
 */
object ContextIcons {
    /** Every name the PC may send, in the order of the spec. */
    val NAMES: List<String> = listOf(
        "arrow_left", "arrow_right", "arrow_up", "refresh",
        "play_pause", "skip_previous", "skip_next", "heart", "shuffle", "repeat",
        "slideshow", "slideshow_current", "screen_black", "exit",
        "tab_new", "tab_close", "zoom_out", "zoom_in",
        "undo", "redo", "bold", "italic", "underline", "save", "sum", "filter", "copy", "paste",
        "command", "search", "terminal", "comment", "folder_new", "rename", "explorer",
        "screenshot", "desktop", "switch_app",
        // Creative tools (Illustrator, Photoshop, Canva, Figma): tools, objects, view.
        "select", "direct_select", "pen", "text", "rectangle", "ellipse", "line", "brush", "eraser", "eyedropper",
        "crop", "lasso", "marquee", "move", "frame",
        "group", "ungroup", "lock", "unlock", "layer_new", "layer_duplicate", "merge", "deselect", "transform",
        "component", "hide", "paste_front",
        "hand", "zoom_fit", "zoom_100", "zoom_selection", "outline", "rulers", "brush_smaller", "brush_larger", "present",
    )

    /** Drawable resource id for [name] (case-insensitive); [R.drawable.ctx_unknown] when it is not in [NAMES]. */
    fun drawable(name: String?): Int = when (name?.trim()?.lowercase()) {
        "arrow_left" -> R.drawable.ctx_arrow_left
        "arrow_right" -> R.drawable.ctx_arrow_right
        "arrow_up" -> R.drawable.ctx_arrow_up
        "refresh" -> R.drawable.ctx_refresh
        "play_pause" -> R.drawable.ctx_play_pause
        "skip_previous" -> R.drawable.ctx_skip_previous
        "skip_next" -> R.drawable.ctx_skip_next
        "heart" -> R.drawable.ctx_heart
        "shuffle" -> R.drawable.ctx_shuffle
        "repeat" -> R.drawable.ctx_repeat
        "slideshow" -> R.drawable.ctx_slideshow
        "slideshow_current" -> R.drawable.ctx_slideshow_current
        "screen_black" -> R.drawable.ctx_screen_black
        "exit" -> R.drawable.ctx_exit
        "tab_new" -> R.drawable.ctx_tab_new
        "tab_close" -> R.drawable.ctx_tab_close
        "zoom_out" -> R.drawable.ctx_zoom_out
        "zoom_in" -> R.drawable.ctx_zoom_in
        "undo" -> R.drawable.ctx_undo
        "redo" -> R.drawable.ctx_redo
        "bold" -> R.drawable.ctx_bold
        "italic" -> R.drawable.ctx_italic
        "underline" -> R.drawable.ctx_underline
        "save" -> R.drawable.ctx_save
        "sum" -> R.drawable.ctx_sum
        "filter" -> R.drawable.ctx_filter
        "copy" -> R.drawable.ctx_copy
        "paste" -> R.drawable.ctx_paste
        "command" -> R.drawable.ctx_command
        "search" -> R.drawable.ctx_search
        "terminal" -> R.drawable.ctx_terminal
        "comment" -> R.drawable.ctx_comment
        "folder_new" -> R.drawable.ctx_folder_new
        "rename" -> R.drawable.ctx_rename
        "explorer" -> R.drawable.ctx_explorer
        "screenshot" -> R.drawable.ctx_screenshot
        "desktop" -> R.drawable.ctx_desktop
        "switch_app" -> R.drawable.ctx_switch_app
        "select" -> R.drawable.ctx_select
        "direct_select" -> R.drawable.ctx_direct_select
        "pen" -> R.drawable.ctx_pen
        "text" -> R.drawable.ctx_text
        "rectangle" -> R.drawable.ctx_rectangle
        "ellipse" -> R.drawable.ctx_ellipse
        "line" -> R.drawable.ctx_line
        "brush" -> R.drawable.ctx_brush
        "eraser" -> R.drawable.ctx_eraser
        "eyedropper" -> R.drawable.ctx_eyedropper
        "crop" -> R.drawable.ctx_crop
        "lasso" -> R.drawable.ctx_lasso
        "marquee" -> R.drawable.ctx_marquee
        "move" -> R.drawable.ctx_move
        "frame" -> R.drawable.ctx_frame
        "group" -> R.drawable.ctx_group
        "ungroup" -> R.drawable.ctx_ungroup
        "lock" -> R.drawable.ctx_lock
        "unlock" -> R.drawable.ctx_unlock
        "layer_new" -> R.drawable.ctx_layer_new
        "layer_duplicate" -> R.drawable.ctx_layer_duplicate
        "merge" -> R.drawable.ctx_merge
        "deselect" -> R.drawable.ctx_deselect
        "transform" -> R.drawable.ctx_transform
        "component" -> R.drawable.ctx_component
        "hide" -> R.drawable.ctx_hide
        "paste_front" -> R.drawable.ctx_paste_front
        "hand" -> R.drawable.ctx_hand
        "zoom_fit" -> R.drawable.ctx_zoom_fit
        "zoom_100" -> R.drawable.ctx_zoom_100
        "zoom_selection" -> R.drawable.ctx_zoom_selection
        "outline" -> R.drawable.ctx_outline
        "rulers" -> R.drawable.ctx_rulers
        "brush_smaller" -> R.drawable.ctx_brush_smaller
        "brush_larger" -> R.drawable.ctx_brush_larger
        "present" -> R.drawable.ctx_present
        else -> R.drawable.ctx_unknown
    }
}
