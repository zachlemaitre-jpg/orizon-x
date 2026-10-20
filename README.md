# Orizon X

**Orizon X** transforme une tablette ou un téléphone Android, branché en USB-C, en **écran étendu pour Windows** (image en 60 fps, tactile et stylet) ou en **barre « Actions »** : des boutons tactiles pour piloter le PC (volume, médias, luminosité, Wi-Fi, clés USB…).

- [Installation](#installation-utilisateurs)
- [Utilisation](#utilisation)
- [Dépannage](#dépannage)
- [Développement](#développement)
- [Historique des essais](#historique-des-essais)

## Installation (utilisateurs)

### Ce qu'il faut télécharger

- `OrizonX-Setup.exe` : l'installateur pour le PC Windows (10 ou 11, 64 bits).
- `OrizonX.apk` : l'application pour l'appareil Android (Android 11 ou plus).

### Sur le PC

1. Lance `OrizonX-Setup.exe`.
2. **SmartScreen** peut afficher « Windows a protégé votre ordinateur », car l'installateur n'est pas signé. Clique sur **Informations complémentaires**, puis sur **Exécuter quand même**.
3. Windows demande les **droits administrateur** (une seule fois) : accepte.
4. Choisis la langue. **English** est présélectionné ; **Français** est disponible dans la liste.
5. Clique sur Suivant jusqu'à l'installation. Trois cases sont proposées : un raccourci sur le bureau (cochée), « Démarrer Orizon X avec Windows » (décochée) et « Manette Xbox virtuelle (pilote ViGEmBus) » (cochée), qui installe le pilote permettant à la tablette de servir de manette ; ViGEmBus **reste installé** quand on désinstalle Orizon X, car d'autres logiciels peuvent l'utiliser.
6. Pendant l'installation, Windows demande d'installer le **pilote d'écran virtuel** (éditeur : **SignPath Foundation**). Clique sur **Installer**. Si la fenêtre n'apparaît pas au premier plan, cherche-la dans la barre des tâches. Si tu refuses, Orizon X fonctionne seulement en mode Dupliquer.
7. Si l'installateur demande de **redémarrer**, redémarre : le pilote n'est prêt qu'après.
8. Lance **Orizon X** (case « Lancer Orizon X » à la fin, ou raccourci).

### Sur l'appareil Android

1. Copie `OrizonX.apk` sur l'appareil.
2. Ouvre le fichier. Android demande d'**autoriser l'installation d'applications inconnues** pour l'application que tu utilises (Fichiers, Chrome…) : autorise-la, puis installe l'APK.
3. Ouvre **Orizon X** sur l'appareil : son **guide de connexion** donne les menus exacts de la marque (Samsung, Xiaomi, Pixel, OnePlus/Oppo/Realme, Huawei, Honor, Motorola, Lenovo, Sony, Nothing, ou un guide générique) et coche chaque étape en direct :
   1. activer les **options pour les développeurs** (tape **7 fois** sur « Numéro de version » ; le bouton du guide ouvre le bon écran) ;
   2. activer le **débogage USB** ;
   3. brancher l'appareil au PC avec un câble USB-C **qui transmet des données** (pas un câble de charge seul) ;
   4. si l'appareil demande « **Autoriser le débogage USB ?** », cocher « Toujours autoriser » et accepter (une seule fois par PC).
4. L'app est en anglais ou en français selon la langue de l'appareil ; le bouton **Auto / EN / FR** en haut à droite force l'une ou l'autre.

L'ordre de lancement n'a pas d'importance : le PC attend l'appareil, et l'appareil attend le PC.

## Utilisation

Ouvre Orizon X sur le PC, puis sur l'appareil. L'appareil affiche un écran d'attente avec trois gros boutons, **Screen**, **Actions** et **Frame** (Tableau), pour choisir son rôle. Le rôle est mémorisé. Par défaut : Screen sur tablette, Actions sur téléphone. Changer de rôle pendant une connexion la ferme et la rouvre aussitôt.

### Mode Écran (Screen)

L'appareil devient un écran en plus.

- **L'écran virtuel apparaît à la connexion** et disparaît quelques secondes après le débranchement du câble (15 s de grâce, pour un rebranchement rapide).
- **Réglages dans la fenêtre Orizon X** (appliqués tout de suite) :

  | Réglage | Choix |
  |---|---|
  | Mode | **Extend** (vrai écran étendu) ou **Duplicate** (copie de l'écran principal) |
  | Position | À droite (par défaut), à gauche, au-dessus, en dessous |
  | Scale | **Auto** (calculée d'après la densité de l'appareil, p. ex. 200 % pour 2880×1800) ou 100 % à 250 % |
  | Encoder | **Auto** (NVENC, puis AMF, puis QuickSync, puis le processeur), AMF (AMD), NVENC (NVIDIA), QuickSync (Intel) ou Processor (CPU) |
  | Language | English ou Français |

  Position et Scale sont grisés en mode Duplicate.
- **Duplicate** : aucun écran virtuel n'est créé, l'appareil montre l'écran principal.
- **Adapté à l'appareil** : l'appareil annonce la plus grande image que son décodeur lit à 60 i/s (sinon 30). L'écran virtuel prend cette taille, et le débit se calcule tout seul. Sans encodeur graphique (AMF, NVENC, QuickSync), le processeur encode, à 30 i/s et 1920 pixels de large au plus.
- **Adjust in Windows…** ouvre les paramètres d'affichage de Windows pour les réglages fins.
- **Tactile et stylet** : le doigt et le S Pen pilotent Windows à l'endroit touché.
  - Doigt : tap = clic, appui long = clic droit, défilement et zoom à deux doigts. Trois doigts au plus sont transmis.
  - S Pen : survol = curseur, encre avec pression et inclinaison, bouton latéral = clic droit. Tant que le stylet est détecté, la paume est ignorée.
- **HUD** : un **appui long à 4 doigts** (2 s, sans bouger) affiche ou masque les infos de connexion (fps, latence envoi→affichage, décodeur) et le bouton **Changer de mode** (vers Actions ou Tableau). Ce geste n'existe que dans le mode Écran.

### Mode Actions

Aucune vidéo : l'appareil affiche seulement des boutons natifs qui pilotent le PC. L'écran reste allumé, et le portrait est autorisé. Les tuiles dont le PC ne dispose pas (pas de batterie, pas de Wi-Fi…) disparaissent.

**Réorganiser les blocs** : un appui long sur une zone libre d'un bloc (l'heure, un titre de carte) passe en mode édition ; la grille de 6 lignes apparaît. On glisse un bloc où l'on veut (les cases deviennent rouges si la place est prise), la poignée ↘ l'agrandit ou le réduit case par case (le Son et la clé USB adaptent leur contenu, la pochette de Spotify grandit avec son bloc), ✕ masque un bloc, « + Ajouter » le rétablit et « Terminé » (en haut à gauche) quitte. La disposition est gardée sur l'appareil, en paysage et en portrait.

- **Horloge** (heure et date du PC) et **batterie du PC**.
- **Volume** (curseur) et **muet**.
- **Médias** : précédent, lecture/pause, suivant.
- **En cours de lecture** : carte avec la pochette, le titre, l'artiste, l'album et l'application. Elle marche avec toute source qui publie dans les contrôles multimédias de Windows (Spotify, navigateur, VLC…).
- **Luminosité**.
- **Wi-Fi** (avec barres de signal), **Bluetooth** et **mode avion**.
- **Clés et disques USB** : **Ouvrir** dans l'Explorateur, **Éjecter** proprement. Si l'éjection est refusée (clé utilisée), un message le dit.
- **Barre contextuelle** (en bas) : des boutons adaptés à l'app au premier plan sur le PC, avec son icône au-dessus de son nom.
  - Apps : Spotify, PowerPoint, Word, Excel, VS Code, Explorateur, Illustrator, Photoshop, InDesign, Premiere Pro, After Effects, Lightroom Classic, et Canva et Figma (app ou site, reconnus par l'adresse).
  - Les apps créatives ont plusieurs pages (Outils, Édition, Affichage…), à choisir par onglets ou par balayage.
  - **Navigateurs** (Chrome, Edge, Opera, Firefox, Brave, Vivaldi, Arc…) : une page **Onglets** liste les onglets ouverts ; un tap bascule sur l'onglet.
- **Clavier** : le bouton **Clavier** ouvre un clavier de PC complet (AZERTY ou QWERTY selon le PC), avec l'heure, le son et la luminosité au-dessus.
  - Les touches sont envoyées par leur position, comme un vrai clavier : accents, AltGr et raccourcis marchent.
  - Maj, Ctrl, Alt et AltGr : un tap les garde pour la touche suivante, un double tap les verrouille. Win s'utilise comme sur un vrai clavier (un tap ouvre Démarrer ; Win + lettre à deux doigts).
  - Une touche tenue se répète ; tout est relâché à la fermeture du clavier ou au débranchement.
- **Trackpad** : un grand pavé tactile qui pilote la souris, avec les mêmes gestes qu'un pavé tactile Windows.
  - Un doigt déplace, un tap clique, un tap à deux doigts fait un clic droit, un double tap tenu fait glisser.
  - Deux doigts font défiler ou zoomer (pincer). Trois doigts vers le haut ou le bas ouvrent l'affichage des tâches ou le bureau ; vers la gauche ou la droite, ils changent d'app.
  - Deux boutons sous le pavé font le clic gauche et le clic droit. La vitesse se règle avec −/+.
- **Manette** : la tablette devient une manette Xbox 360 que Windows et les jeux reconnaissent (pilote ViGEmBus, installé par la case « Manette Xbox virtuelle » de l'installateur).
  - Deux sticks, la croix, A/B/X/Y, LB/RB/LT/RT, View/Xbox/Menu ; un double tap sur un stick fait L3 ou R3.
  - « ✕ Fermer la manette » en haut, ou le geste Retour d'Android, la referme.
  - Vérifier dans Windows : Win+R, `joy.cpl`.
- **Claude Code** : les sessions Claude Code du PC, en lecture seule, groupées par projet.
  - À gauche : l'heure, les boutons « + Nouveau », « Artéfacts », « Personnalisation », « Plus » (ils agissent dans l'app Claude) et les conversations ; un tap ouvre la conversation dans l'app.
  - À droite : contexte détaillé, limite de session et limite hebdomadaire, modifications (+/−), résultats et tâches en arrière-plan. Un tap sur le contexte ou sur une limite ouvre la vue correspondante dans l'app.
  - Le détail du contexte et les limites sont lus dans le panneau de droite de l'app Claude, pour la conversation qui y est ouverte. Aucun texte de conversation ne quitte le PC.

### Mode Tableau (Frame)

L'appareil fait défiler, comme un cadre photo, les images (JPG, PNG, WebP, BMP, GIF) et les vidéos (MP4, MOV, WebM, MKV en H.264, H.265, VP8 ou VP9) d'un dossier du PC, sous-dossiers compris, en ordre aléatoire.

- **Réglages dans le groupe Frame de la fenêtre Orizon X** : **Folder** (bouton Choose…), **Interval** des images (5 s à 1 h) et **Display** : **Crop** (remplit l'écran, bords coupés) ou **Fit** (image entière, bandes noires).
- Les vidéos sont lues jusqu'au bout, sans le son. Les autres formats sont ignorés (ligne dans le journal).
- **Un tap sur l'appareil** affiche une barre : pause/lecture, suivant, Crop/Fit, intervalle −/+, et Changer de mode. Les changements sont enregistrés sur le PC.
- Les photos de téléphone sont redressées (orientation EXIF).

### Fenêtre, zone de notification, quitter

- **La croix** range la fenêtre dans la zone de notification : la connexion continue. Un clic sur l'icône la rouvre. Le menu de l'icône (clic droit) propose Démarrer/Arrêter, Ouvrir la fenêtre, Ouvrir le journal, Lancer avec Windows et Quitter.
- **Quit** (bouton de la fenêtre, ou « Quitter » dans le menu de l'icône) arrête tout proprement : écran virtuel retiré, contacts tactiles relâchés. À utiliser avant de désinstaller, de relancer en administrateur ou de brancher l'appareil à un autre PC.
- La couleur de l'icône indique l'état : gris arrêté, ambre en attente, vert connecté, rouge erreur.

## Dépannage

**L'état reste sur « En attente de la tablette ».**
- Vérifie le câble : il doit transmettre des données. Essaie un autre câble ou un autre port.
- Vérifie que le **débogage USB** est activé.
- Vérifie la fenêtre d'**autorisation** sur l'appareil. Si elle ne s'est jamais affichée : débranche, rebranche, ou dans Options de développement, « Révoquer les autorisations de débogage USB », puis rebranche.
- Ouvre l'application Orizon X sur l'appareil (le PC affiche alors « Ouvre Orizon X sur la tablette » tant qu'elle est fermée).

**Pas d'écran virtuel (message « Virtual display driver not found »).**
- Le pilote n'est pas installé ou attend un redémarrage : redémarre Windows, puis relance Orizon X.
- Sinon, relance `OrizonX-Setup.exe` (réinstallation par-dessus), en acceptant la demande du pilote.
- En attendant, passe en mode **Duplicate** (bouton « Use Duplicate »).
- Si la résolution exacte de l'appareil n'est pas connue du pilote, l'image s'affiche avec des bandes noires. Le bouton **Add exact resolution** l'ajoute (une demande de droits administrateur) ; l'image se corrige à la reconnexion.
- Avant une mise à jour de pilote graphique, désinstalle Orizon X (ou le pilote d'écran virtuel) pour éviter un écran noir au redémarrage.

**Le tactile ne marche pas dans certaines fenêtres (Gestionnaire des tâches, installeurs).** Windows refuse le tactile injecté dans une fenêtre lancée en administrateur tant qu'Orizon X ne l'est pas aussi.
1. Quitte Orizon X (bouton **Quit**). Sinon, le nouveau lancement ne fait que réafficher l'ancienne fenêtre, qui n'est pas administrateur.
2. Clic droit sur le raccourci Orizon X → **Exécuter en tant qu'administrateur**.

**Le tactile ne marche nulle part.** Le tactile vise l'écran Windows qui a la taille du flux. S'il n'existe pas un écran unique de cette taille, il se désactive et la vidéo continue.

**SmartScreen / pare-feu.**
- SmartScreen à l'installation et au premier lancement : voir plus haut (Informations complémentaires → Exécuter quand même).
- Orizon X n'utilise que la boucle locale (127.0.0.1). L'installateur ajoute une règle de pare-feu pour `adb.exe`, qui évite l'invite de Windows Defender au premier lancement.
- Le premier lancement peut être lent : l'antivirus analyse l'exe.

**Le journal.** `%LOCALAPPDATA%\OrizonX\relay.log` (menu de l'icône → Ouvrir le journal). Joins-le à tout signalement de problème. Les opérations qui demandent les droits administrateur écrivent dans `relay-admin.log`, au même endroit.

**NVENC ne marche pas.** NVENC exige un pilote NVIDIA ≥ 610 avec le ffmpeg fourni. En mode Auto, Orizon X retombe sur AMF, puis QuickSync, puis le processeur. Sinon, mets à jour le pilote ou choisis un autre encodeur.

**Image saccadée sur un PC sans carte graphique récente.** Le journal indique « x264 runs on the processor » : l'encodage se fait sur le processeur, limité à 30 i/s. C'est normal ; fermer les applications lourdes aide.

## Développement

### Dépôt

| Dossier | Contenu |
|---|---|
| `host-prototype/` | Appli PC en Python : moteur (`engine.py`), `app/` (fenêtre Qt, icône de notification, réglages, langues, droits admin), `actions/` (fournisseurs du mode Actions), écran virtuel (`vdd*.py`, `virtual_display.py`, `display_layout.py`), `relay.py` (CLI), `tests/` |
| `android/` | App Android (Kotlin, Compose) : réception, décodage MediaCodec, écran d'attente, mode Actions |
| `protocol/` | Référence du protocole (`PROTOCOL.md`) et vecteurs de test partagés Python/Kotlin |
| `installer/` | Installateur Inno Setup (`orizonx.iss`), pilote d'écran virtuel signé (`vdd/`), licences |
| `tools/` | Outils de développement (`svg_to_vector.py`) |
| `extended/` | Sources graphiques : logo, police MAZAGLA, icônes SVG (`icons/`) |
| `docs/` | Specs (`superpowers/specs/`), plans, notes d'exploration (`notes/`) |
| `build-pc.ps1` | Compile l'appli PC et l'installateur dans `dist/` (ignoré par git, comme `build/`) |
| `build-android.ps1` | Compile l'APK release signée dans `dist/OrizonX.apk` |

### Prérequis

- Windows 11 et **Python 3.13** (lanceur `py`).
- Un environnement virtuel `host-prototype\.venv` avec `requirements-dev.txt` (PySide6, PyInstaller, et les dépendances d'exécution). `build-pc.ps1` le crée et l'installe tout seul ; à la main : `py -m venv host-prototype\.venv`, puis `host-prototype\.venv\Scripts\python.exe -m pip install -r host-prototype\requirements-dev.txt`.
- **Android Studio** (SDK + JBR) pour Gradle : `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"`. `adb` est cherché dans le PATH, puis dans `%LOCALAPPDATA%\Android\Sdk\platform-tools`.
- **ffmpeg ≥ 6** (build Gyan, avec `ddagrab`, `h264_amf`, `h264_nvenc`, `h264_qsv`, `libx264`) **dans le PATH**, pour compiler et pour le mode debug `py relay.py`. L'exe compilé embarque ffmpeg et adb. Vérification : `ffmpeg -hide_banner -encoders | Select-String h264_amf`.
- **Inno Setup 6** (pas la 7) pour l'installateur : `winget install --id JRSoftware.InnoSetup -e --scope user`. Sans lui, `build-pc.ps1` compile l'appli mais pas `OrizonX-Setup.exe`.

### Tests

- Python, avec le venv (tous les tests, Qt compris) :
  ```powershell
  cd host-prototype
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  ```
- Python, avec l'interpréteur `py` (les tests Qt, sans PySide6, sont ignorés) :
  ```powershell
  cd host-prototype; py -m unittest discover -s tests -v
  ```
- Android (JVM) :
  ```powershell
  cd android; .\gradlew.bat :app:testDebugUnitTest
  ```
- Convertisseur d'icônes : `cd tools; py -m unittest`.

### Compiler

```powershell
.\build-pc.ps1              # dist\OrizonX-PC\ (OrizonX.exe + ffmpeg + adb), puis dist\OrizonX-Setup.exe
.\build-pc.ps1 -Shortcuts   # crée en plus les raccourcis « Orizon X » (menu Démarrer et bureau)
```

Quitte Orizon X avant (le script refuse de recompiler une appli qui tourne). La compilation prend environ 2 min.

APK à distribuer (signée avec la clé de release, voir plus bas) :
```powershell
.uild-android.ps1        # dist\OrizonX.apk, puis affiche l'empreinte SHA-256 du certificat
```

APK de développement (installé sur l'appareil branché, signée avec la clé de debug) :
```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:installDebug
```
Le fichier est `android\app\build\outputs\apk\debug\app-debug.apk`.

### Publier une version

Le dépôt GitHub est **privé** : https://github.com/animaappcontact-stack/orizon-x. Les fichiers à distribuer sont dans ses Releases.

1. Change `__version__` dans `host-prototype/version.py` (seule source de version, PC et APK), puis commite.
2. Compile : `.uild-pc.ps1`, puis `.uild-android.ps1`.
3. Publie, avec le CLI GitHub (`gh auth login` une fois) :
   ```powershell
   git push
   gh release create v0.7.0 dist\OrizonX-Setup.exe dist\OrizonX.apk --title "Orizon X 0.7.0" --notes "…"
   ```

Le dossier de signature n'est jamais publié (le `.gitignore` refuse `*.jks` et `keystore.properties`).

### Clé de signature Android

L'APK release est signée avec une clé personnelle, **hors du dépôt** : `%USERPROFILE%\OrizonX-signing\` (`orizonx-release.jks` et `keystore.properties`, qui contient les mots de passe). La variable d'environnement `ORIZONX_SIGNING_DIR` permet de pointer vers un autre dossier. Sans ce dossier, seule la compilation release échoue ; la debug marche.

**Sauvegarde ce dossier** (clé USB, gestionnaire de mots de passe, coffre chiffré), et ne le mets jamais dans Git ni dans un message.
- Android n'installe une mise à jour que si elle est signée avec **la même clé**. Si la clé est perdue, la mise à jour suivante doit être signée avec une nouvelle clé, et chaque appareil doit **désinstaller** Orizon X avant d'installer la nouvelle version (ses réglages sont perdus).
- Si la clé fuite, quelqu'un peut publier une fausse mise à jour qu'Android accepterait par-dessus Orizon X.

Passage de l'APK de debug à l'APK release : désinstaller une fois `com.orizonx.client` de l'appareil, puis installer `OrizonX.apk`. Les versions suivantes s'installent par-dessus.

### CLI de debug

Même moteur que l'appli, sans écran virtuel, avec la sortie dans le terminal. **Quitte d'abord l'appli PC** (sinon les deux se disputent l'appareil).

```powershell
cd host-prototype; py relay.py
```

Options : `--encoder auto|nvenc|amf|qsv|x264` (défaut `auto`), `--output auto|N` (défaut `auto` : l'écran à la taille de l'appareil ; `--output 0` duplique l'écran principal), `--list-outputs`, `--fps 60` (plafond), `--bitrate auto` (défaut, ou une valeur fixe comme `30M`). Le tactile a son autotest : `py injector.py --selftest` (survol seulement, sans clic).

Logs de l'appareil : `adb logcat -s VideoDecoder Session Receiver`.

### Icônes

Les icônes des tuiles viennent de SVG monochromes. Dépose-les dans `extended/icons/` puis, depuis la racine du dépôt :

```powershell
py tools/svg_to_vector.py
```

Chaque `<nom>.svg` devient `android/app/src/main/res/drawable/ox_<nom>.xml` (VectorDrawable blanc, teintable). Le sous-ensemble SVG géré (chemins, rectangles, cercles, transformations, opacité) est décrit dans le docstring de `tools/svg_to_vector.py` ; le reste (traits, dégradés, masques, texte) est refusé avec une erreur au lieu d'être ignoré. Arguments facultatifs : `py tools/svg_to_vector.py [DOSSIER_SVG] [DOSSIER_SORTIE]`.

### Tester l'installateur dans Windows Sandbox

Windows Sandbox (Windows Pro) permet de tester l'installation sur un Windows vierge, sans toucher au PC.

1. Compile (`.\build-pc.ps1`) et copie `dist\OrizonX-Setup.exe` dans `build\sandbox\in\`.
2. Double-clique sur `build\sandbox\orizonx.wsb`.
3. Le script `build\sandbox\test.ps1` installe en silencieux, note ses vérifications (pilote, configuration, lancement de l'appli, désinstallation) et copie les journaux dans `build\sandbox\out\` (`result.txt`, `setup.log`, `relay.log`…).

Dans la sandbox, l'appli finit en erreur « pas de tablette » (pas d'USB) et aucun écran virtuel n'apparaît (GPU virtuel) : ces deux points se vérifient sur un vrai PC.

### Pièges connus

- **`winrt` avant `PySide6`** : importer un module `winrt` avant PySide6 fait planter le processus (violation d'accès). Importe toujours PySide6 d'abord. Dans les tests, pas d'import `winrt` au niveau du module (la découverte l'importerait avant les tests Qt).
- **Limite de modes du pilote d'écran virtuel (VDD)** : il multiplie chaque résolution par chaque fréquence de `<global><g_refresh_rate>`. Avec trop de modes (156 constatés), il cesse de créer son moniteur sans erreur. Orizon X limite donc les fréquences à **60 Hz** et plafonne à 64 modes. Ne rajoute pas d'autres fréquences dans `vdd_settings.xml`.
- **NVENC** : pilote NVIDIA ≥ 610 requis avec ce build de ffmpeg ; AMF (iGPU AMD) marche.
- **Pilote d'écran virtuel jamais retiré** : l'appli active et désactive le chemin d'affichage (comme « Déconnecter cet écran ») ; elle ne fait pas varier le nombre de moniteurs de VDD.
- **« Lancer avec Windows »** n'existe que dans l'appli compilée, pas en lançant les sources avec `py`.
- **Textes de l'app Android** : en français pour l'instant (traduction prévue).
- **Specs de référence** : `docs/superpowers/specs/` (appli PC, installateur et écran virtuel — §8 prime —, mode Actions, identité visuelle), et le protocole dans `protocol/PROTOCOL.md`.

## Historique des essais

Notes et résultats des phases 1 et 4, et checklists de vérification manuelle. Gardés pour mémoire.

### Appli PC : checklist

- [ ] Double-clic sur le raccourci : fenêtre en verre, aucune console qui clignote, « En attente de la tablette ».
- [ ] Le fond de la fenêtre est flouté (effet verre), pas transparent.
- [ ] Tablette branchée, Orizon X ouverte : « Connecté », stats qui bougent, vidéo et tactile OK.
- [ ] Croix : la fenêtre disparaît, le flux continue, une bulle s'affiche (la première fois seulement).
- [ ] Clic sur l'icône de notification : la fenêtre revient. Deuxième double-clic sur le raccourci : la même fenêtre revient.
- [ ] Câble débranché puis rebranché : retour en attente, puis reconnexion seule.
- [ ] Changement d'encodeur et d'écran : relance, réglages gardés après redémarrage de l'appli.
- [ ] Quitter en plein flux : la tablette affiche « PC déconnecté », aucun contact ne reste posé.
- [ ] Lancer avec Windows coché, puis session rouverte : l'appli démarre dans la zone de notification.
- [ ] Auto sur secteur et sur batterie : l'encodeur choisi est dans le journal.
### Checklist d'intégration (phase 1)

#### Critères de réussite (spec §9)

- [ ] 60 fps stables pendant 10 min en bougeant des fenêtres, sans artefacts cumulés (stats du relais + HUD).
- [ ] HUD : p50 ≤ 20 ms, p99 ≤ 40 ms. Noter les valeurs et le nom du décodeur.
- [ ] Latence de bout en bout filmée (chronomètre en ms à l'écran, ralenti du téléphone) : valeur notée (référence ; ~20 ms dus aux compromis de la phase 1).
- [ ] Câble débranché puis rebranché (relais laissé tourner) : le flux reprend sans relancer l'app.
- [ ] Relais tué (Ctrl+C) en plein flux : l'app revient à l'écran d'attente avec « PC déconnecté ».
- [ ] Tous les tests passent.

#### Vérifications techniques sur la tablette

Logs utiles : `adb logcat -s VideoDecoder Session Receiver`

`adb` n'est pas forcément dans le PATH : utiliser `& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"` ou ajouter ce dossier au PATH.

- [ ] **Décodeur basse latence** : le HUD affiche le nom du décodeur (ex. `c2.exynos.h264.decoder`). Dans le log `décodeur … paramètres vendeur : […]`, vérifier si `vendor.rtc-ext-dec-low-latency.enable` est listé.
- [ ] **fps du HUD ≈ 60** : s'il reste à 0, `OnFrameRenderedListener` ne se déclenche pas sur ce couple appareil/flux.
- [ ] **Régime permanent propre** : aucune ligne « recréation du décodeur » ni « décodeur bloqué » ; « format de sortie » apparaît une fois par décodeur, pas à chaque IDR.
- [ ] **Si « Décodeur indisponible : configuration… »** : retirer d'abord `KEY_FRAME_RATE`, puis la clé vendeur `vendor.rtc-ext-dec-low-latency.enable` dans `VideoDecoder.kt`, et réessayer.
- [ ] **Surface stable** : une seule création de surface par passage au premier plan ; le démarrage du flux ne doit provoquer qu'un `surfaceChanged` (pas de reconnexion en boucle).
- [ ] **Arrière-plan / premier plan ×20** pendant le flux (bouton Accueil puis retour, écran éteint/allumé) : pas de plantage, le flux reprend, jamais de « Port 27183 déjà utilisé » bloqué.
- [ ] **Relais relancé sans tuer l'app** : nouveau CONFIG, première image en moins d'1 s, pas de plantage.
- [ ] **Changements de configuration en plein flux** (mode sombre, zoom d'écran, clavier Book Cover) : le flux continue sans coupure.
- [ ] **Composition** (HUD masqué) : `adb shell dumpsys SurfaceFlinger` → la couche du SurfaceView en composition DEVICE (pas CLIENT). `adb shell dumpsys gfxinfo com.orizonx.client` → aucune nouvelle frame UI pendant le flux.
- [ ] **Appui long à 4 doigts** : bascule le HUD exactement une fois, uniquement pendant le flux ; aucun geste One UI ne l'intercepte.
- [ ] **Barres système** : restent masquées après arrière-plan, volet de notifications, écran partagé.
- [ ] **Thermique de l'écran d'attente** : le laisser 30 min (flou plein écran animé), puis `adb shell dumpsys thermalservice` et noter le p50/p99 de la session suivante. Si la tablette chauffe ou bride, remplacer le flou par des dégradés radiaux (`Brush.radialGradient`) dans `WaitingScreen.kt`.
- [ ] **Keyframes AMF** : après une recréation du décodeur, l'image revient en ≤ 1 s (IDR toutes les 60 frames). Sinon, AMF n'envoie qu'une IDR : revoir les options de `ENCODERS["amf"]` dans `relay.py`.

#### Vérifications tactile et stylet (phase 4)

- [ ] **Tactile** :
  - tap précis (viser la croix d'une fenêtre) ;
  - défilement à 2 doigts dans un navigateur ;
  - pincement dans Photos ;
  - appui long = menu contextuel.
- [ ] **S Pen** :
  - survol sans clic ;
  - trait plus épais quand on appuie (Paint, Whiteboard) ;
  - inclinaison dans le bon sens ;
  - bouton = clic droit.

  Si le bouton ouvre le menu Air Command de Samsung en survol, le noter. Si l'inclinaison est inversée, changer le signe de `tiltX` ou de `tiltY` dans `InputMapper.penContact`.
- [ ] **Point immobile qui appuie plus fort** : poser le stylet sans bouger et augmenter la pression. Compose ignore les mouvements sans déplacement, donc l'épaisseur peut rester celle du contact initial. À noter si c'est gênant.
- [ ] **Paume** : poser la main en dessinant ne clique nulle part, et le stylet ne « clignote » pas hors de portée.
- [ ] **HUD** :
  - l'appui long à 4 doigts bascule le HUD sans clic ni geste Windows ;
  - le rappel est visible sur l'écran d'attente et en début de connexion.
- [ ] **Contacts coincés** : Ctrl+C sur le relais pendant un toucher → aucun contact ne reste « posé ».
- [ ] **Fenêtre administrateur** :
  - toucher le Gestionnaire des tâches avec un relais non administrateur, puis noter si le message « lance le relais en administrateur » apparaît (il peut ne jamais apparaître, Windows ignorant l'entrée en silence) ;
  - refaire l'essai avec le relais en administrateur.
- [ ] **Garde-fou 100 ms** (`KEEPALIVE_S` dans `injector.py`) : garder un doigt immobile 5 s sur une fenêtre. Mettre ensuite la constante à `3600` et refaire l'essai. Si le contact tient aussi sans garde-fou, le garde-fou est inutile.
- [ ] **Entre deux traits** : `PEN_EXIT_GRACE_MS` (50 ms, `TouchForwarder.kt`) évite que le stylet sorte de portée entre deux traits. Si le curseur du stylet clignote entre les traits, l'augmenter.
### Mesures phase 1

| Date | Mode | Encodeur PC | Résolution | fps | Envoi→affichage moy. / max par s | p50 / p99 (HUD) | RTT USB | Ressenti |
|---|---|---|---|---|---|---|---|---|
| 2026-10-01 | Écran étendu (VDD) | AMF, 30 Mbit/s, IDR/1 s | 2880×1800 | 59–61, 0 perdue | 20–22 ms / 27–33 ms (pics 58–64 ms) | **18 ms** / **60 ms** | 3–8 ms | « suffisamment fluide » |

- Critère p50 ≤ 20 ms : **atteint**. Critère p99 ≤ 40 ms : **non atteint**. Les pics (~1 image sur 60) coïncident avec les IDR envoyées chaque seconde, plus lourdes à transférer et à décoder.
- Pistes, si le besoin se fait sentir : espacer les IDR, ou les remplacer par un rafraîchissement intra progressif. Cette dernière piste dépend de la phase 2 (IDR à la demande).
- Latence filmée de bout en bout : non mesurée.
### Essai phase 4 (tactile et stylet)

| Date | Vérification | Résultat |
|---|---|---|
| 2026-10-05 | Tap au doigt (précision) | OK |
| 2026-10-05 | Défilement à 2 doigts | OK |
| 2026-10-05 | S Pen avec pression | OK |
| 2026-10-05 | Paume posée en dessinant | OK (aucun clic parasite) |
| 2026-10-05 | Appui long à 4 doigts (HUD) | OK |

Non vérifiés à ce jour : bouton latéral du S Pen, survol seul, contacts coincés après arrêt du relais, fenêtres administrateur, utilité du garde-fou de 100 ms (voir la checklist ci-dessus).
