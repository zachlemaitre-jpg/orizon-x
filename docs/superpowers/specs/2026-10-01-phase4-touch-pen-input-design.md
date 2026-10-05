# TabX — Phase 4 : tactile et stylet vers le PC (design)

Date : 2026-10-01
Statut : implémenté et validé sur la tablette le 2026-10-05 (tap, défilement, stylet avec pression, paume, HUD)
Prérequis : phase 1 (`2026-10-01-phase1-video-pipeline-design.md`), fusionnée dans `master`. Écran étendu fourni par Virtual Display Driver (écran virtuel 2880×1800 à 200 %).

## 1. Objectif et périmètre

**Objectif** : le doigt et le S Pen sur la tablette pilotent Windows **directement à l'endroit touché** de l'écran étendu. Le doigt et le stylet comptent autant l'un que l'autre :

- **doigt** : tap = clic, appui long = clic droit, défilement et zoom à deux doigts. Ces gestes sont interprétés par Windows lui-même ;
- **stylet** : survol = déplacement du curseur, encre avec pression et inclinaison, bouton latéral = clic droit.

**Inclus** : message `INPUT` du protocole, capture côté tablette, injection côté PC, geste du HUD remplacé, rappel de ce geste dans l'interface, tests.

**Exclus** : clavier virtuel, mode pavé tactile (déplacement relatif), plusieurs tablettes, pilotage des fenêtres administrateur sans relais lancé en administrateur.

## 2. Approche retenue

Injection depuis le relais Python via `ctypes` et l'API **Synthetic Pointer** de Windows : `CreateSyntheticPointerDevice` / `InjectSyntheticPointerInput`, disponible depuis Windows 10 1809. Deux périphériques virtuels : un écran tactile (10 contacts) et un stylet (1 contact).

L'injection vit dans un module isolé, pour faciliter son portage en C++ en phase 2.

Écartées :
- **injecteur C++ séparé** : un second programme, plus de travail, pour la même latence ;
- **souris via `SendInput`** : ni pression, ni multipoint, ni gestes natifs.

## 3. Protocole : message `INPUT` (0x85, tablette → PC)

Le type était réservé en v1. Son ajout est rétrocompatible (un ancien relais ignore les types inconnus) : **la version du protocole reste 1**.

### 3.1 Payload

```
u8  device     1 = tactile, 2 = stylet
u8  count      nombre de contacts : 0..10 (tactile), 0..1 (stylet)
count × contact (10 octets) :
  u8  id         emplacement stable 0..9 (tactile) ; 0 (stylet)
  u8  flags      bit0 CONTACT    : posé sur l'écran
                 bit1 IN_RANGE   : stylet détecté (survol ou contact) ; toujours 1 pour un doigt présent
                 bit2 BARREL     : bouton latéral du stylet enfoncé
                 bit3 CANCELED   : geste annulé (pas de clic à produire)
                 bits 4-7        : 0, ignorés par le récepteur
  u16 x, y       position normalisée 0..65535 sur l'image vidéo (0 = bord gauche/haut, 65535 = bord droit/bas)
  u16 pressure   0..1024 (stylet) ; 0 pour un doigt
  i8  tilt_x     inclinaison en degrés −90..90 (stylet) ; 0 pour un doigt
  i8  tilt_y     idem
```

Taille exacte du payload : `2 + 10 × count`. Toute autre taille, ou un `device` / `count` hors bornes, est une `ProtocolError`.

### 3.2 Sémantique

- Chaque message est **l'état complet** d'un périphérique juste après un événement. Le récepteur compare avec l'état précédent du même périphérique.
- Un contact présent dans la trame précédente et absent de la nouvelle est **levé**.
- `count = 0` : tous les doigts sont levés (tactile), ou le stylet est hors de portée.
- Un contact marqué `CANCELED` apparaît dans une seule trame, puis disparaît des trames suivantes.

## 4. Tablette (Android)

### 4.1 Modules

```
dev/tabx/client/input/
├── InputMapper.kt     logique pure (Kotlin sans Android, testée sur JVM)
└── TouchForwarder.kt  liaison Android : MotionEvent → état → InputMapper → Session
```

### 4.2 `InputMapper` (pur)

Entrée : un instantané `List<PointerSample>` et l'heure `nowMs`, avec `PointerSample(pointerId, tool = FINGER|PEN, x, y, pressure 0..1, tiltRad, orientationRad, barrel, inContact)`, en coordonnées de la vue vidéo (largeur `w`, hauteur `h`). Sortie : 0 à 2 messages `INPUT`, plus un éventuel événement « basculer le HUD ».

Règles :

1. **Normalisation** : `x_n = round(clamp(x / w, 0, 1) × 65535)`, de même pour y.
2. **Emplacements des doigts** : un id de pointeur Android se voit attribuer le plus petit emplacement libre 0..9 à son apparition (« libre » = absent de la trame précédente : un emplacement libéré n'est jamais réutilisé dans la trame même où il se libère), qu'il garde jusqu'à sa disparition. Au-delà de 10 doigts, les suivants sont ignorés.
3. **Stylet** :
   - `pressure = round(p × 1024)` ;
   - `tilt_x = round(deg(atan(sin(o) × tan(t))))` et `tilt_y = round(deg(atan(−cos(o) × tan(t))))`, avec `t = AXIS_TILT` et `o = AXIS_ORIENTATION`. La convention de signe est à confirmer sur la tablette (§8) ;
   - `BARREL` = `BUTTON_STYLUS_PRIMARY` ;
   - l'outil gomme est traité comme un stylet.
4. **Paume** : tant que le stylet est `IN_RANGE`, aucun doigt n'est transmis. À l'arrivée du stylet, les doigts déjà transmis partent une dernière fois avec `CANCELED`.
5. **Geste du HUD** : dès que 4 doigts ou plus sont posés :
   - les doigts déjà transmis partent avec `CANCELED` ;
   - plus aucune trame tactile n'est émise jusqu'au relâchement de **tous** les doigts ;
   - si les 4 doigts restent posés **2000 ms** sans qu'aucun ne s'éloigne de plus de **48 dp** de sa position initiale, l'événement « basculer le HUD » est émis, une seule fois par geste.
6. **Pas de trame redondante** : une trame identique à la précédente pour le même périphérique n'est pas émise.

### 4.3 `TouchForwarder` (Android)

- Il est attaché au `SurfaceView` vidéo, dont les proportions sont exactement celles du flux, donc ses coordonnées sont celles de l'image :
  - `setOnTouchListener` pour les doigts et le stylet posé ;
  - `setOnGenericMotionListener` pour le survol du stylet (`ACTION_HOVER_*`).
- `requestUnbufferedDispatch(InputDevice.SOURCE_CLASS_POINTER)` une fois, à l'attachement de la vue : toucher et survol arrivent sans attendre la prochaine image (la variante par événement est sans effet sur le survol).
- Seul l'état courant de l'événement est transmis, sans l'historique (`getHistorical*`).
- Il ne transmet rien quand l'état n'est pas `Streaming`. Il réinitialise le mapper à chaque nouvelle connexion.
- Le détecteur Compose du tap à 3 doigts (`detectThreeFingerTap`) est **supprimé**.

### 4.4 Envoi

`Session` expose `sendInput(message: TabletMessage.Input)`, qui confie l'écriture au thread `net-writer` existant (`timers.execute { writer.write(message) }`). Le thread de l'interface ne bloque jamais sur la socket, et l'ordre est préservé. Hors session active, l'appel ne fait rien. `Receiver` relaie l'appel vers la session courante.

### 4.5 Interface

- **Écran d'attente** : nouvelle ligne « Appui long à 4 doigts : infos de connexion ».
- **Début de connexion** : un bandeau en verre simulé (`GlassPanel`), en bas au centre, affiche « Appui long à 4 doigts : infos » pendant 4 s, puis disparaît en fondu. C'est la seule exception, brève, à la règle « rien par-dessus la vidéo ».

## 5. PC (relais Python)

### 5.1 Modules

```
host-prototype/
├── inputstate.py   logique pure : trames INPUT → actions de pointeur Windows (testé)
└── injector.py     Win32 via ctypes : DPI, moniteur cible, périphériques synthétiques, injection
```

`protocol.py` décode `INPUT` en `Input(device, contacts)`. `relay.py` passe chaque `Input` à l'injecteur depuis le thread `read_tablet`, sous un verrou.

### 5.2 `inputstate.py` (pur)

Pour chaque périphérique, l'état précédent est conservé. Une nouvelle trame produit la liste complète des contacts à injecter (exigence de l'API : chaque injection contient tous les contacts actifs) :

| Transition | Flags `POINTER_FLAG_*` |
|---|---|
| Contact nouveau et posé | `DOWN \| INRANGE \| INCONTACT` |
| Contact posé (déplacé ou non) | `UPDATE \| INRANGE \| INCONTACT` |
| Contact qui passe de posé à non posé, stylet toujours en portée | `UP \| INRANGE` |
| Contact disparu de la trame (était posé) | `UP` |
| Contact `CANCELED` | `UP \| CANCELED` |
| Stylet en survol (en portée, non posé) | `UPDATE \| INRANGE` |
| Stylet qui sort de portée (était en survol) | `UPDATE` |

Compléments :
- **Contact principal** (règle Windows : tant qu'un contact principal existe, tous les contacts doivent être levés avant qu'un autre puisse le devenir) : un doigt qui se pose devient principal seulement s'il n'y a ni principal ni autre doigt posé ; il garde `PRIMARY` (y compris sur son `UP`) et n'est jamais remplacé ; une fois levé, aucun doigt n'est principal tant que tous ne sont pas levés. Le stylet porte toujours `PRIMARY`. Le tactile n'a pas de survol : un contact sans le bit `CONTACT` est un doigt levé.
- **Stylet** : `penMask = PRESSURE | TILT_X | TILT_Y`, et `penFlags = BARREL` si le bit `BARREL` est présent.
- **Coordonnées** : `px = left + round(x_n × (width − 1) / 65535)`, de même pour y, dans le rectangle en pixels physiques de l'écran cible.
- **Fin de session** : `cancel_all()` produit `UP | CANCELED` pour les contacts posés, et `UPDATE` (sortie de portée) pour un stylet en survol.

### 5.3 `injector.py` (Win32)

- **DPI** : `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)` au démarrage du relais, avant toute fenêtre ou mesure, pour travailler en pixels physiques.
- **Moniteur cible** : `EnumDisplayMonitors` + `GetMonitorInfoW`. On retient l'unique moniteur dont la taille `rcMonitor` vaut celle du flux (`CONFIG`). Avec 0 ou plusieurs candidats, l'injection est désactivée pour la session avec un message unique, et la vidéo continue.
- **Périphériques** :
  - `CreateSyntheticPointerDevice(PT_TOUCH, 10, POINTER_FEEDBACK_DEFAULT)` et `(PT_PEN, 1, …)`, créés à la première trame de chaque type ;
  - détruits (`DestroySyntheticPointerDevice`) en fin de session, après `cancel_all()`.
- **Garde-fou** : tant qu'au moins un contact est posé, un thread réinjecte la dernière trame (en `UPDATE`) toutes les **100 ms** sans nouvelle trame. Son utilité est à vérifier sur le PC (§8) ; on le supprime s'il s'avère inutile.
- **Erreurs** :
  - périphérique non créé (Windows trop ancien), ou `InjectSyntheticPointerInput` en échec : message unique par session (avec `GetLastError`), injection désactivée, vidéo intacte ;
  - un accès refusé (fenêtre administrateur) donne le message « lance le relais en administrateur pour piloter les fenêtres élevées ».
- **Autotest** : `py injector.py --selftest` déplace le stylet **en survol uniquement** (aucun contact, donc aucun clic) en cercle au centre de l'écran principal pendant 2 s, puis se termine. Il valide la couche `ctypes` sans tablette : il éloigne le curseur, survole une dernière fois le centre et vérifie que le curseur y arrive (à 3 px près), ce qui prouve la conversion en coordonnées de l'écran virtuel (`ptPixelLocation` de `InjectSyntheticPointerInput` est relatif au coin haut-gauche de l'écran virtuel, pas au bureau). Une petite fenêtre de test est posée sous le stylet, car Windows ne déplace le curseur pour un survol que si la fenêtre sous le stylet transmet `WM_POINTER*` à `DefWindowProc`.

## 6. Gestion des erreurs (résumé)

| Situation | Comportement |
|---|---|
| `INPUT` mal formé | `ProtocolError`, la session se termine comme pour tout message invalide |
| Écran cible introuvable ou ambigu | Injection désactivée, message unique, vidéo intacte |
| API synthétique indisponible ou en échec | Idem |
| Fenêtre administrateur | Injection refusée par Windows ; message unique suggérant le mode administrateur |
| Tablette déconnectée ou relais arrêté pendant un toucher | `cancel_all()` puis destruction des périphériques : aucun contact coincé |
| Plus de 10 doigts | Doigts excédentaires ignorés côté tablette |

## 7. Tests

- **Vecteurs partagés** (`protocol/test-vectors.json`, section `tablet_to_pc`), vérifiés par Kotlin (encodage) et par Python (décodage) :
  - tactile à 2 doigts ;
  - stylet posé avec pression, inclinaison et bouton ;
  - `count = 0`.
- **Kotlin (JVM), `InputMapperTest`** :
  - normalisation et bornes ;
  - attribution et réutilisation des emplacements ;
  - geste à 4 doigts : annulation, rien transmis jusqu'au relâchement, bascule après 2000 ms, pas de bascule si les doigts bougent ou se lèvent trop tôt ;
  - paume ;
  - conversion pression et inclinaison ;
  - pas de trame redondante.
- **Python, `test_inputstate.py`** :
  - chaque ligne du tableau §5.2 ;
  - `PRIMARY` ;
  - conversion en pixels avec un moniteur décalé (`left = 2560`, `top = −207`) ;
  - `cancel_all()`.
- **Python, `test_protocol.py`** : décodage de `INPUT`, rejet des tailles incohérentes.
- **Autotest de l'injecteur** sur le PC (§5.3).

## 8. Critères de réussite

1. Un tap du doigt clique au bon endroit de l'écran virtuel, assez précisément pour viser la croix de fermeture d'une fenêtre.
2. Défilement à deux doigts dans un navigateur, zoom par pincement dans Photos, appui long = menu contextuel.
3. S Pen :
   - le survol déplace le curseur sans cliquer ;
   - le trait d'une app de dessin (Paint, Whiteboard) varie avec la pression ;
   - l'inclinaison a le bon sens dans une app qui l'exploite ;
   - le bouton latéral = clic droit.
4. Une paume posée en dessinant ne provoque aucun clic.
5. L'appui long à 4 doigts bascule le HUD sans clic parasite ni geste Windows. Le rappel s'affiche sur l'écran d'attente et au début de chaque connexion.
6. Arrêter le relais pendant un toucher ne laisse aucun contact coincé.
7. Réactivité jugée suffisante par l'utilisateur.
8. Tous les tests automatiques passent.
9. Le garde-fou de 100 ms (§5.3) est confirmé nécessaire ou retiré.
