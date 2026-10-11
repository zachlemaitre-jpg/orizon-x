# Orizon X — Mode « Actions » (barre tactile) (design)

Date : 2026-10-11
Statut : validé par l'utilisateur, à implémenter (branche `pc-app`)
Prérequis : appli PC avec moteur (`2026-10-05-pc-app-design.md`), écran virtuel (`2026-10-05-installer-virtual-display-design.md`).

## 0. Contexte : étape 1 sur 3

1. **Ce document** : mode Actions avec **un appareil à la fois**. Téléphone ou tablette.
2. Plusieurs appareils en même temps (un en écran, les autres en Actions), avec la liste et le changement de rôle dans la fenêtre PC.
3. Barre contextuelle selon l'app au premier plan sur le PC.

## 1. Objectif

L'appareil branché (téléphone ou tablette) choisit son rôle :
- **Screen** : le comportement actuel, écran étendu ;
- **Actions** : **uniquement des boutons natifs** (aucune vidéo, aucun écran virtuel) pour piloter le PC.

Contrôles :
- heure et date du PC en grand ;
- batterie du PC ;
- son : volume et muet ;
- médias : lecture/pause, précédent, suivant ;
- luminosité ;
- Wi-Fi, Bluetooth, mode avion ;
- clés USB : ouvrir, éjecter.

**Exclus** :
- plusieurs appareils à la fois (étape 2) ;
- la barre contextuelle (étape 3) ;
- la traduction de l'app Android (sous-projet « guides ») : ses textes restent en français pour l'instant.

## 2. Protocole

Les ajouts sont **rétrocompatibles** : un ancien PC ignore les types inconnus, et la version reste 1. Les payloads sont en **JSON UTF-8**, au maximum 64 Kio, et un JSON invalide est rejeté comme `ProtocolError`.

| Type | Sens | Nom | Payload |
|---|---|---|---|
| 0x86 | appareil → PC | `DEVICE_INFO` | `{"role":"screen"|"actions","kind":"phone"|"tablet","name":"<modèle>","app":"<version>"}` |
| 0x04 | PC → appareil | `ACTIONS_STATE` | l'état complet (§2.1) |
| 0x87 | appareil → PC | `ACTION` | `{"id":"<action>", …}` (§2.2) |

**Séquence** : l'appareil envoie `HELLO`, puis **immédiatement** `DEVICE_INFO`.
- Le PC attend `DEVICE_INFO` au plus 1 s après le HELLO. Sans réponse (ancienne app), le rôle vaut `screen`.
- En rôle `actions`, le PC envoie un `ACTIONS_STATE` complet, puis un nouveau à **chaque changement** (diffusion de l'état complet, pas de diff) et au moins toutes les 30 s.
- PING/PONG ne change pas.
- **Changer de rôle** : l'appareil ferme la connexion et se reconnecte avec le nouveau `DEVICE_INFO`.

### 2.1 `ACTIONS_STATE`

```json
{"v":1,
 "clock":{"epoch_ms":1760185920000,"utc_offset_min":120},
 "battery":{"available":true,"percent":76,"charging":true},
 "audio":{"available":true,"volume":0.42,"muted":false},
 "media":{"available":true},
 "brightness":{"available":true,"value":0.70},
 "wifi":{"available":true,"on":true,"ssid":"Maison"},
 "bluetooth":{"available":true,"on":true,"connected":["Casque"]},
 "airplane":{"available":true,"on":false},
 "usb":[{"drive":"E:","label":"KINGSTON","free_bytes":12884901888,"total_bytes":31914983424}],
 "notice":{"code":"usb_busy","drive":"E:"}}
```

- `available: false` fait disparaître la tuile côté appareil.
- `notice` est facultatif et n'est envoyé qu'**une fois** : c'est un message ponctuel. Codes possibles : `usb_busy`, `usb_failed`, `radio_denied`, `action_failed`.

### 2.2 `ACTION`

| `id` | Champs | Effet |
|---|---|---|
| `volume.set` | `value` 0..1 | volume de la sortie par défaut |
| `volume.mute` | `value` bool | muet |
| `media.play_pause`, `media.next`, `media.previous` | — | touche multimédia |
| `brightness.set` | `value` 0..1 | luminosité |
| `wifi.set`, `bluetooth.set` | `value` bool | radio on/off |
| `airplane.set` | `value` bool | toutes les radios off, avec mémorisation de leur état ; on restaure cet état à la sortie du mode avion |
| `usb.open` | `drive` | ouvre la clé dans l'Explorateur |
| `usb.eject` | `drive` | éjection propre |

- Un `id` inconnu est journalisé et ignoré.
- Les curseurs envoient **au plus 20 `ACTION` par seconde** côté appareil, et toujours la valeur finale au relâchement.

## 3. PC

**Nouveau paquet `host-prototype/actions/`**, un fournisseur par famille. Chaque fournisseur expose :

```python
class Provider(Protocol):
    def snapshot(self) -> dict          # sa partie de l'état ; {"available": False} si absent
    def handle(self, action: dict) -> str | None   # None si OK, sinon un code notice
```

| Fournisseur | Implémentation |
|---|---|
| `clock` | `time.time()`, décalage UTC local |
| `battery` | `GetSystemPowerStatus` (ctypes). Indisponible si `BatteryFlag` vaut 128 (pas de batterie) |
| `audio` | `pycaw` : `IAudioEndpointVolume` de la sortie par défaut, rééchantillonnée à chaque lecture pour suivre le changement de périphérique |
| `media` | `SendInput` avec `VK_MEDIA_PLAY_PAUSE` / `NEXT_TRACK` / `PREV_TRACK` (ctypes) |
| `brightness` | WMI `root\wmi` `WmiMonitorBrightness` / `WmiMonitorBrightnessMethods.WmiSetBrightness` via `comtypes`. Repli DDC/CI (`dxva2`, VCP 0x10) pour les écrans externes. Indisponible si aucun des deux ne répond |
| `radios` | WinRT `Windows.Devices.Radios` (paquets `winrt-*`) : radios Wi-Fi et Bluetooth, `SetStateAsync`. Mode avion = toutes les radios. Statut ≠ Allowed → `radio_denied` |
| `wifi_info` | `wlanapi.dll` (`WlanOpenHandle`, `WlanEnumInterfaces`, `WlanQueryInterface` `wlan_intf_opcode_current_connection`) pour le SSID |
| `bt_info` | WinRT `Windows.Devices.Enumeration` : appareils Bluetooth et BLE connectés (propriété `System.Devices.Aep.IsConnected`) |
| `usb` | `GetLogicalDrives` + type de bus USB (`IOCTL_STORAGE_QUERY_PROPERTY`), libellé et espace (`GetVolumeInformationW`, `GetDiskFreeSpaceExW`). Ouverture : `os.startfile`. Éjection : `CM_Request_Device_EjectW` sur le disque parent (cfgmgr32), avec `PNP_VetoType` pour détecter une clé occupée → `usb_busy` |

**`actions/hub.py` (`ActionsHub`)** :
- un thread qui interroge les fournisseurs toutes les **250 ms** pour l'audio et toutes les **1 s** pour le reste ;
- il construit l'état complet, compare avec le dernier envoyé, et envoie un `ACTIONS_STATE` s'il diffère ou si 30 s se sont écoulées ;
- `handle(action)` passe l'action au bon fournisseur, puis force un relevé immédiat de l'état ;
- les erreurs d'un fournisseur sont journalisées une fois, et ce fournisseur passe en `available: false` sans arrêter le hub.

**Moteur** :
- après le HELLO, il lit `DEVICE_INFO` (au plus 1 s) ;
- en rôle `actions`, il lance une **session Actions** : lecteur de messages (PING/PONG, ACTION) et `ActionsHub`. Pas d'écran virtuel, ni ffmpeg, ni injecteur ;
- un nouvel état `State.ACTIONS`, avec le détail « Actions device connected: {name} » (en/fr), se range parmi les états actifs ;
- à la fin de la session : arrêt du hub, puis retour à l'attente comme aujourd'hui.

**Dépendances** : `pycaw` (MIT, entraîne `comtypes` et `psutil`) et `winrt-runtime` + `winrt-Windows.Devices.Radios` + `winrt-Windows.Devices.Enumeration` + `winrt-Windows.Foundation` (+ `.Collections`) (MIT).
- Elles sont figées dans `host-prototype/requirements.txt`, nouvelles dépendances d'exécution, et `requirements-dev.txt` l'inclut.
- La CLI `relay.py` fonctionne sans elles : les fournisseurs absents passent en `available: false`.
- PyInstaller doit embarquer les modules `winrt` (vérifier les « hidden imports »).

## 4. Appareil (Android)

- **`DeviceRole`** : `SCREEN` ou `ACTIONS`, mémorisé dans les `SharedPreferences`. Par défaut `SCREEN` sur tablette, `ACTIONS` sur téléphone (`smallestScreenWidthDp` < 600 → téléphone).
- **`DEVICE_INFO`** est envoyé juste après le HELLO, avec `Build.MODEL` comme nom.
- **Écran d'attente** :
  - le logo, le titre, l'état ;
  - **deux grands boutons Screen / Actions**, où le rôle courant est mis en évidence. En changer pendant une connexion la ferme puis la rouvre ;
  - le reste ne change pas.
- **Orientation** : `SENSOR_LANDSCAPE` en Screen, comme aujourd'hui ; `FULL_SENSOR` en Actions, pour autoriser le portrait. Elle est appliquée dynamiquement (`requestedOrientation`). Le `configChanges` existant évite de recréer l'activité.
- **`ActionsScreen`** (Compose, style verre Orizon X, fond animé) :
  - **portrait** : une colonne ;
    1. l'horloge en grand (environ 64 sp), puis la date et la batterie du PC ;
    2. la carte Son (curseur, muet, précédent / lecture-pause / suivant) ;
    3. la carte Luminosité ;
    4. les tuiles Wi-Fi / Bluetooth / Avion ;
    5. une carte par clé USB (Ouvrir, Éjecter) ;
  - **paysage** : l'horloge, la date et la batterie dans une colonne à gauche (environ 35 %), les contrôles à droite en grille de 2 colonnes ;
  - l'horloge tourne localement à partir de `clock.epoch_ms`, avec le décalage mesuré à la réception, et l'affiche dans le fuseau du PC ;
  - **optimiste** : une action met l'interface à jour tout de suite, et le prochain `ACTIONS_STATE` fait foi ;
  - `notice` → un petit message en bas (environ 3 s) ;
  - retour haptique sur les boutons, et écran maintenu allumé (`FLAG_KEEP_SCREEN_ON`) en mode Actions ;
  - le geste du HUD à 4 doigts n'existe pas en mode Actions.
- **Code** : `actions/ActionsState.kt` (parsing JSON avec `org.json`, modèle immuable), `actions/ActionThrottle.kt` (20 Hz), `ui/ActionsScreen.kt`, et `Messages`/`FrameReader`/`FrameWriter` étendus.

## 5. Fenêtre PC

- État `ACTIONS` : titre « Actions device », détail « {name} connected ». Le point de couleur est vert.
- Les réglages Mode, Position et Scale restent affichés mais ne s'appliquent qu'au rôle Screen.

## 6. Tests

- **Protocole** : nouveaux vecteurs dans `protocol/test-vectors.json` (`DEVICE_INFO`, `ACTIONS_STATE`, `ACTION`), vérifiés en Python et en Kotlin ; JSON invalide et payload trop gros.
- **Python** :
  - chaque fournisseur avec des couches Windows simulées (audio, WMI, radios, wlan, USB, power, SendInput) ;
  - le hub : diffusion sur changement, rafraîchissement à 30 s, routage des actions, fournisseur en panne → `available: false`, `notice` envoyé une seule fois ;
  - le moteur : `DEVICE_INFO` en rôle actions → pas de display/ffmpeg, état `ACTIONS` ; absence de `DEVICE_INFO` → screen ; action reçue → hub.
  - Des tests de fumée en lecture seule sur ce PC : batterie, volume lu, liste USB, radios listées. **Aucun changement réel** en test automatique.
- **Kotlin** : parsing de l'état (champs manquants, `available` false), limitation à 20 Hz, rôle par défaut selon la taille, `DEVICE_INFO` encodé.
- **Essai réel**, avec l'accord de l'utilisateur : chaque contrôle sur sa tablette, et sur un téléphone s'il en a un. Le volume clavier du PC doit se refléter sur l'appareil en moins d'une demi-seconde.

## 7. Ajout : bloc « En cours de lecture » (validé le 2026-10-11)

Le bloc couvre **toute source** qui publie ses infos dans les contrôles multimédia de Windows (Spotify, navigateur, Deezer, VLC…), et affiche le nom de l'app.

**État** : nouvelle section `now_playing` dans `ACTIONS_STATE`.

```json
"now_playing":{"available":true,"app":"Spotify","title":"…","artist":"…","album":"…","playing":true,"artwork":"<sha1 hex>"}
```

- `available: false` quand aucune session média n'existe.
- `artwork` vaut null s'il n'y a pas de pochette.

**Nouveau message `MEDIA_ARTWORK` (0x05, PC → appareil)** :
- payload : un octet `n` (longueur de l'id), puis l'id (sha1 hex ASCII, 40 octets), puis l'image brute (JPEG ou PNG telle que fournie par Windows), au maximum 512 Kio ;
- il est envoyé **une fois par pochette**, juste **avant** le premier `ACTIONS_STATE` qui la référence ;
- l'appareil garde en cache la dernière pochette reçue.

**PC** : le fournisseur `actions/now_playing.py` s'appuie sur WinRT `Windows.Media.Control` :
1. `GlobalSystemMediaTransportControlsSessionManager.request_async()`, puis `get_current_session()` ;
2. `try_get_media_properties_async()` pour le titre, l'artiste, l'album et la pochette ;
3. `get_playback_info().playback_status` pour savoir si un morceau joue ;
4. lecture de la pochette par `open_read_async` et `DataReader` (`Windows.Storage.Streams`), sur le worker WinRT existant (`winrt_call`).

Le nom de l'app vient de `source_app_user_model_id`, traduit en nom lisible (Spotify, Chrome, Edge, Firefox, Deezer, VLC… ; sinon le nom de l'exécutable sans `.exe`). Le hub calcule le sha1 de la pochette, envoie `MEDIA_ARTWORK` si elle a changé, puis l'état.

**Appareil** : nouvelle carte « En cours de lecture », affichée seulement si `now_playing.available` :
- la pochette (environ 120 dp, coins arrondis ; une note de musique à défaut) ;
- le titre, l'artiste, l'album et l'app ;
- les boutons précédent / lecture-pause / suivant, qui passent de la carte Son à ce bloc ; le bouton lecture-pause reflète `playing`.
- Quand le bloc est absent, les boutons médias restent dans la carte Son.
