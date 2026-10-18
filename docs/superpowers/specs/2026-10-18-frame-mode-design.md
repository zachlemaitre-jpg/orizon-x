# Orizon X — Mode Tableau (design)

Date : 2026-10-18
Statut : validé par l'utilisateur, à implémenter (branche `frame-mode`, depuis `i18n-guide`)

## 1. Objectif

Un troisième rôle de l'appareil, **Frame** (« Tableau » en français), à côté de Screen et Actions. L'appareil fait défiler, comme un cadre photo, les images et les vidéos d'un dossier du PC.

**Exclus** :
- conversion des vidéos que l'appareil ne sait pas lire (elles sont ignorées) ;
- son des vidéos ;
- fond flou derrière les bandes ;
- plusieurs appareils ;
- mode Tableau dans la CLI `relay.py`.

## 2. Comportement

- **Rôle** : bouton « Frame » / « Tableau » sur l'écran d'attente, avec l'icône `ox_mode_frame` (chemin Material Icons « image », Apache-2.0, mention dans le fichier).
  - Valeur sur le fil : `"frame"`. Rôle par défaut inchangé : Screen sur tablette, Actions sur téléphone.
  - Écran gardé allumé ; orientation libre.
- **Réglages** : ils sont faits dans la fenêtre PC, dans un nouveau groupe « Frame » / « Tableau », et enregistrés dans `settings.json`.

  | Réglage | Choix | Défaut |
  |---|---|---|
  | **Folder** | bouton « Choose… » (`QFileDialog.getExistingDirectory`), chemin affiché, raccourci avec une ellipse au milieu | aucun |
  | **Interval** | 5 s, 10 s, 30 s, 1 min, 5 min, 15 min, 1 h | 30 s |
  | **Display** | **Crop** (remplit l'écran, bords coupés) ou **Fit** (image entière, bandes noires) | Crop |

  Les réglages s'appliquent tout de suite à une session Tableau en cours.
- **Liste de lecture** :
  - fichiers retenus : images `.jpg .jpeg .png .webp .bmp .gif` (le GIF s'affiche comme image fixe) et vidéos `.mp4 .m4v .mov .webm .mkv` ;
  - les sous-dossiers sont inclus, les fichiers cachés ou système ignorés ;
  - ordre aléatoire : chaque fichier passe une fois par tour ;
  - le dernier fichier d'un tour n'est jamais le premier du tour suivant ;
  - le dossier est relu au début de chaque tour et à chaque changement de dossier.
- **Images** :
  - affichées pendant l'intervalle ;
  - le PC les lit avec `QImageReader`, qui suit l'orientation EXIF (`setAutoTransform(True)`) ;
  - il les réduit si le plus petit côté de l'image dépasse le plus grand côté de l'écran annoncé (le format est gardé). L'image couvre ainsi l'écran dans les deux orientations ;
  - il les envoie en JPEG, qualité 90.
- **Vidéos** :
  - lues jusqu'au bout, puis passage au fichier suivant ;
  - sans son ;
  - envoyées telles quelles ;
  - retenues si le codec vidéo, lu dans la sortie de `ffmpeg -hide_banner -i <fichier>` (ligne `Stream #…: Video: <codec>`), est `h264`, `hevc`, `vp8` ou `vp9`, et si le fichier fait au plus 2 Gio. Sinon, elles sont ignorées, avec une ligne de journal.
- **Sur l'appareil**, un tap affiche une barre pendant 5 s :
  - **Pause/Lecture** : en pause, la minuterie et la vidéo s'arrêtent ;
  - **Suivant** ;
  - **Crop/Fit** ;
  - l'**intervalle** (− / + parmi les valeurs du tableau).

  Chaque changement est envoyé au PC, qui l'enregistre et met à jour sa fenêtre. La pause n'est pas enregistrée : chaque session démarre en lecture.
- **Transition** : fondu enchaîné d'environ 1 s.
- **États** : un message centré sur fond noir.

  | État | Message |
  |---|---|
  | aucun dossier choisi | « Choose a folder in Orizon X on the PC » / « Choisis un dossier dans Orizon X sur le PC » |
  | dossier vide | « No images or videos in this folder » / « Aucune image ni vidéo dans ce dossier » |
  | dossier illisible ou supprimé | « Cannot read the folder » / « Impossible de lire le dossier » |
  | premier fichier en cours d'envoi | « Loading… » / « Chargement… » |

## 3. Protocole

Les ajouts sont rétrocompatibles et la version reste 1.

- **`DEVICE_INFO.role`** accepte `"frame"`. Un ancien PC le traite comme un rôle inconnu, donc comme `screen` (comportement actuel pour un rôle inconnu).
- **`FRAME_STATE` (0x06, PC → appareil)**, JSON UTF-8 de 65 536 octets au plus :
  ```json
  {"epoch":<u32>,"status":"ok"|"no_folder"|"empty"|"unreadable","folder":"<nom du dossier>"|null,
   "interval_s":<int>,"fit":"crop"|"fit","paused":<bool>}
  ```
  - Le PC l'envoie au début de la session et à chaque changement de réglage ou d'état.
  - `epoch` augmente à chaque changement de dossier. L'appareil jette alors les fichiers d'une autre époque, déjà reçus ou en cours de réception.
- **`FRAME_FILE` (0x07, PC → appareil)**, un morceau de fichier :
  - en-tête : `epoch` u32, `id` u32, `kind` u8 (1 = image JPEG, 2 = vidéo), `total` u64, `offset` u64 ;
  - puis les données, de 1 à 1 048 576 octets ;
  - les morceaux d'un même fichier arrivent dans l'ordre, sans trou ;
  - le fichier est complet quand `offset + taille des données = total` ;
  - les `id` augmentent dans une session.
- **`ACTION` (appareil → PC)** :
  - `{"id":"frame.next"}` : l'élément affiché est fini (minuterie, fin de vidéo ou bouton Suivant) ;
  - `{"id":"frame.pause","paused":true|false}` ;
  - `{"id":"frame.fit","fit":"crop"|"fit"}` ;
  - `{"id":"frame.interval","interval_s":<int>}` : le PC ignore une valeur hors du tableau ;
  - `{"id":"frame.failed","file":<id>}` : l'appareil n'a pas pu afficher ce fichier. Le PC le retire de la liste pour la session et envoie le suivant.
- **Avance d'un fichier** :
  - le PC envoie le fichier n°1, puis le n°2 aussitôt après ;
  - à chaque `frame.next` ou `frame.failed`, il envoie le fichier suivant de la liste ;
  - l'appareil garde donc toujours un fichier d'avance.
- `protocol/PROTOCOL.md` documente tout cela, et `protocol/test-vectors.json` gagne un vecteur `FRAME_STATE` et un vecteur `FRAME_FILE`, partagés par Python et Kotlin.

## 4. PC

- **`frame/playlist.py`** : `Playlist(scan)`.
  - `scan(folder) -> list[Path]` est injectable ;
  - `next() -> Path | None` applique l'ordre aléatoire par tour et la relecture du dossier à chaque tour ;
  - `remove(path)` retire un fichier ;
  - `status` vaut `ok`, `empty` ou `unreadable`.
- **`frame/prepare.py`** :
  - `prepare_image(path, screen) -> bytes` (JPEG) passe par `QImageReader`. Un échec lève une `PrepareError` ;
  - `video_codec(ffmpeg, path, run) -> str | None` lit le codec ;
  - `cover_size(image_size, screen) -> size` calcule la taille cible (§2).
- **`frame/session.py`** : `FrameSession(send_state, send_file, log, config, prepare…)`.
  - Il tient la liste, les réglages, `epoch` et l'avance d'un fichier ;
  - il découpe les fichiers en morceaux de 1 Mio, lus en flux depuis le disque (jamais le fichier entier en mémoire) ;
  - il traite les actions `frame.*` ;
  - il prévient un écouteur (`on_frame_settings(interval_s, fit, paused)`) quand l'appareil change un réglage.
  - La préparation et l'envoi se font dans un thread à lui. Le `send` de l'engine sérialise les écritures avec les autres messages.
- **`engine.py`** :
  - le rôle `frame` lance une session Tableau à la place de l'écran : pas de vidéo ni d'écran virtuel, comme pour Actions ;
  - `Deps.frame_session_factory` ;
  - les actions `frame.*` sont routées vers la session ;
  - `RelayEngine.set_frame_config(folder, interval_s, fit)` est appelé par la fenêtre et s'applique à la session en cours.
- **`protocol.py`** : constantes et encodage de `FRAME_STATE` et `FRAME_FILE`, plus le décodage dans les tests.
- **Application** :
  - `settings.Settings` gagne `frame_folder: str | None`, `frame_interval_s: int = 30` et `frame_fit: str = "crop"`, validés au chargement ;
  - `window.py` gagne le groupe « Frame » (bouton de dossier, deux listes) ;
  - `controller.py` relie la fenêtre, les réglages et l'engine, dans les deux sens ;
  - les textes sont en anglais et en français dans `messages.py`.

## 5. Android

- **`DeviceRole.FRAME("frame")`**, le bouton de l'écran d'attente et l'icône.
- **`frame/FrameMessages.kt`** : décodage de `FRAME_STATE` et `FRAME_FILE`, avec tolérance pour les champs inconnus.
- **`frame/FrameStore.kt`** reconstitue les fichiers dans `cacheDir/frame/`.
  - Il vérifie l'ordre des morceaux ; un morceau inattendu fait abandonner le fichier, qui est signalé par `frame.failed`.
  - Il jette les fichiers d'une autre époque.
  - Il garde au plus 3 fichiers et vide le dossier en début et en fin de session.
- **`frame/FramePlayer.kt`** : état pur (élément affiché, suivant prêt, minuterie, pause, état) et décisions (quand envoyer `frame.next`, quand basculer), testables sans Android.
- **`ui/FrameScreen.kt`** :
  - **images** : décodées avec `inSampleSize` à la taille de l'écran, `ContentScale.Crop` ou `ContentScale.Fit` ;
  - **vidéos** : `MediaPlayer` dans un `TextureView`, volume 0, avec une matrice de recadrage équivalente à Crop ou Fit ;
  - un échec de lecture envoie `frame.failed` ;
  - fondu enchaîné, barre de contrôle et messages d'état ;
  - tous les textes passent par `Strings`, en anglais et en français.

## 6. Erreurs

- **Fichier** : un fichier illisible, une image que Qt ne sait pas lire ou une vidéo refusée est ignoré et journalisé, puis le PC passe au suivant.
- **Dossier** :
  - si tous les fichiers échouent, l'état devient `empty` ;
  - un dossier supprimé ou illisible donne l’état `unreadable` ; le PC relit alors le dossier toutes les 10 s jusqu’à ce qu’il redevienne lisible.
- **Connexion** : une déconnexion en plein envoi fait jeter le fichier partiel par l'appareil. Le PC arrête son thread.

## 7. Tests

- **PC** :
  - liste : aléatoire sans répétition dans un tour, pas de doublon à la jonction de deux tours, sous-dossiers, filtres d'extensions et fichiers cachés, relecture à chaque tour, `remove`, états ;
  - `cover_size` ;
  - `video_codec` avec de fausses sorties de `ffmpeg -i` (h264, hevc, vp9, av1, erreur) ;
  - encodage de `FRAME_STATE` et `FRAME_FILE` contre les vecteurs ;
  - session avec faux envois :
    - deux fichiers d'avance au départ, puis un par `frame.next` ;
    - morceaux de 1 Mio et dernier morceau ;
    - changement de dossier qui incrémente `epoch` ;
    - `frame.fit`, `frame.pause`, `frame.interval` appliqués et signalés à l'écouteur ;
    - `frame.failed` ;
    - états vide et illisible ;
  - engine : le rôle `frame` crée la session sans écran virtuel et route les actions `frame.*` ;
  - réglages : chargement, valeurs invalides ;
  - fenêtre : le groupe, ses signaux, la mise à jour depuis l'appareil.
- **Android** :
  - décodage des deux messages contre les vecteurs ;
  - `FrameStore` : reconstitution, morceau hors d'ordre, autre époque, limite de 3 fichiers ;
  - `FramePlayer` : minuterie d'image, fin de vidéo, pause, bouton Suivant, fichier suivant pas encore prêt (on attend en gardant l'élément affiché), échec ;
  - textes en anglais et en français (test de complétude existant) ;
  - JSON des actions.
- **Réel**, avec l'utilisateur : un dossier de photos (dont une photo de téléphone en portrait, pour l'EXIF) et une vidéo MP4. On vérifie Crop et Fit, l'intervalle, la pause, Suivant, le changement de dossier en cours de session et une vidéo refusée.
