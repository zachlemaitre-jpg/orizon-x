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
