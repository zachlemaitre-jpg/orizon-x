# Orizon X — Lanceurs du mode Actions et compléments Claude Code (design)

Date : 2026-10-20
Statut : validé par l'utilisateur, à implémenter (branche `launchers-compact` depuis `master` 0.13.0)

## 1. Lanceurs (blocs de la grille du mode Actions)

Quatre nouveaux blocs. Chacun est déplaçable, redimensionnable et masquable comme les autres. Ils mesurent 1×1 par défaut et au minimum.

| id | Bloc | Action sur le PC | Présent si |
|---|---|---|---|
| `settings` | Paramètres | ouvre les Paramètres de Windows : `ms-settings:` | toujours |
| `discord` | Discord | lance Discord : `%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe`, sinon `discord://` si le protocole est enregistré | Discord est installé |
| `spotify` | Spotify | lance Spotify : `%APPDATA%\Spotify\Spotify.exe`, sinon l'URI `spotify:` (version du Microsoft Store) | Spotify est installé |
| `downloads` | Téléchargements | ouvre le dossier Téléchargements dans l'Explorateur (dossier connu `FOLDERID_Downloads`) | toujours |

**PC** (`actions/launchers.py`) :
- `snapshot()` envoie la section `"launchers":{"settings":true,"discord":bool,"spotify":bool,"downloads":true,"icons":{"discord":"<sha1>"|null,"spotify":"<sha1>"|null}}`.
- La détection de l'installation est mise en cache 60 s.
- Les icônes de Discord et de Spotify sont les vraies icônes de leur exe, extraites par `AppIconProvider` et envoyées par `MEDIA_ARTWORK`, comme l'icône de la barre.
- Action `{"id":"launch.open","target":"settings"|"discord"|"spotify"|"downloads"}` :
  - une **liste fermée** associe chaque cible à sa commande ; aucune autre cible n'est acceptée ;
  - lancement sans fenêtre de console ;
  - échec ou application absente : notice `app_not_found`.
- L'action passe par le chemin normal du hub, pas par le fil d'entrée.

**Appareil** :
- Les blocs affichent une icône et un libellé : « Paramètres / Settings », « Discord », « Spotify », « Téléchargements / Downloads ».
- Icônes :
  - Paramètres et Téléchargements : icônes Material `settings` et `download` (Apache-2.0) ;
  - Discord et Spotify : l'icône reçue du PC, et une icône neutre tant qu'elle n'est pas arrivée.
- Un tap envoie `launch.open`, avec un retour haptique.
- Ils s'ajoutent à la fin de l'ordre par défaut et sont placés automatiquement dans la grille. Les dispositions enregistrées les reçoivent comme des blocs nouveaux, à la première place libre.

## 2. Claude Code

### 2.1 Compacter la session

- Un bouton « Compacter la session » / « Compact session » se trouve dans le bloc Contexte détaillé.
- Il n'apparaît que pour la conversation ouverte dans l'app.
- **Confirmation** : le premier tap affiche « Confirmer ? » pendant 3 s ; un second tap dans ce délai envoie l'action.
- Action `{"id":"claude.compact"}` :
  - le PC met l'app au premier plan, puis invoque le bouton « Compacter la session » / « Compact session » du panneau (nom vu dans l'arbre réel) ;
  - échec : notice `claude_ui_not_found`.

### 2.2 Limites : ouvrir et refermer

- `claude.show_usage` devient une bascule : le bouton « Utilisation : … » est déplié s'il est replié, et replié s'il est déplié.

### 2.3 Limites de session et hebdomadaire affichées ensemble

- **PC** : il garde séparément la dernière limite de session et la dernière limite hebdomadaire, chacune avec son heure de lecture (`seen_at` et `weekly_seen_at`, plus `session_seen_at`). Une lecture qui n'apporte que l'une ne fait jamais disparaître l'autre.
- **Appareil** : les deux blocs affichent toujours leur dernière valeur connue avec « vu à HH:MM ». L'un n'est vide que s'il n'a jamais été lu.
- **Cause trouvée (lecture réelle, en lecture seule)** : le bouton « Utilisation : … » de la barre d'état n'affiche **qu'une limite à la fois**. Son nom était « Utilisation : 76 % de la limite de session et Réinitialisation dans 48 min » lors d'une lecture, puis « Utilisation : Hebdomadaire · tous les modèles : 62% et Réinitialisation le sam. 11:00 » lors d'une autre (l'app montre sans doute la limite la plus proche de son plafond). Une lecture n'apportait donc jamais les deux, et le PC ne gardait que l'hebdomadaire : la limite de session disparaissait dès que l'app affichait l'autre. Le PC garde maintenant chaque limite séparément, avec son horodatage (`usage.session_seen_at`, `usage.weekly_seen_at`).

### Notes d'implémentation (PC)

- `launch.open` : cible inconnue ou mal formée = ignorée et journalisée (pas de notice) ; application absente ou lancement en échec = `app_not_found`. Un tap sur un lanceur refait la détection (l'application a pu être installée depuis la dernière lecture).
- L'icône de Discord est celle de `app-<version la plus récente>\Discord.exe` (à défaut `Update.exe`) ; celle de Spotify, de `Spotify.exe`. Avec le seul protocole (Microsoft Store), l'icône reste `null` et l'appareil garde son icône neutre.
- Compacter : le bouton invoqué est celui de la carte Contexte (« Compacter la session », vu en lecture seule avec `InvokePattern`). Si la carte est repliée ou le panneau masqué, la notice `claude_ui_not_found` est envoyée.

## 3. Tests

- **PC** :
  - lanceurs : détection avec un faux système de fichiers ou registre, liste fermée (une cible inconnue est refusée), lanceur simulé ;
  - `claude.compact` avec un faux invocateur ;
  - bascule de `show_usage` (déplié puis replié) ;
  - conservation séparée des deux limites.
- **Android** :
  - lecture de la section `launchers` ;
  - présence des blocs ;
  - placement des blocs nouveaux dans une disposition existante ;
  - JSON des actions ;
  - délai de confirmation du compactage (logique pure).
- **Réel** :
  - chaque lanceur ;
  - compacter la session ;
  - limites qui s'ouvrent puis se referment ;
  - les deux limites visibles ensemble.

## 4. Révision (2026-10-21, retours de l'essai réel)

### 4.1 Icône de Spotify (version Microsoft Store)
- **Constat** : le Spotify de l'utilisateur est la version Store (`SpotifyAB.SpotifyMusic`). Le PC ne trouvait que le protocole `spotify:` et envoyait donc `icons.spotify = null`.
- **PC** : quand `%APPDATA%\Spotify\Spotify.exe` est absent, le PC lit en lecture seule le registre `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages\SpotifyAB.SpotifyMusic_*`, valeur `PackageRootFolder`. Si `<racine>\Spotify.exe` existe (il est lisible), l'icône en est extraite. Le lancement continue de passer par `spotify:`.
- **Appareil** : le bloc « Lecture en cours » affiche cette icône (`launchers.icons.spotify`) en petit (≈ 22 dp, coins arrondis), **en haut à droite du bloc**, quand la source du média (`now.app`) contient « spotify » (casse ignorée) et que l'image est arrivée.

### 4.2 Barre contextuelle : la grille ne bouge plus
- La zone de la barre en bas est **toujours réservée** sur la page normale, à sa hauteur maximale (onglets empilés compris), qu'une barre soit affichée ou non.
- La barre se dessine en bas de cette zone. La grille garde donc la même taille et la même position quand la barre apparaît, disparaît ou change de forme.

### 4.3 Le contenu des blocs suit leur taille
- **Lecture en cours, côte à côte** : la colonne de texte occupe toute la largeur à droite de la pochette.
  - Le titre, l'artiste et l'app sont en haut ; les trois touches sont en bas, réparties sur la largeur de la colonne.
  - La taille du texte ne change pas, sans écrasement (une ligne, points de suspension).
- **Lecture en cours, vertical** : dès que le bloc est plus haut que large (hauteur > largeur), la pochette se met au-dessus et le texte en dessous.
  - La pochette prend au plus la largeur du bloc et au plus 60 % de sa hauteur.
  - Le texte et les touches occupent le reste.
- **Son et Luminosité** agrandis vers le bas : l'en-tête est en haut, le curseur au milieu de l'espace libre, les touches (Son) en bas. Le contenu se répartit dans la hauteur au lieu de rester groupé en haut ; rien ne grossit.
- **Clé USB** : les puces se partagent la hauteur du bloc ; chaque puce a une hauteur minimale de 68 dp et défile s'il en manque.

### 4.4 Lanceurs : ouvrir puis réduire
- Si la fenêtre de l'application ciblée est **au premier plan** sur le PC, un tap la **réduit** (équivalent de « _ », `ShowWindow(SW_MINIMIZE)`). Sinon, le tap l'ouvre ou la ramène, comme avant.
- Reconnaissance de la fenêtre au premier plan :
  - `discord` : processus `Discord.exe` ;
  - `spotify` : processus `Spotify.exe` ;
  - `settings` : fenêtre `ApplicationFrameWindow` dont une fenêtre enfant appartient à `SystemSettings.exe`, ou processus `SystemSettings.exe` ;
  - `downloads` : fenêtre de l'Explorateur (`CabinetWClass`) dont le dossier courant est le dossier Téléchargements (`Shell.Application().Windows()`, correspondance par HWND).
- La liste des cibles reste fermée. Les tests utilisent des fausses fonctions de fenêtre : rien n'est réduit en vrai pendant les tests.
