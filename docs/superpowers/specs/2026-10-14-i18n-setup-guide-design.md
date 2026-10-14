# Orizon X — Interface Android en anglais et guide de première connexion (design)

Date : 2026-10-14
Statut : validé par l'utilisateur, à implémenter (branche `i18n-guide` depuis `master`)

## 1. Objectif

- L'app Android parle **anglais ou français**. Par défaut, elle suit la langue du système, et un bouton permet de forcer l'une ou l'autre.
- Un **guide de première connexion**, adapté à la marque de l'appareil, mène l'utilisateur jusqu'à la première connexion. Il coche chaque étape en direct.
- Le PC accompagne : messages d'attente plus guidants, et libellés de la barre contextuelle dans la langue de l'appareil.

**Exclus** : d'autres langues que EN et FR ; la langue de la fenêtre PC, qui garde son propre bouton ; plusieurs appareils.

## 2. Langue de l'app Android

- **Table de textes** `i18n/Strings.kt`, sur le modèle de `messages.py` côté PC.
  - Chaque clé a sa version `en` et `fr`.
  - Pas de `strings.xml` : changer de langue sans recréer l'Activity, donc sans couper le flux.
  - Elle couvre tous les textes visibles :
    - l'écran d'attente, le mode Actions et le HUD ;
    - les raisons d'attente de `Receiver` et les erreurs d'action (`ActionsFormat`) ;
    - les descriptions d'accessibilité ;
    - les tailles (« 12 GB free » / « 12 Go libres », avec le séparateur décimal de la langue).
  - Paramètres : `{name}` remplacé à l'appel.
- **Langue courante** : `CompositionLocal` (`LocalLang`) fourni par `OrizonXApp`, pour que tout se redessine aussitôt.
- **Préférence** (SharedPreferences, clé `language`) : `system` (par défaut), `en` ou `fr`.
  - `system` donne `fr` si la langue du système (`LocaleList.getDefault()[0].language`) est `fr`, et `en` sinon.
- **Bouton** : une petite pastille en haut à droite de l'écran d'attente, qui affiche `Auto`, `EN` ou `FR`. Un tap passe au choix suivant (système → EN → FR → système).
  - Elle est aussi présente sur l'écran Actions, à côté de « Changer de mode ».

## 3. Protocole et PC : la langue de l'appareil

- **`DEVICE_INFO`** gagne un champ facultatif `"lang":"en"|"fr"`, la langue effective. La version du protocole reste 1.
  - Le PC le lit avec tolérance : absent ou inconnu, il retient `fr`, le comportement actuel.
- **Changement en cours de session** (mode Actions) : l'appareil envoie l'`ACTION` `{"id":"context.lang","lang":"en"}`.
  - Le `ContextProvider` change de langue et diffuse aussitôt la barre traduite.
  - En mode Écran, rien n'est envoyé : aucun texte du PC n'est affiché.
- **Profils** (`actions/context_profiles.py`) :
  - chaque bouton a un libellé `en` et un libellé `fr` ;
  - les noms d'app affichés aussi (« Browser » / « Navigateur », « Explorer » / « Explorateur ») ;
  - le nom par défaut est « App » en anglais et « Application » en français.
- **Hub** : la fabrique reçoit la langue lue dans `DEVICE_INFO` et la passe au `ContextProvider`. `context.lang` est routé vers lui.
- **`protocol/PROTOCOL.md`** documente `lang` et `context.lang`.

## 4. Guide de première connexion (Android)

**Affichage.** Il apparaît sur l'écran d'attente, dans une carte verre « Setup guide » / « Guide de connexion ».
- La carte s'ouvre seule tant que le débogage USB est désactivé.
- Sinon, elle reste accessible par un bouton « Setup guide », qui la rouvre.
- Elle se ferme et disparaît dès que le PC est connecté.

**Marque.** `Build.MANUFACTURER`, sans tenir compte de la casse, donne un guide :

| Guide | Fabricants (alias) |
|---|---|
| `samsung` | samsung |
| `xiaomi` | xiaomi, redmi, poco |
| `pixel` | google |
| `oneplus` | oneplus, oppo, realme |
| `huawei` | huawei |
| `honor` | honor |
| `motorola` | motorola |
| `lenovo` | lenovo |
| `sony` | sony |
| `nothing` | nothing |
| `generic` | tout le reste |

Chaque guide donne deux chemins, en anglais et en français, avec les noms de menus de la marque :
- le chemin vers « Numéro de version » (`build_path`) ;
- le chemin vers « Options pour les développeurs » (`dev_path`).

Il peut porter une **note** propre à la marque. On n'en met que dans les cas sûrs :
- Xiaomi : « Sur HyperOS ou MIUI, tape 7 fois sur la *version de l'OS* ».
- Huawei : « Dans la notification USB, choisis *Transfert de fichiers* ».

**Étapes, vérifiées en direct.** L'état est relu au retour au premier plan (`ON_RESUME`), puis toutes les 2 s tant que la carte est ouverte.

| # | Étape | Fait quand | Bouton |
|---|---|---|---|
| 1 | Activer les options pour les développeurs : tape 7 fois sur *Numéro de version* (`build_path`) | `Settings.Global.DEVELOPMENT_SETTINGS_ENABLED` = 1 | « Ouvrir À propos » (`ACTION_DEVICE_INFO_SETTINGS`) |
| 2 | Activer le débogage USB (`dev_path`) | `Settings.Global.ADB_ENABLED` = 1 | « Ouvrir les options développeur » (`ACTION_APPLICATION_DEVELOPMENT_SETTINGS`) |
| 3 | Brancher un câble USB qui transmet des données | branché en USB (`ACTION_BATTERY_CHANGED`, `EXTRA_PLUGGED` = `BATTERY_PLUGGED_USB`) | — |
| 4 | Accepter « Autoriser le débogage USB ? » et cocher « Toujours autoriser » | conseil, non vérifiable sur l'appareil | — |
| 5 | Ouvrir Orizon X sur le PC | le PC est connecté (la carte se ferme) | — |

Règles d'affichage :
- une étape faite est cochée et atténuée ;
- la première étape non faite est mise en avant ;
- les étapes 1 et 2 restent visibles et cochées une fois faites.

Si un `Intent` n'existe pas sur l'appareil, le bouton ouvre les Paramètres généraux (`ACTION_SETTINGS`). La lecture d'un réglage qui échoue donne « inconnu », et l'étape s'affiche sans coche ni erreur.

**Code** :
- `setup/SetupGuides.kt` : données pures, avec les guides par marque et `guideFor(manufacturer)` ;
- `setup/SetupState.kt` : état pur des étapes, à partir d'un `SetupProbe` injectable (dev options, adb, usb) ;
- `ui/SetupGuideCard.kt` : l'affichage.

## 5. PC : messages d'attente

`adb.no_device` devient un guide court, en anglais et en français :
« No device found. 1. Install Orizon X on the device and open it: it shows how to turn on USB debugging. 2. Plug it in with a USB cable that carries data. »

`adb.unauthorized` ajoute : « Tick *Always allow* to skip this next time. »

La fenêtre les affiche tels quels. Elle sait déjà passer à la ligne.

## 6. Tests

- **Android (JVM)** :
  - chaque clé de `Strings` a `en` et `fr`, non vides, avec les mêmes paramètres `{…}` ;
  - langue effective (`system` + locale fr/de/en, `en`, `fr`) et cycle du bouton ;
  - tailles formatées dans les deux langues ;
  - `guideFor` : chaque fabricant et alias, insensible à la casse, `generic` sinon ;
  - chaque guide a ses chemins dans les deux langues ;
  - `SetupState` avec de fausses sondes : aucune étape faite, dev seul, dev + adb, tout branché, sonde en échec ;
  - `DEVICE_INFO` avec `lang`, et l'action `context.lang`.
- **PC** :
  - libellés de profils en `en` et `fr` pour chaque bouton ;
  - `DEVICE_INFO.lang` lu (absent ou inconnu → `fr`) ;
  - le hub crée la barre dans la langue reçue ;
  - `context.lang` change la langue et diffuse la barre ;
  - nouveaux messages `adb.*` en `en` et `fr`.
- **Réel**, avec l'accord de l'utilisateur, sur sa tablette :
  - bascule EN/FR, à l'attente et en mode Actions (barre traduite) ;
  - le guide, débogage USB désactivé puis réactivé. Désactiver le débogage coupe la connexion au PC : à faire seulement avec l'accord de l'utilisateur.
