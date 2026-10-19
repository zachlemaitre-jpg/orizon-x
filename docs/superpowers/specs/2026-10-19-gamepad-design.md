# Orizon X — Manette Xbox virtuelle sur l'appareil (mode Actions) (design)

Date : 2026-10-19
Statut : validé par l'utilisateur, à implémenter (branche `trackpad`, à la suite du trackpad ; publié avec lui en 0.10.0)

## 1. Objectif

En mode Actions, un bouton **« Gamepad / Manette »** transforme l'appareil en **manette Xbox 360**. Windows et les jeux voient une vraie manette XInput, grâce au pilote **ViGEmBus**.

**Exclus** :
- les vibrations du jeu renvoyées vers l'appareil ;
- les gâchettes analogiques progressives (LT et RT valent 0 ou 255) ;
- plusieurs manettes ;
- la manette DualShock 4.

## 2. Composants tiers (vérifiés le 2026-10-19)

| Fichier | Source | SHA-256 | Licence | Signature |
|---|---|---|---|---|
| `installer/vigem/ViGEmBus_1.22.0_x64_x86_arm64.exe` | GitHub `nefarius/ViGEmBus`, release v1.22.0 (dépôt archivé) | `89220a7865076b342892f98865f3499fb7c4cfd673159e89d352c360fd014c6a` | BSD-3-Clause | Authenticode valide, « Nefarius Software Solutions e.U. » |
| `host-prototype/vendor/ViGEmClient.dll` (x64) | GitHub `yannbouteiller/vgamepad`, `vgamepad/win/vigem/client/x64/` | `2bf0cb1d809039573c922737d298a1653d4dbc61408060ff45a9bcfde82e97d2` | MIT (ViGEmClient, Nefarius) | non signée ; métadonnées Nefarius, v1.0.0.1, exports `vigem_*` attendus |

Les deux licences sont ajoutées à `installer/LICENSES.txt`.

## 3. Installateur

- **Tâche** Inno : `gamepad`, cochée par défaut, intitulée « Manette Xbox virtuelle (pilote ViGEmBus) » / « Virtual Xbox controller (ViGEmBus driver) ».
- **Installation du pilote** : si la tâche est cochée et que le service `ViGEmBus` n'existe pas encore, l'installateur de ViGEmBus est copié dans `{tmp}` puis lancé en silencieux. Les options exactes se déterminent sur le fichier, sans l'exécuter ; une installation WiX Burn prend `/quiet /norestart`.
  - Code de sortie 3010 : redémarrage demandé, sur le même modèle que `RebootNeeded` pour le pilote d'écran.
  - Échec : journalisé, sans bloquer l'installation d'Orizon X.
- **`ViGEmClient.dll`** : toujours installée avec l'application (`--add-binary` de PyInstaller, à côté de l'exe).
- **Désinstallation d'Orizon X** : ViGEmBus reste installé, car d'autres logiciels peuvent s'en servir. Le README le précise.

## 4. Protocole

La version reste 1.

- **`ACTIONS_STATE`** gagne une section `"gamepad"` :
  - `{"available":true}` quand le pilote est prêt ;
  - `{"available":false,"reason":"driver_missing"|"error"}` sinon.
- **Messages `ACTION`** :
  - `{"id":"gamepad.open"}` : branche la manette virtuelle ;
  - `{"id":"gamepad.state","buttons":<u16>,"lt":0|255,"rt":0|255,"lx":<i16>,"ly":<i16>,"rx":<i16>,"ry":<i16>}`. `buttons` suit les bits `XUSB_GAMEPAD_*` (DPAD_UP 0x0001, DPAD_DOWN 0x0002, DPAD_LEFT 0x0004, DPAD_RIGHT 0x0008, START 0x0010, BACK 0x0020, LEFT_THUMB 0x0040, RIGHT_THUMB 0x0080, LEFT_SHOULDER 0x0100, RIGHT_SHOULDER 0x0200, GUIDE 0x0400, A 0x1000, B 0x2000, X 0x4000, Y 0x8000). Les axes Y sont positifs vers le haut, comme en XInput ;
  - `{"id":"gamepad.close"}` : remet la manette au neutre, puis la débranche.
- **`protocol/PROTOCOL.md`** documente cette section et ces messages.

## 5. PC (`actions/gamepad.py`)

- **`ViGEmLayer`** : une couche `ctypes` minimale sur `ViGEmClient.dll`.
  - Fonctions : `vigem_alloc`, `vigem_connect`, `vigem_target_x360_alloc`, `vigem_target_add`, `vigem_target_x360_update` (structure `XUSB_REPORT` : wButtons u16, bLeftTrigger u8, bRightTrigger u8, sThumbLX, sThumbLY, sThumbRX, sThumbRY i16), `vigem_target_remove`, `vigem_target_free`, `vigem_disconnect`, `vigem_free`.
  - La DLL est cherchée dans le dossier de l'application (exe figé), puis dans `host-prototype/vendor/`.
  - Le chargement se fait à la demande, jamais à l'import du module.
- **`GamepadProvider`**, avec une couche injectable :
  - `snapshot()` donne la disponibilité :
    - `driver_missing` si la DLL manque, ou si `vigem_connect` renvoie `VIGEM_ERROR_BUS_NOT_FOUND` ;
    - `error` pour toute autre erreur ;
    - la connexion au bus est tentée une fois, puis relue toutes les 30 s si elle a échoué.
  - `gamepad.open` : alloue et ajoute la cible X360, si ce n'est pas déjà fait.
  - `gamepad.state` :
    - valide les types et les bornes : `buttons` est ramené aux bits connus, les gâchettes valent 0 ou 255, les axes sont bornés à [-32768, 32767] ;
    - envoie le rapport complet par `update`.
  - `gamepad.close` et `stop()` : envoient un rapport neutre (tout à 0), puis `remove`, puis `free`. Ils ne lèvent jamais d'exception.
- **Hub** :
  - le fournisseur est ajouté aux fournisseurs par défaut ;
  - `gamepad.*` lui est routé sans relance du sondage ;
  - la section est relue dans le cycle lent ;
  - `stop()` est appelé à l'arrêt du hub.

## 6. Appareil (Android)

- **Bouton** : pastille « Manette » avec l'icône `ox_gamepad` (Material « sports_esports », Apache-2.0) dans l'en-tête Actions. Elle est visible si `gamepad` est présent. Clavier, trackpad et manette ne sont jamais ouverts en même temps.
- **Écran** : plein écran, sans en-tête, avec un petit ✕ en haut au centre.
  - Ouvrir l'écran envoie `gamepad.open`.
  - Le fermer, changer de mode ou se déconnecter envoie `gamepad.close`.
- **Pilote absent** : si `available` est faux, un message centré remplace la manette. `driver_missing` donne « Install the controller driver: run the Orizon X installer again and keep "Virtual Xbox controller" ticked » ; `error` donne « Controller unavailable on the PC ».
- **Disposition Xbox**, en paysage :
  - **gauche** : le stick gauche en haut, la croix directionnelle en bas ;
  - **droite** : A/B/X/Y en haut (Y en haut, A en bas, X à gauche, B à droite, aux couleurs Xbox), le stick droit en bas ;
  - **coins du haut** : LB et LT à gauche, RB et RT à droite ;
  - **centre** : View (BACK), Xbox (GUIDE), Menu (START).
  - En portrait, la même disposition est réduite à la largeur de l'écran.
- **Sticks** :
  - zone circulaire, position relative au centre, bornée au rayon ;
  - zone morte de 10 % ;
  - valeur = `round(fraction × 32767)`, l'axe Y inversé (haut positif) ;
  - le stick revient au centre au lever du doigt ;
  - un double tap sur un stick envoie L3 ou R3, pendant 100 ms.
- **Multi-touch** : chaque contrôle suit son propre doigt. La croix directionnelle accepte les diagonales (zones de 8 directions).
- **Envoi** : `gamepad.state` à chaque changement, au plus toutes les 8 ms (rapport complet, le dernier l'emporte). Un rapport neutre est envoyé à la fermeture.
- **Retour haptique** à chaque appui sur un bouton.
- **Code** :
  - `gamepad/GamepadState.kt`, pur : la valeur des sticks et la zone morte, les bits des boutons, les secteurs de la croix, la cadence d'envoi ;
  - `gamepad/GamepadActions.kt` : le JSON des actions ;
  - `ui/GamepadScreen.kt`.

## 7. Tests

- **PC**, avec une fausse couche ViGEm :
  - disponibilité : DLL absente, bus introuvable, connexion réussie, nouvel essai au bout de 30 s ;
  - `open` est idempotent ;
  - `state` : bits de boutons et bornes, et les champs invalides sont refusés ;
  - `close` et `stop` : rapport neutre, puis `remove`, puis `free`, sans jamais lever d'exception ;
  - hub : routage, section, `stop` ;
  - la structure `XUSB_REPORT` fait 12 octets.
- **Android** :
  - sticks : zone morte, valeurs aux bords, bornes, inversion de Y ;
  - croix directionnelle à 8 directions ;
  - bits des boutons ;
  - cadence limitée à 8 ms ;
  - rapport neutre à la fermeture ;
  - JSON ;
  - lecture de la section `gamepad`.
- **Réel**, avec l'accord de l'utilisateur pour installer le pilote :
  - installer `OrizonX-Setup.exe` avec la tâche Manette cochée ;
  - vérifier la manette dans `joy.cpl` : boutons, sticks, gâchettes ;
  - essayer un jeu au choix de l'utilisateur.
