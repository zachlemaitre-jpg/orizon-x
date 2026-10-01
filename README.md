# TabX

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
- ffmpeg ≥ 6 avec `ddagrab`, `h264_amf` / `h264_nvenc` (build Gyan). Il doit être dans le PATH. Sur la machine de dev, un build existe dans `D:\NOZAFLU\windows\ffmpeg-2026-09-02-git-9fc8c785e2-essentials_build\ffmpeg-2026-09-02-git-9fc8c785e2-essentials_build\bin` : ajoute ce dossier au PATH utilisateur (Paramètres → Système → Informations système → Paramètres système avancés → Variables d'environnement), ou pour la session courante seulement :
  ```powershell
  $env:PATH = "D:\NOZAFLU\windows\ffmpeg-2026-09-02-git-9fc8c785e2-essentials_build\ffmpeg-2026-09-02-git-9fc8c785e2-essentials_build\bin;$env:PATH"
  ```
- Encodeur : **AMF** (iGPU AMD) fonctionne. **NVENC** exige un pilote NVIDIA ≥ 610 avec ce build de ffmpeg : mets à jour le pilote avant d'utiliser `--encoder nvenc`.
- Android Studio (SDK + JBR). `adb` est cherché dans le PATH puis dans `%LOCALAPPDATA%\Android\Sdk\platform-tools`.
- Tablette Android 11+ avec le débogage USB activé : Paramètres → À propos de la tablette → Informations sur le logiciel → taper 7 fois sur « Numéro de version », puis Options de développement → « Débogage USB ». Brancher le câble et accepter l'autorisation sur la tablette.

## Lancer

1. Installer l'app :
   ```powershell
   $env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
   cd android; .\gradlew.bat :app:installDebug; cd ..
   ```
2. Ouvrir **TabX** sur la tablette : écran d'attente en verre dépoli.
3. Lancer le relais :
   ```powershell
   cd host-prototype; py relay.py --encoder amf; cd ..
   ```
   Options : `--output N` (écran capturé), `--fps 60`, `--bitrate 30M`, `--encoder nvenc` (pilote ≥ 610).
4. Tap à 3 doigts sur la tablette pendant le flux : affiche/masque le HUD (fps, latence envoi→affichage, p50/p99 de session, offset d'horloge, décodeur).

La latence du HUD est mesurée **de l'envoi par le relais à l'affichage** : elle exclut la capture et l'encodage côté PC. La latence de bout en bout se mesure en filmant les deux écrans.

## Tests

- Python : `cd host-prototype; py -m unittest discover -v`
- Android (JVM) : `cd android; .\gradlew.bat :app:testDebugUnitTest`

## Checklist d'intégration (phase 1)

### Critères de réussite (spec §9)

- [ ] 60 fps stables pendant 10 min en bougeant des fenêtres, sans artefacts cumulés (stats du relais + HUD).
- [ ] HUD : p50 ≤ 20 ms, p99 ≤ 40 ms. Noter les valeurs et le nom du décodeur.
- [ ] Latence de bout en bout filmée (chronomètre en ms à l'écran, ralenti du téléphone) : valeur notée (référence ; ~20 ms dus aux compromis de la phase 1).
- [ ] Câble débranché puis rebranché, relais relancé : le flux reprend sans relancer l'app.
- [ ] Relais tué (Ctrl+C) en plein flux : l'app revient à l'écran d'attente avec « PC déconnecté ».
- [ ] Tous les tests passent.

### Vérifications techniques sur la tablette

Logs utiles : `adb logcat -s VideoDecoder Session Receiver`

- [ ] **Décodeur basse latence** : le HUD affiche le nom du décodeur (ex. `c2.exynos.h264.decoder`). Dans le log `décodeur … paramètres vendeur : […]`, vérifier si `vendor.rtc-ext-dec-low-latency.enable` est listé.
- [ ] **fps du HUD ≈ 60** : s'il reste à 0, `OnFrameRenderedListener` ne se déclenche pas sur ce couple appareil/flux.
- [ ] **Régime permanent propre** : aucune ligne « recréation du décodeur » ni « décodeur bloqué » ; « format de sortie » apparaît une fois par décodeur, pas à chaque IDR.
- [ ] **Si « Décodeur indisponible : configuration… »** : retirer d'abord `KEY_FRAME_RATE` dans `VideoDecoder.kt`, puis réessayer.
- [ ] **Surface stable** : une seule création de surface par passage au premier plan ; le démarrage du flux ne doit provoquer qu'un `surfaceChanged` (pas de reconnexion en boucle).
- [ ] **Arrière-plan / premier plan ×20** pendant le flux (bouton Accueil puis retour, écran éteint/allumé) : pas de plantage, le flux reprend, jamais de « Port 27183 déjà utilisé » bloqué.
- [ ] **Relais relancé sans tuer l'app** : nouveau CONFIG, première image en moins d'1 s, pas de plantage.
- [ ] **Changements de configuration en plein flux** (mode sombre, zoom d'écran, clavier Book Cover) : le flux continue sans coupure.
- [ ] **Composition** (HUD masqué) : `adb shell dumpsys SurfaceFlinger` → la couche du SurfaceView en composition DEVICE (pas CLIENT). `adb shell dumpsys gfxinfo dev.tabx.client` → aucune nouvelle frame UI pendant le flux.
- [ ] **Tap à 3 doigts** : bascule le HUD exactement une fois, uniquement pendant le flux ; aucun geste One UI ne l'intercepte.
- [ ] **Barres système** : restent masquées après arrière-plan, volet de notifications, écran partagé.
- [ ] **Thermique de l'écran d'attente** : le laisser 30 min (flou plein écran animé), puis `adb shell dumpsys thermalservice` et noter le p50/p99 de la session suivante. Si la tablette chauffe ou bride, remplacer le flou par des dégradés radiaux (`Brush.radialGradient`) dans `WaitingScreen.kt`.
- [ ] **Keyframes AMF** : après une recréation du décodeur, l'image revient en ≤ 1 s (IDR toutes les 60 frames). Sinon, AMF n'envoie qu'une IDR : revoir les options de `ENCODERS["amf"]` dans `relay.py`.

## Mesures phase 1

À compléter après les essais : date, décodeur, fps, p50/p99 (HUD), latence filmée, encodeur PC.
