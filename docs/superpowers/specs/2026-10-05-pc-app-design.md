# Orizon X — Appli PC (design)

Date : 2026-10-05
Statut : validé par l'utilisateur, à implémenter (branche `pc-app`)
Prérequis : phases 1 et 4 fusionnées dans `master` (relais Python + tactile/stylet).

## 1. Objectif et périmètre

**Objectif** : plus aucune commande à taper côté PC. On double-clique sur **Orizon X** (raccourci menu Démarrer ou bureau) : une petite fenêtre s'ouvre, le relais démarre tout seul et attend la tablette.

**Inclus** :
- refonte du relais en moteur pilotable ;
- fenêtre en verre dépoli et icône de zone de notification ;
- réglages mémorisés et option « Lancer avec Windows » ;
- exe autonome (PyInstaller) avec ffmpeg et adb embarqués, et raccourcis ;
- tests.

**Exclus** :
- installeur `.msi`/`.exe` et signature de code (phase 7) ;
- élévation administrateur automatique ;
- réglage des fps et du débit dans l'interface ;
- mise à jour automatique ;
- plusieurs tablettes.

**Critère de réussite** : sur le PC de l'utilisateur, double-clic sur le raccourci, puis branchement de la tablette avec Orizon X ouverte. Le flux et le tactile marchent comme avec `py relay.py --encoder amf`, sans terminal ouvert ni console qui clignote.

## 2. Approche retenue

**Python + PySide6 (Qt 6)** dans le même processus que le relais, empaqueté avec **PyInstaller en mode dossier**.

Écartées :
- **tkinter** : interface datée, pas d'effet verre, zone de notification à écrire à la main via ctypes ;
- **interface C#** pilotant un relais en sous-processus : deux langages et un protocole stdout de plus, alors que la phase 2 (hôte C++) remplacera le cœur de toute façon.

Le relais est isolé derrière une interface de moteur : l'hôte C++ de la phase 2 pourra la remplacer sans toucher à l'interface.

## 3. Architecture

Tout vit dans `host-prototype/`. Les modules existants (`protocol`, `annexb`, `inputstate`, `injector`) ne changent pas.

| Fichier | Rôle |
|---|---|
| `tools.py` (nouveau) | Trouve `ffmpeg.exe` et `adb.exe` ; lance les sous-processus sans console. |
| `engine.py` (nouveau) | `RelayEngine` : la boucle du relais (attente, adb forward, ffmpeg, flux, tactile) dans un thread, avec états, journal, stats et arrêt propre. |
| `relay.py` (réduit) | CLI : analyse les arguments et affiche les événements du moteur. Mêmes options et même comportement qu'aujourd'hui. |
| `app/settings.py` | Réglages JSON dans `%APPDATA%\OrizonX\settings.json`. |
| `app/status.py` | Titres, couleurs et libellés par état, partagés par la fenêtre et l'icône de notification (sans Qt). |
| `app/make_icons.py` | Génère `app/assets/orizonx.png` et `orizonx.ico` depuis le logo. |
| `app/autostart.py` | « Lancer avec Windows » via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valeur `OrizonX`. |
| `app/controller.py` | Pont thread moteur → thread Qt (signaux), démarrer, arrêter, relancer, repli d'encodeur. |
| `app/glass.py` | Effet verre Windows 11 (DWM Acrylic) et repli peint. |
| `app/window.py` | La fenêtre. |
| `app/tray.py` | L'icône de zone de notification et son menu. |
| `app/main.py` | Point d'entrée : instance unique, journal, DPI, assemblage. |
| `orizonx_pc.py` | Script d'entrée de PyInstaller (`from app.main import main`). |
| `build-pc.ps1` (racine) | Build complet de l'exe. |

### 3.1 `tools.py`

- `find_tool(name)` :
  - **ffmpeg** : d'abord `tools/` à côté de l'exe (ou de `orizonx_pc.py` en dev), puis le PATH ;
  - **adb** : d'abord le PATH, puis le SDK Android (`%LOCALAPPDATA%\Android\Sdk\platform-tools`), puis `tools/`. Un adb d'une autre version que celui d'Android Studio provoquerait des arrêts croisés du serveur adb : on préfère celui déjà installé.
  - Lève `ToolMissing(name)` avec un message lisible si rien n'est trouvé.
- `NO_WINDOW` : `subprocess.CREATE_NO_WINDOW` sous Windows, `0` ailleurs. **Tous** les appels `subprocess` du relais le passent en `creationflags`, sinon chaque appel à adb ou ffmpeg ouvre une console dans l'exe graphique.

### 3.2 `engine.py` : `RelayEngine`

Le code de `relay.py` y est déplacé, et ses `print` et `sys.exit` sont remplacés :

```python
class State(Enum):
    STOPPED = "stopped"
    WAITING_DEVICE = "waiting_device"    # adb : pas de tablette, non autorisée, plusieurs…
    WAITING_APP = "waiting_app"          # adb OK, Orizon X pas ouverte
    STREAMING = "streaming"
    ERROR = "error"                      # fatal : le moteur s'est arrêté

@dataclass(frozen=True)
class Config:
    output: str = "auto"                 # "auto" ou un index ddagrab
    encoder: str = "auto"                # "auto" | "amf" | "nvenc"
    fps: int = 60
    bitrate: str = "30M"

@dataclass(frozen=True)
class StreamStats:
    width: int; height: int; fps: int
    latency_avg_ms: float; latency_max_ms: float; dropped: int; rtt_ms: float

class Listener(Protocol):
    def on_state(self, state: State, detail: str) -> None: ...
    def on_log(self, line: str) -> None: ...
    def on_stats(self, stats: StreamStats) -> None: ...

class RelayEngine:
    def __init__(self, config: Config, listener: Listener, *, ffmpeg: str, adb: str): ...
    def start(self) -> None   # lance le thread ; sans effet s'il tourne déjà
    def stop(self) -> None    # bloquant (≤ 3 s) : tue ffmpeg, ferme le socket, lève tous les contacts
```

**Règles :**

- **Rappels** : ils sont appelés depuis les threads du moteur. Le listener ne doit pas bloquer. Le `detail` est une phrase française prête à afficher.
- **Arrêt** : un `threading.Event` est vérifié partout.
  - Les `time.sleep(1)` deviennent `stop_event.wait(1)`.
  - En session, `stop()` ferme le socket et tue ffmpeg : c'est le même chemin que la déconnexion, donc l'injecteur est fermé dans le `finally` existant.
  - Après l'arrêt, le moteur émet `STOPPED`.
- **Erreurs fatales**, qui donnent `ERROR` avec un message lisible puis la fin du thread :
  - aucun écran à la taille de la tablette en mode `auto` (le message liste les écrans) ;
  - protocole incompatible ;
  - premier message inattendu ;
  - aucun encodeur disponible ;
  - une exception inattendue (journalisée avec sa trace).
- **ffmpeg qui s'arrête tout seul** : aujourd'hui `sys.exit`. Ça arrive aussi pour des causes passagères, comme un écran sécurisé UAC ou un changement de résolution qui coupe ddagrab.
  - Le moteur journalise la fin du stderr et reprend la boucle de connexion après 2 s.
  - Au **3ᵉ échec d'affilée** sans vidéo envoyée, il passe en `ERROR`.
  - Une session qui a envoyé au moins une image remet le compteur à zéro.
- **Choix de l'encodeur** (`resolve_encoder`), exécuté avant chaque connexion avec le sondage des écrans :
  - `encoder="auto"` : `probe_encoder(ffmpeg, "nvenc")` puis `"amf"`, et on garde le premier qui marche ;
  - le sondage encode 1 image d'une source `lavfi color` de 256×256 vers `-f null` ; il réussit si ffmpeg retourne 0 ;
  - le résultat est journalisé (« Encodeur : AMF (NVENC indisponible) ») ;
  - un encodeur forcé n'est pas sondé.

  Le sondage étant refait à chaque connexion, un changement secteur/batterie entre deux sessions est pris en compte.
- **Premier état** : dès le lancement du thread, avant les sondages (encodeur et écrans, plusieurs secondes possibles), le moteur émet `WAITING_DEVICE` avec « Préparation de la capture… », pour que l'interface ne reste pas sur `STOPPED`. Les sondages vérifient l'arrêt entre deux exécutions de ffmpeg : `stop()` n'attend pas les sondes restantes.
- **Stats** : chaque message `STATS` de la tablette produit un `on_stats`, avec la taille du flux en cours. Les stats passent uniquement par `on_stats` : la CLI les affiche avec `format_stats`, l'appli les montre mais ne les écrit pas dans le fichier journal (1 ligne/s le remplirait).
- `probe_outputs`, `ffmpeg_command` et `adb_problem` prennent le chemin de l'outil en paramètre au lieu de `"ffmpeg"` / `adb` en dur.
- La DPI awareness est l'affaire de l'appelant :
  - le moteur n'appelle pas `enable_dpi_awareness` ;
  - la CLI l'appelle comme aujourd'hui ;
  - l'appli Qt n'y touche pas, car Qt 6 active déjà PER_MONITOR_AWARE_V2 ;
  - `injector.enable_dpi_awareness` tolère déjà un contexte déjà fixé, ce qu'un test vérifie.

### 3.3 `relay.py` (CLI)

- Garde ses options.
- `--encoder` devient optionnel, avec `auto` par défaut ; `nvenc` et `amf` restent acceptés.
- `main()` :
  1. construit un `Config` ;
  2. crée un listener qui affiche `detail`, les lignes de journal et les stats au format actuel ;
  3. démarre le moteur et attend sa fin ;
  4. sur Ctrl+C, appelle `engine.stop()` et affiche « Arrêt. ».
- Un état `ERROR` termine avec le code 1.
- `--list-outputs` reste inchangé.
- Les tests existants qui importent des fonctions de `relay` les trouvent dans `engine` : les imports sont mis à jour et le comportement testé ne change pas.

### 3.4 `app/settings.py`

- Dataclass `Settings(output="auto", encoder="auto", first_close_hint_shown=False)`, avec `load(path)` et `save(path)`.
- Fichier absent, JSON corrompu ou valeur invalide : on prend les valeurs par défaut pour les champs fautifs, sans planter.
- Écriture atomique : fichier temporaire puis `os.replace`.
- « Lancer avec Windows » n'est **pas** dans ce fichier : la valeur `Run` du registre fait foi (`autostart.is_enabled()` / `enable(exe_path)` / `disable()`).
- La commande enregistrée est `"<exe>" --minimized` ; elle ne vaut que pour l'exe gelé, et l'option est grisée en dev.

### 3.5 `app/controller.py`

- `Controller(QObject)` porte les signaux Qt `state_changed(State, str)`, `log(str)` et `stats(StreamStats)`.
- Il implémente le `Listener` du moteur en réémettant ses rappels : les signaux Qt traversent les threads en file d'attente, donc l'interface n'est jamais touchée hors du thread Qt.
- `start()`, `stop()`, `restart(config)` :
  - `restart` arrête puis relance ;
  - l'arrêt bloquant (≤ 3 s) tourne dans un thread de travail pour ne pas figer la fenêtre.
- **Intention pendant un redémarrage** : le contrôleur retient si l'utilisateur veut le moteur en marche. `start()` et `restart()` la posent, `stop()` et `stop_blocking()` l'effacent. Le thread de `restart` ne relance le nouveau moteur que si elle est toujours posée une fois l'ancien arrêté : un Arrêter ou un Quitter pendant un redémarrage gagne. `stop_blocking()` attend aussi les redémarrages en cours (≤ `STOP_TIMEOUT_S` + 0,5 s), pour que Quitter ne parte jamais avant que l'ancienne session ait levé ses contacts.
- Le moteur est injecté via une fabrique : les tests y mettent un faux moteur.

### 3.6 `app/glass.py`

- `apply_glass(window)` :
  - mode sombre immersif via `DWMWA_USE_IMMERSIVE_DARK_MODE` (20) ;
  - `DwmExtendFrameIntoClientArea` avec des marges de -1 ;
  - `DWMWA_SYSTEMBACKDROP_TYPE` (38) = 3 (Acrylic), avec `WA_TranslucentBackground` ;
  - coins arrondis via `DWMWA_WINDOW_CORNER_PREFERENCE` (33) = 2.
- Retourne `True` si l'Acrylic est actif.
- Sinon (Windows 10, ou appel refusé) : la fenêtre peint elle-même un fond « verre » opaque, avec un dégradé sombre, une bordure claire à 12 % et un rayon de 12 px.

### 3.7 `app/window.py`

- Fenêtre sans cadre Windows (`FramelessWindowHint`), d'environ 340×300, de taille fixe.
- En-tête maison :
  - le logo, « Orizon X » et les boutons réduire et fermer ;
  - un glisser dans l'en-tête déplace la fenêtre (`windowHandle().startSystemMove()`).
- **Statut au centre** : une icône (ronde, colorée selon l'état), un titre et une ligne de détail.

  | État | Titre | Détail |
  |---|---|---|
  | `WAITING_DEVICE` | En attente de la tablette | `detail` du moteur |
  | `WAITING_APP` | Ouvre Orizon X sur la tablette | `detail` |
  | `STREAMING` | Connecté | `2880×1800 · 60 fps · 18 ms` (taille, fps, latence moyenne) mis à jour à chaque stats |
  | `ERROR` | Erreur | `detail` |
  | `STOPPED` | Arrêté | « Clique sur Démarrer » |

- Réglages :
  - **Écran** : `Auto (taille de la tablette)` ou la liste des écrans connus. La liste est remplie par `probe_outputs` dans un thread à chaque affichage de la fenêtre. La rafraîchir pendant que la liste déroulante est ouverte la ferait sauter.
  - **Encodeur** : `Auto`, `AMF (AMD)` ou `NVENC (NVIDIA)`.
  - Changer un réglage l'enregistre et relance le moteur.
- Bouton principal : **Arrêter** (moteur actif), **Démarrer** (`STOPPED`) ou **Réessayer** (`ERROR`).
- La croix cache la fenêtre (le moteur continue). La première fois, une bulle de la zone de notification l'indique, puis `first_close_hint_shown=True`.
- Couleurs : le thème sombre de l'app tablette, avec du texte blanc à 92 % ou 60 % et une couleur d'accent par état (gris, ambre, vert, rouge).

### 3.8 `app/tray.py`

- `QSystemTrayIcon` avec le logo, superposé d'une pastille de couleur selon l'état, les mêmes que l'icône de la fenêtre (`status.COLORS`) : gris arrêté, ambre en attente (tablette ou app), vert connecté, rouge erreur. L'infobulle reprend le titre et le détail.
- Clic gauche : affiche la fenêtre et la met au premier plan.
- Menu du clic droit :
  1. statut (ligne non cliquable) ;
  2. Démarrer/Arrêter ;
  3. Ouvrir la fenêtre ;
  4. Ouvrir le journal ;
  5. Lancer avec Windows (case à cocher) ;
  6. Quitter.
- **Quitter** : l'icône et la fenêtre disparaissent d'abord (sans bulle « tourne toujours »), puis `controller.stop_blocking()` (contacts levés, redémarrages en cours compris), puis `app.quit()`.

### 3.9 `app/main.py`

- **Instance unique** : `QLocalServer` nommé `OrizonX-PC-<utilisateur>`.
  - Un deuxième lancement se connecte, autorise le premier plan (`AllowSetForegroundWindow(ASFW_ANY)`), envoie `show`, puis quitte. Avec `--minimized`, il quitte sans rien envoyer.
  - La première instance affiche alors sa fenêtre. Elle lit dès la connexion ce qui est déjà arrivé (le client se déconnecte aussitôt), puis à chaque `readyRead`.
  - `setSocketOptions(UserAccessOption)` avant `listen` : une instance administrateur reste joignable par un lancement normal du même utilisateur.
  - Si `listen()` échoue, l'erreur va au journal et l'appli quitte avec le code 1.
- **Journal** : `logging` avec un `RotatingFileHandler` vers `%LOCALAPPDATA%\OrizonX\relay.log`, à 1 Mo × 3 fichiers. Toutes les lignes `on_log` et les traces d'exceptions y vont.
- **Outils** : `find_tool` ; s'il en manque un, état `ERROR` avec le message, sans planter.
- **Démarrage** : `--minimized` démarre caché, dans la zone de notification seulement. Dans tous les cas, le moteur démarre tout de suite.
- `QApplication.setQuitOnLastWindowClosed(False)` : seul Quitter ferme l'appli.

## 4. Build et livraison

- `host-prototype/requirements-dev.txt` : `PySide6` et `pyinstaller`, versions épinglées au moment de l'implémentation.
- `build-pc.ps1` (racine du dépôt) :
  1. crée `host-prototype/.venv` si besoin (`py -m venv`) et y installe `requirements-dev.txt` ;
  2. génère `host-prototype/app/assets/orizonx.ico` (16 à 256 px) et `orizonx.png` depuis `extended/1x/icon_orizonx.png`, avec Qt (`QImage`) pour ne pas dépendre de Pillow ;
  3. lance PyInstaller (`--onedir --windowed --name OrizonX --icon ... --add-data app/assets`) ; sortie dans `dist/OrizonX-PC/` ;
  4. copie dans `dist/OrizonX-PC/tools/` :
     - `ffmpeg.exe` (trouvé dans le PATH) et le `LICENSE` de son build ;
     - `adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll` et le `NOTICE.txt` de platform-tools ;
  5. avec `-Shortcuts`, crée `Orizon X.lnk` dans le menu Démarrer de l'utilisateur et sur le bureau, vers `dist/OrizonX-PC/OrizonX.exe`, via `WScript.Shell`.
- `host-prototype/.venv/` va dans `.gitignore` ; `dist/` y est déjà.
- Les icônes générées sont versionnées, pour que l'appli tourne en dev sans build.
- Le README remplace « Lancer le relais » par « Lancer Orizon X sur le PC » (build une fois, puis le raccourci). La commande `py relay.py` reste documentée comme mode debug.
- Le README ajoute aussi une section « Fenêtres administrateur » : le tactile ne les atteint que si Orizon X est lancée en administrateur (clic droit → Exécuter en tant qu'administrateur).

## 5. Erreurs et cas limites

| Cas | Comportement |
|---|---|
| ffmpeg introuvable | `ERROR` : « ffmpeg introuvable. Recompile l'appli (build-pc.ps1) ou installe ffmpeg. » |
| adb introuvable | `ERROR` : « adb introuvable. Recompile l'appli ou installe Android platform-tools. » |
| Pas de tablette, non autorisée | `WAITING_DEVICE` avec le message actuel ; le moteur réessaie chaque seconde. |
| App tablette fermée | `WAITING_APP`. |
| Aucun écran à la taille de la tablette | `ERROR` avec la liste des écrans ; Réessayer relance. |
| NVENC indisponible en Auto | AMF utilisé, ligne de journal. |
| Aucun encodeur | `ERROR` : « Aucun encodeur matériel H.264 (AMF/NVENC) disponible. » |
| ffmpeg meurt en session | Journal, reprise après 2 s ; `ERROR` au 3ᵉ échec d'affilée sans vidéo. |
| Tactile en échec | Comme aujourd'hui : journalisé, la vidéo continue. |
| Quitter en plein flux | Contacts levés, ffmpeg tué, socket fermé ; la tablette affiche « PC déconnecté ». |
| Deuxième lancement | La fenêtre existante passe au premier plan. |
| `settings.json` corrompu | Valeurs par défaut, fichier réécrit au prochain changement. |
| Acrylic indisponible | Fond verre peint, aucune erreur. |

## 6. Tests

Lancement : `py -m unittest discover -s tests` depuis `host-prototype` ; avec `.venv\Scripts\python`, les tests Qt tournent aussi. Ils sont sautés (`skipUnless`) si PySide6 est absent.

- **Existants (68)** : restent verts. Seuls les imports `relay` → `engine` changent.
- **`test_tools.py`** :
  - ordre de recherche de ffmpeg et d'adb, avec des répertoires temporaires et un PATH simulé ;
  - `ToolMissing` ;
  - `NO_WINDOW` sous Windows.
- **`test_engine.py`**, avec de faux sous-processus, un faux adb, des socket pairs et des fabriques injectées :
  - transitions `WAITING_DEVICE` → `WAITING_APP` → `STREAMING` → retour à l'attente quand la tablette se déconnecte ;
  - `stop()` en attente et en session : ffmpeg tué, `close()` de l'injecteur appelé, état `STOPPED`, retour en moins de 3 s ;
  - `ERROR` pour un protocole incompatible et pour l'absence d'écran en mode auto ;
  - ffmpeg qui meurt 3 fois de suite → `ERROR` ; une session avec vidéo remet le compteur à zéro ;
  - `resolve_encoder` : auto → nvenc qui échoue → amf ; aucun → `ERROR` ; encodeur forcé non sondé ;
  - `on_stats` reçoit la taille du flux.
- **`test_settings.py`** : aller-retour, fichier absent, JSON corrompu, valeur invalide, écriture atomique.
- **`test_autostart.py`** : clé de registre de test (`HKCU\Software\OrizonX-test\Run`, injectée), activer, désactiver, lire. Sauté hors Windows.
- **`test_controller.py`** (Qt offscreen, faux moteur) :
  - les rappels venant d'un autre thread arrivent comme signaux dans le thread Qt ;
  - `restart` arrête puis relance avec la nouvelle config ;
  - `stop` ne bloque pas la boucle Qt.
- **`test_cli.py`** : le listener CLI formate les stats comme aujourd'hui ; `--encoder` optionnel ; `ERROR` donne le code de sortie 1.

**Checklist manuelle** (README), sur le PC de l'utilisateur avec l'exe :
- [ ] Double-clic sur le raccourci : fenêtre en verre, aucune console qui clignote, « En attente de la tablette ».
- [ ] Tablette branchée, Orizon X ouverte : « Connecté », stats qui bougent, vidéo et tactile OK.
- [ ] Croix : la fenêtre disparaît, le flux continue, une bulle s'affiche (la première fois seulement).
- [ ] Clic sur l'icône de notification : la fenêtre revient. Deuxième double-clic sur le raccourci : la même fenêtre revient.
- [ ] Câble débranché puis rebranché : retour en attente, puis reconnexion seule.
- [ ] Changement d'encodeur et d'écran : relance, réglages gardés après redémarrage de l'appli.
- [ ] Quitter en plein flux : la tablette affiche « PC déconnecté », aucun contact ne reste posé.
- [ ] Lancer avec Windows coché, puis session rouverte : l'appli démarre dans la zone de notification.
- [ ] Auto sur secteur et sur batterie : l'encodeur choisi est dans le journal.
