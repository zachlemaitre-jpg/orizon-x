# Orizon X — Barre contextuelle (mode Actions) (design)

Date : 2026-10-13
Statut : validé par l'utilisateur, à implémenter (branche `context-bar` depuis `master`)
Prérequis : mode Actions (`2026-10-11-actions-mode-design.md`).

## 1. Objectif

En mode Actions, une **barre fine en bas de l'écran**, façon Touch Bar, montre des boutons adaptés à l'**app au premier plan sur le PC**. Chaque bouton envoie un raccourci clavier à cette app.

**Exclus** :
- l'édition des profils par l'utilisateur (prévue plus tard) ;
- les automatisations propres à chaque app (COM, mode débogage du navigateur) ;
- plusieurs appareils.

## 2. Architecture

- Le **PC possède les profils** et décide de tout. L'appareil affiche ce qu'il reçoit : aucune APK n'est à republier pour ajouter une app.
- Le **raccourci clavier est envoyé par `SendInput`** à l'app au premier plan. Cette app est forcément celle du profil affiché, puisque la barre suit le premier plan.
- La **détection de l'app** passe par `GetForegroundWindow`, puis `GetWindowThreadProcessId`, puis `QueryFullProcessImageNameW`, ce qui donne le nom de l'exe. Elle est interrogée par le hub dans son cycle rapide (250 ms).
- **App ignorée** : si l'exe au premier plan est Orizon X lui-même (`OrizonX.exe`, ou `python.exe`/`pythonw.exe` exécutant l'appli depuis les sources, que l'on reconnaît à son PID), ou le bureau/l'Explorateur sans fenêtre (`Progman`, `WorkerW`, barre des tâches `Shell_TrayWnd`), on garde la **dernière vraie app**.

## 3. Protocole

Les ajouts sont rétrocompatibles et la version reste 1.

- **`ACTIONS_STATE`** gagne une section `context` :
  ```json
  "context":{"available":true,"app":"PowerPoint","profile":"powerpoint",
             "buttons":[{"id":"ppt.prev","icon":"arrow_left","label":"Précédent"}, …]}
  ```
  - `label` est en français pour l'instant (l'app Android est en français).
  - `icon` est un nom pris dans la liste du §5.
  - Au maximum 8 boutons.
- **`ACTION`** : `{"id":"context.press","button":"<id du bouton>"}`.
  - Le PC vérifie que ce bouton appartient bien au profil actif. Si le premier plan a changé entre-temps, il ignore l'action et journalise.

## 4. Profils (PC, `actions/context_profiles.py`)

Profils, avec les exe reconnus et leurs boutons (`id` → raccourci) :

| Profil | Exe | Boutons |
|---|---|---|
| `spotify` | `Spotify.exe` | précédent `Ctrl+Left`, lecture/pause `Space`, suivant `Ctrl+Right`, j'aime `Alt+Shift+B`, aléatoire `Ctrl+S`, répétition `Ctrl+R` |
| `powerpoint` | `POWERPNT.EXE` | diaporama `F5`, depuis la diapo `Shift+F5`, précédent `Left`, suivant `Right`, écran noir `B`, quitter `Esc` |
| `browser` | `chrome.exe`, `msedge.exe`, `firefox.exe`, `brave.exe`, `opera.exe` | retour `Alt+Left`, avance `Alt+Right`, actualiser `F5`, nouvel onglet `Ctrl+T`, fermer l'onglet `Ctrl+W`, zoom − `Ctrl+-`, zoom + `Ctrl+=` |
| `word` | `WINWORD.EXE` | annuler `Ctrl+Z`, rétablir `Ctrl+Y`, gras `Ctrl+B`, italique `Ctrl+I`, souligné `Ctrl+U`, enregistrer `Ctrl+S` |
| `excel` | `EXCEL.EXE` | annuler `Ctrl+Z`, rétablir `Ctrl+Y`, gras `Ctrl+B`, somme auto `Alt+=`, filtre `Ctrl+Shift+L`, enregistrer `Ctrl+S` |
| `vscode` | `Code.exe` | palette `Ctrl+Shift+P`, rechercher `Ctrl+Shift+F`, terminal `` Ctrl+` ``, commenter `Ctrl+/`, enregistrer `Ctrl+S`, explorateur `Ctrl+Shift+E` |
| `explorer` | `explorer.exe` (fenêtre de classe `CabinetWClass`) | retour `Alt+Left`, dossier parent `Alt+Up`, nouveau dossier `Ctrl+Shift+N`, renommer `F2`, actualiser `F5` |
| `generic` | tout le reste | copier `Ctrl+C`, coller `Ctrl+V`, annuler `Ctrl+Z`, capture `Win+Shift+S`, bureau `Win+D`, changer d'app `Alt+Tab` |

**Noms affichés** : Spotify, PowerPoint, Navigateur (ou le nom réel : Chrome, Edge, Firefox…), Word, Excel, VS Code, Explorateur. Pour `generic`, le nom est le **titre court de la fenêtre** si on l'obtient, sinon le nom de l'exe sans `.exe`.

**Envoi des raccourcis** : `SendInput`, modificateurs enfoncés puis touche, puis relâchement dans l'ordre inverse, en codes virtuels.
- Pour les touches Ctrl/Alt/Shift/Win : `VK_CONTROL`, `VK_MENU`, `VK_SHIFT`, `VK_LWIN`.
- `+`, `-`, `=`, `/`, `` ` `` : `VK_OEM_*` résolus par `VkKeyScanW` selon la disposition clavier active (AZERTY compris).
- Les flèches et autres touches étendues portent `KEYEVENTF_EXTENDEDKEY`.

## 5. Appareil (Android)

- **Barre** : tout en bas de `ActionsScreen`, sur toute la largeur, environ 76 dp de haut, avec le style verre.
  - À gauche, le nom de l'app en petit (environ 13 sp, atténué).
  - Puis les boutons répartis : icône 24 dp au-dessus d'un libellé de 11 sp, une ligne avec ellipsis.
  - Retour haptique, et un fondu enchaîné (environ 200 ms) quand le profil change.
  - En portrait : boutons en défilement horizontal si nécessaire.
  - La barre est cachée si `context` est absent ou indisponible.
- **Placement** : le bloc des cartes existant remonte pour laisser la place à la barre. La barre USB latérale reste où elle est.
- **Icônes** : un jeu de VectorDrawables `ctx_<nom>` (chemins Material Icons, Apache-2.0, avec mention dans chaque fichier). Noms :
  - navigation : `arrow_left`, `arrow_right`, `arrow_up`, `refresh` ;
  - lecture : `play_pause`, `skip_previous`, `skip_next`, `heart`, `shuffle`, `repeat`, `slideshow`, `slideshow_current`, `screen_black`, `exit` ;
  - onglets et zoom : `tab_new`, `tab_close`, `zoom_out`, `zoom_in` ;
  - édition : `undo`, `redo`, `bold`, `italic`, `underline`, `save`, `sum`, `filter`, `copy`, `paste` ;
  - outils : `command`, `search`, `terminal`, `comment`, `folder_new`, `rename`, `explorer` ;
  - système : `screenshot`, `desktop`, `switch_app`.
  - Un nom inconnu donne une icône neutre (un point). L'utilisateur pourra remplacer ces icônes par les siennes avec `tools/svg_to_vector.py`.

## 6. Tests

- **PC** :
  - détection de l'app avec un faux user32/kernel32 : exe, Orizon X ignoré, bureau ignoré, dernière vraie app conservée ;
  - choix du profil (exe connus, insensible à la casse, `explorer.exe` seulement avec `CabinetWClass`) ;
  - suite d'événements `SendInput` pour plusieurs raccourcis (modificateurs, touches étendues, `VkKeyScanW` simulé en AZERTY) ;
  - hub : section `context` dans l'état et changement de profil diffusé ; `context.press` routé, refusé si le bouton n'appartient pas au profil actif.
  - **Aucun raccourci réel envoyé en test.**
- **Android** :
  - parsing de `context` (absent, indisponible, plus de 8 boutons tronqués, icône inconnue) ;
  - correspondance nom d'icône → drawable.
- **Essai réel**, avec l'accord de l'utilisateur : chaque profil sur son PC.
