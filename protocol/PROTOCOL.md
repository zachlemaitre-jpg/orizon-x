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

## Tablette → PC

| Type | Nom | Payload |
|---|---|---|
| 0x81 | HELLO | magic "TABX", version u16 (= 1), width u16, height u16, dpi u16 |
| 0x82 | PING | t_tab_us u64 (toutes les 500 ms) |
| 0x83 | KEYFRAME_REQ | vide |
| 0x84 | STATS | fps u16, latency_avg_us u32, latency_max_us u32, dropped u32, rtt_us u32 (chaque seconde) |
| 0x85 | INPUT | device u8 (1 tactile, 2 stylet), count u8 (≤ 10 tactile, ≤ 1 stylet), puis count × contact de 10 octets (voir ci-dessous) |
| 0x86 | DEVICE_INFO | JSON UTF-8 : `{"role":"screen"\|"actions","kind":"phone"\|"tablet","name":"<modèle>","app":"<version>"}`. Au plus 65 536 octets |
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
2. Le PC attend `DEVICE_INFO` **1 s au plus** après le `HELLO`. Sans réponse (ancienne application), ou si `role` n'est pas `actions`, le rôle vaut `screen` : le comportement est celui de la version précédente (`CONFIG`, `VIDEO`, `INPUT`).
3. En rôle `actions`, le PC n'envoie ni `CONFIG` ni `VIDEO` : il envoie un `ACTIONS_STATE` complet, puis un nouveau à chaque changement (l'état complet, pas de diff) et au moins toutes les 30 s. La tablette envoie des `ACTION`. `PING`/`PONG` ne changent pas.
4. Pour changer de rôle, la tablette ferme la connexion et se reconnecte avec le nouveau `DEVICE_INFO`.

### Pochette (`MEDIA_ARTWORK`, 0x05)

Le bloc « En cours de lecture » de l'état (`now_playing`, voir ci-dessous) référence sa pochette par un identifiant. Le PC envoie `MEDIA_ARTWORK` **une fois par pochette**, juste **avant** le premier `ACTIONS_STATE` qui la référence. L'image est transmise telle que Windows la fournit (JPEG ou PNG, sans transcodage). La tablette garde la dernière pochette reçue et l'affiche tant que `now_playing.artwork` vaut son id.

Sont des erreurs de protocole : un payload de plus de 524 288 octets, vide, avec `n` = 0, dont l'id dépasse le payload ou ne laisse aucun octet d'image, ou dont l'id contient un octet non ASCII. Cette limite remplace, pour ce type, la limite générale. Voir le vecteur `media_artwork_small`.

### Contenu

L'état (`"v":1`) et la liste des actions (`volume.set`, `media.play_pause`, `wifi.set`, `usb.eject`, …) sont décrits dans `docs/superpowers/specs/2026-10-11-actions-mode-design.md` §2.1 et §2.2. Un `ACTION` dont l'`id` est inconnu est journalisé et ignoré.

Le bloc `now_playing` décrit la session média Windows courante (Spotify, navigateur, VLC…) :

```json
"now_playing":{"available":true,"app":"Spotify","title":"…","artist":"…","album":"…","playing":true,"artwork":"<sha1 hex>"}
```

`available: false` (ou section absente) quand aucune session média n'existe. `app`, `title`, `artist`, `album` sont des chaînes (vides si inconnues), `playing` un booléen, `artwork` l'id d'un `MEDIA_ARTWORK` ou `null` sans pochette.

### Compatibilité

Les ajouts sont rétrocompatibles et la version reste 1 : aucun message existant ne change. Un ancien PC ignore les types 0x86 et 0x87 (type inconnu) et reste en rôle `screen` côté tablette. Une ancienne tablette n'envoie pas `DEVICE_INFO` et reçoit l'écran comme avant.

## Horloges

- PC : `time.perf_counter_ns() // 1000` (même horloge pour `pts_us` et `t_pc_us`).
- Tablette : `System.nanoTime() / 1000`.
- À la réception d'un PONG à `t_recv` : `rtt = t_recv − t_tab`, `offset = t_tab + rtt/2 − t_pc`.
  On garde l'offset de l'échantillon au plus petit RTT parmi les 16 derniers.
- Latence d'une frame = `t_affichage − (pts_us + offset)`.

Les octets attendus de chaque message sont dans `test-vectors.json`.
