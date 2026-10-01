# TabX — Phase 1 : pipeline vidéo PC → tablette (design)

Date : 2026-10-01
Statut : validé en brainstorming, en attente de relecture

## 1. Contexte

TabX transforme une tablette Android en second écran étendu pour un PC Windows, via câble USB-C uniquement.

Matériel cible :

- **PC** : portable hybride, iGPU AMD (sur batterie) + GPU NVIDIA (sur secteur), Windows 11.
- **Tablette** : Samsung Galaxy Tab S10 FE+ — Exynos 1580, Android 15, écran 2880×1800 (16:10) 90 Hz, USB-C probablement USB 2.0 (~30 Mo/s utiles via adb).

Usage : personnel d'abord, distribution possible plus tard. Conséquence : test-signing du driver et débogage USB acceptés pour l'instant, mais protocole indépendant du transport pour ne pas fermer la porte à AOA ni à un driver signé.

### Feuille de route globale

| Phase | Bloc | Livrable |
|---|---|---|
| 0 | Environnement | VS 2022 + WDK, Android Studio, adb, débogage USB |
| **1** | **Client Android + tunnel adb** (ce document) | Flux H.264 affiché sur la tablette, latence mesurée |
| 2 | Hôte C++ | Capture DDA + encodage Media Foundation + envoi TCP, remplace le relais Python |
| 3 | Moniteur virtuel | Driver IDD (fork de `IddSampleDriver`) en 2880×1800, GPU de rendu choisi via `IddCxAdapterSetRenderAdapter` |
| 4 | Entrées | Tactile + stylet → injection via `InjectSyntheticPointerInput` |
| 5 | Robustesse | Reconnexion, rotation, keyframe à la demande, débit adaptatif |
| 6 | Transport production | AOA (WinUSB) ou USB NCM, selon mesures |
| 7 | Packaging | Signature d'attestation du driver, installeur |

Chaque phase a son propre cycle spec → plan → implémentation.

### Pourquoi commencer par la phase 1

Le risque technique principal est la latence du décodeur MediaCodec, qui varie selon le constructeur (buffering interne). Il faut la mesurer avant d'investir dans un driver. ffmpeg remplace temporairement tout le côté PC, ce qui isole le côté tablette.

## 2. Objectif et périmètre

**Objectif** : la tablette affiche en temps réel le bureau du PC, encodé en H.264 par le GPU, transmis via `adb forward`, avec mesure intégrée de la latence envoi→affichage.

**Inclus** :

- Protocole TABX v1 (définitif, réutilisé par toutes les phases).
- Application Android complète pour la réception, le décodage, l'affichage et l'interface glassmorphism.
- Relais Python jetable qui alimente la tablette depuis ffmpeg.
- Tests unitaires des deux côtés et vecteurs de test partagés.

**Exclus** : driver IDD, hôte C++, entrées tactiles, AOA, rotation, débit adaptatif, audio.

## 3. Structure du dépôt

```
/
├── android/                 projet Android Studio (Gradle, Kotlin)
├── host-prototype/          relais Python de la phase 1
├── protocol/
│   ├── PROTOCOL.md          spécification de référence du protocole TABX
│   └── test-vectors.json    messages + octets attendus, partagés par les tests Kotlin et Python
└── docs/superpowers/specs/
```

## 4. Protocole TABX v1

### 4.1 Transport

- La tablette écoute sur `127.0.0.1:27183` (loopback uniquement, jamais `0.0.0.0` : sinon tout appareil du Wi-Fi pourrait injecter un flux dans le décodeur).
- Le PC exécute `adb forward tcp:27183 tcp:27183` puis se connecte à `127.0.0.1:27183`.
- Une seule connexion TCP full-duplex. `TCP_NODELAY` des deux côtés.
- Tous les entiers sont non signés, **big-endian**.
- Le protocole ne dépend que d'un flux d'octets bidirectionnel ordonné : il fonctionnera tel quel sur les endpoints bulk AOA.

### 4.2 En-tête commun (8 octets)

| Champ | Type | Description |
|---|---|---|
| `type` | u8 | Type de message |
| `flags` | u8 | Dépend du type, 0 sinon |
| `reserved` | u16 | Toujours 0 |
| `payload_length` | u32 | Taille du payload en octets. Rejet si > 16 777 216 (16 Mo) |

### 4.3 Messages PC → tablette

| Type | Nom | Payload | Rôle |
|---|---|---|---|
| 0x01 | `CONFIG` | `codec` u8 (1 = H.264), `width` u16, `height` u16, `fps` u16 | Envoyé avant toute vidéo et à chaque changement de format. La tablette (re)crée son décodeur. |
| 0x02 | `VIDEO` | `pts_us` u64, puis une unité d'accès H.264 complète en Annex-B | flags : `KEY` = 0x01 (IDR), `CODEC_CONFIG` = 0x02 (SPS+PPS seuls) |
| 0x03 | `PONG` | `t_tab_us` u64 (renvoyé tel quel), `t_pc_us` u64 | Réponse à `PING` |

### 4.4 Messages tablette → PC

| Type | Nom | Payload | Rôle |
|---|---|---|---|
| 0x81 | `HELLO` | `magic` 4 octets ASCII `"TABX"`, `version` u16 (= 1), `width` u16, `height` u16, `dpi` u16 | Premier message après connexion. Dimensions physiques de l'écran en paysage. |
| 0x82 | `PING` | `t_tab_us` u64 | Envoyé toutes les 500 ms |
| 0x83 | `KEYFRAME_REQ` | vide | Au démarrage et après toute erreur de décodage |
| 0x84 | `STATS` | `fps` u16, `latency_avg_us` u32, `latency_max_us` u32, `dropped` u32, `rtt_us` u32 | Une fois par seconde, sur la fenêtre de la dernière seconde |
| 0x85 | `INPUT` | réservé (phase 4) | — |

Règles :

- Un type inconnu est ignoré (le payload est lu puis jeté), pour la compatibilité ascendante.
- Si la version du `HELLO` ne correspond pas, le PC ferme la connexion avec un message explicite.

### 4.5 Horloges et mesure de latence

- **Horloge PC** : `time.perf_counter_ns() // 1000` dans le relais (QueryPerformanceCounter, haute résolution ; ne pas utiliser `time.monotonic`, limité à ~15,6 ms sur Windows avant Python 3.13). Les `pts_us` et `t_pc_us` utilisent la même horloge.
- **Horloge tablette** : `System.nanoTime() / 1000`, même base que le `nanoTime` fourni par `MediaCodec.OnFrameRenderedListener`.
- **Calcul (côté tablette)**, à la réception d'un `PONG` à l'instant `t_recv` :
  - `rtt = t_recv − t_tab`
  - `offset = t_tab + rtt/2 − t_pc` (convertit une heure PC en heure tablette)
  - On conserve l'`offset` de l'échantillon ayant le plus petit `rtt` parmi les 16 derniers.
- **Latence d'une frame** = `t_affichage − (pts_us + offset)`, où `t_affichage` vient de `OnFrameRenderedListener`.
- En phase 1, `pts_us` correspond au moment où le relais a reçu la frame complète de ffmpeg : la capture, l'encodage et le délai de découpage du relais ne sont donc **pas** inclus. La latence de bout en bout réelle se mesure en filmant les deux écrans.

## 5. Client Android

### 5.1 Projet

- Kotlin, minSdk 30, targetSdk 35, package `dev.tabx.client` (nom provisoire).
- Interface en Jetpack Compose (seule dépendance hors framework). Le `SurfaceView` est intégré via `AndroidView`.
- Une seule activité, paysage forcé, plein écran immersif, écran maintenu allumé.

### 5.2 Modules

```
dev/tabx/client/
├── protocol/        Kotlin pur, sans dépendance Android (testable sur JVM)
│   ├── Messages.kt      sealed class Message + constantes de types et flags
│   ├── FrameReader.kt   InputStream → Message (garde-fou de taille, types inconnus ignorés)
│   └── FrameWriter.kt   Message → OutputStream, thread-safe
├── net/
│   └── Server.kt        ServerSocket sur 127.0.0.1:27183, un client à la fois
├── video/
│   └── VideoDecoder.kt  encapsule MediaCodec : configure(config, surface), submit(frame), release()
├── stats/
│   └── LatencyTracker.kt  offset d'horloge, latence par frame, agrégat par seconde (Kotlin pur)
├── ui/
│   ├── Glass.kt         GlassCard (vrai verre), GlassPanel (verre simulé), GlassText
│   ├── WaitingScreen.kt écran d'attente / erreur, fond flouté animé
│   ├── StreamScreen.kt  SurfaceView, HUD, détection du tap à 3 doigts
│   └── TabXApp.kt       composition racine (vidéo letterboxée + écran d'attente + HUD)
├── Session.kt           une connexion de bout en bout (+ ScreenInfo)
├── Receiver.kt          boucle d'accept sur le thread net-reader, une Session à la fois
├── UiModel.kt           état observable par Compose (connexion, HUD)
└── MainActivity.kt
```

### 5.3 Décodeur

- `MediaFormat` : `video/avc`, dimensions issues de `CONFIG`, `KEY_LOW_LATENCY = 1`, `KEY_PRIORITY = 0`.
- Mode asynchrone (`setCallback` sur un `HandlerThread` dédié).
- Les indices de buffers d'entrée libres sont placés dans une `ArrayBlockingQueue`. Le thread réseau prend un indice (attente bloquante), copie la frame, appelle `queueInputBuffer` avec `presentationTimeUs = pts_us`. Si le décodeur sature, le thread réseau bloque et TCP applique la contre-pression jusqu'au PC : aucune file ne grossit.
- Les paquets `CODEC_CONFIG` sont soumis avec `BUFFER_FLAG_CODEC_CONFIG`.
- Après création ou recréation du décodeur, toute frame non-`KEY` est ignorée jusqu'à la première `KEY`.
- En sortie : `releaseOutputBuffer(index, true)` immédiatement, sans attendre le pts.
- `setOnFrameRenderedListener` fournit l'heure d'affichage réelle au `LatencyTracker`.
- Le `SurfaceView` est dimensionné au ratio du flux (letterbox sur fond noir).

### 5.4 Threads

| Thread | Rôle |
|---|---|
| `net-reader` | accept, lecture des messages, aiguillage vers le décodeur / le tracker |
| `net-writer` | file d'envoi (`HELLO`, `PING`, `STATS`, `KEYFRAME_REQ`) |
| `codec` | callbacks MediaCodec |
| UI | cycle de vie de la Surface, écrans, HUD |

### 5.5 Déroulé d'une session

1. Accept → envoi de `HELLO` (dimensions physiques en paysage, `densityDpi`).
2. Attente de `CONFIG` → création du décodeur → envoi de `KEYFRAME_REQ`.
3. Boucle : `VIDEO` vers le décodeur, `PONG` vers le tracker. `PING` toutes les 500 ms, `STATS` chaque seconde.
4. Fin (erreur, déconnexion, Surface détruite) → libération du décodeur et de la socket → retour à l'écran d'attente avec la raison → nouvel accept.

### 5.6 Interface (glassmorphism)

Contrainte : le contenu d'un `SurfaceView` est composé par SurfaceFlinger et n'est pas visible par `RenderEffect` / `Modifier.blur`. Le seul flou possible au-dessus de la vidéo (flou de fenêtre) force la composition GPU et ajoute de la latence. D'où :

| Écran | Rendu |
|---|---|
| Attente / connexion / erreur | **Vrai verre dépoli** : fond sombre avec 3 formes colorées animées et floutées (`Modifier.blur`, API 31+), `GlassCard` translucide par-dessus (fond blanc ~10 % d'opacité, bordure blanche ~28 %, coins 20 dp). Contenu : nom de l'app, version du protocole, statut animé (« En attente du PC… »), commande du relais à lancer sur le PC (`py relay.py --encoder nvenc`), résolution et port. |
| Streaming | Vidéo plein écran, **rien par-dessus par défaut**. HUD optionnel en **verre simulé** (teinte sombre ~55 %, bordure claire, reflet en haut, sans flou) : fps, latence moyenne/max de la dernière seconde, p50/p99 de la session (histogramme par pas de 1 ms), offset d'horloge, nom du décodeur. Affichage et masquage par tap à 3 doigts. |

- Thème sombre uniquement.
- Transition : fondu de la carte au démarrage de la session, retour animé de l'écran d'attente à la déconnexion, avec la raison (« PC déconnecté », « Protocole invalide : … », « Port 27183 déjà utilisé »). Une version de protocole incompatible est détectée et expliquée côté PC (c'est le PC qui lit le `HELLO`) ; la tablette voit seulement une déconnexion.

## 6. Relais PC (prototype Python)

### 6.1 Chaîne

```
ffmpeg (ddagrab → encodeur matériel → H.264 Annex-B sur stdout)
  → relay.py (découpage en unités d'accès → protocole TABX)
  → TCP 127.0.0.1:27183 → adb forward → tablette
```

### 6.2 Commande ffmpeg (ffmpeg ≥ 6.0)

NVIDIA :

```
ffmpeg -f lavfi -i ddagrab=output_idx=0:framerate=60,hwdownload,format=bgra
  -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -delay 0
  -rc cbr -b:v 30M -bf 0 -g 60
  -bsf:v h264_metadata=aud=insert -f h264 -
```

AMD : `-c:v h264_amf -latency 1 -quality speed -aud 0`, le reste identique.

Mesuré sur la machine cible : avec `-usage ultralowlatency`, AMF ignore `-g` (une seule IDR) ; AMF ajoute ses propres AUD si `-aud 0` est absent. Le relais réinsère SPS/PPS dans toute IDR qui n'en porte pas. NVENC exige un pilote NVIDIA ≥ 610 avec ce build de ffmpeg.

Le relais construit cette commande : `relay.py --encoder nvenc|amf --output 0 --bitrate 30M --fps 60`.

### 6.3 Compromis assumés en phase 1

| Compromis | Raison | Corrigé en |
|---|---|---|
| `hwdownload` (copie via le CPU) | Sur le portable hybride, l'écran est piloté par l'AMD et NVENC est sur la NVIDIA : le passage direct GPU→GPU échoue dans ffmpeg (mesuré : sans `hwdownload`, AMF échoue avec « SubmitInput() failed with error 18 »). | Phase 2 |
| GOP fixe de 60 | Le relais ne peut pas forcer d'IDR dans ffmpeg : `KEYFRAME_REQ` est journalisé et satisfait en ≤ 1 s. | Phase 2 |
| Fin de frame détectée à l'AUD suivant | Seul découpage fiable sur un pipe ; ajoute ~1 frame (16 ms) hors mesure tablette. | Phase 2 |
| Résolution = écran PC existant | La tablette letterboxe ; le 2880×1800 natif arrive avec l'IDD. | Phase 3 |

### 6.4 Fonctionnement de `relay.py` (Python ≥ 3.10, bibliothèque standard uniquement)

1. Vérifie `adb devices` et exécute `adb forward tcp:27183 tcp:27183`.
2. Se connecte (`TCP_NODELAY`). En cas de refus, réessaie chaque seconde en affichant « Ouvre l'app sur la tablette ».
3. Lit le `HELLO`, vérifie le magic et la version.
4. Lance ffmpeg, lit le premier SPS pour obtenir la taille (en appliquant le `frame_cropping` : 1080 lignes sont codées en 1088), envoie `CONFIG` avec le `fps` passé en argument.
5. Découpe le flux : ignore tout jusqu'au premier IDR, envoie SPS+PPS en `VIDEO` avec `CODEC_CONFIG`, puis chaque unité d'accès en `VIDEO` (flag `KEY` si elle contient un IDR). `pts_us` = horloge PC à la fin du découpage.
6. Thread lecteur : répond à chaque `PING` par un `PONG` immédiat, affiche les `STATS` en console (fps, latence moyenne/max, frames perdues, RTT), journalise les `KEYFRAME_REQ`.
7. Si la tablette se déconnecte : arrêt de ffmpeg, retour à l'étape 2. Ctrl+C : arrêt propre.

### 6.5 Fichiers

```
host-prototype/
├── relay.py      point d'entrée, arguments, orchestration
├── protocol.py   encodage / décodage des messages
├── annexb.py     découpeur NAL / unités d'accès, extraction de la taille depuis le SPS (logique pure)
└── tests/
    ├── sample.h264           ~30 frames générées par ffmpeg testsrc, avec AUD
    ├── test_annexb.py
    └── test_protocol.py
```

## 7. Gestion des erreurs

### 7.1 Android

| Situation | Réaction |
|---|---|
| En-tête invalide, payload > 16 Mo | Fin de session, raison affichée |
| Type de message inconnu | Payload ignoré, session continue |
| `CodecException` transitoire | Nouvel essai |
| `CodecException` non transitoire (récupérable ou fatale), ou aucun buffer d'entrée libre pendant 500 ms | Décodeur libéré et recréé (couvre aussi le cas récupérable, plus simple qu'un `stop`/`configure`/`start`), `KEYFRAME_REQ`, frames ignorées jusqu'à la prochaine `KEY` |
| Exception inattendue (ex. `IllegalStateException` de MediaCodec) | Fin de session, raison affichée, l'app ne plante pas |
| Nouveau `CONFIG` en cours de session | Décodeur recréé |
| Socket fermée / `IOException` | Fin de session, « PC déconnecté » |
| Port 27183 occupé (`BindException`) | Message d'erreur, nouvel essai toutes les 2 s |
| Surface détruite | Fin de session propre ; écoute reprise au retour de l'app |

### 7.2 Relais

| Situation | Réaction |
|---|---|
| `adb` introuvable / aucun appareil / appareil `unauthorized` | Message explicite avec l'action à faire, code de sortie ≠ 0 |
| Connexion refusée | Nouvel essai chaque seconde |
| Version incompatible | Message explicite, code de sortie ≠ 0 |
| ffmpeg introuvable ou terminé | Dernières lignes de son stderr, code de sortie ≠ 0 |
| Tablette déconnectée | ffmpeg arrêté, retour à l'attente de connexion |

## 8. Tests

- **Vecteurs partagés** (`protocol/test-vectors.json`) : pour chaque type de message, ses champs et ses octets attendus en hexadécimal. Les tests Kotlin et Python lisent ce même fichier et vérifient l'encodage et le décodage.
- **Kotlin (JUnit, JVM)** : vecteurs partagés ; rejet d'un payload trop gros ; type inconnu ignoré ; flux tronqué → exception propre ; `LatencyTracker` (offset au plus petit RTT, latence, agrégats) sur des valeurs synthétiques.
- **Python (unittest)** : vecteurs partagés ; découpeur sur `sample.h264` (nombre d'unités d'accès, détection des IDR, extraction SPS/PPS, taille lue depuis le SPS).
- **Intégration manuelle** : checklist dans le README, reprenant les critères de la section 9.

## 9. Critères de réussite

1. Le bureau PC s'affiche à 60 fps stables pendant 10 minutes, sans artefacts cumulés.
2. Latence envoi→affichage mesurée par la tablette (p50/p99 de session affichés dans le HUD) : médiane ≤ 20 ms, 99e centile ≤ 40 ms.
3. Latence de bout en bout (vidéo au téléphone, chronomètre en ms) relevée comme référence. La cible < 50 ms s'applique à partir de la phase 2.
4. Câble débranché puis rebranché, relais relancé : le flux reprend sans redémarrer l'app.
5. Relais tué en plein flux : l'app revient à l'écran d'attente avec la raison.
6. Tous les tests unitaires passent.

Si le critère 2 n'est pas atteint, c'est un résultat de mesure, pas un échec : il déclenche l'essai de clés MediaCodec spécifiques Samsung et d'autres modes de rendu avant la phase 2.
