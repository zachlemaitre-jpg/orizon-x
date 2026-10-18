package com.orizonx.client.i18n

import androidx.compose.runtime.Composable

/** Every user-visible text of the app. Each key has an English and a French version in [Strings]. */
enum class S {
    // Waiting screen
    LOGO_DESC,
    WAITING_FOR_PC,
    PC_CONNECTED_ACTIONS,
    ROLE_SCREEN,
    ROLE_ACTIONS,
    ROLE_FRAME,
    HINT_LAUNCH_PC,
    HINT_HUD_LONG,
    HINT_HUD_SHORT,
    PROTOCOL_VERSION,

    // Language pill
    LANG_AUTO,
    LANG_EN,
    LANG_FR,
    LANG_PILL_DESC,

    // Why the waiting screen is shown
    REASON_PORT_BUSY,
    REASON_PC_UNRESPONSIVE,
    REASON_PROTOCOL,
    REASON_DECODER,
    REASON_LISTEN,
    REASON_PC_DISCONNECTED,
    REASON_ERROR,
    DETAIL_CODEC_UNSUPPORTED,
    DETAIL_CONFIG_INVALID,
    DETAIL_NO_DECODER,
    DETAIL_DECODER_CONFIG,
    DETAIL_DECODER_RECREATE,

    // HUD
    HUD_LATENCY,
    HUD_OFFSET,
    HUD_OFFSET_SYNC,

    // Actions screen
    SWITCH_MODE,
    CONNECTING_TO_PC,
    NOTICE_USB_BUSY,
    NOTICE_USB_FAILED,
    NOTICE_RADIO_DENIED,
    NOTICE_DEFAULT,
    SOUND,
    MUTED,
    MUTE_DESC,
    UNMUTE_DESC,
    PERCENT,
    NOW_PLAYING,
    BRIGHTNESS,
    WIFI,
    BLUETOOTH,
    AIRPLANE,
    STATE_ON,
    STATE_OFF,
    USB_DRIVE,
    USB_OPEN_DESC,
    USB_EJECT_DESC,

    // ActionsFormat
    BATTERY,
    BATTERY_CHARGING,
    FREE_SPACE,
    SIZE_GB,
    SIZE_MB,

    // Setup guide
    SETUP_GUIDE,
    SETUP_STEP_1,
    SETUP_STEP_2,
    SETUP_STEP_3,
    SETUP_STEP_4,
    SETUP_STEP_5,
    SETUP_TIP_SEARCH,
    SETUP_OPEN_ABOUT,
    SETUP_OPEN_DEV,
    SETUP_DONE_DESC,

    // Frame mode
    FRAME_NO_FOLDER,
    FRAME_EMPTY,
    FRAME_UNREADABLE,
    FRAME_LOADING,
    FRAME_PAUSE_DESC,
    FRAME_PLAY_DESC,
    FRAME_NEXT_DESC,
    FRAME_CROP,
    FRAME_FIT,
    FRAME_DISPLAY_DESC,
    FRAME_INTERVAL_LESS_DESC,
    FRAME_INTERVAL_MORE_DESC,
    FRAME_SECONDS,
    FRAME_MINUTES,
    FRAME_HOURS,
}

/** A text to translate later: key plus arguments, so a language switch can re-translate what is already on screen. */
data class Msg(val key: S, val args: List<Pair<String, Any>>) {
    constructor(key: S, vararg args: Pair<String, Any>) : this(key, args.toList())
}

object Strings {
    private fun t(en: String, fr: String) = en to fr

    private val table: Map<S, Pair<String, String>> = mapOf(
        S.LOGO_DESC to t("Orizon X logo", "Logo Orizon X"),
        S.WAITING_FOR_PC to t("Waiting for the PC…", "En attente du PC…"),
        S.PC_CONNECTED_ACTIONS to t("PC connected — Actions mode", "PC connecté — mode Actions"),
        S.ROLE_SCREEN to t("Screen", "Écran"),
        S.ROLE_ACTIONS to t("Actions", "Actions"),
        S.ROLE_FRAME to t("Frame", "Tableau"),
        S.HINT_LAUNCH_PC to t("Open Orizon X on the PC.", "Lance Orizon X sur le PC."),
        S.HINT_HUD_LONG to t("Long-press with 4 fingers: connection info", "Appui long à 4 doigts : infos de connexion"),
        S.HINT_HUD_SHORT to t("Long-press with 4 fingers: info", "Appui long à 4 doigts : infos"),
        S.PROTOCOL_VERSION to t("protocol v{version}", "protocole v{version}"),

        S.LANG_AUTO to t("Auto", "Auto"),
        S.LANG_EN to t("EN", "EN"),
        S.LANG_FR to t("FR", "FR"),
        S.LANG_PILL_DESC to t("Language: {value}", "Langue : {value}"),

        S.REASON_PORT_BUSY to t("Port {port} already in use, retrying…", "Port {port} déjà utilisé, nouvel essai…"),
        S.REASON_PC_UNRESPONSIVE to t("The PC stopped responding", "Le PC ne répond plus"),
        S.REASON_PROTOCOL to t("Invalid protocol: {detail}", "Protocole invalide : {detail}"),
        S.REASON_DECODER to t("Decoder unavailable: {detail}", "Décodeur indisponible : {detail}"),
        S.REASON_LISTEN to t("Cannot listen: {detail}", "Écoute impossible : {detail}"),
        S.REASON_PC_DISCONNECTED to t("PC disconnected", "PC déconnecté"),
        S.REASON_ERROR to t("Error: {detail}", "Erreur : {detail}"),
        S.DETAIL_CODEC_UNSUPPORTED to t("unsupported codec: {codec}", "codec non supporté : {codec}"),
        S.DETAIL_CONFIG_INVALID to t("invalid CONFIG: {config}", "CONFIG invalide : {config}"),
        S.DETAIL_NO_DECODER to t("no H.264 decoder available", "aucun décodeur H.264 disponible"),
        S.DETAIL_DECODER_CONFIG to t("cannot configure the decoder: {detail}", "configuration du décodeur impossible : {detail}"),
        S.DETAIL_DECODER_RECREATE to t("failed right after recreation: {detail}", "échec juste après recréation : {detail}"),

        S.HUD_LATENCY to t("send→disp. {avg} / max {max} ms", "envoi→aff. {avg} / max {max} ms"),
        S.HUD_OFFSET to t("offset {value} ms", "offset {value} ms"),
        S.HUD_OFFSET_SYNC to t("offset: syncing…", "offset : synchro…"),

        S.SWITCH_MODE to t("Change mode", "Changer de mode"),
        S.CONNECTING_TO_PC to t("Connecting to the PC…", "Connexion au PC…"),
        S.NOTICE_USB_BUSY to t("The drive is in use, close any open files", "La clé est utilisée, ferme les fichiers ouverts"),
        S.NOTICE_USB_FAILED to t("Cannot eject the drive", "Impossible d'éjecter la clé"),
        S.NOTICE_RADIO_DENIED to t("Windows won't change this radio", "Windows refuse de changer cette radio"),
        S.NOTICE_DEFAULT to t("Action failed", "Action impossible"),
        S.SOUND to t("Sound", "Son"),
        S.MUTED to t("Muted", "Muet"),
        S.MUTE_DESC to t("Mute", "Couper le son"),
        S.UNMUTE_DESC to t("Unmute", "Réactiver le son"),
        S.PERCENT to t("{value}%", "{value} %"),
        S.NOW_PLAYING to t("Now playing", "Lecture en cours"),
        S.BRIGHTNESS to t("Brightness", "Luminosité"),
        S.WIFI to t("Wi-Fi", "Wi-Fi"),
        S.BLUETOOTH to t("Bluetooth", "Bluetooth"),
        S.AIRPLANE to t("Airplane", "Avion"),
        S.STATE_ON to t("On", "Activé"),
        S.STATE_OFF to t("Off", "Désactivé"),
        S.USB_DRIVE to t("USB drive", "Clé USB"),
        S.USB_OPEN_DESC to t("Open {drive}", "Ouvrir {drive}"),
        S.USB_EJECT_DESC to t("Eject {drive}", "Éjecter {drive}"),

        S.BATTERY to t("PC {percent}%", "PC {percent} %"),
        S.BATTERY_CHARGING to t("PC {percent}% · charging", "PC {percent} % · en charge"),
        S.FREE_SPACE to t("{size} free", "{size} libres"),
        S.SIZE_GB to t("{value} GB", "{value} Go"),
        S.SIZE_MB to t("{value} MB", "{value} Mo"),

        S.SETUP_GUIDE to t("Setup guide", "Guide de connexion"),
        S.SETUP_STEP_1 to t("Turn on developer options: tap 7 times on “Build number”.", "Active les options pour les développeurs : tape 7 fois sur « Numéro de version »."),
        S.SETUP_STEP_2 to t("Turn on USB debugging.", "Active le débogage USB."),
        S.SETUP_STEP_3 to t("Plug in a USB cable that carries data.", "Branche un câble USB qui transmet des données."),
        S.SETUP_STEP_4 to t("If the device asks “Allow USB debugging?”, tick “Always allow” and accept. It only asks once per PC.", "Si l’appareil demande « Autoriser le débogage USB ? », coche « Toujours autoriser » et accepte. Il ne le demande qu’une fois par PC."),
        S.SETUP_STEP_5 to t("Open Orizon X on the PC.", "Ouvre Orizon X sur le PC."),
        S.SETUP_TIP_SEARCH to t("Tip: search “build” in Settings.", "Astuce : cherche « numéro » dans la barre de recherche des Paramètres."),
        S.SETUP_OPEN_ABOUT to t("Open About", "Ouvrir À propos"),
        S.SETUP_OPEN_DEV to t("Open developer options", "Ouvrir les options développeur"),
        S.SETUP_DONE_DESC to t("Done", "Fait"),

        S.FRAME_NO_FOLDER to t("Choose a folder in Orizon X on the PC", "Choisis un dossier dans Orizon X sur le PC"),
        S.FRAME_EMPTY to t("No images or videos in this folder", "Aucune image ni vidéo dans ce dossier"),
        S.FRAME_UNREADABLE to t("Cannot read the folder", "Impossible de lire le dossier"),
        S.FRAME_LOADING to t("Loading…", "Chargement…"),
        S.FRAME_PAUSE_DESC to t("Pause", "Pause"),
        S.FRAME_PLAY_DESC to t("Play", "Lecture"),
        S.FRAME_NEXT_DESC to t("Next", "Suivant"),
        S.FRAME_CROP to t("Crop", "Rogner"),
        S.FRAME_FIT to t("Fit", "Ajuster"),
        S.FRAME_DISPLAY_DESC to t("Display: {value}", "Affichage : {value}"),
        S.FRAME_INTERVAL_LESS_DESC to t("Shorter interval", "Intervalle plus court"),
        S.FRAME_INTERVAL_MORE_DESC to t("Longer interval", "Intervalle plus long"),
        S.FRAME_SECONDS to t("{n} s", "{n} s"),
        S.FRAME_MINUTES to t("{n} min", "{n} min"),
        S.FRAME_HOURS to t("{n} h", "{n} h"),
    )

    /** The en/fr pair of [key]; exposed for the completeness test. */
    fun entry(key: S): Pair<String, String>? = table[key]

    /** [key] in [lang] with every `{name}` replaced from [args]; a [Msg] argument is translated too. */
    fun get(key: S, lang: Lang, vararg args: Pair<String, Any>): String {
        val (en, fr) = table[key] ?: return key.name
        var text = if (lang == Lang.FR) fr else en
        for ((name, value) in args) {
            val rendered = if (value is Msg) get(value.key, lang, *value.args.toTypedArray()) else value.toString()
            text = text.replace("{$name}", rendered)
        }
        return text
    }

    fun get(msg: Msg, lang: Lang): String = get(msg.key, lang, *msg.args.toTypedArray())
}

@Composable
fun tr(key: S, vararg args: Pair<String, Any>): String = Strings.get(key, LocalLang.current, *args)

@Composable
fun tr(msg: Msg): String = Strings.get(msg, LocalLang.current)
