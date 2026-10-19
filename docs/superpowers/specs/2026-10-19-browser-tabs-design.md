# Orizon X — Onglets du navigateur dans la barre contextuelle (design)

Date : 2026-10-19
Statut : validé par l'utilisateur, à implémenter (branche `browser-tabs`, depuis `app-icon`)
Prérequis : pages et détection par URL (`2026-10-19-creative-bar-design.md`), icône d'app (`2026-10-19-app-icon-design.md`).

## 1. Objectif

Quand un navigateur est au premier plan, la barre du mode Actions propose une page **« Tabs / Onglets »** : les onglets ouverts dans cette fenêtre. Un tap bascule sur l'onglet touché.

**Exclus** :
- le favicon de chaque onglet (l'interface d'accessibilité ne le donne pas) ;
- fermer ou réordonner des onglets ;
- les onglets des autres fenêtres.

## 2. Lecture des onglets (PC, `actions/browser_tabs.py`)

- **Lecteur** : `BrowserTabsReader`, avec une couche UI Automation injectable. Comme `browser_url.py`, il importe comtypes à la demande et crée l'objet UIA sur le thread qui l'appelle.
- **`tabs(hwnd, title)`** renvoie `list[Tab(index, title, active)]`.
  - Il lit les éléments `TabItem` descendants de la fenêtre.
  - `active` vient de `SelectionItemPattern.CurrentIsSelected`.
  - Il ne lève jamais d'exception : en cas d'erreur, il renvoie `[]` et journalise une fois par type d'erreur.
- **Cache** :
  - clé `(hwnd, titre de la fenêtre)`, relu toutes les 2 s même sans changement de titre ;
  - au plus 24 onglets, dans l'ordre de la barre d'onglets.
- **Titre court** :
  - le suffixe de la bulle mémoire de Chrome est retiré (expression régulière ` - (Utilisation de la mémoire|Memory usage) - .*$`) ;
  - les espaces sont enlevés ;
  - le titre est coupé à 40 caractères, avec « … ».
- **`select(hwnd, index, title) -> bool`** :
  1. Il relit les onglets.
  2. Il choisit l'onglet de rang `index` si son titre court vaut `title`, sinon le premier onglet de ce titre. Si aucun ne correspond, il renvoie `False` sans rien faire.
  3. Il appelle `SelectionItemPattern.Select()`.
  4. En cas d'échec, et si le rang est inférieur à 8, il envoie `Ctrl+<rang+1>` par `actions.keys`.
  5. Après une bascule, le cache est invalidé.
- **Navigateurs concernés** : seulement les exe du profil `browser` (Chrome, Edge, Firefox, Brave, Opera). Firefox expose aussi des `TabItem` ; s'il n'en donne pas, il n'a pas de page Onglets.

## 3. Pages et protocole

- **Place de la page `tabs`** :
  - profil `browser` : `tabs` en première page, puis la page `main` (navigation, inchangée) ;
  - profils de site (`canva`, `figma`) dans un navigateur : `tabs` en dernière page ;
  - aucun onglet lu : pas de page `tabs`.
- **Boutons** de la page `tabs` : `{"id":"tab.<rang>","icon":"tab","label":"<titre court>","active":true|false}`, au plus 24.
- **Défilement** : la page porte `"scroll":true`. C'est la seule qui peut dépasser 8 boutons ; elle en accepte 24.
- **`context.press`** sur `tab.<rang>` :
  - accepté si le rang existe dans la dernière liste envoyée ;
  - le PC appelle `select(hwnd, rang, titre envoyé)`, puis diffuse aussitôt l'état ;
  - un échec est journalisé.
- **Libellé de la page** : « Tabs » / « Onglets ».
- **`protocol/PROTOCOL.md`** documente `scroll`, `active` et `tab.<rang>`.

## 4. Appareil (Android)

- **Modèle** :
  - `ContextPage` gagne `scroll: Boolean` ; `ContextButton` gagne `active: Boolean` ;
  - une page `scroll` garde jusqu'à 24 boutons, les autres 8.
- **Page défilante** :
  - boutons de largeur fixe (environ 132 dp), icône au-dessus du titre (une ligne, « … ») ;
  - rangée qui défile horizontalement ;
  - quand la page apparaît, l'onglet actif est amené dans la vue.
- **Bouton actif** : fond plus clair et bordure, dans le style de l'onglet de page sélectionné.
- **Balayage** : le balayage de page existant reste valable aux extrémités de la rangée, comme aujourd'hui pour une rangée qui défile.
- **Icône** : nouvelle `ctx_tab` (Material « tab »). Le PC ajoute `tab` à `ICON_NAMES`.

## 5. Tests

- **PC** :
  - **lecteur** (fausse couche UIA) :
    - ordre, onglet actif ;
    - suffixe mémoire retiré, coupe à 40 caractères, limite de 24 ;
    - cache et relecture à 2 s ;
    - une erreur donne `[]` ;
  - **`select`** :
    - titre vérifié au même rang ;
    - titre retrouvé à un autre rang ;
    - aucune correspondance : rien n'est fait ;
    - échec de `Select()`, puis repli `Ctrl+N` avec un faux `SendInput` (rang inférieur à 8 seulement) ;
  - **pages** :
    - navigateur : `tabs` en premier ;
    - Canva dans un navigateur : `tabs` en dernier ;
    - aucun onglet : pas de page ;
    - app native : jamais de page `tabs` ;
  - **`context.press`** : `tab.N` accepté, rang inconnu refusé ;
  - **instantané** : `scroll` et `active`.
- **Android** :
  - lecture de `scroll` et `active` ;
  - limite de 24 boutons pour une page défilante, de 8 pour les autres ;
  - correspondance de l'icône `tab`.
- **Réel**, avec l'accord de l'utilisateur au moment de basculer ses onglets :
  - Chrome avec plusieurs onglets : bascule depuis la barre, onglet actif mis en avant ;
  - Canva dans Chrome : page Onglets en dernier.
