# Orizon X — Barre contextuelle : outils des apps créatives (design)

Date : 2026-10-19
Statut : validé par l'utilisateur, à implémenter (branche `creative-bar` depuis `master`)
Prérequis : barre contextuelle (`2026-10-13-context-bar-design.md`), langue de l'appareil (`2026-10-14-i18n-setup-guide-design.md`).

## 1. Objectif

En mode Actions, la barre du bas propose les **vrais outils** d'Illustrator, de Photoshop, de Canva et de Figma. Elle le fait par leurs raccourcis clavier, répartis sur **plusieurs pages** (Outils, Édition, Affichage) qu'on choisit par des onglets ou par un balayage.

**Exclus** :
- l'état de l'app (outil actif, couleurs, curseurs), qui demanderait du scripting Adobe ;
- les icônes Adobe, Canva et Figma (protégées) ;
- l'édition des profils par l'utilisateur.

## 2. Profils (PC, `actions/context_profiles.py`)

- `Profile` gagne `pages: tuple[Page, ...]`, avec `Page(id, labels{en,fr}, buttons)`.
  - Les profils existants ont une seule page `main`, et leurs boutons ne changent pas.
  - `Profile.buttons` reste disponible : c'est la liste de tous les boutons de toutes les pages, pour vérifier `context.press`.
- **Détection** :
  - `Illustrator.exe` → `illustrator` ;
  - `Photoshop.exe` → `photoshop` ;
  - `Canva.exe` → `canva` ;
  - `Figma.exe` → `figma`.
  - Dans un navigateur (les exe du profil `browser`), un titre de fenêtre qui contient `Canva` (sans tenir compte de la casse) donne `canva`, et un titre qui contient `Figma` donne `figma`. Sinon, c'est `browser`.
- **Noms affichés** : Illustrator, Photoshop, Canva, Figma.
- **Pages** : libellés « Tools / Outils », « Edit / Édition », « View / Affichage ». Pour chaque bouton, on donne le libellé anglais, le libellé français, le raccourci et l'icône.

### Illustrator

| Page | Boutons |
|---|---|
| tools | Selection / Sélection `V` select · Direct selection / Sélection directe `A` direct_select · Pen / Plume `P` pen · Type / Texte `T` text · Rectangle / Rectangle `M` rectangle · Ellipse / Ellipse `L` ellipse · Brush / Pinceau `B` brush · Eyedropper / Pipette `I` eyedropper |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Shift+Ctrl+Z` redo · Group / Grouper `Ctrl+G` group · Ungroup / Dissocier `Shift+Ctrl+G` ungroup · Paste in front / Coller devant `Ctrl+F` paste_front · Lock / Verrouiller `Ctrl+2` lock · Unlock all / Tout déverrouiller `Ctrl+Alt+2` unlock · Save / Enregistrer `Ctrl+S` save |
| view | Hand / Main `H` hand · Zoom / Zoom `Z` search · Fit / Ajuster `Ctrl+0` zoom_fit · 100 % / 100 % `Ctrl+1` zoom_100 · Zoom − / Zoom − `Ctrl+-` zoom_out · Zoom + / Zoom + `Ctrl+=` zoom_in · Outline / Tracés `Ctrl+Y` outline · Rulers / Règles `Ctrl+R` rulers |

### Photoshop

| Page | Boutons |
|---|---|
| tools | Move / Déplacement `V` move · Marquee / Rectangle de sélection `M` marquee · Lasso / Lasso `L` lasso · Brush / Pinceau `B` brush · Eraser / Gomme `E` eraser · Crop / Recadrage `C` crop · Type / Texte `T` text · Eyedropper / Pipette `I` eyedropper |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Shift+Ctrl+Z` redo · Deselect / Désélectionner `Ctrl+D` deselect · Transform / Transformer `Ctrl+T` transform · New layer / Nouveau calque `Shift+Ctrl+N` layer_new · Duplicate layer / Dupliquer le calque `Ctrl+J` layer_duplicate · Merge down / Fusionner `Ctrl+E` merge · Save / Enregistrer `Ctrl+S` save |
| view | Hand / Main `H` hand · Zoom / Zoom `Z` search · Fit / Ajuster `Ctrl+0` zoom_fit · 100 % / 100 % `Ctrl+1` zoom_100 · Zoom − / Zoom − `Ctrl+-` zoom_out · Zoom + / Zoom + `Ctrl+=` zoom_in · Brush − / Pinceau − `OEM_4` brush_smaller · Brush + / Pinceau + `OEM_6` brush_larger |

### Canva

| Page | Boutons |
|---|---|
| tools | Text / Texte `T` text · Rectangle / Rectangle `R` rectangle · Circle / Cercle `C` ellipse · Line / Ligne `L` line |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Ctrl+Y` redo · Duplicate / Dupliquer `Ctrl+D` copy · Group / Grouper `Ctrl+G` group · Ungroup / Dissocier `Ctrl+Shift+G` ungroup · Lock / Verrouiller `Alt+Shift+L` lock |
| view | Zoom − / Zoom − `Ctrl+-` zoom_out · Zoom + / Zoom + `Ctrl+=` zoom_in · Fit / Ajuster `Ctrl+Alt+0` zoom_fit · Present / Présenter `Ctrl+Alt+P` present |

### Figma

| Page | Boutons |
|---|---|
| tools | Move / Déplacer `V` move · Frame / Cadre `F` frame · Rectangle / Rectangle `R` rectangle · Ellipse / Ellipse `O` ellipse · Line / Ligne `L` line · Pen / Plume `P` pen · Text / Texte `T` text · Comment / Commentaire `C` comment |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Ctrl+Shift+Z` redo · Duplicate / Dupliquer `Ctrl+D` copy · Group / Grouper `Ctrl+G` group · Ungroup / Dissocier `Ctrl+Shift+G` ungroup · Component / Composant `Ctrl+Alt+K` component · Hide / Masquer `Ctrl+Shift+H` hide |
| view | Zoom − / Zoom − `-` zoom_out · Zoom + / Zoom + `=` zoom_in · Fit / Ajuster `Shift+1` zoom_fit · Selection / Sélection `Shift+2` zoom_selection · 100 % / 100 % `Shift+0` zoom_100 · Rulers / Règles `Shift+R` rulers · Outline / Contours `Ctrl+Y` outline |

**Disposition clavier** :
- `OEM_4` et `OEM_6` sont les touches `[` et `]` du clavier US, envoyées par position comme pour VS Code (voir `actions/keys.py`).
- `Shift+0/1/2` sont des touches de la rangée des chiffres, envoyées par code virtuel (`0`, `1`, `2`), donc indépendantes de AZERTY.
- L'essai réel sur le PC de l'utilisateur valide ou corrige ces raccourcis. Un raccourci qui ne marche pas est retiré ou remplacé, et la spec est mise à jour.

## 3. Protocole

La version reste 1.

`context` gagne `pages` :
```json
"context":{"available":true,"app":"Illustrator","profile":"illustrator",
           "buttons":[…boutons de la page 1…],
           "pages":[{"id":"tools","label":"Outils","buttons":[{"id","icon","label"}…]}, …]}
```
- Au plus 4 pages, de 8 boutons chacune.
- `buttons` vaut la page 1 : une ancienne app continue de marcher avec la première page.
- `pages` est toujours envoyé, même pour un profil d'une seule page.
- `context.press` ne change pas. Les `id` sont uniques dans un profil, et le PC vérifie que le bouton appartient à l'une des pages du profil actif.

## 4. Appareil (Android)

- **Lecture** : `ContextBar` gagne `pages: List<ContextPage(id, label, buttons)>`.
  - Si `pages` est absent ou vide, une seule page faite de `buttons`.
  - Au plus 4 pages et 8 boutons par page ; les pages vides sont ignorées.
- **Barre** :
  - Avec plus d'une page, des **onglets** compacts (pastilles, 12 sp) apparaissent après le nom de l'app, et les boutons de la page choisie suivent.
  - Un **balayage horizontal** sur la zone des boutons passe à la page voisine.
  - Changer de page donne un retour haptique et un fondu d'environ 150 ms.
  - Avec une seule page, la barre est inchangée.
  - En portrait, les onglets passent au-dessus des boutons s'ils ne tiennent pas sur la ligne.
- **Mémoire de la page** : une table `profil → id de page`, gardée en mémoire pour la session. En revenant à une app, on retrouve sa page. Un id de page inconnu donne la page 1.
- **Icônes** : de nouveaux VectorDrawables `ctx_<nom>` (chemins Material Icons, Apache-2.0, mention dans chaque fichier). Ils sont ajoutés à `ContextIcons.NAMES` et au mapping, et le PC les ajoute à `ICON_NAMES`.
  - outils : `select`, `direct_select`, `pen`, `text`, `rectangle`, `ellipse`, `line`, `brush`, `eraser`, `eyedropper`, `crop`, `lasso`, `marquee`, `move`, `frame`, `comment` ;
  - objets : `group`, `ungroup`, `lock`, `unlock`, `layer_new`, `layer_duplicate`, `merge`, `deselect`, `transform`, `component`, `hide`, `paste_front` ;
  - affichage : `hand`, `zoom_fit`, `zoom_100`, `zoom_selection`, `outline`, `rulers`, `brush_smaller`, `brush_larger`, `present`.

  Les noms qui existent déjà (`undo`, `redo`, `save`, `copy`, `zoom_in`, `zoom_out`, `search`) sont réutilisés.

## 5. Tests

- **PC** :
  - chaque page de chaque profil : 1 à 8 boutons, `id` uniques dans le profil, icônes dans `ICON_NAMES`, libellés `en` et `fr` non vides, raccourcis analysables par `actions.keys` (avec un faux `SendInput`) ;
  - au plus 4 pages ;
  - détection par l'exe, sans tenir compte de la casse ;
  - détection par le titre dans un navigateur (Canva, Figma, sinon `browser`), et un titre « Canva » ignoré hors navigateur ;
  - `snapshot()` envoie `pages` et `buttons` égal à la page 1, dans les deux langues ;
  - `context.press` accepte un bouton de la page 3 ;
  - les profils existants ont une page `main` identique à leurs boutons d'avant.
- **Android** :
  - lecture de `pages` (absent, vide, plus de 4 pages, page vide, plus de 8 boutons) ;
  - mémoire de la page (retour au profil, id inconnu) ;
  - toutes les nouvelles icônes associées, `ctx_unknown` pour un nom inconnu.
- **Réel**, avec l'utilisateur :
  - chaque app installée, chaque page, chaque bouton ;
  - les raccourcis sensibles à AZERTY (`[ ]`, `Ctrl+=`, `Shift+1`) ;
  - Canva et Figma dans le navigateur.

## 6. Ajout : autres apps Adobe (validé le 2026-10-19)

Détection par l'exe (sans tenir compte de la casse) : `Adobe Premiere Pro.exe` → `premiere`, `AfterFX.exe` → `aftereffects`, `InDesign.exe` → `indesign`, `Lightroom.exe` → `lightroom` (Lightroom Classic). Noms affichés : Premiere Pro, After Effects, InDesign, Lightroom. Media Encoder est exclu (presque aucun raccourci utile). Ids de boutons préfixés `pr.`, `ae.`, `id.`, `lr.`. Libellés de pages : Tools/Outils, Edit/Édition, et la 3e page selon l'app (Playback/Lecture, Timeline/Montage, View/Affichage) ; Lightroom : Navigate/Navigation, Rate/Notes, Edit/Édition.

### Premiere Pro

| Page | Boutons (libellé en / fr, raccourci, icône) |
|---|---|
| tools | Selection / Sélection `V` select · Track select / Sélection de piste `A` track_select · Ripple edit / Modification par propagation `B` ripple_edit · Razor / Cutter `C` razor · Slip / Déplacement `Y` slip · Pen / Plume `P` pen · Hand / Main `H` hand · Type / Texte `T` text |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Ctrl+Shift+Z` redo · Add edit / Ajouter un montage `Ctrl+K` add_edit · Ripple delete / Supprimer et raccorder `Shift+Delete` ripple_delete · Mark in / Point d'entrée `I` mark_in · Mark out / Point de sortie `O` mark_out · Export / Exporter `Ctrl+M` export · Save / Enregistrer `Ctrl+S` save |
| playback | Play/Pause / Lecture/Pause `Space` play_pause · Previous frame / Image précédente `Left` frame_prev · Next frame / Image suivante `Right` frame_next · Previous edit / Montage précédent `Up` edit_prev · Next edit / Montage suivant `Down` edit_next · Zoom out / Zoom − `-` zoom_out · Zoom in / Zoom + `=` zoom_in · Fit timeline / Ajuster la séquence `OEM_5` timeline_fit |

### After Effects

| Page | Boutons |
|---|---|
| tools | Selection / Sélection `V` select · Hand / Main `H` hand · Zoom / Zoom `Z` search · Rotation / Rotation `W` rotate · Anchor point / Point d'ancrage `Y` anchor · Pen / Plume `G` pen · Shape / Forme `Q` rectangle · Type / Texte `Ctrl+T` text |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Ctrl+Shift+Z` redo · Duplicate / Dupliquer `Ctrl+D` copy · Split layer / Scinder le calque `Ctrl+Shift+D` split_layer · Precompose / Précomposer `Ctrl+Shift+C` precompose · New solid / Nouvel solide `Ctrl+Y` solid · Keyframes / Images clés `U` keyframes · Save / Enregistrer `Ctrl+S` save |
| timeline | Play / Lecture `Space` play_pause · Previous frame / Image précédente `PageUp` frame_prev · Next frame / Image suivante `PageDown` frame_next · Start / Début `Home` go_start · End / Fin `End` go_end · Previous keyframe / Image clé précédente `J` keyframe_prev · Next keyframe / Image clé suivante `K` keyframe_next · Render queue / File de rendu `Ctrl+M` render |

### InDesign

| Page | Boutons |
|---|---|
| tools | Selection / Sélection `V` select · Direct selection / Sélection directe `A` direct_select · Type / Texte `T` text · Rectangle frame / Bloc rectangulaire `F` rect_frame · Rectangle / Rectangle `M` rectangle · Ellipse / Ellipse `L` ellipse · Pen / Plume `P` pen · Hand / Main `H` hand |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Shift+Ctrl+Z` redo · Group / Grouper `Ctrl+G` group · Ungroup / Dissocier `Shift+Ctrl+G` ungroup · Place / Importer `Ctrl+D` place · Duplicate / Dupliquer `Alt+Shift+Ctrl+D` copy · Lock / Verrouiller `Ctrl+L` lock · Save / Enregistrer `Ctrl+S` save |
| view | Zoom / Zoom `Z` search · Fit page / Ajuster la page `Ctrl+0` zoom_fit · 100 % / 100 % `Ctrl+1` zoom_100 · Zoom − / Zoom − `Ctrl+-` zoom_out · Zoom + / Zoom + `Ctrl+=` zoom_in · Preview / Aperçu `W` preview · Rulers / Règles `Ctrl+R` rulers · Export / Exporter `Ctrl+E` export |

### Lightroom Classic

| Page | Boutons |
|---|---|
| navigate | Grid / Grille `G` grid · Loupe / Loupe `E` loupe · Develop / Développement `D` develop · Compare / Comparaison `C` compare · Crop / Recadrage `R` crop · Spot removal / Retouche `Q` spot · Previous / Précédente `Left` arrow_left · Next / Suivante `Right` arrow_right |
| rate | Pick / Retenir `P` pick · Reject / Rejeter `X` reject · Unflag / Sans marque `U` unflag · 1 ★ / 1 ★ `1` star · 2 ★ / 2 ★ `2` star · 3 ★ / 3 ★ `3` star · 4 ★ / 4 ★ `4` star · 5 ★ / 5 ★ `5` star |
| edit | Undo / Annuler `Ctrl+Z` undo · Redo / Rétablir `Ctrl+Y` redo · Auto / Auto `Ctrl+U` auto · Copy settings / Copier les réglages `Ctrl+Shift+C` copy_settings · Paste settings / Coller les réglages `Ctrl+Shift+V` paste_settings · Before/After / Avant/Après `Y` before_after · Export / Exporter `Ctrl+Shift+E` export · Fullscreen / Plein écran `F` fullscreen |

Les chiffres `1`…`5` de Lightroom sont envoyés par code virtuel de la rangée des chiffres (`0x31`…`0x35`), comme `Shift+1` de Figma. `OEM_5` est la touche `\` du clavier US, envoyée par position. L'essai réel valide `OEM_5`, `Shift+Delete` et les chiffres.

**Nouvelles icônes** (`ctx_<nom>`, chemins Material Icons, Apache-2.0) : `track_select`, `ripple_edit`, `razor`, `slip`, `add_edit`, `ripple_delete`, `mark_in`, `mark_out`, `export`, `frame_prev`, `frame_next`, `edit_prev`, `edit_next`, `timeline_fit`, `rotate`, `anchor`, `split_layer`, `precompose`, `solid`, `keyframes`, `go_start`, `go_end`, `keyframe_prev`, `keyframe_next`, `render`, `rect_frame`, `place`, `preview`, `grid`, `loupe`, `develop`, `compare`, `spot`, `pick`, `reject`, `unflag`, `star`, `auto`, `copy_settings`, `paste_settings`, `before_after`, `fullscreen`.
