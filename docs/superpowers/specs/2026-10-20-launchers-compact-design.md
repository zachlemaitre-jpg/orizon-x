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
