# Orizon X — Bloc Claude Code (mode Actions) (design)

Date : 2026-10-20
Statut : validé par l'utilisateur, à implémenter (branche `claude-code` depuis `master` 0.10.0)

## 1. Objectif

En mode Actions, un bouton **« Claude Code »** ouvre un écran qui montre, en **lecture seule**, les sessions Claude Code du PC. On y voit les titres, l'état, le contexte, le modèle, la dernière demande, la dernière réponse, les fichiers modifiés et les connecteurs. Un bouton met l'app Claude au premier plan sur le PC.

**Exclus** :
- envoyer des messages à Claude ;
- les connecteurs claude.ai (non stockés localement) ;
- le pourcentage de contexte (la taille de la fenêtre du modèle n'est pas stockée) ;
- ouvrir une session précise dans l'app.

## 2. Données (PC, lecture seule)

- **Emplacement** :
  - sessions : `%USERPROFILE%\.claude\projects\<projet>\<id>.jsonl`, au premier niveau seulement ; les sous-dossiers (sous-agents, mémoire) sont ignorés ;
  - connecteurs : `%USERPROFILE%\.claude.json`, plus `<cwd>\.mcp.json` pour chaque projet listé.
- **Choix des sessions** : les 12 fichiers `.jsonl` modifiés le plus récemment, tous projets confondus.
- **Lecture d'un fichier** :
  - au premier passage, seuls les 2 derniers Mio sont lus, et la première ligne, incomplète, est ignorée ;
  - aux passages suivants, seul ce qui a été ajouté depuis l'offset précédent est lu (cache par chemin : offset, mtime, taille, champs extraits) ;
  - un fichier raccourci ou remplacé est relu comme au premier passage ;
  - une ligne JSON invalide est ignorée.
- **Champs extraits** (le dernier rencontré l'emporte) :
  - `title` : le dernier `custom-title.customTitle`, sinon le `slug` d'un enregistrement, sinon l'id raccourci ;
  - `cwd` et `gitBranch`, tirés des enregistrements `user` ou `assistant` ;
  - `project` : le dernier composant de `cwd` ;
  - `updated` : le `timestamp` le plus récent, ou la mtime du fichier ;
  - `model` : `requestedModel`, sinon `message.model` d'un `assistant` ;
  - `effort` : `effort` d'un `assistant` ;
  - `mode` : `permissionMode` d'un `user` ;
  - `tokens` : `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` du dernier `assistant.message.usage` ;
  - `last_prompt` : `last-prompt.lastPrompt`, coupé à 300 caractères ;
  - `last_result` : le texte de la dernière réponse `assistant` qui contient au moins un bloc `text`, blocs `text` concaténés, coupé à 1 500 caractères ;
  - `files` : les clés de `trackedFileBackups` du dernier `file-history-snapshot`, rendues relatives à `cwd` quand c'est possible, 20 au plus, dans l'ordre alphabétique ;
  - `entry` : `entrypoint` (`claude-desktop` donne `desktop`, toute autre valeur donne `cli`) ;
  - `status` : `working` si le fichier a été modifié il y a moins de 15 s, sinon `idle`.
- **Connecteurs** : seulement les **noms** et le **type** (`stdio`, `http`, `sse`) des entrées `mcpServers`, avec leur portée (`global`, ou le nom du projet).
  - On ne lit ni n'envoie aucune autre clé de `.claude.json`, qui contient des informations de compte, ni les commandes, URL, en-têtes ou variables d'environnement des serveurs.
  - Au plus 30 connecteurs.

## 3. Protocole

La version reste 1.

- `ACTIONS_STATE` gagne une section `"claude"`.
  - Si aucun dossier `.claude\projects` n'existe : `{"available":false}`.
  - Sinon :
    ```json
    {"available":true,
     "sessions":[{"id","title","project","branch","updated":<epoch s>,"status":"working"|"idle",
                  "model","effort","mode","tokens":<int>|null,"last_prompt","last_result","files":[…],"entry"}],
     "connectors":[{"name","type","scope"}]}
    ```
  - Les champs inconnus sont `null` ou `""`.
  - L'ensemble reste sous 64 Kio. Au besoin, `last_result` est raccourci d'une session à l'autre, de la plus ancienne à la plus récente.
- `ACTION` `{"id":"claude.focus"}` : met la fenêtre principale de l'app Claude au premier plan.
  - Une notice `claude_not_running` est envoyée si l'app ne tourne pas.
- `protocol/PROTOCOL.md` documente la section et l'action.

## 4. PC (`actions/claude_code.py`)

- **`ClaudeCodeProvider(root, clock, fs)`** : système de fichiers injectable.
  - `snapshot()` donne la section ci-dessus.
  - L'analyse est faite dans le cycle lent du hub. Le coût reste faible grâce au cache et aux lectures incrémentales.
- **`claude.focus`** : couche Win32 injectable.
  - Elle cherche la fenêtre visible de premier niveau, sans propriétaire, du processus `claude.exe` (image `...\AnthropicClaude\...\claude.exe` ou toute image nommée `claude.exe` qui possède une fenêtre titrée).
  - Mise au premier plan : `ShowWindow(SW_RESTORE)` si elle est réduite, puis `SetForegroundWindow`. Si Windows refuse, on envoie Alt enfoncé puis relâché (`keybd_event`) et on réessaie, le contournement habituel.
  - L'action passe par le chemin normal du hub, pas par le fil d'entrée.
- **Hub** : fournisseur par défaut, routage de `claude.*`, section dans le cycle lent.

## 5. Appareil (Android)

- **Bouton** : pastille « Claude Code » dans l'en-tête Actions, avec l'icône neutre `ox_claude_code` (Material « terminal »), visible si `claude.available`. Elle n'ouvre jamais en même temps que clavier, trackpad ou manette.
- **Écran** : en-tête partagé (`OverlayTopRow`), puis le contenu, et un ✕.
  - **Paysage** : liste à gauche (environ 38 % de la largeur) et détails à droite.
  - **Portrait** : la liste ; un tap ouvre les détails, avec un bouton « ← Sessions ».
- **Liste** : titre en gras sur une ligne, puis `projet · branche` en atténué, puis l'âge (« à l'instant », « 3 min », « 2 h », « hier »…). À gauche, une pastille d'état : verte et animée si la session est `working`, grise sinon. La session choisie est mise en avant. Par défaut, c'est la plus récente.
- **Détails** :
  - titre et état ;
  - pastilles modèle, effort et mode ;
  - jetons de contexte (« 561 k jetons ») ;
  - « Dernière demande » ;
  - « Dernière réponse », dans une zone qui défile ;
  - « Fichiers modifiés », dans une liste qui défile ;
  - « Connecteurs », la liste globale plus ceux du projet de la session ;
  - le bouton « Mettre Claude au premier plan », qui envoie `claude.focus`.
- **Rafraîchissement** : l'appareil n'a rien à faire, les états arrivent avec `ACTIONS_STATE`. La sélection est gardée par `id`.
- **Textes** : tout passe par `Strings` (en/fr).
- **Formatage pur** (`claude/ClaudeFormat.kt`) : âge relatif, jetons (« 561 k », « 1,2 M » ou « 1.2 M »).

## 6. Tests

- **PC** :
  - lecture d'un faux `.jsonl` : chaque champ, la priorité du dernier, une ligne invalide, la première ligne coupée de la fenêtre de 2 Mio, la lecture incrémentale (seul l'ajout est lu), le fichier raccourci ;
  - choix des 12 plus récents ;
  - `status` selon l'âge ;
  - coupes et limite de 64 Kio ;
  - connecteurs : seulement les noms, les types et les portées, sans aucune autre clé (vérifié avec un faux `.claude.json` qui contient des secrets) ;
  - `focus` avec une fausse couche Win32 : trouvé, réduit, refusé puis contourné, pas lancé ;
  - hub ;
  - une lecture réelle de `~/.claude/projects`, en lecture seule, en vérification manuelle.
- **Android** :
  - lecture de la section `claude` ;
  - formats d'âge et de jetons ;
  - sélection par défaut et sélection conservée.
- **Réel** :
  - les sessions de l'utilisateur ;
  - la session en cours en vert ;
  - la dernière réponse ;
  - les fichiers ;
  - le bouton qui met Claude au premier plan.

## 7. Révision (2026-10-20, après essai réel) : nouvelle disposition et lecture du panneau de l'app

L'utilisateur a validé le bloc et demandé la disposition de sa maquette. Il a aussi demandé les informations du panneau de droite de l'app Claude (Contexte détaillé, Connecteurs, Résultats, Modifications, limites d'utilisation).

### 7.1 Lecture du panneau de l'app Claude (PC, `actions/claude_app_ui.py`, UI Automation, lecture seule)

Un essai réel en lecture seule a montré que l'app Claude (Electron) expose son arbre d'accessibilité après une première requête. Le premier appel renvoie 24 éléments ; un second, quelques secondes plus tard, en renvoie 641 en environ 180 ms. On y lit :
- **Contexte** : « 61 % utilisé » ; des paires nom/valeur (Messages 540.3k, System tools, MCP tools, Skills, System prompt, Custom agents, Memory files, « Depuis la dernière mise à jour », Autocompact buffer, Free space, MCP tools (deferred), System tools (deferred)) ; le total « 598.5k / 1M » quand il est présent ;
- **Connecteurs** : « 1 connecté(s) » ;
- **Résultats** : les noms de fichiers ;
- **Modifications** : `+N` et `−M` ;
- **Usage** : « Utilisation : 42 % de la limite de session et Réinitialisation dans 1 h 12 min » ; la limite hebdomadaire n'est lue que si elle apparaît (ligne « Hebdomadaire … % … Réinitialisation … »).

Règles :
- **Libellés** : en français ou en anglais selon la langue de l'app. L'analyse repose sur la structure (paires libellé/valeur dans l'ordre), avec des listes de libellés FR et EN.
- **Fenêtre** : c'est celle de `claude.exe` décrite au §4. On ne lit que le sous-arbre du panneau de droite si on peut l'isoler, sinon toute la fenêtre. Seuls les libellés et valeurs du panneau sont gardés : aucun texte de la conversation n'est conservé ni envoyé.
- **Session** : le titre de la fenêtre de l'app (par exemple « OrizonX App ») désigne la conversation ouverte. On la relie à une session locale par son `title`.
- **Coût** : la lecture n'a lieu que pendant que l'écran Claude Code est ouvert sur l'appareil, ce qui est signalé par l'action `claude.watch` `{"open":true|false}`. Elle se fait au plus toutes les 3 s, dans le cycle lent ; elle prend environ 200 ms.
- **Réveil** : si la lecture renvoie moins de 100 éléments, l'arbre est considéré comme pas encore réveillé, et on réessaie au cycle suivant.
- **Échec** : la section `app` est absente.

### 7.2 Protocole (ajouts)

- La section `claude` gagne `"app"`. Elle n'existe que si le panneau a été lu.
  ```json
  {"session_title":"…","seen_at":<epoch s>,
   "context":{"percent":61,"used":"598.5k","window":"1M","items":[{"name":"Messages","tokens":"540.3k","percent":"54,0 %"},…],"deferred":[{"name","tokens"}]},
   "connected":1,"results":["…"],"changes":{"added":2140,"removed":9},
   "usage":{"session":{"percent":42,"reset":"1 h 12 min"},"weekly":{"percent":34,"reset":"sam. 11:00"}|null},
   "tasks":[{"name":"…","status":"running"|"completed","elapsed":"3min 46s"}],"tasks_done":3}
  ```
  - `tasks` : la carte « Tâches en arrière-plan » (EN « Background tasks »), au plus 10 lignes de 120 caractères ; `running` si la ligne a son bouton « Arrêter cette tâche », sinon `completed`. `tasks_done` : son résumé « N terminé(s) ». Les deux n'existent que si la carte est présente ; `tasks` vaut `[]` quand elle ne liste rien.
  - `session_title` vient du bouton « <titre>, renommer la session » de la barre d'outils de la session (le titre de la fenêtre Windows est simplement « Claude »).
  - Les lignes de la liste de contexte sans pourcentage (compteurs d'outils, de fichiers, d'agents) ne sont pas des tranches de la fenêtre et sont ignorées ; les lignes « deferred » n'ont pas de pourcentage et vont dans `deferred`.
- Chaque session locale gagne `"changes":{"added","removed"}|null`. Ce sont les statistiques git du `cwd` (`git diff --shortstat` contre la base de la branche principale `main`/`master`, puis les fichiers non suivis exclus). Elles sont mises en cache 30 s et calculées pour les 12 sessions au plus.
- Nouvelles `ACTION` :
  - `{"id":"claude.watch","open":bool}` ;
  - `{"id":"claude.new"}`, `{"id":"claude.artifacts"}`, `{"id":"claude.customize"}`, `{"id":"claude.more"}` : elles mettent l'app au premier plan puis invoquent le bouton de la barre latérale qui porte ce nom (FR : « Nouveau », « Artéfacts », « Personnalisation », « Plus » ; EN : « New », « Artifacts », « Customize », « More ») par `InvokePattern` ;
  - `{"id":"claude.open","title":"…"}` : elle met l'app au premier plan puis invoque l'élément de la barre latérale portant ce titre.
  - En cas d'échec, la notice `claude_ui_not_found` est envoyée.

### 7.3 Disposition de l'appareil (maquette de l'utilisateur, sans couleurs, style verre de l'app)

- **En haut, sur toute la largeur** : la barre contextuelle.
- **Colonne de gauche** (environ 32 %), de haut en bas :
  - heure, date et batterie (le bloc horloge existant) ;
  - quatre boutons empilés : « + Nouveau », « Artéfacts », « Personnalisation », « Plus » ;
  - un bloc « Conversations » : les sessions **groupées par projet**, comme la barre latérale de l'app. L'en-tête de groupe porte le nom du projet ; dessous, les titres avec leur pastille d'état. Le bloc défile.
  - Un tap sur une conversation l'ouvre dans l'app (`claude.open`) et la sélectionne sur l'appareil.
- **Panneau de droite** :
  - **barre d'en-tête** : titre de la session, `projet · branche`, pastille d'état, modèle et mode, et le bouton « Mettre au premier plan » ;
  - **Contexte détaillé** (grand bloc) :
    - si `app` correspond à la session choisie : « 61 % utilisé · 598.5k / 1M », une barre, puis la liste nom / jetons / %, puis les entrées « deferred » en atténué ;
    - sinon : le total de jetons local, et la mention « Détail disponible pour la conversation ouverte dans l'app » ;
  - **Modifications** (une ligne) : `+2140 −9` en vert et rouge, depuis `app.changes` si c'est la session ouverte, sinon depuis les statistiques git locales ;
  - **Résultats** : la liste des fichiers (`app.results`, sinon `files` en local), qui défile ;
  - **Limite de session** : pourcentage, barre et « Réinitialisation dans … », avec « vu à HH:MM » ;
  - **Hebdomadaire · tous les modèles** : pareil s'il est disponible, sinon « Ouvre le panneau des limites dans l'app pour l'actualiser ».
  - Les limites sont globales : elles s'affichent quelle que soit la session choisie.
- **Portrait** : la colonne de gauche, puis le panneau de droite en dessous ou en vue séparée (bouton « ← »).
- Le style suit celui de l'app : verre, sans les couleurs de la maquette. Seuls les `+` et `−` sont en vert et rouge.
