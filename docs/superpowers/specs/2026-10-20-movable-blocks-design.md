# Orizon X — Blocs déplaçables du mode Actions (design)

Date : 2026-10-20
Statut : validé par l'utilisateur, à implémenter (branche `movable-blocks` depuis `master` 0.11.0)

## 1. Objectif

En mode Actions, l'utilisateur **réorganise les blocs** de l'écran principal et peut en **masquer**. La barre contextuelle du bas et les pastilles de l'en-tête ne bougent pas. Tout se passe sur l'appareil : le PC n'est pas concerné.

**Exclus** :
- placement libre ;
- changement de taille ;
- bouton de réinitialisation (non demandé).

## 2. Blocs

Chaque bloc a un identifiant stable et une taille fixe, exprimée en colonnes × lignes.

| id | Bloc | Paysage (4 col.) | Portrait / téléphone (2 col.) | Présence |
|---|---|---|---|---|
| `clock` | heure, date, batterie | 4 × 1 | 2 × 1 | si horloge ou batterie |
| `sound` | Son (volume, muet, touches média s'il n'y a pas de lecture en cours) | 2 × 1 | 2 × 1 | si le son est disponible |
| `now_playing` | Spotify / En cours de lecture | 2 × 2 | 2 × 2 | si quelque chose joue |
| `brightness` | Luminosité | 2 × 1 | 2 × 1 | si disponible |
| `wifi` | Wi-Fi | 1 × 1 | 1 × 1 | si disponible |
| `bluetooth` | Bluetooth | 1 × 1 | 1 × 1 | si disponible |
| `airplane` | Mode avion | 1 × 1 | 1 × 1 | si disponible |
| `usb` | Clé USB (ouvrir, éjecter) | 2 × 1 | 2 × 1 | si une clé est branchée |

- Les tuiles actuelles « Wi-Fi / Bluetooth / Avion » deviennent **trois blocs indépendants**. Elles gardent leurs icônes, leur état et leurs actions.
- La **colonne USB latérale** disparaît : la clé devient le bloc `usb`.
- **Ordre par défaut** : `clock`, `now_playing`, `sound`, `brightness`, `wifi`, `bluetooth`, `airplane`, `usb`.

## 3. Grille

**Placement**, par un algorithme pur `actions/BlockGrid.kt` :
- les blocs **visibles et présents** sont placés dans l'ordre enregistré ;
- chaque bloc prend la première position libre en parcourant les lignes de haut en bas, puis les colonnes de gauche à droite ;
- un petit bloc peut ainsi remplir un trou laissé plus haut ;
- un bloc plus large que la grille est ramené à sa largeur.

**Dimensions** :
- largeur d'une colonne = largeur disponible ÷ nombre de colonnes ;
- hauteur d'une ligne fixe, environ 150 dp en paysage et 130 dp en portrait. Le bloc horloge peut prendre sa hauteur naturelle à l'intérieur de sa case.

**Défilement** : la grille défile verticalement si elle dépasse l'écran.

**Bloc absent** (pas de clé, rien en lecture) : il n'est pas affiché mais garde sa place dans l'ordre. S'il revient, il réapparaît à sa place.

## 4. Mode édition

- **Entrée** : appui long (environ 500 ms) sur un bloc, hors de ses contrôles. Un curseur de volume ou un bouton garde son geste à lui.
- **Pendant l'édition** :
  - les blocs **ondulent** légèrement (rotation de ±1°, décalée d'un bloc à l'autre) ;
  - leurs contrôles sont **désactivés** : un calque transparent prend les touchers ;
  - une pastille **✕** est en haut à gauche de chaque bloc. Elle **masque** le bloc ;
  - un bouton **« + Ajouter »** n'apparaît que s'il y a des blocs masqués. Il ouvre une petite liste des blocs masqués, et un tap en rétablit un ; le bloc revient à sa place dans l'ordre ;
  - un bouton **« Terminé »** quitte l'édition.
  - Ces boutons sont placés en haut de la grille.
- **Glisser** :
  - on fait glisser un bloc, qui suit le doigt, agrandi à 1,05 avec une ombre ;
  - quand il passe au-dessus d'un autre bloc, il **prend sa place** : il est retiré de l'ordre puis inséré à la position de la cible, et les autres se décalent ;
  - la grille se replace en direct, avec une animation d'environ 200 ms ;
  - au lâcher, le bloc se range dans sa case.
- **Retour haptique** à l'entrée en édition, à chaque changement de place et au masquage.
- **Sortie automatique** : on quitte aussi l'édition en ouvrant le clavier, le trackpad, la manette ou Claude Code, ou en changeant de mode.

## 5. Enregistrement

- Les préférences existantes (`orizonx`) gagnent la clé `actions_layout`, de la forme `{"order":[ids…],"hidden":[ids…]}`.
- Elle est enregistrée à chaque changement.
- **Lecture tolérante** :
  - un id inconnu est ignoré ;
  - un bloc connu mais absent de l'ordre enregistré (par exemple un bloc ajouté dans une version suivante) est ajouté **à la fin** ;
  - un JSON invalide donne la disposition par défaut.
- La même disposition sert en paysage et en portrait. Seule la grille change.

## 6. Tests

- **`BlockGrid`** :
  - placement de l'ordre par défaut en 4 et en 2 colonnes ;
  - trous comblés par les petits blocs ;
  - bloc trop large ramené à la largeur de la grille ;
  - blocs absents et masqués non placés, mais leur ordre conservé ;
  - grille vide.
- **Réordonnancement** :
  - déplacement d'un bloc sur un autre, vers l'avant et vers l'arrière ;
  - sur lui-même : aucun changement ;
  - avec des blocs absents ou masqués entre les deux.
- **Masquer et rétablir** : le bloc rétabli revient à sa place dans l'ordre.
- **Préférences** :
  - aller-retour ;
  - id inconnu ;
  - nouveau bloc ajouté à la fin ;
  - JSON invalide.
- **Réel** : sur la tablette, en paysage et en portrait :
  - réorganiser les blocs ;
  - masquer puis rétablir un bloc ;
  - quitter puis relancer l'app : la disposition est conservée ;
  - brancher puis retirer une clé USB : le bloc apparaît puis disparaît à sa place.

## 7. Révision (2026-10-20, après essai réel) : cellules carrées et blocs redimensionnables

L'utilisateur a demandé des cellules carrées à la taille de l'ancienne tuile Wi-Fi, et des blocs de taille réglable. Cette section remplace le §2 (tailles), le §3 (grille et dimensions) et complète le §4 et le §5.

### 7.1 Grille

- **Cellules carrées** d'environ **120 dp** :
  - colonnes = `max(2, ⌊largeur disponible ÷ 120 dp⌋)` ;
  - côté d'une cellule = (largeur − écarts) ÷ colonnes, la hauteur d'une ligne est le même côté ;
  - écart entre cellules : 8 dp.
- Environ **11 colonnes** sur la tablette en paysage (1440 dp), **7** en portrait (900 dp), **2 à 3** sur un téléphone.
- Le placement reste le premier emplacement libre, en parcourant les lignes puis les colonnes (`BlockGrid.place`). Une taille plus large que la grille est ramenée à sa largeur au moment du placement ; la taille enregistrée n'est pas modifiée.

### 7.2 Tailles des blocs (en cellules, largeur × hauteur)

Un bloc a une taille par défaut, un minimum et un maximum. Le minimum est ce dont son contenu a besoin, avec le remplissage serré de 14 dp, pour ne jamais être coupé.

| Bloc | Défaut | Minimum | Maximum |
|---|---|---|---|
| `clock` | 4 × 2 | 2 × 1 | 8 × 3 |
| `now_playing` | 3 × 2 | 3 × 2 | 6 × 4 |
| `sound` (sans touches média) | 3 × 1 | 2 × 1 | 6 × 2 |
| `sound` (avec touches média) | 3 × 2 | 3 × 2 | 6 × 3 |
| `brightness` | 3 × 1 | 2 × 1 | 6 × 2 |
| `wifi`, `bluetooth`, `airplane` | 1 × 1 | 1 × 1 | 2 × 2 |
| `usb` | 3 × 1 | 3 × 1 | 6 × 3 |

Pourquoi ces minimums (estimations de hauteur et de largeur utiles pour une cellule de 120 dp) :
- Son sans touches : en-tête de 28 dp et ligne muet + curseur de 56 dp, soit 84 dp pour 92 dp utiles sur une ligne.
- Son avec touches : en-tête, curseur, puis muet et trois touches, soit environ 146 dp pour 220 dp utiles sur deux lignes ; la ligne des touches demande environ 330 dp de large, d'où trois colonnes.
- Lecture en cours : pochette de 112 dp, plus un texte et trois touches (environ 190 dp), soit 3 colonnes et 2 lignes.
- Luminosité : en-tête de 28 dp, curseur de 44 dp, soit 80 dp sur une ligne, et deux colonnes pour l'en-tête et la valeur.
- Tuiles Wi-Fi, Bluetooth, Avion : 104 dp de haut au minimum, dans une cellule.
- Clé USB : une puce de 68 dp, qui demande environ 300 dp de large.
- Horloge : la taille des chiffres suit la cellule (hauteur − 64 dp, divisé par 1,2).

### 7.3 Édition

- **Plus d'ondulation** : en édition, les blocs ne bougent pas.
- **Cellules visibles** : en édition, toutes les cellules de la grille sont dessinées derrière les blocs (carrés arrondis, fond blanc 7 %, bordure blanche 20 %), sur toutes les colonnes et sur les lignes utilisées plus **une ligne vide** en bas. Pendant un glissement, les cellules que le bloc occuperait sont plus claires.
- **Poignée de redimensionnement** : en bas à droite de chaque bloc. Faire glisser la poignée agrandit ou réduit le bloc cellule par cellule, dans son minimum et son maximum et dans le nombre de colonnes. La grille se replace en direct, avec un retour haptique à chaque pas.
- **Dépôt sous la dernière ligne** : lâcher un bloc dans la ligne vide du bas le met en fin d'ordre.

### 7.4 Enregistrement

La clé `actions_layout` gagne `"sizes":{"<id>":[largeur,hauteur]}`. Seules les tailles choisies y figurent.
- Un id inconnu, ou une valeur qui n'est pas deux entiers positifs, est ignoré.
- Une taille hors limites est ramenée entre le minimum et le maximum du bloc ; elle est ensuite ramenée au nombre de colonnes au moment du placement.
- Un JSON sans `sizes` donne les tailles par défaut.
- Les mêmes tailles servent en paysage et en portrait.

### 7.5 Tests

Placement avec tailles (11, 7 et 2 colonnes, avec et sans touches média), trous comblés, tailles ramenées aux colonnes, pas de redimensionnement dans le minimum et le maximum, aller-retour du JSON, JSON ancien et tolérance, déplacement en fin d'ordre.

## 8. Révision 2 (2026-10-20, après essai réel) : six lignes fixes, commandes dans l'en-tête, redimensionnement libre, placement libre

Cette section remplace ce qui contredit le §7 (tailles maximales, ligne vide supplémentaire, barre d'édition au-dessus de la grille) et le §3 (placement par ordre).

### 8.1 Grille fixe de 6 lignes

- La zone de la grille va **de la ligne d'en-tête (pastilles) jusqu'à la barre contextuelle** ; elle est rognée à cette zone et ne passe jamais sous les pastilles.
- Le **côté d'une cellule carrée** vient de la hauteur : `côté = ⌊(hauteur − 5 × écart) ÷ 6⌋`, avec un écart de 8 dp. La grille fait toujours **6 lignes** et remplit la hauteur.
- Le **nombre de colonnes** vient de la largeur : `max(2, ⌊(largeur + écart) ÷ (côté + écart)⌋)`. La grille est centrée.
- Sur la tablette en paysage (zone d'environ 1408 × 740 dp), le côté est de 116 dp et la grille a 11 colonnes. La ligne vide supplémentaire du §7.3 disparaît.
- Si des blocs ne tiennent pas dans les 6 lignes, ils sont placés en dessous et la grille défile.

### 8.2 Commandes de l'édition dans l'en-tête

- La barre au-dessus de la grille est supprimée : entrer ou sortir de l'édition ne décale rien.
- Pendant l'édition, **« Terminé »** puis, s'il y a des blocs masqués, **« + Ajouter »** prennent la place des pastilles de l'en-tête, à gauche, dans la même rangée. « + Ajouter » ouvre la liste des blocs masqués dans une fenêtre flottante sous le bouton.

### 8.3 Tailles libres

Plus aucun maximum : un bloc peut avoir n'importe quelle largeur jusqu'au nombre de colonnes, et n'importe quelle hauteur (un plafond de 64 cellules ne sert qu'à protéger contre une valeur enregistrée aberrante).

| Bloc | Défaut | Minimum |
|---|---|---|
| `clock` | 4 × 2 | 2 × 1 |
| `now_playing` | 3 × 2 | 3 × 2 |
| `sound` | 3 × 1 (3 × 2 avec touches média) | 2 × 1 |
| `brightness` | 3 × 1 | 2 × 1 |
| `wifi`, `bluetooth`, `airplane` | 1 × 1 | 1 × 1 |
| `usb` | 3 × 1 | 2 × 1 |

Le minimum du Son ne dépend plus des touches média : **le contenu s'adapte à la taille**.
- **Son** (`SoundContent.mode`) : à 2 × 1, le seul curseur de volume ; à partir de 3 cellules de large, ou de 2 de haut, l'en-tête avec la valeur, le bouton muet et le curseur ; à partir de 3 × 2, si les touches média appartiennent à ce bloc, les touches précédent, lecture et suivant.
- **Clé USB** (`UsbContent.mode`) : à 2 cellules de large, une puce compacte (icône, nom, éjecter) ; à partir de 3, la puce complète (espace libre, ouvrir, éjecter).

### 8.4 Placement libre, sans gravité

- Chaque bloc occupe **les cellules exactes** où l'utilisateur l'a déposé ; les trous entre blocs sont permis. L'ordre ne sert plus qu'à donner la priorité quand il faut trouver une place.
- **Glisser** : le bloc suit le doigt ; les cellules sous son coin supérieur gauche (arrondi à la cellule la plus proche) sont éclairées, **en blanc si l'emplacement est libre** (dans la grille de 6 lignes et sans toucher un autre bloc), **en rouge sinon**. Au lâcher, le bloc se range sur un emplacement libre ; sinon il retourne à sa place.
- **Redimensionner** : la poignée ↘ ne fait grandir le bloc que dans des cellules libres (elle s'arrête aux autres blocs et aux bords de la grille, largeur d'abord puis hauteur) et le réduit jusqu'à son minimum.
- **Résolution des emplacements** (`GridPlanner.place`) :
  1. les blocs qui ont un emplacement enregistré encore valide (dans les colonnes, sans recouvrement) le gardent, dans l'ordre de priorité ;
  2. les autres (nouveaux, revenus, réparés) prennent le premier emplacement libre, en parcourant les lignes puis les colonnes ; sinon le premier emplacement libre pour leur taille minimale ; sinon le premier emplacement sous les 6 lignes.
  Sans aucun emplacement enregistré, c'est l'ancien tassement dense de l'ordre : la disposition par défaut est donc celle d'avant, convertie en emplacements.
- **Retour d'un bloc** (masqué rétabli, clé USB rebranchée, lecture en cours) : il reprend son emplacement enregistré s'il est libre, sinon la règle ci-dessus s'applique.

### 8.5 Enregistrement

`actions_layout` gagne `"pos":{"landscape":{"<id>":[x,y]},"portrait":{…}}` : les emplacements sont enregistrés par orientation, car le nombre de colonnes diffère ; les tailles restent communes.
- Les emplacements de tous les blocs affichés sont enregistrés à chaque action (dépôt, redimensionnement, masquage), pour que rien ne bouge ensuite tout seul ; un bloc masqué ou absent garde le sien.
- Lecture tolérante : id inconnu, orientation inconnue, valeur qui n'est pas deux entiers positifs ou nuls : ignorés. Un emplacement hors grille ou qui en recouvre un autre est déplacé à la résolution, sans perdre les autres. Un JSON sans `pos` (ancienne version) donne la disposition par défaut tirée de l'ordre.
