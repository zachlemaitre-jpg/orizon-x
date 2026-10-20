# Orizon X — Profils IA de la barre contextuelle (design)

Date : 2026-10-20
Statut : validé par l'utilisateur, à implémenter (branche `ai-profiles`, créée depuis `master` 0.12.0)
Prérequis : barre contextuelle avec pages, détection par URL et page Onglets (`2026-10-19-creative-bar-design.md`, `2026-10-19-browser-tabs-design.md`).

## 1. Objectif

La barre du mode Actions propose une page **« Chat »** quand Claude, ChatGPT ou Gemini est au premier plan, que ce soit dans son app ou dans le navigateur.

## 2. Détection

- **Claude** (`claude`) :
  - l'app Claude (`claude.exe`) ;
  - un onglet de navigateur sur `claude.ai`.
- **ChatGPT** (`chatgpt`) :
  - l'app ChatGPT (`ChatGPT.exe`) ;
  - un onglet sur `chatgpt.com` ou `chat.openai.com`.
- **Gemini** (`gemini`) : un onglet sur `gemini.google.com`. La règle d'hôte doit viser précisément ce sous-domaine : le reste de `google.com` garde le profil `browser`.
- **Navigateur** : dans un navigateur, ces profils gagnent en dernière page la page `tabs` existante (même règle que pour Canva et Figma).
- **Noms affichés** : « Claude », « ChatGPT », « Gemini ».

## 3. Page « Chat » (libellés en anglais et en français)

| Bouton (en / fr) | Icône | Claude (app) | Claude (claude.ai) | ChatGPT | Gemini |
|---|---|---|---|---|---|
| New chat / Nouvelle discussion | `chat_new` | UIA : bouton de la barre latérale « Nouveau » / « New » | raccourci à vérifier | `Ctrl+Shift+O` | `Ctrl+Shift+O` |
| Search / Rechercher | `search` | UIA : « Rechercher » / « Search », si présent | à vérifier | `Ctrl+K` | à vérifier |
| Sidebar / Barre latérale | `sidebar` | UIA : bascule de la barre latérale, si présente | à vérifier | `Ctrl+Shift+S` | à vérifier |
| Copy reply / Copier la réponse | `copy_reply` | — | — | `Ctrl+Shift+C` | à vérifier |
| Copy code / Copier le code | `copy_code` | — | — | `Ctrl+Shift+;` (par la position de la touche, comme les touches OEM de VS Code) | — |
| Input / Zone de saisie | `input_focus` | à vérifier | à vérifier | `Shift+Esc` | à vérifier |
| Stop / Arrêter | `stop` | `Esc` | `Esc` | `Esc` | `Esc` |

Règles :
- **Boutons « à vérifier »** : un bouton n'est livré que si son raccourci est connu de façon fiable. Les autres sont livrés **masqués**, avec une note dans la spec, puis validés ou retirés pendant l'essai réel.
- **Boutons UIA** (app Claude) : un bouton de profil peut avoir une action UIA (`invoke_named` avec des noms FR/EN) au lieu d'un raccourci. Le PC met l'app au premier plan si besoin, puis invoque l'élément. Les noms se cherchent dans l'arbre réel, en lecture seule, sans rien invoquer.
- **Ids des boutons** : préfixés `cl.`, `gpt.` et `gem.`. Les variantes app/web de Claude sont deux profils distincts : `claude_app` et `claude_web`.

### Notes d'implémentation (PC, 2026-10-20)

- **Boutons livrés masqués** (donnée `hidden` du profil : absents de l'instantané, refusés par `context.press`), à valider ou retirer à l'essai réel :
  - Claude (app) : `cl.app.input` (Zone de saisie) ;
  - Claude (claude.ai) : `cl.web.new`, `cl.web.search`, `cl.web.sidebar`, `cl.web.input` (seul `cl.web.stop`, Échap, est livré) ;
  - Gemini : `gem.search`, `gem.sidebar`, `gem.copy_reply`, `gem.input` (livrés : `gem.new`, `gem.stop`).
- **Boutons livrés** : Claude (app) : Nouvelle discussion, Rechercher, Barre latérale (UIA) et Arrêter (Échap) ; ChatGPT : les sept boutons ; Gemini : Nouvelle discussion et Arrêter ; claude.ai : Arrêter.
- **Noms UIA relevés en lecture seule dans l'app Claude (interface française)** : « Nouveau » (Button, Invoke), « Rechercher » (Button, Invoke), « Masquer la barre latérale » (Button, Invoke ; l'état replié porte sans doute « Afficher la barre latérale », non vérifié). Les noms anglais « New », « Search », « Hide sidebar » / « Show sidebar » sont des suppositions à confirmer. La bascule « Panneau des sessions » existe aussi, mais c'est celle du panneau de droite, pas de la barre latérale.
- Un bouton UIA invoque l'élément de la fenêtre au premier plan (l'app Claude l'est déjà) ; s'il est introuvable, la notice `claude_ui_not_found` est envoyée.
- `Ctrl+Maj+;` de ChatGPT est envoyé par la position de la touche (`Ctrl+Shift+OEM_1`, la touche `;` d'un clavier US).
- Les favicons des profils de site (`claude.ai`, `chatgpt.com`, `gemini.google.com`) servent d'icône de la barre, comme pour Canva et Figma.

## 4. Appareil

- Nouvelles icônes `ctx_<nom>` (tracés Material Icons, licence Apache-2.0) :

  | Icône | Symbole Material |
  |---|---|
  | `chat_new` | `add_comment` |
  | `sidebar` | `view_sidebar` |
  | `copy_reply` | `content_copy` (ou un fichier distinct si nécessaire) |
  | `copy_code` | `code` |
  | `input_focus` | `keyboard` |
  | `stop` | `stop_circle` |

  `search` existe déjà.
- Rien d'autre ne change : la barre affiche ce que le PC envoie.

## 5. Tests

- **PC** :
  - détection par exe et par hôte (`claude.ai`, `chatgpt.com`, `chat.openai.com`, `gemini.google.com`) ;
  - `www.google.com` qui reste `browser` ;
  - pages (Chat, plus Onglets dans un navigateur) ;
  - libellés en anglais et en français ;
  - raccourcis analysés avec un faux `SendInput` ;
  - boutons UIA joués avec un faux invocateur ;
  - `context.press` refusé pour un bouton masqué ou d'un autre profil.
- **Android** : correspondance des nouvelles icônes.
- **Réel** : chaque bouton dans l'app Claude, sur claude.ai, sur ChatGPT et sur Gemini. Les boutons « à vérifier » sont validés ou retirés.
