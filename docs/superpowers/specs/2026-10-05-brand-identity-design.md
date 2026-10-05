# Orizon X — Identité visuelle (logo + police du titre) (design)

Date : 2026-10-05
Statut : validé par l'utilisateur, à implémenter (branche `pc-app`)

## 1. Objectif

L'écran d'attente de la tablette et la fenêtre PC portent l'identité du logo : le **logo** (`extended/SVG/icon_app.svg`) et le titre **« Orizon X » en police MAZAGLA** (`extended/Maglaza-Regular.otf`, famille `MAZAGLA`).

**Exclus** : les icônes de l'exe, de la zone de notification et du lanceur Android (carré noir actuel inchangé), et le HUD pendant le flux.

**Licence** : la police est fournie par l'utilisateur, qui en a les droits d'intégration. Le fichier ne contient aucune mention de licence.

## 2. Règles communes

- **Logo** : vectoriel, blanc, sans le carré noir.
  - Le SVG contient le X central et deux « pilules » latérales, en noir par défaut.
  - Il est recoloré en blanc (`#FFFFFF`) dans les copies embarquées.
- **Police** : MAZAGLA sert **uniquement au titre « Orizon X »**. Tout le reste garde la police système.

## 3. Tablette (Android, Compose)

- **Logo** : `android/app/src/main/res/drawable/ic_orizonx_logo.xml`, un VectorDrawable avec `viewportWidth`/`Height` à 1024 et les trois tracés du SVG copiés tels quels (`pathData`), en `fillColor="#FFFFFFFF"`.
- **Police** : `android/app/src/main/res/font/mazagla.otf` (nom de ressource en minuscules). Dans `ui/Glass.kt`, `val BrandFont = FontFamily(Font(R.font.mazagla))`.
- **`WaitingScreen`** : la carte en verre est centrée et son contenu centré horizontalement. De haut en bas :
  1. le logo à 96 dp (`Image(painterResource(R.drawable.ic_orizonx_logo))`) ;
  2. « Orizon X » en `BrandFont`, 44 sp, blanc ;
  3. 20 dp d'espace ;
  4. le statut « En attente du PC… » avec le point qui pulse ; le motif d'erreur éventuel en ambre dessous ;
  5. « Lance Orizon X sur le PC. », qui remplace la boîte de commande `py relay.py --encoder amf` ;
  6. « Appui long à 4 doigts : infos de connexion » ;
  7. le pied de carte : résolution · `127.0.0.1:port` · `protocole v1`. La version du protocole quitte l'en-tête et rejoint ce pied.
- Le fond animé (blobs) ne change pas.

## 4. PC (PySide6)

- **Ressources** :
  - `host-prototype/app/assets/logo.svg`, la copie du SVG avec `fill="#FFFFFF"` sur les tracés ;
  - `host-prototype/app/assets/mazagla.otf`.
- **`app/brand.py`** (nouveau, Qt) :
  - `load_brand_font() -> str` : charge la police via `QFontDatabase.addApplicationFont` une seule fois et retourne la famille. Si le chargement échoue, retourne la famille système par défaut et journalise un avertissement ; l'appli ne plante pas.
  - `logo_pixmap(size_px: int, device_pixel_ratio: float) -> QPixmap` : rend le SVG via `QSvgRenderer`, net sur les écrans à 200 %.
- **`MainWindow`** :
  - La barre du haut ne garde que la zone de déplacement et les boutons « — » et « ✕ ». Le logo 18 px et le libellé « Orizon X » en sont retirés.
  - Bloc central, centré :
    - le logo à 44 px ;
    - « Orizon X » en MAZAGLA, 26 px ;
    - puis une ligne de statut : un petit point coloré de 10 px, suivi du titre d'état (« Connecté »…) en 16 px, gras ;
    - puis la ligne de détail.
  - `StatusDot` est réduit à un point de 10 px, sans halo.
  - La hauteur de la fenêtre passe à 380 px. La largeur reste 360 px.
  - Le constructeur `MainWindow(logo)` garde sa signature. Le pixmap passé sert à l'icône de fenêtre ; le logo du bloc central vient de `brand.logo_pixmap`.
- **Packaging** : `--add-data app/assets` couvre déjà les nouveaux fichiers. Il faut vérifier que PyInstaller embarque le module QtSvg (`PySide6.QtSvg` est importé par `brand.py`, donc détecté).

## 5. Tests et vérifications

- **PC** :
  - `tests/test_brand.py` (Qt offscreen) : la police chargée a pour famille `MAZAGLA` ; `logo_pixmap(44, 2.0)` n'est pas nul et fait 88×88 pixels physiques ; le logo a des pixels blancs opaques au centre et des coins transparents.
  - `tests/test_window.py` : le titre de marque est affiché avec la famille MAZAGLA, et il n'y a plus de libellé « Orizon X » dans la barre du haut.
  - Puis une capture de la fenêtre lancée depuis les sources, sans adb (même procédure de sécurité que pour la tâche 10 de l'appli PC), vérifiée à l'œil.
  - Puis rebuild de l'exe.
- **Android** : `:app:testDebugUnitTest :app:assembleDebug` au vert, puis installation sur la tablette. L'installation coupe un flux en cours : l'utilisateur est prévenu avant.
