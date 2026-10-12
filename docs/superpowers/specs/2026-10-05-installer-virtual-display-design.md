# Orizon X — Installateur Windows et écran virtuel intégré (design)

Date : 2026-10-05
Statut : validé par l'utilisateur, à implémenter (branche `pc-app`)
Prérequis : appli PC (`2026-10-05-pc-app-design.md`) et identité visuelle (`2026-10-05-brand-identity-design.md`).

## 0. Contexte : distribution gratuite, en 4 sous-projets

**But global** : l'utilisateur envoie deux fichiers à qui il veut, `OrizonX-Setup.exe` et `OrizonX.apk`, et ça marche sur la plupart des PC Windows et tablettes Android. Pas de Play Store, aucun coût : pas de certificat de signature, pas de compte Microsoft Partner.

1. **Ce document** : installateur Windows tout-en-un, écran virtuel piloté par l'appli, appli PC bilingue.
2. Compatibilité PC : Intel QuickSync, repli logiciel, portables hybrides, diagnostic.
3. Compatibilité tablettes : résolution et débit adaptés, APK release signé avec la clé de l'utilisateur.
4. Guides de première connexion, au cas par cas par fabricant, et traduction de l'app Android (anglais par défaut, suit la langue de la tablette).

Conséquences du « gratuit » acceptées :
- l'exe non signé déclenche SmartScreen (« Informations complémentaires » > « Exécuter quand même ») ;
- le seul pilote d'écran virtuel possible est **VDD** (Virtual Display Driver, MikeTheTech, licence MIT, déjà signé), redistribué dans l'installateur.

La police MAZAGLA appartient à l'utilisateur : aucune mention de licence n'est nécessaire.

## 1. Objectif du sous-projet 1

Un utilisateur sans connaissances techniques suit ce parcours :
1. il lance `OrizonX-Setup.exe` ;
2. il clique Next jusqu'à la fin, avec une seule demande de droits administrateur ;
3. il lance Orizon X ;
4. il branche la tablette, préparée selon le sous-projet 4 ;
5. **un écran étendu apparaît**, à la bonne résolution, placé et mis à l'échelle, sans jamais ouvrir les paramètres de Windows.

**Exclus** :
- les guides de préparation de la tablette (sous-projet 4) ;
- les encodeurs Intel et logiciel (sous-projet 2) ;
- notre propre pilote ;
- la mise à jour automatique.

## 2. Pilotage de VDD

Faits vérifiés sur le paquet VDD 25.7.23 installé chez l'utilisateur :
- le pilote se compose de `MttVDD.inf`, `MttVDD.dll` et `mttvdd.cat` (signé), avec l'ID matériel `Root\MttVDD` et la classe Display ;
- le paquet fournit aussi `devcon.exe` ;
- la config est dans `C:\VirtualDisplayDriver\vdd_settings.xml` (`<monitors><count>`, `<gpu><friendlyname>`, `<resolutions>`…) ;
- le pilote ouvre le canal nommé `\\.\pipe\MTTVirtualDisplayPipe` avec le DACL `D:(A;;GA;;;WD)` : tout le monde y a accès, **sans droits admin** ;
- les commandes repérées dans le binaire sont `RELOAD_DRIVER`, `SETDISPLAYCOUNT`, `SETGPU`, `GETSETTINGS`, `LOGGING`, `LOG_DEBUG`, `HDRPLUS` et `PING`.

À **vérifier en premier** (tâche d'exploration du plan, sur le PC de l'utilisateur, avec son accord, car l'affichage clignote) :
- le format exact des messages (encodage UTF-16 ou ASCII, arguments) et les réponses ;
- si `SETDISPLAYCOUNT n` réécrit le XML et recharge seul ;
- si une résolution ajoutée au XML est prise en compte par `RELOAD_DRIVER` ;
- le délai d'apparition et de disparition de l'écran.

Le code source public de VDD (GitHub `VirtualDrivers/Virtual-Display-Driver`, `Driver.cpp`) sert de référence.

**Module `vdd.py`** (nouveau, sans Qt) :
- `VddController(settings_path, pipe_name)` ;
- `is_installed()` : le canal répond à `PING` ;
- `set_display_count(n)` ;
- `ensure_resolution(w, h, hz)` : ajoute la résolution au XML si elle manque, sans toucher au reste, puis recharge ;
- `set_gpu(friendly_name)` ;
- `reload()`.
- Écritures du XML atomiques (fichier temporaire puis `os.replace`), avec une sauvegarde unique `vdd_settings.xml.bak-orizonx` avant la première modification.

## 3. Cycle de vie de l'écran virtuel

L'écran virtuel n'existe **que quand la tablette est connectée**.

**Au HELLO de la tablette** (largeur, hauteur, dpi), en mode *Extend* :
1. `ensure_resolution(w, h, 60)`, puis `set_display_count(1)`.
2. Attente de l'écran Windows de taille `w×h`, avec `injector.monitors()` interrogé toutes les 200 ms et un **délai maximal de 10 s**.
3. **À chaque allumage du chemin** (révision après le test sur le vrai PC : Windows ne restaurait pas la position choisie, l'écran revenait à droite après `Position = À gauche`) : la **position** réglée est calculée avec `display_layout.place` (écran principal, autres écrans actifs) et passée à `set_path_active(..., mode=..., position=...)` ; dans le repli en deux temps, elle est donnée à la seconde étape (avec le mode). Une fois l'écran allumé, l'**échelle** lue (`get_scale`) est corrigée par `set_scale` si elle diffère de celle réglée (Auto : `auto_scale(dpi)`), sans appel sinon. Un écran trouvé déjà allumé à la bonne taille (gardé par la grâce) n'est pas touché. La paire `applied_position`/`applied_scale` (l'ancien drapeau `layout_applied` est encore lu) reste utile pour ce dernier cas : quand elle diffère des réglages, la position et l'échelle sont appliquées aussi à un écran déjà allumé. Une position ou une échelle changée pendant la préparation est appliquée dès que l'écran est allumé.
4. Repérage de l'index ddagrab de l'écran virtuel (révision après le test sur le vrai PC : `probe_outputs`, une capture ffmpeg par sortie, prenait ~5 s à chaque connexion) : lu instantanément dans DXGI (`dxgi_outputs`) par son nom GDI (`\\.\DISPLAYn`), comme ddagrab le compte (carte DXGI par défaut, rang brut dans `EnumOutputs`) ; `probe_outputs` reste le repli si DXGI échoue ou si l'écran n'est pas sur cette carte. Puis démarrage de la capture.
   - **ffmpeg qui s'arrête seul** pendant que la tablette reste (déplacer l'écran coupe ddagrab : `AcquireNextFrame failed: 887a0026`, DXGI_ERROR_ACCESS_LOST ; sur le vrai PC la session entière tombait, ~8 s de coupure) : la capture est relancée dans la même session, tout de suite, l'index étant recherché de nouveau, sans reconnecter la tablette. Après `MAX_FFMPEG_FAILURES` captures de suite sans vidéo (2 s entre deux relances sans vidéo), état ERROR comme avant. Un changement de **Position** qui déplace l'écran relance la capture aussitôt.
5. **Pendant les étapes 1 à 4**, le moteur répond déjà aux PING de la tablette (le lecteur de session démarre avant la préparation de l'écran). Sinon la tablette coupe après 5 s de silence.

**Au départ de la tablette, sur Stop ou sur Quit** : `set_display_count(0)` après **15 s de grâce** (un débranchement/rebranchement du câble a pris ~5,5 s sur le vrai PC : 5 s expiraient 1 s trop tôt), annulées si la tablette revient entre-temps. Quit ne garde pas cette grâce : il retire l'écran immédiatement.

**Au lancement de l'appli** : `set_display_count(0)`, pour nettoyer après un plantage. **À la désinstallation** : pareil, via l'appli lancée avec `--cleanup`.

**Mode *Duplicate*** : aucun écran virtuel ; capture de l'écran principal (index ddagrab 0), comme l'ancien mode `--output 0`.

**Position** (À droite par défaut, ou À gauche / Au-dessus / En dessous) :
- calculée contre **tous les autres écrans actifs** : au-delà de leur bord le plus éloigné du côté choisi (À droite : x = le plus grand bord droit), centrée sur l'écran **principal** dans l'autre axe, en pixels physiques ; elle ne chevauche donc jamais un second écran physique. Une échelle seule changée ne déplace pas l'écran ;
- appliquée via `SetDisplayConfig` (QueryDisplayConfig, modification de `sourceMode.position`, puis `SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_SAVE_TO_DATABASE | SDC_ALLOW_CHANGES`).

**Échelle** :
- **Auto** = densité de la tablette ÷ 96 × 0,75, arrondie au palier inférieur (le palier Windows à ou sous cette valeur : 100, 125, 150, 175, 200, 225, 250, 300 %), bornée à 100–300 %. Pour 2880×1800 à 274 dpi : 274/96 × 0,75 ≈ 2,14, soit **200 %**. Le facteur 0,75 tient compte de la tablette tenue plus près des yeux qu'un moniteur. La formule est isolée et testée.
- Appliquée par `DisplayConfigSetDeviceInfo` avec le type non documenté `DISPLAYCONFIG_DEVICE_INFO_SET_DPI_SCALE` (-4), en valeur relative au palier recommandé (lu par le type -3). C'est la méthode connue et utilisée par les outils de la communauté.
- En cas d'échec : journalisé, le flux continue.

**Modules** :
- `display_layout.py` : fonctions pures pour la position et l'échelle, plus une fine couche ctypes testée à part ;
- `virtual_display.py` : le cycle de vie, sur `VddController`, avec horloge et moniteurs injectables pour les tests.

## 4. Moteur : intégration

- `Config` gagne les champs `mode` (`"extend"` | `"duplicate"`), `position`, `scale` (`"auto"` ou un pourcentage), et un objet `display` (le gestionnaire de `virtual_display`, ou `None` pour la CLI et les tests).
- La session démarre son lecteur (PING/PONG, stats, input) **avant** la préparation de l'écran. La préparation se fait ensuite, puis ffmpeg démarre sur l'index trouvé.
- Nouvel état `PREPARING_DISPLAY`, avec le détail « Preparing the screen… », affiché par la fenêtre. La tablette affiche son écran d'attente habituel, puis la vidéo. Le protocole ne change pas.
- La sélection d'écran (`output`) disparaît de l'appli. La CLI `relay.py` garde `--output` pour le debug, sans écran virtuel.

## 5. Appli PC : fenêtre et langue

**Langue** :
- `app/i18n.py` contient un dictionnaire `{clé: {"en": …, "fr": …}}` et `tr(key, **fmt)`.
- La langue courante vient des réglages. Sinon, de la valeur `HKCU\Software\OrizonX\Language` écrite par l'installateur. Sinon, l'anglais.
- **Tous** les textes visibles de l'appli passent par `tr` : fenêtre, icône de notification, états, messages d'erreur du moteur. Le moteur émet des **clés et arguments** pour ses messages destinés à l'utilisateur, et la CLI les traduit en anglais.
- Changer de langue dans la fenêtre réapplique immédiatement tous les textes.
- Un test vérifie que chaque clé a ses deux langues et que les arguments `{}` correspondent.

**Fenêtre**, de haut en bas :
1. le logo et « Orizon X » ;
2. l'état ;
3. les réglages :
   - Mode : Extend / Duplicate ;
   - Position : Right / Left / Above / Below ;
   - Scale : Auto / 100 % … 250 % ;
   - Encoder : Auto / AMF / NVENC ;
   - Language : English / Français ;
4. le lien « Adjust in Windows… » (`ms-settings:display`) ;
5. deux boutons côte à côte, **[Stop / Start / Retry]** et **[Quit]**.

- Position et Scale sont grisés en mode Duplicate.
- Changer Position ou Scale pendant un flux les applique tout de suite.
- La fenêtre grandit autant qu'il faut, environ 520 px, en gardant la largeur de 360 px.
- **Quit** a le même effet que Quitter dans le menu de l'icône : arrêt propre, écran virtuel retiré, contacts relâchés.

**Diagnostic VDD** : si `is_installed()` est faux en mode Extend, l'état devient ERROR avec « Virtual display driver not found. Reinstall Orizon X, or switch to Duplicate mode. », et un bouton « Use Duplicate » apparaît.

## 6. Installateur (Inno Setup 6)

- **Fichiers** :
  - `installer/orizonx.iss`, plus les fichiers VDD dans `installer/vdd/` : `MttVDD.inf`, `MttVDD.dll`, `mttvdd.cat`, `devcon.exe`, `LICENSE` (MIT) ;
  - la version x64 seulement ; ARM64 est hors périmètre.
- **Langues** : `ShowLanguageDialog=yes` et `LanguageDetectionMethod=none` (English toujours présélectionné, quelle que soit la langue de Windows), English puis Français. Le choix est écrit dans `HKCU\Software\OrizonX\Language`.
- **Droits** : `PrivilegesRequired=admin`. L'installation par défaut va dans `{autopf}\Orizon X`.
- **Étapes** :
  1. Accueil ;
  2. Licences : un texte unique résumant MIT (VDD) et GPL (ffmpeg, avec lien vers les sources) ;
  3. Dossier ;
  4. Tâches : « Create a desktop shortcut » **cochée**, « Start Orizon X when Windows starts » **décochée** ;
  5. Installation ;
  6. Fin : « Launch Orizon X » cochée, et un lien vers le guide de préparation de la tablette (le README tant que le sous-projet 4 n'est pas fait).
- **Pilote**, après la copie des fichiers :
  - si un périphérique `Root\MttVDD` existe déjà : on ne réinstalle rien, et on note `HKLM\Software\OrizonX\VddInstalledByUs=0` ;
  - sinon : `devcon install MttVDD.inf Root\MttVDD`, puis `VddInstalledByUs=1`.
  - En cas d'échec : un message clair (« The virtual display driver could not be installed. Orizon X will work in Duplicate mode. ») et l'installation continue.
- **Config VDD** :
  - création de `C:\VirtualDisplayDriver` si besoin, puis sauvegarde du XML existant ;
  - écriture d'un XML minimal : `count` = 0, le GPU qui affiche l'écran principal (détecté par l'appli lancée avec `--configure-vdd`, en admin pendant l'installation), une résolution 1920×1080 à 60 ;
  - droits « Modify » pour le groupe Users (`icacls <dossier> /grant *S-1-5-32-545:(OI)(CI)M`) sur le dossier, pour que l'appli écrive sans droits admin : donnés par `OrizonX.exe --configure-vdd` (`app/admin.py`) et non plus par l'installateur, sur le dossier du XML résolu (`VDDPATH` compris) ; un échec est journalisé et ne change pas le code de sortie (0, sauf échec d'une étape du XML).
- **Démarrage auto** : si la tâche est cochée, une valeur `Run` dans HKCU, compatible avec `app/autostart.py`.
- **Désinstallation** :
  1. `OrizonX.exe --cleanup` (count 0) ;
  2. suppression des fichiers ;
  3. si `VddInstalledByUs=1`, demande « Also remove the virtual display driver? (another program may use it) », puis `devcon remove Root\MttVDD` et `pnputil /delete-driver` en cas de oui.
  - Les réglages utilisateur (`%APPDATA%\OrizonX`) sont gardés.
- **Mise à jour** : même `AppId`, donc l'installation remplace l'existant. `CloseApplications=yes` ferme Orizon X avant la copie.

**Build** : `build-pc.ps1` construit l'appli (comme aujourd'hui), puis, si `ISCC.exe` est trouvé, compile `installer/orizonx.iss` vers `dist/OrizonX-Setup.exe`. Inno Setup est installé une fois par winget (`JRSoftware.InnoSetup`), avec l'accord de l'utilisateur. Les fichiers VDD sont copiés depuis le paquet winget local, ou téléchargés depuis la release GitHub officielle si absents.

## 7. Tests

- **Unitaires, sans Windows réel** :
  - `vdd.py` : faux canal (serveur de pipe nommé de test, ou transport injecté), XML aller-retour qui préserve les sections inconnues, sauvegarde unique ;
  - `display_layout` : positions (4 côtés, écrans de tailles différentes, origine négative) et paliers d'échelle ;
  - `virtual_display` : apparition, délai de 10 s, grâce de 15 s annulée par un retour, nettoyage au démarrage, Quit immédiat ;
  - moteur : PING servi pendant la préparation, état `PREPARING_DISPLAY`, mode duplicate ;
  - `i18n` : complétude des clés et arguments ;
  - fenêtre : bouton Quit, champs grisés en Duplicate, changement de langue.
- **Réel, sur le PC de l'utilisateur** (VDD déjà présent), avec son accord : apparition et disparition à la connexion et à la déconnexion, position droite puis gauche, échelle auto 200 %, Quit, puis relance après un `taskkill` (nettoyage).
- **Installateur, dans Windows Sandbox** (gratuit, Windows Pro), activé avec l'accord de l'utilisateur. On vérifie :
  - le dialogue de langue ;
  - l'installation complète avec le pilote ;
  - la présence de `Root\MttVDD` et le XML (`count` 0, ACL Users) ;
  - le lancement de l'appli, en ERROR « no tablet », la sandbox n'ayant pas d'USB ;
  - la désinstallation avec retrait du pilote.
  - L'écran virtuel lui-même ne peut pas apparaître dans la sandbox (GPU virtuel) : c'est vérifié sur le vrai PC.

## 8. Révision après exploration (prime sur §2, §3 et §6)

Validée par l'utilisateur le 2026-10-05, après l'exploration `docs/notes/vdd-control.md` :

- **L'écran virtuel n'est jamais retiré au niveau du pilote.**
  - VDD garde `count` = 1 : avec 0, il crée quand même un écran.
  - Les commandes de rechargement du pipe plantent l'hôte du pilote (bug upstream #351).
  - L'appli **active ou désactive le chemin d'affichage** du moniteur VDD via `SetDisplayConfig`, comme « Déconnecter cet écran » dans Windows. Ça ne demande pas les droits admin et ne redémarre pas le pilote.
  - Activation au HELLO, désactivation après la grâce de 15 s, désactivation au lancement de l'appli et par `--cleanup`.
  - Le pipe ne sert qu'à `PING` (détection du pilote).
- **Résolutions.**
  - L'installateur écrit dans le XML une liste de résolutions de tablettes courantes, puis redémarre le périphérique une fois (`pnputil /restart-device`, il est déjà élevé).
  - La liste : 2880×1800, 2560×1600, 1920×1200, 1280×800, 2000×1200, 2800×1752, 2960×1848, 2944×1840, 3000×1876, 3200×2000, 2304×1440, 2048×1536, 2732×2048, 2224×1668, 2360×1640, 2388×1668, 2160×1620, 2400×1080, 1920×1080, 2560×1440, 1600×2560, toutes à 60 Hz.
  - **Règle des modes (constat du 2026-10-12, vérifié sur le PC de l'utilisateur).** Le pilote multiplie chaque `<resolution>` par chaque `<global><g_refresh_rate>` : modes = résolutions × fréquences. Avec 26 résolutions et les fréquences 60, 90, 120, 144, 165 et 244 (156 modes), le pilote cessait de créer son moniteur sans aucune erreur (périphérique « OK », `DISPLAY\MTT1337` absent). Les mêmes 26 résolutions avec seulement `60` marchent, comme l'ancien fichier de 7 résolutions. Donc `--configure-vdd` et `--add-resolution` réduisent `<global>` à la seule fréquence 60 (`VddController.limit_global_refresh_rates`, avant l'ajout des résolutions), le fichier créé de zéro n'a que 60, et `add_resolutions` plafonne le total à 64 modes (`vdd.MAX_MODES`) : au-delà, les résolutions les moins prioritaires sont ignorées avec un avertissement (celle de la tablette d'abord, puis la liste dans l'ordre).
  - **Au HELLO**, si la résolution exacte de la tablette n'est pas proposée par le moniteur VDD, l'appli choisit la plus proche **de même format** (même rapport largeur/hauteur à 1 % près, sinon la plus grande qui tient) et la tablette affiche des bandes noires.
  - La fenêtre propose alors **« Add exact resolution »** : une seule demande UAC, qui lance `OrizonX.exe --add-resolution WxH` en admin pour ajouter la résolution au XML et redémarrer le périphérique.
  - Le flux reprend tout seul quand la tablette se reconnecte.
- **Installation du pilote sans devcon** (devcon est un outil Microsoft non redistribuable).
  - `OrizonX.exe --install-driver <inf>` crée le périphérique racine `Root\MttVDD` avec SetupAPI (`SetupDiCreateDeviceInfo` + `SPDRP_HARDWAREID` + `DIF_REGISTERDEVICE`), puis installe le pilote par `UpdateDriverForPlugAndPlayDevicesW`.
  - `--remove-driver` fait `SetupDiRemoveDevice`, puis `pnputil /delete-driver <oemNN.inf> /uninstall`.
  - La détection d'un pilote déjà présent passe par l'ID matériel `Root\MttVDD` dans `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY`.
- **Invite « SignPath Foundation »** : on la laisse apparaître (choix A de l'utilisateur). Une page de l'installateur l'annonce juste avant : « Windows will ask you to install the virtual display driver (publisher: SignPath Foundation). Click Install. »
- **Langue** : écrite aussi dans `HKLM\Software\OrizonX\Language`. L'appli lit ses réglages, puis HKCU, puis HKLM, puis prend l'anglais.
- **Licence VDD** : le texte MIT vient du dépôt GitHub VDD, le paquet winget n'en contenant pas.
