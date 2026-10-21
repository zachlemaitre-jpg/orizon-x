# Orizon X — Blocs de performances du mode Actions (design)

Date : 2026-10-21
Statut : validé par l'utilisateur, à implémenter (branche `perf-blocks`, créée depuis `master` 0.14.0)
Suite prévue : un bloc Discord, avec sa propre spec.

## 1. Objectif

Cinq nouveaux blocs dans la grille du mode Actions : **Processeur**, **GPU**, **RAM**, **Wi-Fi** et **NPU**, un bloc par mesure. Chaque bloc montre une grande valeur, un mini-graphe des 60 dernières secondes et une ligne de détail, comme le Gestionnaire des tâches.

## 2. Mesures (PC)

Toutes les mesures passent par les **compteurs de performance de Windows (PDH)**, appelés par ctypes (`pdh.dll`), sans nouvelle dépendance. Ce sont les compteurs du Gestionnaire des tâches.

| Bloc | Valeur | Courbe | Ligne de détail |
|---|---|---|---|
| `cpu` | `\Processor Information(_Total)\% Processor Utility`, plafonné à 100 (à défaut `% Processor Time`) | % | fréquence courante en GHz : `Processor Frequency` × `% Processor Performance` / 100 |
| `gpu` | % du moteur le plus occupé de la carte graphique (somme par moteur des instances `\GPU Engine(*luid_<gpu>*)\Utilization Percentage`, puis maximum entre moteurs), plafonné à 100 | % | mémoire utilisée / totale : `\GPU Adapter Memory(luid_<gpu>*)\Dedicated Usage` + `Shared Usage`, sur `DedicatedVideoMemory` + `SharedSystemMemory` (DXGI) |
| `ram` | % de la mémoire physique utilisée (`GlobalMemoryStatusEx`) | % | « 12,3 / 32 Go » |
| `net` | débit reçu de l'adaptateur Wi-Fi actif (`\Network Interface(<adaptateur>)\Bytes Received/sec`) | reçu et envoyé (deux courbes, échelle automatique) | débit envoyé (`Bytes Sent/sec`) ; le signal reste celui de la section `wifi` existante |
| `npu` | % du moteur le plus occupé du NPU (`\GPU Engine(*luid_<npu>*)\Utilization Percentage`, même calcul que le GPU) | % | — |

**Reconnaître le GPU et le NPU par leur LUID** :
- **GPU** : l'adaptateur DXGI (`EnumAdapters1`) qui n'est ni logiciel (`DXGI_ADAPTER_FLAG_SOFTWARE`) ni le « Virtual Display Driver » d'Orizon X, avec le plus de mémoire (dédiée + partagée).
- **NPU** : un LUID présent dans les instances `GPU Engine` qui n'est pas un adaptateur DXGI et qui n'a que des moteurs `compute*`.
  - Sur le PC de l'utilisateur (Ryzen AI 9 HX 370, Radeon 890M), trois LUID sont vus et le périphérique « NPU Compute Accelerator Device » est présent.
- La découverte est refaite toutes les 60 s, et quand une instance disparaît (pilote rechargé).

**Échantillonnage** :
- Un fil dédié (`actions/perf.py`, classe `PerfSampler`) lit les compteurs **une fois par seconde**. Il ne bloque ni le fil d'entrée ni le hub.
- Il garde 60 points par courbe.
- Le hub lit le dernier instantané sans attendre.
- Le fil ne démarre qu'à la première demande de la section et s'arrête avec le hub.

**Section de l'état** :

```json
"perf": {"available": true,
  "cpu": {"value": 23, "ghz": 4.1, "history": [..60 entiers 0-100..]},
  "gpu": {"value": 8, "mem_used": 3.2, "mem_total": 16.0, "history": [...]},
  "ram": {"value": 41, "used": 12.3, "total": 32.0, "history": [...]},
  "net": {"down": 1250000, "up": 82000, "down_history": [...], "up_history": [...]},
  "npu": {"value": 0, "history": [...]}}
```

- Une mesure introuvable est absente de la section.
- Les courbes en pourcentage sont des entiers de 0 à 100 ; les débits sont en octets par seconde, entiers ; les quantités de mémoire sont en Go, avec une décimale.
- La section pèse environ 2 Kio, bien sous le budget de 64 Kio de l'état.
- Elle est envoyée avec le groupe rapide, au plus une fois par seconde (nouvel échantillon seulement).

**Erreurs** : un compteur qui échoue rend sa mesure absente, puis le PC réessaie à la découverte suivante. Rien n'est journalisé plus d'une fois par minute et par mesure.

## 3. Appareil

- Cinq nouveaux blocs : `perf_cpu`, `perf_gpu`, `perf_ram`, `perf_net` et `perf_npu`.
  - Ils sont déplaçables, redimensionnables et masquables, comme les autres.
  - Taille par défaut 2×1, minimum 1×1.
  - Ils s'ajoutent à la fin de l'ordre par défaut et vont à la première place libre des dispositions enregistrées.
- Un bloc n'existe que si sa mesure est présente.
- **Contenu** :
  - en haut : l'icône, le nom (« Processeur / CPU », « GPU », « RAM », « Wi-Fi », « NPU ») et la valeur à droite (« 23 % » ; pour le Wi-Fi « ↓ 1,2 Mo/s ») ;
  - au milieu : la courbe, qui prend toute la place libre et grandit avec le bloc ; le texte garde sa taille ;
  - en bas : la ligne de détail (« 4,1 GHz », « 3,2 / 16 Go », « 12,3 / 32 Go », « ↑ 82 Ko/s »).
  - Un bloc de 1×1 n'affiche que l'icône, le nom et la valeur, sans courbe ni détail.
- **Courbe** :
  - tracé lissé blanc sur un remplissage dégradé discret, avec 0–100 % fixe ;
  - pour le Wi-Fi, deux tracés (reçu plein, envoyé en pointillés) et une échelle automatique, arrondie au palier supérieur (1, 2, 5 × 10ⁿ).
- **Formats** : débits en o/s, Ko/s, Mo/s (unités françaises ; B/s, KB/s, MB/s en anglais), une décimale au-delà de 1 Mo/s.
- **Icônes** : tracés Material Icons (Apache-2.0) `memory` (Processeur), `developer_board` (GPU), `storage` (RAM), `wifi` existante (Wi-Fi), `psychology` (NPU).

## 4. Tests

- **PC** :
  - calcul du GPU et du NPU depuis de fausses instances `GPU Engine` (somme par moteur, maximum, plafond) ;
  - reconnaissance des LUID avec de faux adaptateurs DXGI (logiciel et Virtual Display Driver écartés, NPU = compute seul) ;
  - fréquence, mémoire, débits ;
  - historique de 60 points ;
  - section JSON et sa taille ;
  - mesure absente quand un compteur échoue.
  - Le lecteur PDH est injectable ; un test en lecture seule sur le vrai système vérifie seulement que l'ouverture des requêtes marche.
- **Android** :
  - lecture de la section `perf` ;
  - présence des blocs ;
  - formats des valeurs (pourcentages, Go, débits, en français et en anglais) ;
  - échelle automatique du Wi-Fi ;
  - forme compacte en 1×1 (logique pure).
- **Réel** : comparer chaque bloc au Gestionnaire des tâches, sous charge (vidéo, téléchargement, une app qui utilise le NPU si possible).
