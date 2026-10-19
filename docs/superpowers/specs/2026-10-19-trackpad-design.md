# Orizon X — Trackpad sur l'appareil (mode Actions) (design)

Date : 2026-10-19
Statut : validé par l'utilisateur, à implémenter (branche `trackpad` depuis `master` 0.9.0)
Prérequis : clavier (`2026-10-19-keyboard-design.md`), qui fournit l'en-tête réutilisé.

## 1. Objectif

En mode Actions, un bouton **« Trackpad »** ouvre un grand pavé tactile qui pilote la souris du PC. Ses gestes sont ceux d'un pavé tactile Windows d'ordinateur portable.

**Exclus** :
- gestes à 4 doigts ;
- le stylet sur le pavé ;
- le défilement inertiel (Windows gère les deltas fins).

## 2. Appareil (Android)

### Bouton et écran

- **Bouton** : pastille « Trackpad » avec l'icône `ox_trackpad` (Material « touch_app » ou « mouse », Apache-2.0). Elle se trouve dans l'en-tête de l'écran Actions, à côté de « Clavier ». Le clavier et le trackpad ne sont jamais ouverts en même temps.
- **Écran** :
  - **en haut**, le même en-tête que le clavier : barre contextuelle, puis la rangée heure/date/batterie, Son et Luminosité, partagée avec le clavier (le même composable, refactorisé si besoin) ;
  - **dessous**, le pavé : une surface en verre qui prend toute la place restante, avec des coins arrondis de 24 dp ;
  - **sous le pavé**, deux boutons de 64 dp de haut, **gauche** et **droit**, chacun sur la moitié de la largeur ;
  - le **✕** en haut à droite de la zone du pavé ;
  - le contrôle de **sensibilité** « − x1,0 + » dans un coin du pavé. Il va de 0,5 à 3,0 par pas de 0,25 et il est enregistré dans les préférences de l'appareil.
- **Fermeture** : fermer le trackpad envoie `trackpad.release`.

### Gestes

Ils sont reconnus par un automate pur, `trackpad/TrackpadGestures.kt`, avec une horloge injectable et des positions en dp.

| Geste | Reconnaissance | Effet |
|---|---|---|
| Déplacement | 1 doigt, mouvement > 2 dp | `move` (dx, dy) × sensibilité |
| Tap | 1 doigt, < 200 ms, < 8 dp de mouvement | clic gauche (`down` puis `up`) |
| Tap à 2 doigts | 2 doigts posés à moins de 150 ms d'écart, levés en < 250 ms, < 10 dp | clic droit |
| Glisser | tap, puis doigt reposé en < 300 ms et déplacé | `down` gauche, `move`… ; `up` au lever |
| Défilement | 2 doigts qui bougent ensemble (même sens) | `scroll` (dx, dy) en dp, sens naturel (comme Windows : le contenu suit les doigts) |
| Zoom | 2 doigts dont l'écart change de plus de 10 % avant tout défilement | `zoom` (pas de +1 ou −1 par tranche de 12 % d'écart) |
| 3 doigts vers le haut | déplacement moyen > 60 dp vers le haut | `gesture` `task_view` |
| 3 doigts vers le bas | > 60 dp vers le bas | `gesture` `desktop` |
| 3 doigts gauche / droite | > 60 dp à gauche / droite | `gesture` `app_prev` / `app_next` |
| Boutons sous le pavé | appui : `down`, lever : `up` | clic gauche ou droit tenu (sert à glisser avec un autre doigt sur le pavé) |

- Les déplacements sont **cumulés et envoyés au plus toutes les 16 ms** : un `move`, un `scroll` ou un `zoom` par trame.
- Un geste à 3 doigts ne se déclenche qu'une fois par pose.

## 3. Protocole

La version reste 1. Tous les messages sont des `ACTION`.

- `{"id":"trackpad.move","dx":<float>,"dy":<float>}` : en pixels d'appareil (dp × sensibilité) ; le PC arrondit en gardant le reste.
- `{"id":"trackpad.button","button":"left"|"right","down":<bool>}`
- `{"id":"trackpad.scroll","dx":<float>,"dy":<float>}` : en dp.
- `{"id":"trackpad.zoom","steps":<int>}`
- `{"id":"trackpad.gesture","name":"task_view"|"desktop"|"app_prev"|"app_next"}`
- `{"id":"trackpad.release"}`
- **Disponibilité** : `ACTIONS_STATE` gagne `"trackpad":{"available":true}`.
- **Documentation** : `protocol/PROTOCOL.md` documente tout cela.

## 4. PC (`actions/trackpad.py`)

- **`TrackpadProvider`**, avec un `SendInput` injectable (structures de `actions/keys.py`, plus `MOUSEINPUT`) :
  - **`move`** : `MOUSEEVENTF_MOVE` relatif. Les décimales sont cumulées et seule la partie entière est envoyée. Windows applique sa vitesse et son accélération de pointeur, comme pour une vraie souris.
  - **`button`** :
    - gauche : `LEFTDOWN` / `LEFTUP` ; droit : `RIGHTDOWN` / `RIGHTUP` ;
    - le fournisseur retient les boutons enfoncés ;
    - un `up` d'un bouton qui n'est pas enfoncé est ignoré.
  - **`scroll`** :
    - vertical : `MOUSEEVENTF_WHEEL`, de valeur `round(-dy × 4)` (1 dp = 4 unités, 120 = un cran) ;
    - horizontal : `MOUSEEVENTF_HWHEEL`, de valeur `round(dx × 4)` ;
    - les restes sont cumulés et rien n'est envoyé pour 0 ;
    - les signes sont réglés pour que le contenu suive les doigts (« défilement naturel »).
  - **`zoom`** : Ctrl enfoncé, puis `WHEEL` ±120 par pas, puis Ctrl relâché (`actions.keys`).
  - **`gesture`** (raccourcis par `actions.keys.send_shortcut`) : `task_view` → `Win+Tab`, `desktop` → `Win+D`, `app_prev` → `Alt+Shift+Tab`, `app_next` → `Alt+Tab`.
  - **`release`** et **`stop()`** relâchent les boutons enfoncés.
  - **Validation** : les nombres doivent être finis ; `dx` et `dy` sont bornés à ±2000 ; `steps` à ±10 ; un nom ou un bouton inconnu est refusé et journalisé.
- **Hub** :
  - le fournisseur est ajouté aux fournisseurs par défaut ;
  - `trackpad.*` lui est routé sans relance du sondage (comme `keyboard.*`) ;
  - `stop()` est appelé à l'arrêt du hub.
- **Limite connue** : celle de l'injection (les fenêtres administrateur), déjà dans le README.

## 5. Tests

- **Android** : `TrackpadGestures` avec de faux événements et une fausse horloge :
  - déplacement et sensibilité ;
  - cumul par trame de 16 ms ;
  - tap, et mouvement trop grand qui n'est pas un tap ;
  - tap à 2 doigts ;
  - glisser (tap puis appui) ;
  - défilement à 2 doigts ;
  - zoom et défilement exclusifs ;
  - les quatre gestes à 3 doigts, une seule fois par pose ;
  - boutons tenus ;
  - JSON des actions ;
  - section `trackpad` ;
  - bornes de la sensibilité.
- **PC** (faux `SendInput`) :
  - `move` avec cumul des décimales ;
  - boutons et état des boutons enfoncés ;
  - roulette verticale et horizontale avec leurs signes et leurs restes ;
  - zoom (Ctrl puis roulette) ;
  - gestes et leurs raccourcis ;
  - `release` et `stop` ;
  - refus des valeurs invalides ;
  - hub : routage, section, `stop`.
- **Réel** :
  - déplacement et précision ;
  - clic et clic droit ;
  - glisser une fenêtre ;
  - défilement dans Chrome ;
  - zoom ;
  - gestes à 3 doigts ;
  - sensibilité.
