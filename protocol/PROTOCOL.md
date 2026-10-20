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
- `app` : le nom à afficher (chaîne non vide). `profile` : l'identifiant du profil (`spotify`, `powerpoint`, `browser`, `word`, `excel`, `vscode`, `explorer`, `illustrator`, `photoshop`, `canva`, `figma`, `premiere`, `aftereffects`, `indesign`, `lightroom`, `claude_app`, `claude_web`, `chatgpt`, `gemini`, `generic`), informatif.
- `buttons` : au plus 8 éléments `{"id","icon","label"}`. `icon` est un nom d'icône connu de la tablette (un nom inconnu donne une icône neutre) ; `label` est dans la langue de l'appareil (`DEVICE_INFO.lang`, français par défaut), de même que `app` pour les noms qui varient (« Explorer » / « Explorateur »). Le raccourci clavier ne quitte jamais le PC.
- `icon` : `"<sha1 hex>"` ou `null`. C'est l'id de l'icône de l'app au premier plan (son exe, telle que Windows l'affiche) ou, pour un onglet de navigateur reconnu par son URL (Canva, Figma), l'icône du site ; le navigateur générique garde l'icône du navigateur. Le PC extrait ou télécharge l'icône dans un thread à part : `icon` vaut `null` tant qu'elle n'est pas prête, puis l'état suivant porte l'id. Le PC envoie l'image (PNG 96 × 96, `MEDIA_ARTWORK`) **avant** l'état, **chaque fois que `context.icon` change** vers un id non nul différent de celui du dernier état diffusé (revenir à une app déjà vue renvoie donc son icône : le cache d'images de la tablette est petit et partagé avec les pochettes). Une icône qui ne peut pas être envoyée est remplacée par `null`. Un ancien appareil ignore ce champ.
- Page défilante `tabs` (onglets du navigateur) : quand un navigateur est au premier plan et que le PC peut lire ses onglets (UI Automation), `pages` contient une page `{"id":"tabs","label":"Onglets"|"Tabs","scroll":true,"buttons":[…]}`, **première** page du profil `browser`, **dernière** page des profils de site (`canva`, `figma`) ; aucun onglet lu, pas de page. C'est la seule page qui porte `scroll` (la tablette l'affiche en rangée qui défile) et la seule qui peut avoir plus de 8 boutons : au plus 24, `{"id":"tab.<rang>","icon":"tab","label":"<titre court>","active":true|false}` (rang à partir de 0, dans l'ordre de la barre d'onglets ; `active` : l'onglet affiché). Les autres boutons n'ont pas de champ `active`. Pour une ancienne app, `buttons` vaut la première page qui ne défile pas.
  `context.press` sur `tab.<rang>` : accepté si le rang existe dans la dernière liste d'onglets envoyée pour la fenêtre du navigateur au premier plan ; le PC bascule sur l'onglet (par son titre court, retrouvé à un autre rang si la barre a changé), puis l'état est rediffusé aussitôt. Sinon, ou en cas d'échec, l'action est ignorée et journalisée (pas de `notice`).
- `pages` : au plus 4 éléments `{"id","label","buttons"}`, chacun avec au plus 8 boutons (même forme que `buttons`) ; la tablette les affiche en onglets quand il y en a plus d'un. `label` est dans la langue de l'appareil. `pages` est toujours envoyé, même pour un profil d'une seule page (`main`, dont la tablette cache l'onglet), et `buttons` vaut la première page : une ancienne app qui ignore `pages` garde sa première page. Les `id` de boutons sont uniques dans un profil, toutes pages confondues. Les profils d'apps créatives ont des pages `tools`, `edit`, `view` (`illustrator`, `photoshop`, `canva`, `figma`, `indesign`), `tools`, `edit`, `playback` (`premiere`), `tools`, `edit`, `timeline` (`aftereffects`) ou `navigate`, `rate`, `edit` (`lightroom`) ; les profils `claude_app` (`claude.exe`), `chatgpt` (`ChatGPT.exe`) et, dans un navigateur, `claude_web` (hôte `claude.ai`), `chatgpt` (`chatgpt.com`, `chat.openai.com`) et `gemini` (exactement `gemini.google.com` : le reste de `google.com` reste `browser`) n'ont qu'une page `chat` ; ils reçoivent en plus la page `tabs` en dernière position dans un navigateur ; certains boutons y sont des actions d'interface de l'app (UI Automation) plutôt que des raccourcis, et les boutons dont le raccourci reste à vérifier ne sont pas envoyés ; dans un navigateur, l'adresse de l'onglet (lue par le PC dans la barre d'adresse, via UI Automation) dont l'hôte est `canva.com` ou `figma.com` (ou un sous-domaine) donne le profil `canva` ou `figma`, à défaut un titre de fenêtre qui contient « Canva » ou « Figma » (sans tenir compte de la casse). Les noms d'icônes se trouvent dans `ICON_NAMES` (`host-prototype/actions/context_profiles.py`).
- Le bloc est relevé toutes les 250 ms avec l'audio ; un changement de profil est diffusé aussitôt (état complet).

Action associée : `{"id":"context.press","button":"<id du bouton>"}`. Le PC regarde l'app au premier plan **à cet instant** et n'envoie le raccourci que si le bouton appartient à l'une des pages de son profil ; sinon l'action est ignorée et journalisée (la tablette n'a pas encore redessiné sa barre). Un raccourci qui ne peut pas être injecté (app élevée au premier plan, touche absente de la disposition) donne un `notice` `{"code":"action_failed"}`.

Action `{"id":"context.lang","lang":"en"|"fr"}` : l'appareil change de langue pendant une session Actions. Le PC retraduit aussitôt la barre (état complet diffusé, comme après tout `ACTION`). Une valeur inconnue est ignorée et journalisée ; aucune `notice` n'est produite.

### Clavier du PC (`keyboard`, `keyboard.key`, `keyboard.release`)

L'appareil affiche un clavier de PC complet et envoie chaque touche par sa **position physique** (scan code « set 1 ») ; Windows applique ensuite sa propre disposition, si bien que les caractères, AltGr, les raccourcis et les jeux marchent.

```json
"keyboard":{"available":true,"layout":"azerty"}
```

- `layout` : `"azerty"` ou `"qwerty"`, la disposition que l'appareil doit dessiner. Le PC la lit (`GetKeyboardLayout`) sur la fenêtre au premier plan : langue principale française (`0x0C`), sauf français canadien (`0x0C0C`), donne `azerty`, tout le reste `qwerty`. Elle est relue avec le cycle lent du hub. Une section absente ou `available:false` : pas de clavier ; une disposition inconnue se lit comme `qwerty`.
- Action `{"id":"keyboard.key","sc":<1..127>,"ext":<bool>,"down":<bool>}` : une touche enfoncée (`down:true`) ou relâchée (`down:false`). `ext` est le préfixe E0 (flèches, Suppr, Win, AltGr, Ctrl droite…). Le PC injecte `SendInput` avec `wVk=0`, `wScan=sc`, `KEYEVENTF_SCANCODE`, plus `KEYEVENTF_EXTENDEDKEY` si `ext`, plus `KEYEVENTF_KEYUP` si `down:false`. La répétition d'une touche tenue est faite par l'appareil (un `down` toutes les 33 ms après 500 ms). Seuls les couples `(sc, ext)` du clavier de l'appareil sont acceptés (`actions/keyboard.py`, `KEY_TABLE`) ; tout autre couple, ou une action mal formée, est ignoré et journalisé.
- Action `{"id":"keyboard.release"}` : relâche toutes les touches enfoncées, la dernière enfoncée d'abord. Le PC fait la même chose à la fin de la session Actions (la tablette part, la connexion tombe, changement de rôle, arrêt), pour qu'aucune touche ne reste bloquée.
- Ces actions ne produisent jamais de `notice` et, contrairement aux autres `ACTION`, ne provoquent pas de nouveau relevé complet des fournisseurs. Une fenêtre lancée en administrateur refuse les touches injectées si Orizon X ne l'est pas aussi (même limite que pour le tactile) : l'échec est journalisé une fois.

### Trackpad (`trackpad`, `trackpad.*`)

L'appareil affiche un pavé tactile qui pilote la souris du PC. Tous les messages sont des `ACTION`. Les gestes sont reconnus par l'appareil, qui envoie au plus un `move`, un `scroll` ou un `zoom` par trame de 16 ms.

```json
"trackpad":{"available":true}
```

- `{"id":"trackpad.move","dx":<nombre>,"dy":<nombre>}` : déplacement relatif en pixels d'appareil (dp × sensibilité), x vers la droite, y vers le bas. Le PC multiplie ce déplacement par un gain de **2,0** (`MOVE_GAIN` : le pavé est petit face à un écran ; la sensibilité réglée sur l'appareil s'applique en plus), puis envoie un `MOUSEEVENTF_MOVE` relatif (jamais absolu : Windows applique la vitesse et l'accélération du pointeur comme pour une vraie souris), en cumulant les décimales (après le gain) et en n'envoyant que la partie entière. La borne de ±2000 s'applique au déplacement reçu, avant le gain.
- `{"id":"trackpad.button","button":"left"|"right","down":<bool>}` : bouton enfoncé ou relâché. Le PC retient les boutons enfoncés ; un `up` d'un bouton qui ne l'est pas est ignoré.
- `{"id":"trackpad.scroll","dx":<nombre>,"dy":<nombre>}` : le **déplacement des doigts en dp** (mêmes axes que `move`). Le PC l'envoie en `WHEEL` / `HWHEEL` (1 dp = 4 unités, 120 = un cran), en cumulant les restes et sans rien envoyer pour 0. Sens naturel (le contenu suit les doigts) : doigts vers le bas (`dy > 0`) → `WHEEL` positif (défilement vers le haut, convention Windows : positif = molette poussée vers l'avant) ; doigts vers la droite (`dx > 0`) → `HWHEEL` négatif (défilement vers la gauche ; `HWHEEL` positif = vers la droite).
- `{"id":"trackpad.zoom","steps":<entier>}` : Ctrl enfoncé, un cran de molette (±120) par pas, Ctrl relâché, en un seul appel `SendInput`. Positif = zoom avant.
- `{"id":"trackpad.gesture","name":"task_view"|"desktop"|"app_prev"|"app_next"}` : `Win+Tab`, `Win+D`, `Alt+Maj+Tab`, `Alt+Tab`.
- `{"id":"trackpad.release"}` : relâche les boutons enfoncés. Le PC le fait aussi à la fin de la session Actions.
- Validation : les nombres doivent être des nombres JSON finis (ni booléens ni texte), `dx` et `dy` sont bornés à ±2000, `steps` est un entier borné à ±10 ; un nom, un bouton ou une action inconnus ou mal formés sont ignorés et journalisés.
- Ces actions ne produisent jamais de `notice` et, comme `keyboard.*`, ne provoquent pas de nouveau relevé complet des fournisseurs. Le PC les exécute sur un thread à part, dans l'ordre d'arrivée et sans attendre les relevés des autres fournisseurs (qui peuvent durer plus d'une seconde) ; des `move` (ou des `scroll`) consécutifs qui attendent ensemble sont additionnés, tout autre message entre deux étant une barrière. Une fenêtre lancée en administrateur refuse l'entrée injectée si Orizon X ne l'est pas aussi : l'échec est journalisé une fois.

### Manette Xbox virtuelle (`gamepad`, `gamepad.*`)

L'appareil devient une manette Xbox 360 : Windows et les jeux voient une vraie manette XInput, grâce au pilote **ViGEmBus** (installé par la tâche « Manette Xbox virtuelle » de l'installateur) et à `ViGEmClient.dll`. Tous les messages sont des `ACTION`.

```json
"gamepad":{"available":true}
"gamepad":{"available":false,"reason":"driver_missing"|"error"}
```

- `available:true` : le PC a pu se connecter au bus ViGEmBus. `driver_missing` : `ViGEmClient.dll` est introuvable ou le bus n'existe pas (pilote non installé) ; `error` : toute autre erreur. Le PC retente la connexion toutes les 30 s tant qu'elle échoue, et relit la section avec le cycle lent du hub. Une section absente : pas de manette.
- `{"id":"gamepad.open"}` : branche la manette virtuelle (idempotent). À envoyer à l'ouverture de l'écran manette.
- `{"id":"gamepad.state","buttons":<u16>,"lt":0|255,"rt":0|255,"lx":<i16>,"ly":<i16>,"rx":<i16>,"ry":<i16>}` : le rapport complet (le dernier l'emporte). `buttons` suit les bits `XUSB_GAMEPAD_*` : DPAD_UP `0x0001`, DPAD_DOWN `0x0002`, DPAD_LEFT `0x0004`, DPAD_RIGHT `0x0008`, START `0x0010`, BACK `0x0020`, LEFT_THUMB `0x0040`, RIGHT_THUMB `0x0080`, LEFT_SHOULDER `0x0100`, RIGHT_SHOULDER `0x0200`, GUIDE `0x0400`, A `0x1000`, B `0x2000`, X `0x4000`, Y `0x8000` ; les autres bits sont ignorés. Les gâchettes sont numériques (toute valeur supérieure à 0 vaut 255). Les axes sont bornés à [-32768, 32767] et **Y est positif vers le haut**, comme en XInput. Un champ absent, non entier (booléen, texte, `null`, décimal, NaN) fait ignorer tout le rapport, avec une entrée au journal. Ignoré tant que la manette n'est pas ouverte.
- `{"id":"gamepad.close"}` : rapport neutre (tout à 0), puis la manette est débranchée. Le PC le fait aussi à la fin de la session Actions.
- Ces actions ne produisent jamais de `notice` et, comme `keyboard.*` et `trackpad.*`, ne provoquent pas de nouveau relevé complet des fournisseurs. Exclus : les vibrations renvoyées par le jeu, les gâchettes progressives, plusieurs manettes, la manette DualShock 4.

### Sessions Claude Code (`claude`, `claude.focus`)

En lecture seule, le PC décrit les sessions Claude Code récentes (fichiers `~/.claude/projects/<projet>/<id>.jsonl`) et leurs connecteurs MCP. L'appareil n'envoie rien à Claude.

```json
"claude":{"available":true,
  "sessions":[{"id":"…","title":"…","project":"…","branch":"main","updated":1792404007,"status":"working"|"idle",
               "model":"…","effort":"…","mode":"…","tokens":561000,"last_prompt":"…","last_result":"…",
               "files":["src/a.py"],"entry":"desktop"|"cli"}],
  "connectors":[{"name":"…","type":"stdio"|"http"|"sse","scope":"global"|"<projet>"}]}
"claude":{"available":false}
```

- `available:false` : aucun dossier `~/.claude/projects`. Sinon, jusqu'à 12 sessions, **la plus récemment modifiée en premier** (les 12 fichiers `.jsonl` de premier niveau modifiés le plus récemment, tous projets confondus ; les sous-dossiers — sous-agents, mémoire — sont ignorés). Un champ inconnu vaut `""` (`null` pour `tokens`).
- `title` : le dernier titre personnalisé, sinon le `slug`, sinon les 8 premiers caractères de l'`id`. `project` : le dernier composant du dossier de travail. `updated` : secondes depuis l'époque (dernier horodatage de la session, sinon la date du fichier). `status` : `working` si le fichier a été modifié il y a moins de 15 s, sinon `idle`. `tokens` : `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` de la dernière réponse. `last_prompt` est coupé à 300 caractères, `last_result` (dernière réponse contenant du texte) à 1 500 ; `files` : au plus 20 fichiers suivis, relatifs au dossier de travail quand c'est possible, par ordre alphabétique. `entry` : `desktop` pour l'app Claude, `cli` sinon.
- `connectors` : au plus 30, **uniquement le nom, le type et la portée** (`global`, ou le nom du projet) des serveurs `mcpServers` de `~/.claude.json` (globaux, et ceux des projets des sessions listées) et de `<projet>/.mcp.json`. Aucune autre clé de `.claude.json` (compte, jetons…) n'est lue vers l'état, ni commande, URL, en-tête ou variable d'environnement de serveur. Les connecteurs de claude.ai ne sont pas stockés sur le PC et n'apparaissent pas.
- La section reste sous 40 Kio (JSON compact UTF-8) : l'`ACTIONS_STATE` entier est limité à 64 Kio. Au besoin, `last_result` est raccourci session après session, de la plus ancienne à la plus récente, puis `last_prompt`, puis `files`.
- `app` (facultatif) : l'état du panneau de droite de l'app Claude, **seulement** pendant que l'appareil a son écran Claude Code ouvert (`{"id":"claude.watch","open":true|false}`) et que le panneau a pu être lu (UI Automation, en lecture seule, au plus toutes les 3 s ; l'arbre d'accessibilité de l'app met quelques secondes à se réveiller après la première lecture : moins de 100 éléments = pas encore lu, on réessaie). Absent sinon.
  ```json
  "app":{"session_title":"…","seen_at":1792508209,
    "context":{"percent":61,"used":"614.3k","window":"1M",
               "items":[{"name":"Messages","tokens":"540.3k","percent":"54,0 %"},…],
               "deferred":[{"name":"MCP tools (deferred)","tokens":"88.3k"}]}|null,
    "connected":1|null,"results":["plan.md",…],"changes":{"added":2198,"removed":9}|null,
    "usage":{"session":{"percent":44,"reset":"1 h 10 min"}|null,"weekly":{"percent":34,"reset":"sam. 11:00"}|null,"session_seen_at":1792508200|null,"weekly_seen_at":1792508000|null},
    "tasks":[{"name":"…","status":"running"|"completed","elapsed":"3min 46s"}],"tasks_done":3}
  ```
  `session_title` est le titre de la conversation ouverte dans l'app (l'appareil la relie à une session locale par son `title`). Les libellés sont ceux de l'app, en français ou en anglais. Seuls les libellés et les valeurs du panneau sont gardés : aucun texte de la conversation n'est lu vers l'état. Les parties introuvables valent `null` (`[]` pour `results`). `tasks` (carte « Tâches en arrière-plan » / « Background tasks » : au plus 10 lignes, noms de 120 caractères au plus, `running` quand la ligne a son bouton « Arrêter cette tâche », sinon `completed`) et `tasks_done` (le résumé « N terminé(s) ») n'existent que si la carte est présente ; `tasks` vaut `[]` quand elle ne liste rien. Le bouton « Utilisation : … » de la barre d'état de l'app n'affiche **qu'une limite à la fois** (« Utilisation : 76 % de la limite de session et Réinitialisation dans 48 min » ou « Utilisation : Hebdomadaire · tous les modèles : 62% et Réinitialisation le sam. 11:00 »), et la fenêtre des limites d'utilisation les montre toutes deux quand elle est ouverte. Le PC garde donc **chaque limite séparément**, avec son propre horodatage (`usage.session_seen_at` et `usage.weekly_seen_at`, secondes depuis l'époque, `null` si la limite n'a jamais été vue) : une lecture qui n'apporte que l'une ne fait jamais disparaître l'autre, et la tablette peut toujours afficher les deux avec « vu à HH:MM ». Si la section dépasse son budget, la fin de `results` est raccourcie en premier.
- Chaque session gagne `"changes":{"added","removed"}|null` : les statistiques git de son dossier de travail (`git diff --shortstat` contre la base commune avec `main`/`master`, ou contre `HEAD` à défaut ; fichiers non suivis exclus), calculées en tâche de fond et gardées 30 s ; `null` si le dossier n'est pas un dépôt git ou tant que le calcul n'est pas fini.
- Action `{"id":"claude.watch","open":true|false}` : l'appareil indique que son écran Claude Code est ouvert ou fermé ; la lecture du panneau (`app`) n'a lieu que pendant qu'il est ouvert.
- Actions `{"id":"claude.new"}`, `{"id":"claude.artifacts"}`, `{"id":"claude.customize"}`, `{"id":"claude.more"}` : mettent l'app Claude au premier plan puis invoquent (`InvokePattern`, jamais la souris) le bouton de la barre latérale de ce nom (FR « Nouveau », « Artéfacts », « Personnalisation », « Plus » ; EN « New », « Artifacts », « Customize », « More »). `{"id":"claude.open","title":"…"}` invoque de même l'élément de la barre latérale qui porte ce titre. Notice `{"code":"claude_not_running"}` si l'app ne tourne pas, `{"code":"claude_ui_not_found"}` si le bouton ou le titre n'est pas trouvé (ou si le titre est vide ou trop long).
- Action `{"id":"claude.compact"}` : met l'app au premier plan puis invoque (`InvokePattern`) le bouton « Compacter la session » / « Compact session » de la carte Contexte du panneau ; notice `claude_ui_not_found` s'il est introuvable (carte repliée, panneau masqué).
- Actions `{"id":"claude.show_usage"}` et `{"id":"claude.show_context"}` (touche sur les blocs Limites et Contexte de la tablette) : mettent l'app au premier plan, puis, par `ExpandCollapsePattern` (aucun des deux éléments n'a d'`InvokePattern`), `show_usage` **bascule** le bouton « Utilisation : … » de la barre d'état (déplié s'il est replié, replié s'il est déplié) qui ouvre la fenêtre des limites d'utilisation du forfait, et `show_context` affiche le panneau de droite (bouton à bascule « Panneau des sessions ») et déplient la carte « Contexte ». Notice `claude_ui_not_found` si l'élément est introuvable, `claude_not_running` si l'app ne tourne pas.
- Action `{"id":"claude.focus"}` : met au premier plan la fenêtre principale de l'app Claude (fenêtre visible, de premier niveau, sans propriétaire, d'un processus `claude.exe` ; restaurée si réduite). Si l'app ne tourne pas, une `notice` `{"code":"claude_not_running"}` ; si Windows refuse le focus même après le contournement habituel (Alt), `action_failed`. Action normale (pas le fil d'entrée du clavier).

### Lanceurs (`launchers`, `launch.open`)

Les blocs de lancement de la grille du mode Actions (Paramètres, Discord, Spotify, Téléchargements).

```json
"launchers":{"settings":true,"discord":true,"spotify":false,"downloads":true,
             "icons":{"discord":"<sha1 hex>"|null,"spotify":"<sha1 hex>"|null}}
```

- `settings` et `downloads` sont toujours `true`. `discord` et `spotify` valent `true` si l'application est installée (détection mise en cache 60 s : `%LOCALAPPDATA%\Discord\Update.exe` ou le protocole `discord://` ; `%APPDATA%\Spotify\Spotify.exe` ou le protocole `spotify:` de la version du Microsoft Store).
- `icons` : l'identifiant (sha1 du PNG 96 × 96) de la vraie icône de l'exe de Discord et de Spotify, ou `null` tant qu'elle n'est pas prête ou quand l'application n'a pas d'exe connu (protocole seul). L'image est envoyée par `MEDIA_ARTWORK`, avant l'état qui la référence, chaque fois qu'un identifiant change vers un identifiant non nul différent du dernier diffusé (comme `context.icon`).
- Action `{"id":"launch.open","target":"settings"|"discord"|"spotify"|"downloads"}` : une **liste fermée** associe chaque cible à sa commande (`ms-settings:` ; `Update.exe --processStart Discord.exe` ou `discord://` ; `Spotify.exe` ou `spotify:` ; le dossier Téléchargements, `FOLDERID_Downloads`, ouvert dans l'Explorateur). Aucune autre cible n'est acceptée (elle est ignorée et journalisée). Rien ne passe par un interpréteur de commandes et aucune fenêtre de console n'apparaît. Application absente ou lancement en échec : `notice` `{"code":"app_not_found"}`. Action normale du hub (pas le fil d'entrée).

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
