# Orizon X

Tablette Android comme second écran pour Windows, via câble USB-C.

Phase actuelle : **1 — pipeline vidéo** (spec : `docs/superpowers/specs/2026-10-01-phase1-video-pipeline-design.md`, plan : `docs/superpowers/plans/2026-10-01-phase1-video-pipeline.md`). Le PC capture son écran principal, l'encode en H.264 matériel et l'envoie à la tablette par `adb forward` ; la tablette décode et affiche, et mesure la latence.

## Structure

| Dossier | Contenu |
|---|---|
| `protocol/` | Référence du protocole TABX v1 et vecteurs de test partagés |
| `host-prototype/` | Relais Python (phase 1) : ffmpeg → protocole TABX → tablette |
| `android/` | App Android (Kotlin, Compose) : réception, décodage MediaCodec, interface |

## Prérequis

- Windows 11, Python ≥ 3.10 (lanceur `py`).
- ffmpeg ≥ 6 avec `ddagrab`, `h264_amf` / `h264_nvenc` (build Gyan), dans le PATH. Sur la machine de dev, il est installé dans `%LOCALAPPDATA%\Programs\ffmpeg\bin` (déjà ajouté au PATH utilisateur ; ouvrir un nouveau terminal après l'installation). Vérifier avec `ffmpeg -hide_banner -encoders | Select-String h264_amf`.
- Encodeur : **AMF** (iGPU AMD) fonctionne. **NVENC** exige un pilote NVIDIA ≥ 610 avec ce build de ffmpeg : mets à jour le pilote avant d'utiliser `--encoder nvenc`.
- Android Studio (SDK + JBR). `adb` est cherché dans le PATH puis dans `%LOCALAPPDATA%\Android\Sdk\platform-tools`.
- Tablette Android 11+ avec le débogage USB activé : Paramètres → À propos de la tablette → Informations sur le logiciel → taper 7 fois sur « Numéro de version », puis Options de développement → « Débogage USB ». Brancher le câble et accepter l'autorisation sur la tablette.

## Lancer

1. Installer l'app :
   ```powershell
   $env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
   cd android; .\gradlew.bat :app:installDebug; cd ..
   ```
2. Ouvrir **Orizon X** sur la tablette : écran d'attente en verre dépoli.
3. Lancer le relais :
   ```powershell
   cd host-prototype; py relay.py --encoder amf; cd ..
   ```
   Options : `--output auto|N` (par défaut `auto` : l'écran à la taille de la tablette ; pour dupliquer l'écran principal, `--output 0`), `--list-outputs`, `--fps 60`, `--bitrate 30M`, `--encoder nvenc` (pilote ≥ 610).

   Le relais attend la tablette et l'app tout seul (il refait `adb forward` à chaque essai) : l'ordre de lancement n'a pas d'importance. Les demandes de keyframe après une erreur de décodage sont journalisées.
4. Appui long à 4 doigts (2 s, sans bouger) sur la tablette pendant le flux : affiche/masque le HUD (fps, latence envoi→affichage, p50/p99 de session, offset d'horloge, décodeur).

La latence du HUD est mesurée **de l'envoi par le relais à l'affichage** : elle exclut la capture et l'encodage côté PC. La latence de bout en bout se mesure en filmant les deux écrans.

## Second écran étendu

Sans configuration, le relais **duplique** un écran existant. Pour un vrai écran étendu, il faut un moniteur virtuel. En attendant le driver maison (phase 3), on utilise [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver), un driver signé : pas besoin du mode test.

1. Installer : `winget install --id=VirtualDrivers.Virtual-Display-Driver -e`. Lancer ensuite **VDD Control** (dans `%LOCALAPPDATA%\Microsoft\WinGet\Packages\VirtualDrivers.Virtual-Display-Driver_*`) et cliquer **une seule fois** sur « Install Driver » : chaque clic crée un adaptateur de plus.
2. Configurer `C:\VirtualDisplayDriver\vdd_settings.xml` :
   - `<friendlyname>` = le GPU qui pilote l'écran principal (ici `AMD Radeon(TM) 890M Graphics`) ;
   - ajouter la résolution `2880`×`1800` à `60` Hz dans `<resolutions>`.

   Cliquer ensuite sur « Restart Driver » dans VDD Control.
3. Dans Paramètres → Écran : « Étendre ces affichages », écran virtuel en 2880×1800 à 200 %, placé du côté où se trouve la tablette.
4. Lancer le relais : par défaut (`--output auto`), il capture l'écran qui a la taille de la tablette (2880×1800), ce qui vise donc l'écran virtuel. Les numéros d'écran changent quand on branche ou débranche un moniteur, d'où ce mode automatique.
   ```powershell
   py relay.py --encoder amf
   ```
   Pour voir les écrans ou en forcer un : `py relay.py --list-outputs`, puis `--output N`.

**À savoir :**
- **Désinstaller le driver (VDD Control ou Gestionnaire de périphériques) avant toute mise à jour de pilote GPU**, sinon risque d'écran noir au démarrage.

## Tactile et stylet (phase 4)

Pendant le flux, le doigt et le S Pen pilotent Windows à l'endroit touché de l'écran étendu :

- **Doigt** :
  - tap = clic ;
  - appui long = clic droit ;
  - défilement et zoom à deux doigts (gestes natifs de Windows).

  Au plus 3 doigts sont transmis : le 4e est réservé au HUD.
- **S Pen** :
  - survol = curseur ;
  - encre avec pression et inclinaison ;
  - bouton latéral = clic droit.

  Tant que le stylet est détecté, les doigts (la paume) sont ignorés.
- **HUD** : appui long à 4 doigts (2 s, sans bouger).
- **Écran ciblé** : le relais vise l'écran Windows qui a la taille du flux. S'il n'existe pas un écran unique de cette taille, le tactile se désactive mais la vidéo continue.
- **Fenêtres administrateur** (Gestionnaire des tâches, installeurs) : elles ne répondent qu'à un relais **lancé en administrateur**.
- **Autotest de l'injection**, sans tablette et sans clic (survol uniquement) : `cd host-prototype; py injector.py --selftest`. Il vérifie que le curseur arrive au pixel visé.

## Tests

- Python : `cd host-prototype; py -m unittest discover -v`
- Android (JVM) : `cd android; .\gradlew.bat :app:testDebugUnitTest`

## Checklist d'intégration (phase 1)

### Critères de réussite (spec §9)

- [ ] 60 fps stables pendant 10 min en bougeant des fenêtres, sans artefacts cumulés (stats du relais + HUD).
- [ ] HUD : p50 ≤ 20 ms, p99 ≤ 40 ms. Noter les valeurs et le nom du décodeur.
- [ ] Latence de bout en bout filmée (chronomètre en ms à l'écran, ralenti du téléphone) : valeur notée (référence ; ~20 ms dus aux compromis de la phase 1).
- [ ] Câble débranché puis rebranché (relais laissé tourner) : le flux reprend sans relancer l'app.
- [ ] Relais tué (Ctrl+C) en plein flux : l'app revient à l'écran d'attente avec « PC déconnecté ».
- [ ] Tous les tests passent.

### Vérifications techniques sur la tablette

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

### Vérifications tactile et stylet (phase 4)

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

## Mesures phase 1

| Date | Mode | Encodeur PC | Résolution | fps | Envoi→affichage moy. / max par s | p50 / p99 (HUD) | RTT USB | Ressenti |
|---|---|---|---|---|---|---|---|---|
| 2026-10-01 | Écran étendu (VDD) | AMF, 30 Mbit/s, IDR/1 s | 2880×1800 | 59–61, 0 perdue | 20–22 ms / 27–33 ms (pics 58–64 ms) | **18 ms** / **60 ms** | 3–8 ms | « suffisamment fluide » |

- Critère p50 ≤ 20 ms : **atteint**. Critère p99 ≤ 40 ms : **non atteint**. Les pics (~1 image sur 60) coïncident avec les IDR envoyées chaque seconde, plus lourdes à transférer et à décoder.
- Pistes, si le besoin se fait sentir : espacer les IDR, ou les remplacer par un rafraîchissement intra progressif. Cette dernière piste dépend de la phase 2 (IDR à la demande).
- Latence filmée de bout en bout : non mesurée.

## Essai phase 4 (tactile et stylet)

| Date | Vérification | Résultat |
|---|---|---|
| 2026-10-05 | Tap au doigt (précision) | OK |
| 2026-10-05 | Défilement à 2 doigts | OK |
| 2026-10-05 | S Pen avec pression | OK |
| 2026-10-05 | Paume posée en dessinant | OK (aucun clic parasite) |
| 2026-10-05 | Appui long à 4 doigts (HUD) | OK |

Non vérifiés à ce jour : bouton latéral du S Pen, survol seul, contacts coincés après arrêt du relais, fenêtres administrateur, utilité du garde-fou de 100 ms (voir la checklist ci-dessus).
