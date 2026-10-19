# Orizon X — Icône de l'app ou du site dans la barre contextuelle (design)

Date : 2026-10-19
Statut : validé par l'utilisateur, à implémenter (branche `app-icon` depuis `master` après la 0.8.0)
Prérequis : barre contextuelle avec pages et détection par URL (`2026-10-19-creative-bar-design.md`).

## 1. Objectif

Dans la barre du bas du mode Actions, l'**icône de l'app ou du site** au premier plan s'affiche au-dessus de son nom.

**Exclus** :
- favicons de tous les sites pour le profil navigateur générique : ce profil garde l'icône du navigateur ;
- icônes livrées avec Orizon X (aucune marque embarquée).

## 2. Source de l'icône (PC, `actions/app_icons.py`)

- **App native** :
  - l'icône de l'exe au premier plan, telle que Windows l'affiche ;
  - `ForegroundApp` gagne `path` (chemin complet de l'exe, déjà lu par `QueryFullProcessImageNameW`), `compare=False` comme `hwnd` ;
  - extraction par `SHDefExtractIconW(path, 0, 0, &hicon, NULL, 256)`, puis, en repli, `ExtractIconExW` (grande icône) ;
  - conversion avec `QImage.fromHICON` (Qt importé à la demande, jamais à l'import du module), mise à 96 × 96 px, PNG ;
  - `DestroyIcon` dans tous les cas.
- **Site** : seulement pour les profils reconnus par l'URL, `canva` et `figma` aujourd'hui, et ceux qui suivront.
  - le PC télécharge `https://<hôte>/favicon.ico`, puis, en cas d'échec, `https://<hôte>/apple-touch-icon.png` ;
  - délai de 3 s, 512 Kio au plus, HTTPS uniquement, sans cookie et avec un User-Agent neutre ;
  - l'image est décodée avec `QImage` (qui sait lire ICO et PNG), puis convertie en PNG 96 × 96 ;
  - la requête ne part que vers le site déjà ouvert par l'utilisateur ;
  - en cas d'échec, c'est l'icône du navigateur (son exe) qui s'affiche.
- **Cache** :
  - en mémoire, par chemin d'exe ou par hôte ;
  - les favicons sont aussi gardés sur disque dans `%LOCALAPPDATA%\OrizonX\icons\<hôte>.png`, avec 7 jours de validité ;
  - un échec est mémorisé 10 minutes, pour ne pas retenter à chaque cycle.
- **Fil d'exécution** :
  - l'extraction et le téléchargement se font dans un thread dédié ;
  - le hub n'attend jamais : tant que l'icône n'est pas prête, `icon` vaut `null`, puis l'état suivant porte l'id.
- **Identifiant** : sha1 hexadécimal du PNG, comme `now_playing.artwork`.

## 3. Protocole

La version reste 1.

- **`context.icon`** : `"<sha1>"` ou `null`.
- **Image** : envoyée par `MEDIA_ARTWORK` (0x05), comme une pochette.
  - L'image est envoyée chaque fois que `context.icon` change, vers un id non nul différent de celui du dernier état diffusé (revenir à une app déjà vue renvoie donc son icône). La tablette ne garde que 16 images, partagées avec les pochettes : une icône envoyée « une fois par session » pourrait être évincée et ne plus revenir. Les icônes sont petites (PNG 96 px). Le comportement des pochettes ne change pas.
  - Généralisation dans le hub : `artwork_bytes(id)` est demandé au fournisseur qui a produit l'id (`now_playing` ou `context`).
- `protocol/PROTOCOL.md` documente `context.icon` et le fait que `MEDIA_ARTWORK` sert aussi aux icônes.

## 4. Appareil (Android)

- **Cache d'images** : la dernière pochette (`artwork`) est remplacée par une table id → `ImageBitmap`, LRU de 16 entrées.
  - Le décodage reste en arrière-plan.
  - La pochette en cours et l'icône de la barre lisent la table par leur id.
- **`ContextBar`** gagne `icon: String?`.
- **Barre** : à gauche, une colonne centrée avec l'icône (28 dp, coins arrondis de 6 dp) au-dessus du nom de l'app.
  - Sans icône (id nul, ou image pas encore reçue), le nom seul s'affiche, comme aujourd'hui.
  - L'icône est en couleurs, sans teinte.

## 5. Tests

- **PC** :
  - extraction avec une fausse couche Win32 : succès, repli, échec, `DestroyIcon` toujours appelé ;
  - favicon avec un faux téléchargement : ICO, repli PNG, délai dépassé, trop gros, non-HTTPS refusé ;
  - cache : mémoire, disque avec validité, échec mémorisé ;
  - choix de la source (app native, profil de site, navigateur générique) ;
  - `context.icon` nul puis l'id ;
  - le hub envoie l'image chaque fois que `context.icon` change (retour à une app déjà vue compris) et demande `artwork_bytes` au bon fournisseur ;
  - une conversion réelle, en lecture seule, de l'icône d'un exe Windows (`notepad.exe`) en PNG.
- **Android** :
  - LRU (ajout, éviction, lecture) ;
  - lecture de `context.icon` ;
  - la pochette marche toujours.
- **Réel** : Illustrator, Spotify, VS Code, Chrome (icône de Chrome), Canva dans Chrome (favicon de Canva).
