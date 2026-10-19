# Protocole TABX v1

Flux d'octets bidirectionnel ordonné (TCP via `adb forward` en phase 1, endpoints bulk AOA plus tard).
La tablette écoute sur `127.0.0.1:27183` ; le PC se connecte. Entiers non signés, big-endian.

## En-tête (8 octets)

| Champ | Type | Description |
|---|---|---|
| type | u8 | Type de message |
| flags | u8 | Dépend du type, 0 sinon |
| reserved | u16 | 0 |
| payload_length | u32 | Taille du payload. Rejet si > 16 777 216 |

Un type inconnu est ignoré (payload lu puis jeté).

Le récepteur ignore `reserved` et les bits de `flags` qu'il ne connaît pas.
La taille du payload d'un type connu est exacte : une taille différente est une erreur de protocole. Toute extension d'un message existant impose une nouvelle version du protocole.

## PC → tablette

| Type | Nom | Payload |
|---|---|---|
| 0x01 | CONFIG | codec u8 (1 = H.264), width u16, height u16, fps u16 |
| 0x02 | VIDEO | pts_us u64, puis une unité d'accès H.264 Annex-B. Flags : KEY = 0x01, CODEC_CONFIG = 0x02 |
| 0x03 | PONG | t_tab_us u64 (renvoyé tel quel), t_pc_us u64 |
| 0x04 | ACTIONS_STATE | JSON UTF-8 : l'état complet du mode Actions (voir « Mode Actions »). Au plus 65 536 octets |
| 0x05 | MEDIA_ARTWORK | `n` u8 (longueur de l'id, 1..255), puis l'id (`n` octets ASCII, sha1 hexadécimal : 40 caractères), puis l'image brute (JPEG ou PNG, au moins 1 octet). Payload total de 524 288 octets (512 Kio) au plus |
| 0x06 | FRAME_STATE | JSON UTF-8 : les réglages et l'état du mode Tableau (voir « Mode Tableau »). Au plus 65 536 octets |
| 0x07 | FRAME_FILE | epoch u32, id u32, kind u8 (1 = image JPEG, 2 = vidéo), total u64, offset u64 (25 octets), puis 1 à 1 048 576 octets de données du fichier (voir « Mode Tableau ») |

## Tablette → PC

| Type | Nom | Payload |
|---|---|---|
| 0x81 | HELLO | magic "TABX", version u16 (= 1), width u16, height u16, dpi u16 |
| 0x82 | PING | t_tab_us u64 (toutes les 500 ms) |
| 0x83 | KEYFRAME_REQ | vide |
| 0x84 | STATS | fps u16, latency_avg_us u32, latency_max_us u32, dropped u32, rtt_us u32 (chaque seconde) |
| 0x85 | INPUT | device u8 (1 tactile, 2 stylet), count u8 (≤ 10 tactile, ≤ 1 stylet), puis count × contact de 10 octets (voir ci-dessous) |
| 0x86 | DEVICE_INFO | JSON UTF-8 : `{"role":"screen"\|"actions"\|"frame","kind":"phone"\|"tablet","name":"<modèle>","app":"<version>"[,"video":{"width":<int>,"height":<int>,"fps":60\|30}][,"lang":"en"\|"fr"]}`. Au plus 65 536 octets |
| 0x87 | ACTION | JSON UTF-8 : `{"id":"<action>", …}` ; `id` est une chaîne obligatoire. Au plus 65 536 octets |

## INPUT (phase 4)

Contact (10 octets) : `id u8, flags u8, x u16, y u16, pressure u16, tilt_x i8, tilt_y i8`.

- `id` : emplacement stable 0..9 (tactile) ; 0 (stylet).
- `flags` : bit0 CONTACT (posé), bit1 IN_RANGE (détecté, y compris en survol), bit2 BARREL (bouton du stylet), bit3 CANCELED (geste annulé, aucun clic). Les autres bits valent 0 et sont ignorés.
- `x`, `y` : 0..65535 sur l'image vidéo. `pressure` : 0..1024 (stylet). `tilt_x`, `tilt_y` : degrés −90..90 (stylet).

Chaque message est l'**état complet** d'un périphérique. Un contact absent de la trame suivante est levé, et `count = 0` signifie que tout est levé ou hors de portée. Un contact CANCELED n'apparaît que dans une trame.

## Mode Actions

Les messages 0x04, 0x86 et 0x87 portent un **objet JSON encodé en UTF-8**, de 65 536 octets au plus. Un payload plus grand, un JSON invalide, un JSON qui n'est pas un objet, de l'UTF-8 invalide, un champ de `DEVICE_INFO` absent ou qui n'est pas une chaîne, ou un `ACTION` sans `id` chaîne sont des erreurs de protocole. Les champs inconnus d'un objet sont ignorés. Les JSON envoyés sont compacts (sans espace) et les clés de `DEVICE_INFO` sont dans l'ordre ci-dessus ; `ACTION` écrit `id` en premier, puis les autres clés par ordre alphabétique. Les vecteurs de `test-vectors.json` fixent ces octets.

### Séquence

1. La tablette envoie `HELLO`, puis **immédiatement** `DEVICE_INFO`.
2. Le PC attend `DEVICE_INFO` **1 s au plus** après le `HELLO`. Sans réponse (ancienne application), ou si `role` est inconnu, le rôle vaut `screen` : le comportement est celui de la version précédente (`CONFIG`, `VIDEO`, `INPUT`). Les rôles connus sont `screen`, `actions` et `frame` ; un PC antérieur au mode Tableau traite `frame` comme un rôle inconnu, donc comme `screen`.
3. En rôle `actions`, le PC n'envoie ni `CONFIG` ni `VIDEO` : il envoie un `ACTIONS_STATE` complet, puis un nouveau à chaque changement (l'état complet, pas de diff) et au moins toutes les 30 s. La tablette envoie des `ACTION`. `PING`/`PONG` ne changent pas.
4. Pour changer de rôle, la tablette ferme la connexion et se reconnecte avec le nouveau `DEVICE_INFO`.

### Capacités vidéo (`video`, facultatif)

En rôle `screen`, `DEVICE_INFO` peut porter `"video":{"width":W,"height":H,"fps":F}` en dernière clé : la plus grande taille (paysage, format de l'écran) que le décodeur AVC matériel de la tablette sait décoder à 60 i/s, sinon à 30 i/s (`fps` vaut 60 ou 30). Le champ est omis quand la tablette ne peut pas le déterminer ; il n'est pas envoyé en rôle `actions`. Le PC s'en sert pour choisir la taille de l'écran virtuel, les i/s et le débit ; sans lui, il garde la taille native et 60 i/s. Un ancien PC ignore ce champ (les champs inconnus sont ignorés).

### Langue de l'appareil (`lang`, facultatif)

`DEVICE_INFO` peut porter `"lang":"en"` ou `"lang":"fr"` : la langue effective de l'interface de l'appareil. Le PC la lit avec tolérance : un champ absent, d'une autre valeur ou qui n'est pas une chaîne vaut `fr` (le comportement d'avant ce champ), sans erreur de protocole. Elle sert à traduire ce que le PC fait afficher à l'appareil (la barre contextuelle). L'ordre des clés n'a pas d'importance pour le PC ; un ancien PC ignore le champ. En rôle `actions`, un changement de langue pendant la session est signalé par l'action `context.lang` (voir plus bas) ; en rôle `screen`, le PC n'affiche aucun texte sur l'appareil et rien n'est envoyé.

### Pochette (`MEDIA_ARTWORK`, 0x05)

Le bloc « En cours de lecture » de l'état (`now_playing`, voir ci-dessous) référence sa pochette par un identifiant. Le PC envoie `MEDIA_ARTWORK` **une fois par pochette**, juste **avant** le premier `ACTIONS_STATE` qui la référence. L'image est transmise telle que Windows la fournit (JPEG ou PNG, sans transcodage). La tablette garde la dernière pochette reçue et l'affiche tant que `now_playing.artwork` vaut son id.

`MEDIA_ARTWORK` sert aussi aux **icônes de la barre contextuelle** (PNG 96 × 96, voir `context.icon` plus bas) : même format, même position (avant l'`ACTIONS_STATE` qui les référence). La tablette garde un cache d'images de taille limitée, partagé entre les pochettes et les icônes, et indexé par id.

Sont des erreurs de protocole : un payload de plus de 524 288 octets, vide, avec `n` = 0, dont l'id dépasse le payload ou ne laisse aucun octet d'image, ou dont l'id contient un octet non ASCII. Cette limite remplace, pour ce type, la limite générale. Voir le vecteur `media_artwork_small`.

### Contenu

L'état (`"v":1`) et la liste des actions (`volume.set`, `media.play_pause`, `wifi.set`, `usb.eject`, …) sont décrits dans `docs/superpowers/specs/2026-10-11-actions-mode-design.md` §2.1 et §2.2. Un `ACTION` dont l'`id` est inconnu est journalisé et ignoré.

Le bloc `now_playing` décrit la session média Windows courante (Spotify, navigateur, VLC…) :

```json
"now_playing":{"available":true,"app":"Spotify","title":"…","artist":"…","album":"…","playing":true,"artwork":"<sha1 hex>"}
```

`available: false` (ou section absente) quand aucune session média n'existe. `app`, `title`, `artist`, `album` sont des chaînes (vides si inconnues), `playing` un booléen, `artwork` l'id d'un `MEDIA_ARTWORK` ou `null` sans pochette.

### Barre contextuelle (`context`, `context.press`)

Le bloc `context` décrit l'app au premier plan sur le PC et les boutons que la tablette affiche en bas de l'écran. Le PC possède les profils : la tablette n'affiche que ce qu'elle reçoit.

```json
"context":{"available":true,"app":"PowerPoint","profile":"powerpoint",
           "buttons":[{"id":"ppt.prev","icon":"arrow_left","label":"Précédent"}, …],
           "pages":[{"id":"main","label":"Principal","buttons":[{"id":"ppt.prev","icon":"arrow_left","label":"Précédent"}, …]}]}
```

- `available: false` (ou section absente) tant qu'aucune app n'a été vue : la barre est cachée.
- `app` : le nom à afficher (chaîne non vide). `profile` : l'identifiant du profil (`spotify`, `powerpoint`, `browser`, `word`, `excel`, `vscode`, `explorer`, `illustrator`, `photoshop`, `canva`, `figma`, `premiere`, `aftereffects`, `indesign`, `lightroom`, `generic`), informatif.
- `buttons` : au plus 8 éléments `{"id","icon","label"}`. `icon` est un nom d'icône connu de la tablette (un nom inconnu donne une icône neutre) ; `label` est dans la langue de l'appareil (`DEVICE_INFO.lang`, français par défaut), de même que `app` pour les noms qui varient (« Explorer » / « Explorateur »). Le raccourci clavier ne quitte jamais le PC.
- `icon` : `"<sha1 hex>"` ou `null`. C'est l'id de l'icône de l'app au premier plan (son exe, telle que Windows l'affiche) ou, pour un onglet de navigateur reconnu par son URL (Canva, Figma), l'icône du site ; le navigateur générique garde l'icône du navigateur. Le PC extrait ou télécharge l'icône dans un thread à part : `icon` vaut `null` tant qu'elle n'est pas prête, puis l'état suivant porte l'id. Le PC envoie l'image (PNG 96 × 96, `MEDIA_ARTWORK`) **avant** l'état, **chaque fois que `context.icon` change** vers un id non nul différent de celui du dernier état diffusé (revenir à une app déjà vue renvoie donc son icône : le cache d'images de la tablette est petit et partagé avec les pochettes). Une icône qui ne peut pas être envoyée est remplacée par `null`. Un ancien appareil ignore ce champ.
- `pages` : au plus 4 éléments `{"id","label","buttons"}`, chacun avec au plus 8 boutons (même forme que `buttons`) ; la tablette les affiche en onglets quand il y en a plus d'un. `label` est dans la langue de l'appareil. `pages` est toujours envoyé, même pour un profil d'une seule page (`main`, dont la tablette cache l'onglet), et `buttons` vaut la première page : une ancienne app qui ignore `pages` garde sa première page. Les `id` de boutons sont uniques dans un profil, toutes pages confondues. Les profils d'apps créatives ont des pages `tools`, `edit`, `view` (`illustrator`, `photoshop`, `canva`, `figma`, `indesign`), `tools`, `edit`, `playback` (`premiere`), `tools`, `edit`, `timeline` (`aftereffects`) ou `navigate`, `rate`, `edit` (`lightroom`) ; dans un navigateur, l'adresse de l'onglet (lue par le PC dans la barre d'adresse, via UI Automation) dont l'hôte est `canva.com` ou `figma.com` (ou un sous-domaine) donne le profil `canva` ou `figma`, à défaut un titre de fenêtre qui contient « Canva » ou « Figma » (sans tenir compte de la casse). Les noms d'icônes se trouvent dans `ICON_NAMES` (`host-prototype/actions/context_profiles.py`).
- Le bloc est relevé toutes les 250 ms avec l'audio ; un changement de profil est diffusé aussitôt (état complet).

Action associée : `{"id":"context.press","button":"<id du bouton>"}`. Le PC regarde l'app au premier plan **à cet instant** et n'envoie le raccourci que si le bouton appartient à l'une des pages de son profil ; sinon l'action est ignorée et journalisée (la tablette n'a pas encore redessiné sa barre). Un raccourci qui ne peut pas être injecté (app élevée au premier plan, touche absente de la disposition) donne un `notice` `{"code":"action_failed"}`.

Action `{"id":"context.lang","lang":"en"|"fr"}` : l'appareil change de langue pendant une session Actions. Le PC retraduit aussitôt la barre (état complet diffusé, comme après tout `ACTION`). Une valeur inconnue est ignorée et journalisée ; aucune `notice` n'est produite.

### Compatibilité

Les ajouts sont rétrocompatibles et la version reste 1 : aucun message existant ne change. Un ancien PC ignore les types 0x86 et 0x87 (type inconnu) et reste en rôle `screen` côté tablette. Une ancienne tablette n'envoie pas `DEVICE_INFO` et reçoit l'écran comme avant.

## Mode Tableau (`frame`)

Le rôle `frame` fait de l'appareil un cadre photo : le PC possède la liste de lecture (images et vidéos d'un dossier) et envoie les fichiers ; l'appareil les affiche en diaporama. En rôle `frame`, le PC n'envoie ni `CONFIG` ni `VIDEO`, et `DEVICE_INFO` n'a pas de `video`. `PING`/`PONG` ne changent pas. Les octets de chaque message sont fixés par les vecteurs `frame_state_*` et `frame_file_*` de `test-vectors.json`.

### FRAME_STATE (0x06, PC → appareil)

JSON UTF-8 compact de 65 536 octets au plus, clés dans cet ordre :

```json
{"epoch":3,"status":"ok","folder":"Photos","interval_s":30,"fit":"crop","paused":false}
```

- `epoch` : entier de 0 à 4 294 967 295. Il augmente à chaque changement de dossier ; l'appareil jette alors tous les fichiers d'une autre époque, déjà reçus ou en cours de réception.
- `status` : `"ok"`, `"no_folder"` (aucun dossier choisi), `"empty"` (aucune image ni vidéo) ou `"unreadable"` (dossier illisible ou supprimé).
- `folder` : le nom du dossier à afficher (chaîne), ou `null` sans dossier.
- `interval_s` : la durée d'affichage d'une image en secondes, entier ≥ 1 (valeurs proposées : 5, 10, 30, 60, 300, 900, 3600).
- `fit` : `"crop"` (l'image remplit l'écran, rognée) ou `"fit"` (l'image entière, bandes noires).
- `paused` : booléen.

Le PC l'envoie au début de la session, puis à chaque changement de réglage ou d'état. Lecture tolérante côté appareil : un champ inconnu est ignoré, un `status` inconnu ou absent vaut `unreadable`, un `fit` inconnu vaut `crop`, un `folder` qui n'est pas une chaîne vaut `null`, un `paused` qui n'est pas un booléen vaut `false`. Un JSON invalide, un `epoch` absent ou hors de 0..4 294 967 295 et un `interval_s` absent ou qui n'est pas un entier ≥ 1 sont des erreurs de protocole.

### FRAME_FILE (0x07, PC → appareil)

Un morceau de fichier. Le payload est l'en-tête suivant (25 octets, big-endian), puis les données :

| Champ | Type | Description |
|---|---|---|
| epoch | u32 | L'époque du `FRAME_STATE` sous laquelle le fichier a été choisi |
| id | u32 | L'identifiant du fichier ; il augmente dans une session |
| kind | u8 | 1 = image JPEG, 2 = vidéo (telle quelle) |
| total | u64 | La taille du fichier complet, en octets |
| offset | u64 | La position de ce morceau dans le fichier |
| data | octets | De 1 à 1 048 576 octets |

- Les morceaux d'un même fichier arrivent dans l'ordre, sans trou ni chevauchement ; le premier a `offset` 0.
- Le fichier est complet quand `offset` + taille des données = `total`.
- Sont des erreurs de protocole : un payload d'au plus 25 octets (aucune donnée), plus de 1 048 576 octets de données, un `kind` autre que 1 ou 2, un morceau qui dépasse `total` (`offset` + taille > `total`).
- Un `offset` ou un `total` dont le bit de poids fort est à 1 dépasse tout fichier réel : erreur de protocole.
- Une rupture dans l'ordre des morceaux n'est pas une erreur de protocole : l'appareil rejette le fichier et ignore ses morceaux (voir `frame.failed`).

### Actions `frame.*` (appareil → PC, dans un `ACTION`)

- `{"id":"frame.next"}` : l'élément affiché est fini (minuterie, fin de vidéo ou bouton Suivant).
- `{"id":"frame.pause","paused":true|false}`.
- `{"id":"frame.fit","fit":"crop"|"fit"}`.
- `{"id":"frame.interval","interval_s":<int>}` : le PC ignore une valeur hors de la liste proposée.
- `{"id":"frame.failed","file":<id>}` : l'appareil n'a pas pu afficher ce fichier. Le PC le retire de la liste pour la session et envoie le suivant.

Après une action de réglage, le PC renvoie un `FRAME_STATE` à jour.

### Avance d'un fichier

- Le PC envoie le fichier n° 1, puis le n° 2 aussitôt après.
- À chaque `frame.next` ou `frame.failed`, il envoie le fichier suivant de la liste.
- L'appareil garde donc toujours un fichier d'avance. Un changement de dossier (nouvelle `epoch`) repart de zéro avec deux fichiers de la nouvelle époque.

## Horloges

- PC : `time.perf_counter_ns() // 1000` (même horloge pour `pts_us` et `t_pc_us`).
- Tablette : `System.nanoTime() / 1000`.
- À la réception d'un PONG à `t_recv` : `rtt = t_recv − t_tab`, `offset = t_tab + rtt/2 − t_pc`.
  On garde l'offset de l'échantillon au plus petit RTT parmi les 16 derniers.
- Latence d'une frame = `t_affichage − (pts_us + offset)`.

Les octets attendus de chaque message sont dans `test-vectors.json`.
