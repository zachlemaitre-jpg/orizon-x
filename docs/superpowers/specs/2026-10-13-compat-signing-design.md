# Orizon X — APK signée et compatibilité large (design)

Date : 2026-10-13
Statut : validé par l'utilisateur, à implémenter (branche `compat` depuis `master`)

## 1. APK signée avec la clé de l'utilisateur

- **Keystore** : `C:\Users\zachl\OrizonX-signing\orizonx-release.jks`, alias `orizonx`, RSA 4096, validité 10950 jours. Il est généré une fois avec le `keytool` du JBR d'Android Studio, avec un mot de passe aléatoire fort (32 caractères alphanumériques).
- **Paramètres** : `C:\Users\zachl\OrizonX-signing\keystore.properties`, qui contient `storeFile`, `storePassword`, `keyAlias` et `keyPassword`. **Ni le dossier ni les secrets ne vont dans Git.**
- **Gradle** (`android/app/build.gradle.kts`) : `signingConfigs.release` lit les paramètres depuis `ORIZONX_SIGNING_DIR` (variable d'environnement) ou, par défaut, `%USERPROFILE%\OrizonX-signing`.
  - Si le fichier manque, la tâche `assembleRelease` échoue avec un message clair. `assembleDebug` n'est pas concerné.
  - `minifyEnabled` reste à `false`.
- **Version** :
  - `versionName` est lu dans `host-prototype/version.py` (`__version__`), seule source de version ;
  - `versionCode` = `major*10000 + minor*100 + patch` (0.6.0 donne 600) ;
  - un test Gradle ou Kotlin vérifie la lecture.
- **`build-android.ps1`** (racine) :
  1. il fixe `JAVA_HOME` sur le JBR ;
  2. il lance `:app:assembleRelease` ;
  3. il copie `app-release.apk` vers `dist/OrizonX.apk` ;
  4. il affiche l'empreinte SHA-256 du certificat (`apksigner verify --print-certs` ou `keytool -printcert -jarfile`).
- **Bascule unique sur la tablette** : désinstaller `com.orizonx.client` (signé avec la clé de debug), puis installer l'APK release. Les mises à jour suivantes s'installent par-dessus.
- Le README explique comment sauvegarder le dossier de signature et ce qu'on perd s'il disparaît.

## 2. Encodeurs

`engine.ENCODERS` gagne deux encodeurs :
- **`qsv`** : `-c:v h264_qsv -preset veryfast -look_ahead 0 -async_depth 1` ;
- **`x264`** : `-c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -x264-params "keyint=<fps>:min-keyint=<fps>:scenecut=0"`.

`AUTO_ORDER = ("nvenc", "amf", "qsv", "x264")`. Les sondes sont les mêmes qu'aujourd'hui (une image encodée). x264 est toujours disponible si ffmpeg l'embarque, ce qui est le cas du build Gyan.

**Quand l'encodeur retenu est `x264`** : `fps` est plafonné à 30 et la taille de capture à 1920 pixels de large (même format). Le moteur choisit une résolution réduite pour l'écran virtuel, comme au §3. Une ligne de journal explique pourquoi.

Le réglage **Encodeur** de la fenêtre propose `Auto`, `AMF (AMD)`, `NVENC (NVIDIA)`, `QuickSync (Intel)` et `Processor (CPU)`, en anglais et en français. Les réglages sont validés en conséquence.

## 3. Résolution et débit adaptés à l'appareil

**Annonce de l'appareil** : `DEVICE_INFO` gagne un champ facultatif.

```json
"video":{"width":<int>,"height":<int>,"fps":60|30}
```

C'est la plus grande taille au format de l'écran (paysage) que le décodeur AVC matériel sait décoder à 60 i/s, sinon à 30 i/s.

Calcul sur Android (`video/DecoderCaps.kt`) :
- `MediaCodecList(REGULAR_CODECS)` ;
- décodeurs `video/avc` qui ne sont pas logiciels (`isHardwareAccelerated` ; à défaut, le nom n'est ni `OMX.google.` ni `c2.android.`) ;
- candidats : la résolution native, puis ×0,85, ×0,75, ×2/3 et ×0,5. Les tailles sont arrondies à un multiple de 8, et le format est conservé ;
- on retient le premier candidat pour lequel `VideoCapabilities.areSizeAndRateSupported(w, h, fps)` est vrai, d'abord avec fps = 60, puis avec 30 ;
- s'il n'y en a aucun, ou si la vérification lève une exception, le champ est omis.

**Côté PC** :
- `video` absent : comportement actuel (taille native, 60 i/s).
- `video` présent :
  - en mode Extend, l'écran virtuel est préparé à `video.width × video.height` au lieu de la taille native. `pick_mode` reste le filet de sécurité ;
  - en mode Duplicate, la capture garde la taille de l'écran principal, et la tablette réduit l'image ;
  - `fps` vaut le minimum entre `video.fps` et la limite de l'encodeur.
- **Débit** (`Config.bitrate = "auto"` par défaut) : `round(w × h × fps × 0,09)` bit/s, borné à [8, 40] Mb/s. Une valeur fixe (CLI `--bitrate`) l'emporte.
- **Échelle Auto** : le pourcentage est calculé sur le dpi annoncé, multiplié par le rapport taille capturée / taille native. Le texte garde ainsi la même taille physique.

## 4. Tests

- **PC** :
  - ordre Auto et repli : seul x264 disponible donne x264 ;
  - arguments ffmpeg de qsv et de x264 ;
  - plafonds de x264 (30 i/s, 1920 de large, format conservé) ;
  - calcul du débit et bornes ;
  - `DEVICE_INFO.video` lu et appliqué (taille de l'écran virtuel, fps) ;
  - absence de `video` : comportement inchangé ;
  - échelle corrigée.
- **Android** : `DecoderCaps` avec de fausses capacités (native supportée, réduction à ×0,75, uniquement 30 i/s, aucune) ; encodage de `DEVICE_INFO` avec `video` ; lecture de la version.
- **Réel** :
  - sur le PC de l'utilisateur, sonde `qsv` (absent, ce qui est attendu) ;
  - un flux forcé en `x264` (encodeur Processor), avec le ressenti de l'utilisateur ;
  - l'APK release installée après la désinstallation unique ;
  - la tablette annonce bien sa taille native à 60 i/s.
