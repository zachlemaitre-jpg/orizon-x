# Protocole TABX v1

Flux d'octets bidirectionnel ordonné (TCP via `adb forward` en phase 1, endpoints bulk AOA plus tard).
La tablette écoute sur `127.0.0.1:27183` ; le PC se connecte. Entiers non signés, big-endian.

## En-tête (8 octets)

| Champ | Type | Description |
|---|---|---|
| type | u8 | Type de message |
| flags | u8 | Dépend du type, 0 sinon |
| reserved | u16 | 0 |
| payload_length | u32 | Taille du payload. Rejet si > 16 777 216 |

Un type inconnu est ignoré (payload lu puis jeté).

## PC → tablette

| Type | Nom | Payload |
|---|---|---|
| 0x01 | CONFIG | codec u8 (1 = H.264), width u16, height u16, fps u16 |
| 0x02 | VIDEO | pts_us u64, puis une unité d'accès H.264 Annex-B. Flags : KEY = 0x01, CODEC_CONFIG = 0x02 |
| 0x03 | PONG | t_tab_us u64 (renvoyé tel quel), t_pc_us u64 |

## Tablette → PC

| Type | Nom | Payload |
|---|---|---|
| 0x81 | HELLO | magic "TABX", version u16 (= 1), width u16, height u16, dpi u16 |
| 0x82 | PING | t_tab_us u64 (toutes les 500 ms) |
| 0x83 | KEYFRAME_REQ | vide |
| 0x84 | STATS | fps u16, latency_avg_us u32, latency_max_us u32, dropped u32, rtt_us u32 (chaque seconde) |
| 0x85 | INPUT | réservé (phase 4) |

## Horloges

- PC : `time.perf_counter_ns() // 1000` (même horloge pour `pts_us` et `t_pc_us`).
- Tablette : `System.nanoTime() / 1000`.
- À la réception d'un PONG à `t_recv` : `rtt = t_recv − t_tab`, `offset = t_tab + rtt/2 − t_pc`.
  On garde l'offset de l'échantillon au plus petit RTT parmi les 16 derniers.
- Latence d'une frame = `t_affichage − (pts_us + offset)`.

Les octets attendus de chaque message sont dans `test-vectors.json`.
