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
