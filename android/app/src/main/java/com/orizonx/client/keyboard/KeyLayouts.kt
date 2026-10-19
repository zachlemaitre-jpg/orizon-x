package com.orizonx.client.keyboard

/** Layout the PC reports in `keyboard.layout`: French AZERTY (ISO) or US QWERTY (ANSI). */
enum class KeyboardLayoutId(val wire: String) {
    AZERTY("azerty"),
    QWERTY("qwerty"),
    ;

    companion object {
        /** Anything but "azerty" (unknown, missing) is the US layout. */
        fun fromWire(value: String?): KeyboardLayoutId = if (value?.trim()?.lowercase() == "azerty") AZERTY else QWERTY
    }
}

/** One cell of a keyboard row: a key or an empty space, [width] in key units (a normal key is 1). */
sealed interface KeyCell {
    val width: Float
}

data class Gap(override val width: Float) : KeyCell

/**
 * A physical key, sent to the PC by its scan code ([sc], with the E0 prefix when [ext]).
 * [base], [shift] and [altGr] are the characters it gives on each level (empty when it has none).
 * [modifier] keys (Shift, Ctrl, Alt, Win, AltGr) latch and lock; [repeat] is false for keys that must not auto-repeat.
 */
data class KeySpec(
    val sc: Int,
    val ext: Boolean,
    val base: String,
    val shift: String = "",
    val altGr: String = "",
    override val width: Float = 1f,
    val modifier: Boolean = false,
    val repeat: Boolean = true,
) : KeyCell {
    /** Identity of the physical key: the scan code, plus 0x100 for the extended (E0) ones. */
    val id: Int get() = sc or (if (ext) 0x100 else 0)
}

class KeyboardLayout(val id: KeyboardLayoutId, val rows: List<List<KeyCell>>) {
    val keys: List<KeySpec> = rows.flatMap { row -> row.filterIsInstance<KeySpec>() }

    fun key(sc: Int, ext: Boolean): KeySpec? = keys.firstOrNull { it.sc == sc && it.ext == ext }
}

/** The two keyboards of spec section 4. Every row is [ROW_WIDTH] units wide: 15 for the main block, a gap, 3 for the navigation block. */
object KeyLayouts {
    const val ROW_WIDTH = 18.25f

    fun of(id: KeyboardLayoutId): KeyboardLayout = if (id == KeyboardLayoutId.AZERTY) AZERTY else QWERTY

    private fun key(sc: Int, base: String, shift: String = "", altGr: String = "", width: Float = 1f) =
        KeySpec(sc, false, base, shift, altGr, width)

    private fun ext(sc: Int, base: String, width: Float = 1f) = KeySpec(sc, true, base, width = width)

    private fun mod(sc: Int, ext: Boolean, base: String, width: Float) = KeySpec(sc, ext, base, width = width, modifier = true)

    /** Keys of consecutive scan codes starting at [first], one per base label (letters: no shift or AltGr character). */
    private fun run(first: Int, bases: List<String>): List<KeySpec> = bases.mapIndexed { i, b -> key(first + i, b) }

    /** The number row 0x02..0x0B from (base, shift, altGr) triples. */
    private fun digitRow(vararg labels: Triple<String, String, String>): List<KeySpec> =
        labels.mapIndexed { i, (b, s, a) -> key(0x02 + i, b, s, a) }

    private fun functionRow(esc: String, del: String): List<KeyCell> = buildList {
        add(key(0x01, esc, width = 1.5f))
        for (i in 1..10) add(key(0x3A + i, "F$i"))
        add(key(0x57, "F11"))
        add(key(0x58, "F12"))
        add(ext(0x53, del, 1.5f))
        add(Gap(3.25f))
    }

    private fun backspace() = key(0x0E, "⌫", width = 2f)
    private fun tab() = key(0x0F, "Tab", width = 1.5f)
    private fun caps(label: String) = KeySpec(0x3A, false, label, width = 1.75f, repeat = false)
    private fun space() = key(0x39, "", width = 6f)

    private fun bottomRow(altGr: String, menu: String): List<KeyCell> = listOf(
        mod(0x1D, false, "Ctrl", 1.5f), mod(0x5B, true, "Win", 1.5f), mod(0x38, false, "Alt", 1.5f),
        space(),
        mod(0x38, true, altGr, 1.5f), ext(0x5D, menu, 1.5f), mod(0x1D, true, "Ctrl", 1.5f),
        Gap(0.25f), ext(0x4B, "←"), ext(0x50, "↓"), ext(0x4D, "→"),
    )

    private val AZERTY: KeyboardLayout by lazy {
        val digits = digitRow(
            Triple("&", "1", ""), Triple("é", "2", "~"), Triple("\"", "3", "#"), Triple("'", "4", "{"), Triple("(", "5", "["),
            Triple("-", "6", "|"), Triple("è", "7", "`"), Triple("_", "8", "\\"), Triple("ç", "9", "^"), Triple("à", "0", "@"),
        )
        val rows = listOf(
            functionRow("Échap", "Suppr"),
            listOf(key(0x29, "²")) + digits + listOf(key(0x0C, ")", "°", "]"), key(0x0D, "=", "+", "}"), backspace()) +
                listOf(Gap(0.25f), ext(0x52, "Inser"), ext(0x47, "Début"), ext(0x49, "Pg préc")),
            listOf<KeyCell>(tab()) + run(0x10, "a z e r t y u i o p".split(" ")) +
                listOf(key(0x1A, "^", "¨"), key(0x1B, "$", "£", "¤"), key(0x1C, "Entrée", width = 1.5f)) +
                listOf(Gap(1.25f), ext(0x4F, "Fin"), ext(0x51, "Pg suiv")),
            listOf<KeyCell>(caps("Verr. Maj")) + run(0x1E, "q s d f g h j k l".split(" ")) +
                listOf(key(0x27, "m"), key(0x28, "ù", "%"), key(0x2B, "*", "µ"), Gap(1.25f), Gap(3.25f)),
            listOf<KeyCell>(mod(0x2A, false, "Maj", 1.25f), key(0x56, "<", ">")) +
                run(0x2C, "w x c v b n".split(" ")) +
                listOf(key(0x32, ",", "?"), key(0x33, ";", "."), key(0x34, ":", "/"), key(0x35, "!", "§"), mod(0x36, false, "Maj", 2.75f)) +
                listOf(Gap(1.25f), ext(0x48, "↑"), Gap(1f)),
            bottomRow("AltGr", "Menu"),
        )
        KeyboardLayout(KeyboardLayoutId.AZERTY, rows)
    }

    private val QWERTY: KeyboardLayout by lazy {
        val digits = digitRow(
            Triple("1", "!", ""), Triple("2", "@", ""), Triple("3", "#", ""), Triple("4", "$", ""), Triple("5", "%", ""),
            Triple("6", "^", ""), Triple("7", "&", ""), Triple("8", "*", ""), Triple("9", "(", ""), Triple("0", ")", ""),
        )
        val rows = listOf(
            functionRow("Esc", "Del"),
            listOf(key(0x29, "`", "~")) + digits + listOf(key(0x0C, "-", "_"), key(0x0D, "=", "+"), backspace()) +
                listOf(Gap(0.25f), ext(0x52, "Ins"), ext(0x47, "Home"), ext(0x49, "PgUp")),
            listOf<KeyCell>(tab()) + run(0x10, "q w e r t y u i o p".split(" ")) +
                listOf(key(0x1A, "[", "{"), key(0x1B, "]", "}"), key(0x2B, "\\", "|", width = 1.5f)) +
                listOf(Gap(1.25f), ext(0x4F, "End"), ext(0x51, "PgDn")),
            listOf<KeyCell>(caps("Caps")) + run(0x1E, "a s d f g h j k l".split(" ")) +
                listOf(key(0x27, ";", ":"), key(0x28, "'", "\""), key(0x1C, "Enter", width = 2.25f), Gap(3.25f)),
            listOf<KeyCell>(mod(0x2A, false, "Shift", 2.25f)) + run(0x2C, "z x c v b n m".split(" ")) +
                listOf(key(0x33, ",", "<"), key(0x34, ".", ">"), key(0x35, "/", "?"), mod(0x36, false, "Shift", 2.75f)) +
                listOf(Gap(1.25f), ext(0x48, "↑"), Gap(1f)),
            bottomRow("Alt", "Menu"),
        )
        KeyboardLayout(KeyboardLayoutId.QWERTY, rows)
    }
}
