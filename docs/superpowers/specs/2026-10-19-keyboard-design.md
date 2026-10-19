# Orizon X — Clavier PC sur l'appareil (mode Actions) (design)

Date : 2026-10-19
Statut : validé par l'utilisateur, à implémenter (branche `keyboard`, depuis `browser-tabs`)

## 1. Objectif

En mode Actions, un bouton **« Keyboard / Clavier »** ouvre un **clavier de PC complet** en plein écran sur l'appareil. Chaque touche est envoyée au PC comme une vraie touche, par sa position physique (scan code). Windows applique ensuite sa propre disposition, si bien que les caractères, AltGr, les raccourcis et les jeux marchent.

**Exclus** :
- le clavier Android (correction automatique, emoji, dictée) ;
- un pavé numérique ;
- des dispositions autres qu'AZERTY français et QWERTY US.

## 2. Appareil (Android)

### Bouton et écran

- **Bouton** : une pastille avec une icône clavier (`ox_keyboard`, Material « keyboard », Apache-2.0) dans l'en-tête de l'écran Actions, à côté de « Changer de mode ». Libellé « Keyboard / Clavier ».
- **Écran clavier** :
  - il remplace les tuiles en plein écran ;
  - la barre contextuelle reste au-dessus du clavier ;
  - un bouton **✕** en haut à droite revient aux tuiles ;
  - fermer le clavier envoie `keyboard.release`.

### Disposition

Elle est choisie par `keyboard.layout`, que le PC envoie : `azerty` ou `qwerty`.

- **Rangée 0** : Esc, F1…F12, Suppr.
- **Rangées principales** : les quatre rangées du clavier ISO (AZERTY) ou ANSI (QWERTY). Le tableau du §4 donne, pour chaque touche, son scan code et ses libellés dans chaque disposition.
- **Rangée du bas** : Ctrl, Win, Alt, Espace, AltGr (dans les deux dispositions ; c'est la touche Alt droite), Menu, Ctrl.
- **Bloc de navigation**, à droite de la rangée du bas et de la rangée 4 :
  - flèches ;
  - Début/Fin ;
  - Page préc./suiv. ;
  - Inser.
- **Libellés** : chaque touche montre son caractère principal en gros, et ses caractères Maj et AltGr en petit dans les coins.
- **Taille** : les touches se partagent la largeur de l'écran. Les largeurs relatives suivent celles d'un clavier réel (Retour arrière 2, Tab 1,5, Verr. Maj 1,75, Entrée 2,25, Maj gauche 1,25 en ISO ou 2,25 en ANSI, Espace 6).

### Comportement

L'état est géré par un automate pur, `keyboard/KeyboardState.kt`, testable sans Android.

- **Touche normale** :
  - doigt posé → `down` ;
  - doigt levé → `up` ;
  - tenue plus de 500 ms → `down` répété toutes les 33 ms (comme la répétition d'un vrai clavier).
- **Modificateurs** (Maj, Ctrl, Alt, Win, AltGr) :
  - doigt posé → `down` ;
  - doigt levé après qu'une autre touche a été pressée pendant l'appui → `up` (combinaison tenue à deux doigts) ;
  - doigt levé sans autre touche → **verrou ponctuel** : le modificateur reste enfoncé et se relâche (`up`) au relâchement de la prochaine touche normale ;
  - **double tap** (moins de 300 ms) → **verrouillé** : il reste enfoncé jusqu'au tap suivant ;
  - verrou ponctuel et verrou sont signalés visuellement (fond clair, et bordure pour le verrou).
- **Verr. Maj** : touche normale (`down`/`up`). Windows gère le basculement.
- **Multi-touch** : chaque touche suit son propre doigt.
- **Retour** : une vibration à chaque `down`, et la touche est mise en avant tant qu'elle est enfoncée.

## 3. Protocole

La version reste 1.

- **`ACTIONS_STATE`** gagne la section `"keyboard":{"available":true,"layout":"azerty"|"qwerty"}`.
- **`ACTION`** :
  - `{"id":"keyboard.key","sc":<1..127>,"ext":<bool>,"down":<bool>}` ;
  - `{"id":"keyboard.release"}` : relâche toutes les touches enfoncées.
- **`protocol/PROTOCOL.md`** documente ces messages.

## 4. Touches (positions, scan codes « set 1 »)

`ext` = préfixe E0. Les libellés sont donnés dans l'ordre base / Maj / AltGr ; un « - » signifie que la touche n'a pas de caractère pour ce niveau.

| Position | sc | ext | AZERTY | QWERTY |
|---|---|---|---|---|
| Esc | 0x01 | n | Échap | Esc |
| F1…F10 | 0x3B…0x44 | n | F1…F10 | F1…F10 |
| F11, F12 | 0x57, 0x58 | n | F11, F12 | F11, F12 |
| Suppr | 0x53 | o | Suppr | Del |
| (gauche de 1) | 0x29 | n | ² | ` / ~ |
| 1…0 | 0x02…0x0B | n | & 1 · é 2 ~ · " 3 # · ' 4 { · ( 5 [ · - 6 \| · è 7 ` · _ 8 \\ · ç 9 ^ · à 0 @ | 1 ! · 2 @ · 3 # · 4 $ · 5 % · 6 ^ · 7 & · 8 * · 9 ( · 0 ) |
| (après 0) | 0x0C | n | ) ° ] | - _ |
| (après) | 0x0D | n | = + } | = + |
| Retour arrière | 0x0E | n | ⌫ | ⌫ |
| Tab | 0x0F | n | Tab | Tab |
| rangée 2 | 0x10…0x19 | n | a z e r t y u i o p | q w e r t y u i o p |
| (après p) | 0x1A | n | ^ ¨ | [ { |
| (après) | 0x1B | n | $ £ ¤ | ] } |
| Entrée | 0x1C | n | Entrée | Enter |
| Verr. Maj | 0x3A | n | Verr. Maj | Caps |
| rangée 3 | 0x1E…0x26 | n | q s d f g h j k l | a s d f g h j k l |
| (après l) | 0x27 | n | m | ; : |
| (après) | 0x28 | n | ù % | ' " |
| (ISO, avant Entrée) | 0x2B | n | * µ | \\ \| (placée au-dessus d'Entrée en ANSI) |
| Maj gauche | 0x2A | n | Maj | Shift |
| (ISO, après Maj) | 0x56 | n | < > | absente en QWERTY ANSI |
| rangée 4 | 0x2C…0x32 | n | w x c v b n , ? | z x c v b n m |
| (après) | 0x33 | n | ; . | , < |
| (après) | 0x34 | n | : / | . > |
| (après) | 0x35 | n | ! § | / ? |
| Maj droite | 0x36 | n | Maj | Shift |
| Ctrl gauche | 0x1D | n | Ctrl | Ctrl |
| Win | 0x5B | o | Win | Win |
| Alt | 0x38 | n | Alt | Alt |
| Espace | 0x39 | n | (vide) | (vide) |
| AltGr / Alt droite | 0x38 | o | AltGr | Alt |
| Menu | 0x5D | o | Menu | Menu |
| Ctrl droite | 0x1D | o | Ctrl | Ctrl |
| Inser | 0x52 | o | Inser | Ins |
| Début, Fin | 0x47, 0x4F | o | Début, Fin | Home, End |
| Page préc., suiv. | 0x49, 0x51 | o | Pg préc, Pg suiv | PgUp, PgDn |
| ↑ ← ↓ → | 0x48, 0x4B, 0x50, 0x4D | o | flèches | flèches |

## 5. PC (`actions/keyboard.py`)

- **`KeyboardProvider`** :
  - `snapshot()` donne `{"available":true,"layout":…}`. La disposition se lit avec `GetKeyboardLayout` sur le thread de la fenêtre au premier plan (ou du shell s'il n'y en a pas) :
    - identifiant de langue principale `0x0C` (français), sauf `0x0C0C` (français canadien) → `azerty` ;
    - sinon → `qwerty` ;
  - `handle("keyboard.key")` :
    - vérifie que le couple `(sc, ext)` figure dans le tableau du §4 ; sinon, il refuse et journalise ;
    - envoie `SendInput` avec `KEYBDINPUT{wVk=0, wScan=sc, dwFlags=KEYEVENTF_SCANCODE | (EXTENDEDKEY si ext) | (KEYUP si non down)}` ;
    - tient l'ensemble des touches enfoncées ;
  - `handle("keyboard.release")` et `stop()` relâchent toutes les touches enfoncées, dans l'ordre inverse.
  - `SendInput` est injectable, comme dans `actions/keys.py`.
- **Hub** :
  - le fournisseur s'ajoute aux fournisseurs par défaut ;
  - `keyboard.*` est routé vers lui ;
  - la disposition est relue dans le cycle lent du hub ;
  - à l'arrêt du hub (fin de session, débranchement, changement de rôle), `stop()` est toujours appelé.
- **Limite connue** : une fenêtre lancée en administrateur refuse les touches injectées si Orizon X ne tourne pas lui aussi en administrateur. C'est la même limite que pour le tactile, déjà décrite dans le README.

## 6. Tests

- **PC** :
  - tableau : couples `(sc, ext)` uniques ;
  - `SendInput` simulé : `down`, `up`, touche étendue (flèches, AltGr, Win, Suppr), refus d'une touche hors tableau ;
  - `release` et `stop` relâchent tout, dans l'ordre inverse ;
  - disposition : `040C` donne azerty, `080C` azerty, `0C0C` qwerty, `0409` qwerty ;
  - hub : section `keyboard`, routage, `stop` appelé en fin de session.
- **Android** :
  - `KeyboardState` : touche simple, répétition (horloge simulée), combinaison tenue, verrou ponctuel relâché après la touche suivante, double tap qui verrouille, tap qui déverrouille, multi-touch ;
  - lecture de `keyboard` (absente, disposition inconnue → qwerty) ;
  - JSON des actions ;
  - les deux tableaux de disposition couvrent les mêmes positions (sauf `0x56`, absente en ANSI).
- **Réel** :
  - Bloc-notes : lettres, chiffres, é è à ç, @ (AltGr+à), majuscules (Maj ponctuelle et Verr. Maj), Retour arrière tenu (répétition) ;
  - raccourcis : Ctrl+C / Ctrl+V à deux doigts et par verrou ponctuel, Alt+Tab, Win.
