# TabX Phase 1 — Pipeline vidéo PC → tablette : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** afficher sur la Galaxy Tab S10 FE+ le bureau du PC encodé en H.264 matériel, transmis par `adb forward`, avec mesure intégrée de la latence envoi→affichage.

**Architecture :** côté PC, ffmpeg (`ddagrab` + NVENC/AMF) écrit du H.264 Annex-B dans un pipe. Un relais Python le découpe en unités d'accès et l'emballe dans le protocole TABX v1 vers `127.0.0.1:27183` (via `adb forward`). Côté tablette, une app Kotlin/Compose écoute en loopback, décode avec MediaCodec (mode asynchrone, low-latency) directement dans un `SurfaceView`, mesure la latence (sync d'horloge par ping/pong) et affiche une interface glassmorphism.

**Tech Stack :** Python ≥ 3.10 (bibliothèque standard uniquement), ffmpeg ≥ 6 (build Gyan), Kotlin, AGP 9.0.1 + Gradle 9.1.0, Jetpack Compose (BOM 2026.09.00), JUnit 4, org.json (tests uniquement).

**Spec :** `docs/superpowers/specs/2026-10-01-phase1-video-pipeline-design.md`

---

## Environnement constaté sur le PC (2026-10-01)

| Outil | État | Chemin / commande |
|---|---|---|
| Python | 3.13 via le lanceur `py` (`python` n'est pas dans le PATH) | `py` |
| adb | présent, pas dans le PATH | `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe` |
| JDK pour Gradle | JBR 21 d'Android Studio | `C:\Program Files\Android\Android Studio\jbr` |
| Gradle | distribution 9.1.0 en cache | `~\.gradle\wrapper\dists\gradle-9.1.0-all\…` |
| SDK Android | platforms 30, 35, 36 ; build-tools 36/37 | `$env:LOCALAPPDATA\Android\Sdk` |
| ffmpeg | **absent** → installé en tâche 0 | — |

Toutes les commandes sont en PowerShell, lancées depuis la racine du dépôt `D:\TumorScreen App` sauf indication contraire.

## Structure des fichiers

```
/
├── .gitignore, .gitattributes
├── README.md                              démarrage + checklist d'intégration
├── protocol/
│   ├── PROTOCOL.md                        référence du protocole TABX v1
│   └── test-vectors.json                  vecteurs partagés Kotlin/Python
├── host-prototype/
│   ├── protocol.py                        encodage PC→tablette, décodage tablette→PC
│   ├── annexb.py                          découpeur AUD, liste des NAL, taille depuis le SPS
│   ├── relay.py                           adb + ffmpeg + session TCP
│   └── tests/
│       ├── __init__.py
│       ├── sample.h264                    30 frames 320×180, IDR toutes les 10 frames, avec AUD
│       ├── test_protocol.py
│       └── test_annexb.py
└── android/
    ├── settings.gradle.kts, build.gradle.kts, gradle.properties, gradlew(.bat), gradle/wrapper/*
    └── app/
        ├── build.gradle.kts
        └── src/
            ├── main/AndroidManifest.xml
            ├── main/java/dev/tabx/client/
            │   ├── protocol/Messages.kt       constantes, PcMessage, TabletMessage, ProtocolException
            │   ├── protocol/FrameReader.kt    InputStream → PcMessage
            │   ├── protocol/FrameWriter.kt    TabletMessage → octets
            │   ├── stats/LatencyTracker.kt    offset d'horloge, latence, histogramme
            │   ├── video/VideoDecoder.kt      MediaCodec asynchrone → Surface
            │   ├── net/Server.kt              ServerSocket loopback
            │   ├── Session.kt                 une connexion (+ ScreenInfo)
            │   ├── Receiver.kt                boucle d'accept (thread net-reader)
            │   ├── UiModel.kt                 état Compose
            │   ├── MainActivity.kt
            │   └── ui/Glass.kt, ui/WaitingScreen.kt, ui/StreamScreen.kt, ui/TabXApp.kt
            └── test/java/dev/tabx/client/
                ├── protocol/TestHex.kt
                ├── protocol/ProtocolVectorsTest.kt
                ├── protocol/FrameReaderTest.kt
                └── stats/LatencyTrackerTest.kt
```

Ordre : socle → protocole partagé → côté Python (testable sans tablette) → côté Android (tests JVM, puis code appareil) → intégration sur la tablette.

---

### Task 0 : Prérequis et socle du dépôt

**Files:**
- Create: `.gitignore`
- Create: `.gitattributes`

- [ ] **Step 1 : Installer ffmpeg** (demander l'accord de l'utilisateur avant d'installer un logiciel)

```powershell
winget install --id Gyan.FFmpeg -e
```

Fermer puis rouvrir le terminal pour recharger le PATH.

- [ ] **Step 2 : Vérifier les encodeurs disponibles**

```powershell
ffmpeg -hide_banner -encoders | Select-String "h264_nvenc|h264_amf|libx264"
```

Attendu : trois lignes, contenant `h264_nvenc`, `h264_amf` et `libx264`.

- [ ] **Step 3 : Vérifier que `ddagrab` est disponible**

```powershell
ffmpeg -hide_banner -filters | Select-String "ddagrab"
```

Attendu : une ligne contenant `ddagrab`.

- [ ] **Step 4 : Créer `.gitignore`**

```gitignore
# Android / Gradle
android/.gradle/
android/.kotlin/
android/build/
android/app/build/
android/local.properties
android/.idea/
*.iml

# Python
__pycache__/
*.pyc
```

- [ ] **Step 5 : Créer `.gitattributes`**

```gitattributes
* text=auto
*.h264 binary
*.jar binary
gradlew text eol=lf
*.bat text eol=crlf
```

- [ ] **Step 6 : Commit**

```powershell
git add .gitignore .gitattributes
git commit -m "chore: add gitignore and gitattributes"
```

---

### Task 1 : Référence du protocole et vecteurs de test

**Files:**
- Create: `protocol/PROTOCOL.md`
- Create: `protocol/test-vectors.json`

- [ ] **Step 1 : Écrire `protocol/PROTOCOL.md`**

````markdown
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
````

- [ ] **Step 2 : Écrire `protocol/test-vectors.json`**

```json
{
  "pc_to_tablet": [
    {
      "name": "config_1080p60",
      "type": "CONFIG",
      "fields": {"codec": 1, "width": 1920, "height": 1080, "fps": 60},
      "hex": "01000000000000070107800438003c"
    },
    {
      "name": "video_key",
      "type": "VIDEO",
      "fields": {"flags": 1, "pts_us": 1000000, "data": "000000016588"},
      "hex": "020100000000000e00000000000f4240000000016588"
    },
    {
      "name": "video_codec_config",
      "type": "VIDEO",
      "fields": {"flags": 2, "pts_us": 0, "data": "00000001670000000168"},
      "hex": "0202000000000012000000000000000000000001670000000168"
    },
    {
      "name": "pong",
      "type": "PONG",
      "fields": {"t_tab_us": 123456789, "t_pc_us": 987654321},
      "hex": "030000000000001000000000075bcd15000000003ade68b1"
    }
  ],
  "tablet_to_pc": [
    {
      "name": "hello",
      "type": "HELLO",
      "fields": {"version": 1, "width": 2880, "height": 1800, "dpi": 320},
      "hex": "810000000000000c5441425800010b4007080140"
    },
    {
      "name": "ping",
      "type": "PING",
      "fields": {"t_tab_us": 123456789},
      "hex": "820000000000000800000000075bcd15"
    },
    {
      "name": "keyframe_req",
      "type": "KEYFRAME_REQ",
      "fields": {},
      "hex": "8300000000000000"
    },
    {
      "name": "stats",
      "type": "STATS",
      "fields": {"fps": 60, "latency_avg_us": 15000, "latency_max_us": 31000, "dropped": 2, "rtt_us": 850},
      "hex": "8400000000000012003c00003a98000079180000000200000352"
    }
  ]
}
```

- [ ] **Step 3 : Vérifier que le JSON est valide**

```powershell
py -c "import json; d = json.load(open('protocol/test-vectors.json')); print(len(d['pc_to_tablet']), len(d['tablet_to_pc']))"
```

Attendu : `4 4`

- [ ] **Step 4 : Commit**

```powershell
git add protocol
git commit -m "docs(protocol): add TABX v1 reference and shared test vectors"
```

---

### Task 2 : Protocole côté Python

**Files:**
- Create: `host-prototype/tests/__init__.py` (vide)
- Create: `host-prototype/tests/test_protocol.py`
- Create: `host-prototype/protocol.py`

- [ ] **Step 1 : Créer `host-prototype/tests/__init__.py` vide**

```powershell
New-Item -ItemType Directory -Force host-prototype/tests | Out-Null
New-Item -ItemType File host-prototype/tests/__init__.py | Out-Null
```

- [ ] **Step 2 : Écrire le test qui échoue, `host-prototype/tests/test_protocol.py`**

```python
import io
import json
import unittest
from pathlib import Path

import protocol

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "protocol" / "test-vectors.json").read_text()
)

EXPECTED_TABLET_MESSAGES = {
    "HELLO": lambda f: protocol.Hello(**f),
    "PING": lambda f: protocol.Ping(**f),
    "KEYFRAME_REQ": lambda f: protocol.KeyframeRequest(),
    "STATS": lambda f: protocol.Stats(**f),
}


def encode_vector(vector: dict) -> bytes:
    f = vector["fields"]
    if vector["type"] == "CONFIG":
        assert f["codec"] == protocol.CODEC_H264
        return protocol.encode_config(f["width"], f["height"], f["fps"])
    if vector["type"] == "VIDEO":
        return protocol.encode_video(f["pts_us"], bytes.fromhex(f["data"]), f["flags"])
    if vector["type"] == "PONG":
        return protocol.encode_pong(f["t_tab_us"], f["t_pc_us"])
    raise AssertionError(f"type inattendu : {vector['type']}")


class VectorTest(unittest.TestCase):
    def test_encodes_pc_to_tablet_vectors(self):
        for vector in VECTORS["pc_to_tablet"]:
            with self.subTest(vector["name"]):
                self.assertEqual(encode_vector(vector).hex(), vector["hex"])

    def test_decodes_tablet_to_pc_vectors(self):
        for vector in VECTORS["tablet_to_pc"]:
            with self.subTest(vector["name"]):
                message = protocol.read_message(io.BytesIO(bytes.fromhex(vector["hex"])))
                self.assertEqual(message, EXPECTED_TABLET_MESSAGES[vector["type"]](vector["fields"]))


class ReadMessageTest(unittest.TestCase):
    PING_HEX = "820000000000000800000000075bcd15"

    def test_skips_unknown_type(self):
        unknown = bytes.fromhex("99000000" "00000003" "010203")
        stream = io.BytesIO(unknown + bytes.fromhex(self.PING_HEX))
        self.assertEqual(protocol.read_message(stream), protocol.Ping(123456789))

    def test_rejects_oversized_payload(self):
        header = bytes.fromhex("82000000") + (protocol.MAX_PAYLOAD + 1).to_bytes(4, "big")
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(header))

    def test_truncated_stream_raises_eof(self):
        with self.assertRaises(EOFError):
            protocol.read_message(io.BytesIO(bytes.fromhex(self.PING_HEX)[:-1]))

    def test_rejects_bad_magic(self):
        bad = bytes.fromhex("810000000000000c" "41424344" "00010b4007080140")
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(bad))

    def test_rejects_wrong_payload_size(self):
        short_ping = bytes.fromhex("8200000000000004" "00000001")
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(short_ping))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3 : Lancer le test, vérifier qu'il échoue**

```powershell
cd host-prototype; py -m unittest discover -v; cd ..
```

Attendu : ERROR `ModuleNotFoundError: No module named 'protocol'`.

- [ ] **Step 4 : Écrire `host-prototype/protocol.py`**

```python
"""TABX protocol v1, PC side. Reference: protocol/PROTOCOL.md."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO

VERSION = 1
PORT = 27183
MAGIC = b"TABX"
MAX_PAYLOAD = 16 * 1024 * 1024
HEADER = struct.Struct(">BBHI")

# PC -> tablet
CONFIG = 0x01
VIDEO = 0x02
PONG = 0x03
# tablet -> PC
HELLO = 0x81
PING = 0x82
KEYFRAME_REQ = 0x83
STATS = 0x84

FLAG_KEY = 0x01
FLAG_CODEC_CONFIG = 0x02
CODEC_H264 = 1

_CONFIG = struct.Struct(">BHHH")
_U64 = struct.Struct(">Q")
_PONG = struct.Struct(">QQ")
_HELLO = struct.Struct(">4sHHHH")
_STATS = struct.Struct(">HIIII")


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class Hello:
    version: int
    width: int
    height: int
    dpi: int


@dataclass(frozen=True)
class Ping:
    t_tab_us: int


@dataclass(frozen=True)
class KeyframeRequest:
    pass


@dataclass(frozen=True)
class Stats:
    fps: int
    latency_avg_us: int
    latency_max_us: int
    dropped: int
    rtt_us: int


TabletMessage = Hello | Ping | KeyframeRequest | Stats


def _frame(msg_type: int, flags: int, payload: bytes) -> bytes:
    return HEADER.pack(msg_type, flags, 0, len(payload)) + payload


def encode_config(width: int, height: int, fps: int) -> bytes:
    return _frame(CONFIG, 0, _CONFIG.pack(CODEC_H264, width, height, fps))


def encode_video(pts_us: int, data: bytes, flags: int = 0) -> bytes:
    return _frame(VIDEO, flags, _U64.pack(pts_us) + data)


def encode_pong(t_tab_us: int, t_pc_us: int) -> bytes:
    return _frame(PONG, 0, _PONG.pack(t_tab_us, t_pc_us))


def decode_payload(msg_type: int, payload: bytes) -> TabletMessage | None:
    """Decodes a tablet->PC payload. Returns None for unknown types."""
    try:
        if msg_type == HELLO:
            magic, version, width, height, dpi = _HELLO.unpack(payload)
            if magic != MAGIC:
                raise ProtocolError(f"magic invalide : {magic!r}")
            return Hello(version, width, height, dpi)
        if msg_type == PING:
            return Ping(*_U64.unpack(payload))
        if msg_type == KEYFRAME_REQ:
            return KeyframeRequest()
        if msg_type == STATS:
            return Stats(*_STATS.unpack(payload))
    except struct.error as e:
        raise ProtocolError(f"payload invalide pour le type 0x{msg_type:02x} : {e}") from e
    return None


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) < size:
        raise EOFError("connexion fermée")
    return data


def read_message(stream: BinaryIO) -> TabletMessage:
    """Reads the next known message, skipping unknown types. Raises EOFError at end of stream."""
    while True:
        msg_type, _flags, _reserved, length = HEADER.unpack(_read_exact(stream, HEADER.size))
        if length > MAX_PAYLOAD:
            raise ProtocolError(f"payload trop gros : {length} octets")
        message = decode_payload(msg_type, _read_exact(stream, length))
        if message is not None:
            return message
```

- [ ] **Step 5 : Lancer les tests, vérifier qu'ils passent**

```powershell
cd host-prototype; py -m unittest discover -v; cd ..
```

Attendu : `Ran 7 tests` … `OK`.

- [ ] **Step 6 : Commit**

```powershell
git add host-prototype/protocol.py host-prototype/tests
git commit -m "feat(relay): add TABX protocol encoder/decoder with shared vectors"
```

---

### Task 3 : Découpeur Annex-B et échantillon H.264

**Files:**
- Create: `host-prototype/tests/sample.h264` (généré)
- Create: `host-prototype/tests/test_annexb.py`
- Create: `host-prototype/annexb.py`

- [ ] **Step 1 : Générer l'échantillon** (320×180 pour tester le recadrage du SPS : 180 lignes sont codées en 192)

```powershell
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=size=320x180:rate=30 -frames:v 30 -c:v libx264 -pix_fmt yuv420p -bf 0 -x264-params keyint=10:min-keyint=10:scenecut=0 -bsf:v h264_metadata=aud=insert -f h264 host-prototype/tests/sample.h264
```

Vérifier : `(Get-Item host-prototype/tests/sample.h264).Length` → quelques dizaines de Ko.

- [ ] **Step 2 : Écrire le test qui échoue, `host-prototype/tests/test_annexb.py`**

```python
import unittest
from pathlib import Path

import annexb

SAMPLE = (Path(__file__).parent / "sample.h264").read_bytes()
AUD_4 = b"\x00\x00\x00\x01\x09"


def split_all(data: bytes, chunk_size: int) -> list[bytes]:
    splitter = annexb.AccessUnitSplitter()
    units: list[bytes] = []
    for i in range(0, len(data), chunk_size):
        units += splitter.feed(data[i : i + chunk_size])
    last = splitter.flush()
    if last is not None:
        units.append(last)
    return units


class SplitterTest(unittest.TestCase):
    def test_sample_splits_into_30_units(self):
        self.assertEqual(len(split_all(SAMPLE, 1000)), 30)

    def test_every_unit_starts_with_aud(self):
        for unit in split_all(SAMPLE, 1000):
            self.assertTrue(unit.startswith(AUD_4), unit[:8].hex())

    def test_units_reassemble_to_input(self):
        self.assertEqual(b"".join(split_all(SAMPLE, 1000)), SAMPLE)

    def test_chunk_size_does_not_change_result(self):
        self.assertEqual(split_all(SAMPLE, 7), split_all(SAMPLE, len(SAMPLE)))

    def test_bytes_before_first_aud_are_dropped(self):
        units = split_all(b"\xff\xfe\x00" + SAMPLE, 1000)
        self.assertEqual(len(units), 30)
        self.assertTrue(units[0].startswith(AUD_4))

    def test_nothing_emitted_before_second_aud(self):
        splitter = annexb.AccessUnitSplitter()
        second_aud = SAMPLE.find(AUD_4, 1)
        self.assertEqual(splitter.feed(SAMPLE[:second_aud]), [])


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.units = split_all(SAMPLE, 1000)

    def test_idr_every_10_frames(self):
        idr = [i for i, unit in enumerate(self.units) if annexb.describe(unit).is_idr]
        self.assertEqual(idr, [0, 10, 20])

    def test_idr_unit_carries_sps_and_pps(self):
        info = annexb.describe(self.units[0])
        self.assertEqual(info.sps[0] & 0x1F, annexb.NAL_SPS)
        self.assertEqual(info.pps[0] & 0x1F, annexb.NAL_PPS)

    def test_non_idr_unit_has_no_sps(self):
        self.assertIsNone(annexb.describe(self.units[1]).sps)

    def test_split_nals_strips_start_codes(self):
        nals = annexb.split_nals(self.units[0])
        self.assertEqual(nals[0][0] & 0x1F, annexb.NAL_AUD)
        self.assertTrue(all(nal[:3] != b"\x00\x00\x01" for nal in nals))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3 : Lancer, vérifier l'échec**

```powershell
cd host-prototype; py -m unittest tests.test_annexb -v; cd ..
```

Attendu : ERROR `ModuleNotFoundError: No module named 'annexb'`.

- [ ] **Step 4 : Écrire `host-prototype/annexb.py`**

```python
"""H.264 Annex-B helpers: access-unit splitting on AUD, NAL listing, SPS size parsing."""
from __future__ import annotations

from dataclasses import dataclass

START_CODE = b"\x00\x00\x00\x01"
_START_3 = b"\x00\x00\x01"
_AUD_MARK = b"\x00\x00\x01\x09"  # an AUD always has nal_ref_idc == 0, so its header byte is exactly 0x09

NAL_IDR = 5
NAL_SPS = 7
NAL_PPS = 8
NAL_AUD = 9


class AccessUnitSplitter:
    """Splits a streamed Annex-B byte stream into access units.

    Every access unit must start with an AUD (ffmpeg: -bsf:v h264_metadata=aud=insert).
    A unit is emitted only once the next AUD arrives. Bytes before the first AUD are dropped.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._synced = False
        self._search_from = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        units: list[bytes] = []
        while True:
            idx = self._buf.find(_AUD_MARK, self._search_from)
            if idx < 0:
                # Keep the last bytes searchable: a mark may straddle two chunks.
                self._search_from = max(self._search_from, len(self._buf) - len(_AUD_MARK) + 1)
                return units
            start = idx - 1 if idx > 0 and self._buf[idx - 1] == 0 else idx  # include 4-byte start code
            if self._synced:
                units.append(bytes(self._buf[:start]))
            self._synced = True
            del self._buf[:start]
            self._search_from = idx - start + len(_AUD_MARK)

    def flush(self) -> bytes | None:
        """Returns the pending (last) unit, if any, and resets the splitter."""
        unit = bytes(self._buf) if self._synced and self._buf else None
        self._buf.clear()
        self._synced = False
        self._search_from = 0
        return unit


def split_nals(data: bytes) -> list[bytes]:
    """Returns the NAL units of an Annex-B buffer (header byte first, start codes removed)."""
    nals: list[bytes] = []
    pos = data.find(_START_3)
    while pos >= 0:
        begin = pos + len(_START_3)
        nxt = data.find(_START_3, begin)
        nal = data[begin : len(data) if nxt < 0 else nxt].rstrip(b"\x00")
        if nal:
            nals.append(nal)
        pos = nxt
    return nals


@dataclass(frozen=True)
class AccessUnitInfo:
    is_idr: bool
    sps: bytes | None
    pps: bytes | None


def describe(unit: bytes) -> AccessUnitInfo:
    is_idr = False
    sps = pps = None
    for nal in split_nals(unit):
        nal_type = nal[0] & 0x1F
        if nal_type == NAL_IDR:
            is_idr = True
        elif nal_type == NAL_SPS and sps is None:
            sps = nal
        elif nal_type == NAL_PPS and pps is None:
            pps = nal
    return AccessUnitInfo(is_idr, sps, pps)
```

- [ ] **Step 5 : Lancer, vérifier que les tests passent**

```powershell
cd host-prototype; py -m unittest tests.test_annexb -v; cd ..
```

Attendu : `Ran 10 tests` … `OK`.

- [ ] **Step 6 : Commit**

```powershell
git add host-prototype/annexb.py host-prototype/tests/test_annexb.py host-prototype/tests/sample.h264
git commit -m "feat(relay): add Annex-B access-unit splitter with H.264 sample"
```

---

### Task 4 : Taille d'image depuis le SPS

**Files:**
- Modify: `host-prototype/tests/test_annexb.py` (ajout d'une classe)
- Modify: `host-prototype/annexb.py` (ajout en fin de fichier)

- [ ] **Step 1 : Ajouter le test qui échoue** à la fin de `host-prototype/tests/test_annexb.py`, juste avant `if __name__ == "__main__":`

```python
class SpsTest(unittest.TestCase):
    def test_sample_size_applies_frame_cropping(self):
        units = split_all(SAMPLE, 1000)
        sps = annexb.describe(units[0]).sps
        self.assertEqual(annexb.parse_sps_size(sps), (320, 180))

    def test_baseline_sps_without_cropping(self):
        # Baseline profile 66, 1280x720 (80x45 macroblocks), frame_mbs_only, no cropping.
        # Bits after the 3 fixed bytes: sps_id ue(0)=1, log2_max_frame_num-4 ue(0)=1, poc_type ue(2)=011,
        # max_num_ref ue(1)=010, gaps u1=0, width_mbs-1 ue(79), height_map-1 ue(44),
        # frame_mbs_only=1, direct_8x8=1, cropping=0, vui=0, stop bit.
        bits = "1" + "1" + "011" + "010" + "0" + _ue(79) + _ue(44) + "1" + "1" + "0" + "0" + "1"
        bits += "0" * (-len(bits) % 8)
        payload = int(bits, 2).to_bytes(len(bits) // 8, "big")
        sps = bytes([0x67, 66, 0xC0, 31]) + payload
        self.assertEqual(annexb.parse_sps_size(sps), (1280, 720))


def _ue(value: int) -> str:
    code = bin(value + 1)[2:]
    return "0" * (len(code) - 1) + code
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```powershell
cd host-prototype; py -m unittest tests.test_annexb -v; cd ..
```

Attendu : 2 erreurs `AttributeError: module 'annexb' has no attribute 'parse_sps_size'`.

- [ ] **Step 3 : Ajouter le parseur** à la fin de `host-prototype/annexb.py`

```python
_HIGH_PROFILES = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}


class _BitReader:
    def __init__(self, rbsp: bytes) -> None:
        self._data = rbsp
        self._pos = 0

    def u(self, bits: int) -> int:
        value = 0
        for _ in range(bits):
            byte = self._data[self._pos >> 3]
            value = (value << 1) | ((byte >> (7 - (self._pos & 7))) & 1)
            self._pos += 1
        return value

    def ue(self) -> int:
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self) -> int:
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


def _skip_scaling_list(reader: _BitReader, size: int) -> None:
    last = nxt = 8
    for _ in range(size):
        if nxt != 0:
            nxt = (last + reader.se() + 256) % 256
        last = last if nxt == 0 else nxt


def parse_sps_size(sps: bytes) -> tuple[int, int]:
    """Returns the displayed (width, height) of an SPS NAL (header byte included), cropping applied."""
    r = _BitReader(sps[1:].replace(b"\x00\x00\x03", b"\x00\x00"))  # remove emulation prevention bytes
    profile_idc = r.u(8)
    r.u(16)  # constraint flags + level_idc
    r.ue()  # seq_parameter_set_id
    chroma_format_idc = 1
    separate_colour_plane = 0
    if profile_idc in _HIGH_PROFILES:
        chroma_format_idc = r.ue()
        if chroma_format_idc == 3:
            separate_colour_plane = r.u(1)
        r.ue()  # bit_depth_luma_minus8
        r.ue()  # bit_depth_chroma_minus8
        r.u(1)  # qpprime_y_zero_transform_bypass_flag
        if r.u(1):  # seq_scaling_matrix_present_flag
            for i in range(8 if chroma_format_idc != 3 else 12):
                if r.u(1):
                    _skip_scaling_list(r, 16 if i < 6 else 64)
    r.ue()  # log2_max_frame_num_minus4
    poc_type = r.ue()
    if poc_type == 0:
        r.ue()  # log2_max_pic_order_cnt_lsb_minus4
    elif poc_type == 1:
        r.u(1)
        r.se()
        r.se()
        for _ in range(r.ue()):
            r.se()
    r.ue()  # max_num_ref_frames
    r.u(1)  # gaps_in_frame_num_value_allowed_flag
    width_mbs = r.ue() + 1
    height_map_units = r.ue() + 1
    frame_mbs_only = r.u(1)
    if not frame_mbs_only:
        r.u(1)  # mb_adaptive_frame_field_flag
    r.u(1)  # direct_8x8_inference_flag
    width = width_mbs * 16
    height = (2 - frame_mbs_only) * height_map_units * 16
    if r.u(1):  # frame_cropping_flag
        left, right, top, bottom = r.ue(), r.ue(), r.ue(), r.ue()
        chroma_array_type = 0 if separate_colour_plane else chroma_format_idc
        sub_w, sub_h = {1: (2, 2), 2: (2, 1), 3: (1, 1)}.get(chroma_array_type, (1, 1))
        crop_x = 1 if chroma_array_type == 0 else sub_w
        crop_y = (2 - frame_mbs_only) * (1 if chroma_array_type == 0 else sub_h)
        width -= (left + right) * crop_x
        height -= (top + bottom) * crop_y
    return width, height
```

- [ ] **Step 4 : Lancer toute la suite Python**

```powershell
cd host-prototype; py -m unittest discover -v; cd ..
```

Attendu : `Ran 19 tests` … `OK`.

- [ ] **Step 5 : Commit**

```powershell
git add host-prototype/annexb.py host-prototype/tests/test_annexb.py
git commit -m "feat(relay): parse display size from H.264 SPS"
```

---

### Task 5 : Relais `relay.py`

> Note d'exécution : le code final diffère de ce bloc (options AMF mesurées, réinsertion SPS/PPS, durcissements de revue) — la référence est `host-prototype/relay.py` et la spec §6.2.

Ce fichier orchestre des processus et des sockets : il n'a pas de test unitaire (la logique testable est dans `protocol.py` et `annexb.py`). Il est vérifié manuellement ici, puis en intégration (tâche 12).

**Files:**
- Create: `host-prototype/relay.py`

- [ ] **Step 1 : Écrire `host-prototype/relay.py`**

```python
"""Phase-1 relay: ffmpeg (ddagrab + hardware H.264) -> TABX protocol -> tablet through adb forward.

Usage: py relay.py --encoder nvenc|amf [--output 0] [--fps 60] [--bitrate 30M]
"""
from __future__ import annotations

import argparse
import collections
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable

import annexb
import protocol

ADB_FALLBACK = Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe"

ENCODERS = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0"],
    "amf": ["-c:v", "h264_amf", "-usage", "ultralowlatency", "-quality", "speed"],
}


def now_us() -> int:
    # perf_counter (QueryPerformanceCounter) : time.monotonic n'a que ~15,6 ms de résolution sous Windows avant 3.13.
    return time.perf_counter_ns() // 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relais TABX phase 1 : écran PC -> tablette via adb")
    parser.add_argument("--encoder", choices=sorted(ENCODERS), required=True,
                        help="nvenc (sur secteur, GPU NVIDIA) ou amf (sur batterie, iGPU AMD)")
    parser.add_argument("--output", type=int, default=0, help="index de l'écran capturé (ddagrab output_idx)")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--bitrate", default="30M")
    return parser.parse_args()


def ffmpeg_command(args: argparse.Namespace) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        # hwdownload : sur le portable hybride l'écran est sur l'AMD et NVENC sur la NVIDIA (corrigé en phase 2).
        "-f", "lavfi", "-i", f"ddagrab=output_idx={args.output}:framerate={args.fps},hwdownload,format=bgra",
        *ENCODERS[args.encoder],
        "-rc", "cbr", "-b:v", args.bitrate, "-bf", "0", "-g", str(args.fps),
        "-bsf:v", "h264_metadata=aud=insert", "-f", "h264", "-",
    ]


def find_adb() -> str:
    found = shutil.which("adb")
    if found:
        return found
    if ADB_FALLBACK.exists():
        return str(ADB_FALLBACK)
    sys.exit("adb introuvable : installe Android platform-tools ou ajoute-le au PATH.")


def setup_adb_forward(adb: str) -> None:
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, check=True).stdout
    states = [line.split("\t")[1] for line in out.splitlines()[1:] if "\t" in line]
    if not states:
        sys.exit("Aucune tablette détectée : branche le câble USB et active le débogage USB.")
    if "unauthorized" in states:
        sys.exit("Tablette non autorisée : accepte la demande de débogage USB sur l'écran de la tablette.")
    if states.count("device") != 1:
        sys.exit(f"Il faut exactement une tablette prête. État actuel : {states}")
    subprocess.run([adb, "forward", f"tcp:{protocol.PORT}", f"tcp:{protocol.PORT}"], check=True)


def connect() -> tuple[socket.socket, BinaryIO, protocol.Hello]:
    """Connects through adb forward and waits for HELLO, retrying while the app isn't listening."""
    announced = False
    while True:
        sock = None
        try:
            sock = socket.create_connection(("127.0.0.1", protocol.PORT), timeout=2)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # adb accepte la connexion locale même si rien n'écoute sur la tablette : seul le HELLO prouve que l'app est là.
            rfile = sock.makefile("rb")
            hello = protocol.read_message(rfile)
            sock.settimeout(None)
        except (OSError, EOFError, protocol.ProtocolError):
            if sock is not None:
                sock.close()
            if not announced:
                print("En attente de l'app sur la tablette (ouvre TabX)…")
                announced = True
            time.sleep(1)
            continue
        if not isinstance(hello, protocol.Hello):
            sys.exit(f"Premier message inattendu de la tablette : {hello}")
        if hello.version != protocol.VERSION:
            sys.exit(f"Protocole incompatible : tablette v{hello.version}, relais v{protocol.VERSION}. "
                     "Mets à jour l'app ou le relais.")
        return sock, rfile, hello


def stream(source: BinaryIO, send: Callable[[bytes], None], fps: int, stop: threading.Event) -> None:
    """Forwards ffmpeg's Annex-B output as TABX messages until EOF or stop."""
    splitter = annexb.AccessUnitSplitter()
    size: tuple[int, int] | None = None
    last_sps: bytes | None = None
    while not stop.is_set():
        chunk = source.read1(65536)
        if not chunk:
            return
        for unit in splitter.feed(chunk):
            info = annexb.describe(unit)
            if size is None and not (info.is_idr and info.sps and info.pps):
                continue  # on attend la première IDR avec ses SPS/PPS
            if info.sps is not None and info.pps is not None and info.sps != last_sps:
                new_size = annexb.parse_sps_size(info.sps)
                if new_size != size:
                    size = new_size
                    send(protocol.encode_config(size[0], size[1], fps))
                    print(f"Flux : {size[0]}x{size[1]} @ {fps} fps")
                codec_config = annexb.START_CODE + info.sps + annexb.START_CODE + info.pps
                send(protocol.encode_video(now_us(), codec_config, protocol.FLAG_CODEC_CONFIG))
                last_sps = info.sps
            send(protocol.encode_video(now_us(), unit, protocol.FLAG_KEY if info.is_idr else 0))


def run_session(sock: socket.socket, rfile: BinaryIO, args: argparse.Namespace) -> None:
    """Streams until the tablet disconnects. Exits the program if ffmpeg stops on its own."""
    send_lock = threading.Lock()

    def send(data: bytes) -> None:
        with send_lock:
            sock.sendall(data)

    ffmpeg = subprocess.Popen(ffmpeg_command(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
    disconnected = threading.Event()

    def pump_stderr() -> None:
        for line in ffmpeg.stderr:
            text = line.decode(errors="replace").rstrip()
            stderr_tail.append(text)
            print(f"[ffmpeg] {text}")

    def read_tablet() -> None:
        try:
            while True:
                message = protocol.read_message(rfile)
                if isinstance(message, protocol.Ping):
                    send(protocol.encode_pong(message.t_tab_us, now_us()))
                elif isinstance(message, protocol.Stats):
                    print(f"{message.fps:3d} fps | latence moy {message.latency_avg_us / 1000:5.1f} ms, "
                          f"max {message.latency_max_us / 1000:5.1f} ms | perdues {message.dropped} | "
                          f"RTT {message.rtt_us / 1000:.2f} ms")
                elif isinstance(message, protocol.KeyframeRequest):
                    print("Keyframe demandée : prochaine IDR sous 1 s (GOP fixe en phase 1)")
        except (EOFError, OSError, protocol.ProtocolError) as e:
            print(f"Tablette déconnectée ({e})")
        finally:
            disconnected.set()
            ffmpeg.kill()

    threading.Thread(target=pump_stderr, daemon=True).start()
    threading.Thread(target=read_tablet, daemon=True).start()
    send_failed = False
    try:
        stream(ffmpeg.stdout, send, args.fps, disconnected)
    except OSError:
        send_failed = True  # sendall a échoué : la tablette est partie
    finally:
        tablet_gone = send_failed or disconnected.is_set()
        ffmpeg.kill()
        ffmpeg.wait()
        sock.close()
    if not tablet_gone:
        print("ffmpeg s'est arrêté de lui-même. Dernières lignes :", *stderr_tail, sep="\n  ")
        sys.exit(1)


def main() -> None:
    args = parse_args()
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg introuvable : winget install Gyan.FFmpeg, puis rouvre le terminal.")
    adb = find_adb()
    try:
        while True:
            setup_adb_forward(adb)
            sock, rfile, hello = connect()
            print(f"Tablette connectée : écran {hello.width}x{hello.height}, {hello.dpi} dpi")
            run_session(sock, rfile, args)
            print("Nouvelle tentative de connexion…")
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Vérifier l'aide**

```powershell
cd host-prototype; py relay.py --help; cd ..
```

Attendu : usage avec `--encoder {amf,nvenc}`, `--output`, `--fps`, `--bitrate`.

- [ ] **Step 3 : Vérifier le message sans tablette** (câble débranché)

```powershell
cd host-prototype; py relay.py --encoder nvenc; cd ..
```

Attendu : `Aucune tablette détectée : branche le câble USB et active le débogage USB.`, code de sortie 1.

- [ ] **Step 4 : Vérifier la commande ffmpeg seule** (5 secondes de capture vers un fichier, sans tablette)

```powershell
ffmpeg -hide_banner -loglevel warning -f lavfi -i "ddagrab=output_idx=0:framerate=60,hwdownload,format=bgra" -t 5 -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -delay 0 -rc cbr -b:v 30M -bf 0 -g 60 -bsf:v h264_metadata=aud=insert -f h264 $env:TEMP\tabx-test.h264
py -c "import sys; sys.path.insert(0, 'host-prototype'); import annexb; d = open(sys.argv[1], 'rb').read(); s = annexb.AccessUnitSplitter(); u = s.feed(d); print(len(u), 'unités,', sum(annexb.describe(x).is_idr for x in u), 'IDR, taille', annexb.parse_sps_size(annexb.describe(u[0]).sps))" $env:TEMP\tabx-test.h264
```

Attendu : environ `299 unités, 5 IDR, taille (L, H)`, où (L, H) est la résolution de l'écran principal. Si NVENC échoue (« No capable devices found »), PC sur batterie : refaire avec `-c:v h264_amf -usage ultralowlatency -quality speed` à la place des options nvenc.

- [ ] **Step 5 : Commit**

```powershell
git add host-prototype/relay.py
git commit -m "feat(relay): add ffmpeg-to-tablet relay over adb forward"
```

---

### Task 6 : Squelette du projet Android

**Files:**
- Create: `android/settings.gradle.kts`
- Create: `android/build.gradle.kts`
- Create: `android/gradle.properties`
- Create: `android/local.properties` (non versionné)
- Create: `android/app/build.gradle.kts`
- Create: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/dev/tabx/client/MainActivity.kt` (provisoire, remplacé en tâche 11)
- Generate: `android/gradlew`, `android/gradlew.bat`, `android/gradle/wrapper/*`

- [ ] **Step 1 : `android/settings.gradle.kts`**

```kotlin
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "TabX"
include(":app")
```

- [ ] **Step 2 : `android/build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application") version "9.0.1" apply false
    // AGP 9 intègre Kotlin (KGP 2.2.10) : le plugin Compose doit avoir la même version.
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10" apply false
}
```

- [ ] **Step 3 : `android/gradle.properties`**

```properties
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
```

- [ ] **Step 4 : `android/local.properties`** (ignoré par git)

```properties
sdk.dir=C\:\\Users\\zachl\\AppData\\Local\\Android\\Sdk
```

- [ ] **Step 5 : `android/app/build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "dev.tabx.client"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.tabx.client"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }

    testOptions {
        unitTests.all {
            it.systemProperty("tabx.vectors", rootProject.file("../protocol/test-vectors.json").absolutePath)
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")

    testImplementation("junit:junit:4.13.2")
    // android.jar ne fournit qu'un bouchon de org.json en test JVM : on embarque la vraie implémentation.
    testImplementation("org.json:json:20240303")
}
```

- [ ] **Step 6 : `android/app/src/main/AndroidManifest.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <!-- Obligatoire pour ouvrir un ServerSocket, même en loopback. -->
    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:label="TabX"
        android:theme="@android:style/Theme.Material.NoActionBar.Fullscreen">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:screenOrientation="sensorLandscape"
            android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

- [ ] **Step 7 : `MainActivity.kt` provisoire** (`android/app/src/main/java/dev/tabx/client/MainActivity.kt`)

```kotlin
package dev.tabx.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.text.BasicText

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { BasicText("TabX") }
    }
}
```

- [ ] **Step 8 : Générer le wrapper Gradle avec la distribution 9.1.0 en cache**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$gradle = Get-ChildItem "$env:USERPROFILE\.gradle\wrapper\dists\gradle-9.1.0-all" -Recurse -Filter gradle.bat | Select-Object -First 1
cd android; & $gradle.FullName wrapper --gradle-version 9.1.0; cd ..
```

Attendu : `BUILD SUCCESSFUL`, avec `android/gradlew.bat` et `android/gradle/wrapper/gradle-wrapper.jar` créés.

- [ ] **Step 9 : Compiler l'APK**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:assembleDebug; cd ..
```

Attendu : `BUILD SUCCESSFUL`.

En cas d'échec :
- Erreur de version du plugin Compose contre la version de Kotlin : mettre dans `android/build.gradle.kts` la version de Kotlin indiquée par le message d'erreur.
- Erreur « Inconsistent JVM-target compatibility » : ajouter à la fin de `android/app/build.gradle.kts` :

```kotlin
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
```

- [ ] **Step 10 : Commit**

```powershell
git add android
git commit -m "build(android): scaffold Compose app (AGP 9.0.1, Gradle 9.1.0)"
```

Vérifier avec `git status` que `android/local.properties` et `android/.gradle/` ne sont **pas** commités.

---

### Task 7 : Protocole côté Kotlin

**Files:**
- Create: `android/app/src/test/java/dev/tabx/client/protocol/TestHex.kt`
- Create: `android/app/src/test/java/dev/tabx/client/protocol/ProtocolVectorsTest.kt`
- Create: `android/app/src/test/java/dev/tabx/client/protocol/FrameReaderTest.kt`
- Create: `android/app/src/main/java/dev/tabx/client/protocol/Messages.kt`
- Create: `android/app/src/main/java/dev/tabx/client/protocol/FrameReader.kt`
- Create: `android/app/src/main/java/dev/tabx/client/protocol/FrameWriter.kt`

- [ ] **Step 1 : Fonctions utilitaires de test, `TestHex.kt`**

```kotlin
package dev.tabx.client.protocol

fun hex(text: String): ByteArray = text.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
```

- [ ] **Step 2 : Test des vecteurs partagés, `ProtocolVectorsTest.kt`**

```kotlin
package dev.tabx.client.protocol

import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File

class ProtocolVectorsTest {
    private val vectors = JSONObject(File(System.getProperty("tabx.vectors")!!).readText())

    @Test
    fun decodesPcToTabletVectors() {
        val list = vectors.getJSONArray("pc_to_tablet")
        for (i in 0 until list.length()) {
            val vector = list.getJSONObject(i)
            val f = vector.getJSONObject("fields")
            val message = FrameReader(ByteArrayInputStream(hex(vector.getString("hex")))).read()
            when (vector.getString("type")) {
                "CONFIG" -> assertEquals(
                    PcMessage.Config(f.getInt("codec"), f.getInt("width"), f.getInt("height"), f.getInt("fps")),
                    message,
                )
                "VIDEO" -> {
                    message as PcMessage.Video
                    assertEquals(f.getLong("pts_us"), message.ptsUs)
                    assertEquals(f.getInt("flags"), message.flags)
                    assertArrayEquals(hex(f.getString("data")), message.data)
                }
                "PONG" -> assertEquals(PcMessage.Pong(f.getLong("t_tab_us"), f.getLong("t_pc_us")), message)
                else -> fail("type inattendu : ${vector.getString("type")}")
            }
        }
    }

    @Test
    fun encodesTabletToPcVectors() {
        val list = vectors.getJSONArray("tablet_to_pc")
        for (i in 0 until list.length()) {
            val vector = list.getJSONObject(i)
            val f = vector.getJSONObject("fields")
            val message = when (vector.getString("type")) {
                "HELLO" -> TabletMessage.Hello(f.getInt("width"), f.getInt("height"), f.getInt("dpi"), f.getInt("version"))
                "PING" -> TabletMessage.Ping(f.getLong("t_tab_us"))
                "KEYFRAME_REQ" -> TabletMessage.KeyframeRequest
                "STATS" -> TabletMessage.Stats(
                    f.getInt("fps"), f.getLong("latency_avg_us"), f.getLong("latency_max_us"),
                    f.getLong("dropped"), f.getLong("rtt_us"),
                )
                else -> error("type inattendu : ${vector.getString("type")}")
            }
            assertEquals(vector.getString("name"), vector.getString("hex"), FrameWriter.encode(message).toHex())
        }
    }
}
```

- [ ] **Step 3 : Tests des cas limites du lecteur, `FrameReaderTest.kt`**

```kotlin
package dev.tabx.client.protocol

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.EOFException

class FrameReaderTest {
    private val pongHex = "030000000000001000000000075bcd15000000003ade68b1"

    private fun read(hexText: String) = FrameReader(ByteArrayInputStream(hex(hexText))).read()

    @Test
    fun skipsUnknownTypes() {
        assertEquals(PcMessage.Pong(123456789, 987654321), read("9900000000000003" + "010203" + pongHex))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsOversizedPayload() {
        read("0200000001000001")
    }

    @Test(expected = EOFException::class)
    fun truncatedStreamThrowsEof() {
        read(pongHex.dropLast(2))
    }

    @Test(expected = ProtocolException::class)
    fun rejectsConfigWithWrongSize() {
        read("0100000000000006" + "010780043800")
    }

    @Test(expected = ProtocolException::class)
    fun rejectsVideoShorterThanTimestamp() {
        read("0200000000000004" + "00000000")
    }
}
```

- [ ] **Step 4 : Lancer, vérifier l'échec de compilation**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:testDebugUnitTest; cd ..
```

Attendu : FAIL, `Unresolved reference 'FrameReader'` (ainsi que `PcMessage`, `TabletMessage`, `FrameWriter`).

- [ ] **Step 5 : `Messages.kt`**

```kotlin
package dev.tabx.client.protocol

import java.io.IOException

/** TABX protocol v1 constants. Reference: protocol/PROTOCOL.md. */
object Protocol {
    const val VERSION = 1
    const val PORT = 27183
    const val HEADER_SIZE = 8
    const val MAX_PAYLOAD = 16 * 1024 * 1024
    val MAGIC: ByteArray = "TABX".toByteArray(Charsets.US_ASCII)

    // PC -> tablet
    const val TYPE_CONFIG = 0x01
    const val TYPE_VIDEO = 0x02
    const val TYPE_PONG = 0x03

    // tablet -> PC
    const val TYPE_HELLO = 0x81
    const val TYPE_PING = 0x82
    const val TYPE_KEYFRAME_REQ = 0x83
    const val TYPE_STATS = 0x84

    const val FLAG_KEY = 0x01
    const val FLAG_CODEC_CONFIG = 0x02
    const val CODEC_H264 = 1
}

class ProtocolException(message: String) : IOException(message)

/** Messages received from the PC. */
sealed interface PcMessage {
    data class Config(val codec: Int, val width: Int, val height: Int, val fps: Int) : PcMessage

    class Video(val ptsUs: Long, val flags: Int, val data: ByteArray) : PcMessage {
        val isKey: Boolean get() = (flags and Protocol.FLAG_KEY) != 0
        val isCodecConfig: Boolean get() = (flags and Protocol.FLAG_CODEC_CONFIG) != 0
    }

    data class Pong(val tTabUs: Long, val tPcUs: Long) : PcMessage
}

/** Messages sent to the PC. */
sealed interface TabletMessage {
    data class Hello(val width: Int, val height: Int, val dpi: Int, val version: Int = Protocol.VERSION) : TabletMessage

    data class Ping(val tTabUs: Long) : TabletMessage

    data object KeyframeRequest : TabletMessage

    data class Stats(
        val fps: Int,
        val latencyAvgUs: Long,
        val latencyMaxUs: Long,
        val dropped: Long,
        val rttUs: Long,
    ) : TabletMessage
}
```

- [ ] **Step 6 : `FrameReader.kt`**

```kotlin
package dev.tabx.client.protocol

import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.InputStream

/** Reads PC -> tablet messages. Not thread-safe: use from a single reader thread. */
class FrameReader(input: InputStream) {
    private val stream = DataInputStream(BufferedInputStream(input, 64 * 1024))

    /** Blocks until the next known message; unknown types are skipped. Throws EOFException at end of stream. */
    fun read(): PcMessage {
        while (true) {
            val type = stream.readUnsignedByte()
            val flags = stream.readUnsignedByte()
            stream.readUnsignedShort() // reserved
            val length = stream.readInt().toLong() and 0xFFFF_FFFFL
            if (length > Protocol.MAX_PAYLOAD) throw ProtocolException("payload trop gros : $length octets")
            val size = length.toInt()
            when (type) {
                Protocol.TYPE_CONFIG -> {
                    expectSize("CONFIG", size, 7)
                    return PcMessage.Config(
                        codec = stream.readUnsignedByte(),
                        width = stream.readUnsignedShort(),
                        height = stream.readUnsignedShort(),
                        fps = stream.readUnsignedShort(),
                    )
                }
                Protocol.TYPE_VIDEO -> {
                    if (size < 8) throw ProtocolException("VIDEO trop court : $size octets")
                    val ptsUs = stream.readLong()
                    val data = ByteArray(size - 8)
                    stream.readFully(data)
                    return PcMessage.Video(ptsUs, flags, data)
                }
                Protocol.TYPE_PONG -> {
                    expectSize("PONG", size, 16)
                    return PcMessage.Pong(stream.readLong(), stream.readLong())
                }
                else -> stream.readFully(ByteArray(size))
            }
        }
    }

    private fun expectSize(name: String, actual: Int, expected: Int) {
        if (actual != expected) throw ProtocolException("$name : $actual octets au lieu de $expected")
    }
}
```

- [ ] **Step 7 : `FrameWriter.kt`**

```kotlin
package dev.tabx.client.protocol

import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.OutputStream
import java.nio.ByteBuffer

/** Writes tablet -> PC messages. Thread-safe. */
class FrameWriter(output: OutputStream) {
    private val stream = BufferedOutputStream(output)

    @Synchronized
    fun write(message: TabletMessage) {
        stream.write(encode(message))
        stream.flush()
    }

    companion object {
        fun encode(message: TabletMessage): ByteArray {
            val payload = ByteArrayOutputStream()
            val out = DataOutputStream(payload)
            val type = when (message) {
                is TabletMessage.Hello -> {
                    out.write(Protocol.MAGIC)
                    out.writeShort(message.version)
                    out.writeShort(message.width)
                    out.writeShort(message.height)
                    out.writeShort(message.dpi)
                    Protocol.TYPE_HELLO
                }
                is TabletMessage.Ping -> {
                    out.writeLong(message.tTabUs)
                    Protocol.TYPE_PING
                }
                TabletMessage.KeyframeRequest -> Protocol.TYPE_KEYFRAME_REQ
                is TabletMessage.Stats -> {
                    out.writeShort(message.fps)
                    out.writeInt(message.latencyAvgUs.toInt())
                    out.writeInt(message.latencyMaxUs.toInt())
                    out.writeInt(message.dropped.toInt())
                    out.writeInt(message.rttUs.toInt())
                    Protocol.TYPE_STATS
                }
            }
            val body = payload.toByteArray()
            return ByteBuffer.allocate(Protocol.HEADER_SIZE + body.size)
                .put(type.toByte())
                .put(0.toByte())
                .putShort(0.toShort())
                .putInt(body.size)
                .put(body)
                .array()
        }
    }
}
```

- [ ] **Step 8 : Lancer les tests, vérifier qu'ils passent**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:testDebugUnitTest; cd ..
```

Attendu : `BUILD SUCCESSFUL`. Le rapport `android/app/build/reports/tests/testDebugUnitTest/index.html` doit montrer 7 tests, 0 échec.

- [ ] **Step 9 : Commit**

```powershell
git add android/app/src
git commit -m "feat(android): add TABX protocol reader/writer with shared vectors"
```

---

### Task 8 : `LatencyTracker`

**Files:**
- Create: `android/app/src/test/java/dev/tabx/client/stats/LatencyTrackerTest.kt`
- Create: `android/app/src/main/java/dev/tabx/client/stats/LatencyTracker.kt`

- [ ] **Step 1 : Écrire le test qui échoue**

```kotlin
package dev.tabx.client.stats

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LatencyTrackerTest {

    @Test
    fun offsetFromSinglePong() {
        val tracker = LatencyTracker()
        tracker.onPong(tTabSentUs = 1_000, tPcUs = 50_000, tTabReceivedUs = 1_200) // rtt 200
        assertEquals(1_000L + 100 - 50_000, tracker.takeWindow().offsetUs)
    }

    @Test
    fun keepsOffsetOfSmallestRtt() {
        val tracker = LatencyTracker()
        tracker.onPong(1_000, 50_000, 1_200) // rtt 200 -> offset -48_900
        tracker.onPong(2_000, 51_000, 2_600) // rtt 600 -> ignored
        assertEquals(-48_900L, tracker.takeWindow().offsetUs)
        tracker.onPong(3_000, 52_000, 3_100) // rtt 100 -> offset -48_950
        assertEquals(-48_950L, tracker.takeWindow().offsetUs)
    }

    @Test
    fun oldClockSamplesLeaveTheWindow() {
        val tracker = LatencyTracker(clockSamples = 2)
        tracker.onPong(0, 0, 100) // rtt 100, sera évincé
        tracker.onPong(1_000, 0, 1_400) // rtt 400 -> offset 1_200
        tracker.onPong(2_000, 0, 2_300) // rtt 300 -> offset 2_150
        assertEquals(2_150L, tracker.takeWindow().offsetUs)
    }

    @Test
    fun latencyStatsAndPercentiles() {
        val tracker = LatencyTracker()
        tracker.onPong(0, 0, 0) // offset 0
        tracker.onFrameRendered(ptsUs = 1_000, renderedUs = 11_000) // 10 ms
        tracker.onFrameRendered(ptsUs = 2_000, renderedUs = 32_000) // 30 ms
        val window = tracker.takeWindow()
        assertEquals(2, window.fps)
        assertEquals(20_000L, window.latencyAvgUs)
        assertEquals(30_000L, window.latencyMaxUs)
        assertEquals(10, window.p50Ms)
        assertEquals(30, window.p99Ms)
    }

    @Test
    fun framesBeforeClockSyncCountForFpsOnly() {
        val tracker = LatencyTracker()
        tracker.onFrameRendered(0, 5_000)
        val window = tracker.takeWindow()
        assertEquals(1, window.fps)
        assertEquals(0L, window.latencyAvgUs)
        assertNull(window.offsetUs)
    }

    @Test
    fun windowResetsButPercentilesCoverSession() {
        val tracker = LatencyTracker()
        tracker.onPong(0, 0, 0)
        tracker.onFrameRendered(0, 12_000)
        tracker.onFrameDropped()
        val first = tracker.takeWindow()
        assertEquals(1L, first.dropped)
        val second = tracker.takeWindow()
        assertEquals(0, second.fps)
        assertEquals(0L, second.dropped)
        assertEquals(12, second.p50Ms)
    }

    @Test
    fun rttIsTheLastMeasured() {
        val tracker = LatencyTracker()
        tracker.onPong(0, 0, 300)
        tracker.onPong(1_000, 0, 1_800)
        assertEquals(800L, tracker.takeWindow().rttUs)
    }
}
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:testDebugUnitTest; cd ..
```

Attendu : FAIL, `Unresolved reference 'LatencyTracker'`.

- [ ] **Step 3 : Écrire `LatencyTracker.kt`**

```kotlin
package dev.tabx.client.stats

import kotlin.math.ceil

/**
 * Clock sync (offset of the smallest-RTT sample among recent ping/pongs) and per-frame latency stats.
 * Times are microseconds; the offset converts PC time to tablet time. Thread-safe.
 */
class LatencyTracker(private val clockSamples: Int = 16) {

    data class Window(
        val fps: Int,
        val latencyAvgUs: Long,
        val latencyMaxUs: Long,
        val dropped: Long,
        val rttUs: Long,
        val p50Ms: Int,
        val p99Ms: Int,
        val offsetUs: Long?,
    )

    private class ClockSample(val rttUs: Long, val offsetUs: Long)

    private val samples = ArrayDeque<ClockSample>()
    private val histogram = IntArray(HISTOGRAM_MAX_MS + 1)
    private var histogramCount = 0L
    private var offsetUs: Long? = null
    private var lastRttUs = 0L
    private var frames = 0
    private var latencyCount = 0
    private var latencySumUs = 0L
    private var latencyMaxUs = 0L
    private var dropped = 0L

    @Synchronized
    fun onPong(tTabSentUs: Long, tPcUs: Long, tTabReceivedUs: Long) {
        val rtt = tTabReceivedUs - tTabSentUs
        samples.addLast(ClockSample(rtt, tTabSentUs + rtt / 2 - tPcUs))
        if (samples.size > clockSamples) samples.removeFirst()
        offsetUs = samples.minBy { it.rttUs }.offsetUs
        lastRttUs = rtt
    }

    @Synchronized
    fun onFrameRendered(ptsUs: Long, renderedUs: Long) {
        frames++
        val offset = offsetUs ?: return
        val latency = renderedUs - (ptsUs + offset)
        latencyCount++
        latencySumUs += latency
        latencyMaxUs = maxOf(latencyMaxUs, latency)
        histogram[(latency / 1000).coerceIn(0, HISTOGRAM_MAX_MS.toLong()).toInt()]++
        histogramCount++
    }

    @Synchronized
    fun onFrameDropped() {
        dropped++
    }

    /** Stats since the previous call (percentiles cover the whole session), then resets the window. */
    @Synchronized
    fun takeWindow(): Window {
        val window = Window(
            fps = frames,
            latencyAvgUs = if (latencyCount > 0) latencySumUs / latencyCount else 0,
            latencyMaxUs = latencyMaxUs,
            dropped = dropped,
            rttUs = lastRttUs,
            p50Ms = percentileMs(0.50),
            p99Ms = percentileMs(0.99),
            offsetUs = offsetUs,
        )
        frames = 0
        latencyCount = 0
        latencySumUs = 0
        latencyMaxUs = 0
        dropped = 0
        return window
    }

    private fun percentileMs(quantile: Double): Int {
        if (histogramCount == 0L) return 0
        val target = ceil(quantile * histogramCount).toLong().coerceAtLeast(1)
        var cumulative = 0L
        for (ms in histogram.indices) {
            cumulative += histogram[ms]
            if (cumulative >= target) return ms
        }
        return HISTOGRAM_MAX_MS
    }

    companion object {
        const val HISTOGRAM_MAX_MS = 500
    }
}
```

- [ ] **Step 4 : Lancer, vérifier que tout passe**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:testDebugUnitTest; cd ..
```

Attendu : `BUILD SUCCESSFUL`, 14 tests, 0 échec.

- [ ] **Step 5 : Commit**

```powershell
git add android/app/src
git commit -m "feat(android): add latency tracker with clock sync and percentiles"
```

---

### Task 9 : Décodeur vidéo

Ce code dépend de MediaCodec, qui n'existe pas en test JVM : il est vérifié par la compilation ici, puis sur la tablette (tâche 12).

**Files:**
- Create: `android/app/src/main/java/dev/tabx/client/video/VideoDecoder.kt`

- [ ] **Step 1 : Écrire `VideoDecoder.kt`**

```kotlin
package dev.tabx.client.video

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Surface
import dev.tabx.client.protocol.PcMessage
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Raised when the decoder must be recreated (codec error or stalled input). */
class DecoderFailure(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * Hardware H.264 decoder rendering straight to [surface], in async mode.
 * [submit] and [release] must be called from the same thread (the network reader).
 * [onFrameRendered] receives the pts (µs) and the System.nanoTime() of actual display.
 */
class VideoDecoder(
    config: PcMessage.Config,
    surface: Surface,
    onFrameRendered: (ptsUs: Long, renderedNanos: Long) -> Unit,
) {
    private val thread = HandlerThread("codec").apply { start() }
    private val handler = Handler(thread.looper)
    private val freeInputs = LinkedBlockingQueue<Int>()
    private val codec = MediaCodec.createDecoderByType(MIME)
    @Volatile private var failure: MediaCodec.CodecException? = null
    private var waitingForKey = true

    /** Codec name and low-latency status, shown in the HUD. */
    val description: String

    init {
        val lowLatency = codec.codecInfo.getCapabilitiesForType(MIME)
            .isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_LowLatency)
        val format = MediaFormat.createVideoFormat(MIME, config.width, config.height).apply {
            setInteger(MediaFormat.KEY_PRIORITY, 0) // temps réel
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, config.width * config.height)
            if (lowLatency) setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
        }
        codec.setCallback(object : MediaCodec.Callback() {
            override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {
                freeInputs.offer(index)
            }

            override fun onOutputBufferAvailable(codec: MediaCodec, index: Int, info: MediaCodec.BufferInfo) {
                codec.releaseOutputBuffer(index, true) // affichage immédiat, sans attendre le pts
            }

            override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
                if (e.isTransient) Log.w(TAG, "erreur transitoire du décodeur", e) else failure = e
            }

            override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {}
        }, handler)
        codec.setOnFrameRenderedListener({ _, ptsUs, nanos -> onFrameRendered(ptsUs, nanos) }, handler)
        codec.configure(format, surface, null, 0)
        codec.start()
        description = codec.name + if (lowLatency) " (low-latency)" else ""
    }

    /** Queues one frame, blocking until an input buffer is free. Returns false if the frame was skipped. */
    fun submit(frame: PcMessage.Video): Boolean {
        failure?.let { throw DecoderFailure("erreur du décodeur : ${it.diagnosticInfo}", it) }
        if (waitingForKey && !frame.isKey && !frame.isCodecConfig) return false
        if (frame.isKey) waitingForKey = false
        val index = freeInputs.poll(INPUT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            ?: throw DecoderFailure("décodeur bloqué : aucun buffer libre depuis $INPUT_TIMEOUT_MS ms")
        val flags = when {
            frame.isCodecConfig -> MediaCodec.BUFFER_FLAG_CODEC_CONFIG
            frame.isKey -> MediaCodec.BUFFER_FLAG_KEY_FRAME
            else -> 0
        }
        try {
            val buffer = codec.getInputBuffer(index) ?: throw DecoderFailure("buffer d'entrée $index indisponible")
            buffer.clear()
            buffer.put(frame.data)
            codec.queueInputBuffer(index, 0, frame.data.size, frame.ptsUs, flags)
        } catch (e: IllegalStateException) {
            throw DecoderFailure("décodeur dans un état invalide", e)
        }
        return true
    }

    fun release() {
        runCatching { codec.stop() }
        codec.release()
        thread.quitSafely()
    }

    private companion object {
        const val MIME = MediaFormat.MIMETYPE_VIDEO_AVC
        const val INPUT_TIMEOUT_MS = 500L
        const val TAG = "VideoDecoder"
    }
}
```

- [ ] **Step 2 : Compiler**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:assembleDebug; cd ..
```

Attendu : `BUILD SUCCESSFUL`.

- [ ] **Step 3 : Commit**

```powershell
git add android/app/src
git commit -m "feat(android): add low-latency MediaCodec H.264 decoder"
```

---

### Task 10 : Réseau, session et boucle d'accept

**Files:**
- Create: `android/app/src/main/java/dev/tabx/client/net/Server.kt`
- Create: `android/app/src/main/java/dev/tabx/client/Session.kt`
- Create: `android/app/src/main/java/dev/tabx/client/UiModel.kt`
- Create: `android/app/src/main/java/dev/tabx/client/Receiver.kt`

- [ ] **Step 1 : `net/Server.kt`**

```kotlin
package dev.tabx.client.net

import dev.tabx.client.protocol.Protocol
import java.io.Closeable
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket

/** Loopback-only listening socket: reachable through `adb forward`, never from the Wi-Fi. */
class Server(port: Int = Protocol.PORT) : Closeable {
    private val serverSocket = ServerSocket().apply {
        reuseAddress = true
        bind(InetSocketAddress(InetAddress.getLoopbackAddress(), port), 1) // BindException si le port est pris
    }

    fun accept(): Socket = serverSocket.accept()

    override fun close() = serverSocket.close()
}
```

- [ ] **Step 2 : `Session.kt`**

```kotlin
package dev.tabx.client

import android.util.Log
import android.view.Surface
import dev.tabx.client.protocol.FrameReader
import dev.tabx.client.protocol.FrameWriter
import dev.tabx.client.protocol.PcMessage
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.ProtocolException
import dev.tabx.client.protocol.TabletMessage
import dev.tabx.client.stats.LatencyTracker
import dev.tabx.client.video.DecoderFailure
import dev.tabx.client.video.VideoDecoder
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Physical screen in landscape, sent in HELLO. */
data class ScreenInfo(val width: Int, val height: Int, val dpi: Int)

/** One PC connection: handshake, decode loop, ping and stats timers. [run] blocks until the connection ends. */
class Session(
    private val socket: Socket,
    private val surface: Surface,
    private val screen: ScreenInfo,
    private val listener: Listener,
) {
    interface Listener {
        fun onStreaming(config: PcMessage.Config, decoder: String)
        fun onStats(window: LatencyTracker.Window)
    }

    private val tracker = LatencyTracker()

    fun run() {
        socket.tcpNoDelay = true
        val reader = FrameReader(socket.getInputStream())
        val writer = FrameWriter(socket.getOutputStream())
        val timers = Executors.newSingleThreadScheduledExecutor { Thread(it, "net-writer") }
        var decoder: VideoDecoder? = null
        var config: PcMessage.Config? = null
        try {
            writer.write(TabletMessage.Hello(screen.width, screen.height, screen.dpi))
            timers.scheduleWithFixedDelay({ writer.write(TabletMessage.Ping(nowUs())) },
                0, PING_INTERVAL_MS, TimeUnit.MILLISECONDS)
            timers.scheduleWithFixedDelay({ sendStats(writer) },
                STATS_INTERVAL_MS, STATS_INTERVAL_MS, TimeUnit.MILLISECONDS)
            while (true) {
                when (val message = reader.read()) {
                    is PcMessage.Config -> {
                        if (message.codec != Protocol.CODEC_H264) {
                            throw ProtocolException("codec non supporté : ${message.codec}")
                        }
                        decoder?.release()
                        decoder = createDecoder(message)
                        config = message
                        writer.write(TabletMessage.KeyframeRequest)
                        listener.onStreaming(message, decoder.description)
                    }
                    is PcMessage.Video -> {
                        val current = decoder ?: continue // vidéo reçue avant CONFIG : ignorée
                        try {
                            if (!current.submit(message)) tracker.onFrameDropped()
                        } catch (e: DecoderFailure) {
                            Log.w(TAG, "recréation du décodeur", e)
                            current.release()
                            decoder = createDecoder(config!!)
                            tracker.onFrameDropped()
                            writer.write(TabletMessage.KeyframeRequest)
                        }
                    }
                    is PcMessage.Pong -> tracker.onPong(message.tTabUs, message.tPcUs, nowUs())
                }
            }
        } finally {
            timers.shutdownNow()
            decoder?.release()
            socket.close()
        }
    }

    private fun createDecoder(config: PcMessage.Config) =
        VideoDecoder(config, surface) { ptsUs, renderedNanos -> tracker.onFrameRendered(ptsUs, renderedNanos / 1000) }

    private fun sendStats(writer: FrameWriter) {
        val window = tracker.takeWindow()
        listener.onStats(window)
        writer.write(
            TabletMessage.Stats(
                fps = window.fps,
                latencyAvgUs = window.latencyAvgUs.coerceAtLeast(0),
                latencyMaxUs = window.latencyMaxUs.coerceAtLeast(0),
                dropped = window.dropped,
                rttUs = window.rttUs.coerceAtLeast(0),
            ),
        )
    }

    private companion object {
        const val TAG = "Session"
        const val PING_INTERVAL_MS = 500L
        const val STATS_INTERVAL_MS = 1000L
        fun nowUs() = System.nanoTime() / 1000
    }
}
```

- [ ] **Step 3 : `UiModel.kt`**

```kotlin
package dev.tabx.client

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import dev.tabx.client.protocol.PcMessage
import dev.tabx.client.stats.LatencyTracker

sealed interface ConnectionState {
    data class Waiting(val reason: String?) : ConnectionState
    data class Streaming(val width: Int, val height: Int) : ConnectionState
}

data class HudData(
    val fps: Int,
    val avgMs: Double,
    val maxMs: Double,
    val p50Ms: Int,
    val p99Ms: Int,
    val offsetMs: Double?,
    val decoder: String,
)

/** Compose-observable app state. Written from background threads, read by the UI. */
class UiModel : Session.Listener {
    var state by mutableStateOf<ConnectionState>(ConnectionState.Waiting(null))
        private set
    var hud by mutableStateOf<HudData?>(null)
        private set
    var hudVisible by mutableStateOf(false)
        private set

    @Volatile private var decoderName = ""

    fun showWaiting(reason: String?) {
        state = ConnectionState.Waiting(reason)
        hud = null
    }

    fun toggleHud() {
        hudVisible = !hudVisible
    }

    override fun onStreaming(config: PcMessage.Config, decoder: String) {
        decoderName = decoder
        state = ConnectionState.Streaming(config.width, config.height)
    }

    override fun onStats(window: LatencyTracker.Window) {
        hud = HudData(
            fps = window.fps,
            avgMs = window.latencyAvgUs / 1000.0,
            maxMs = window.latencyMaxUs / 1000.0,
            p50Ms = window.p50Ms,
            p99Ms = window.p99Ms,
            offsetMs = window.offsetUs?.let { it / 1000.0 },
            decoder = decoderName,
        )
    }
}
```

- [ ] **Step 4 : `Receiver.kt`**

```kotlin
package dev.tabx.client

import android.util.Log
import android.view.Surface
import dev.tabx.client.net.Server
import dev.tabx.client.protocol.Protocol
import dev.tabx.client.protocol.ProtocolException
import java.io.IOException
import java.net.BindException
import java.net.Socket
import kotlin.concurrent.thread

/** Accept loop on the "net-reader" thread: one [Session] at a time until [stop]. */
class Receiver(
    private val surface: Surface,
    private val screen: ScreenInfo,
    private val model: UiModel,
) {
    @Volatile private var running = true
    @Volatile private var server: Server? = null
    @Volatile private var socket: Socket? = null
    private val worker = thread(name = "net-reader") { loop() }

    private fun loop() {
        var reason: String? = null
        while (running) {
            model.showWaiting(reason)
            try {
                val listening = server ?: Server().also { server = it }
                val connection = listening.accept().also { socket = it }
                Session(connection, surface, screen, model).run()
            } catch (e: BindException) {
                reason = "Port ${Protocol.PORT} déjà utilisé, nouvel essai…"
                model.showWaiting(reason)
                try {
                    Thread.sleep(BIND_RETRY_MS)
                } catch (e: InterruptedException) {
                    return
                }
            } catch (e: ProtocolException) {
                reason = "Protocole invalide : ${e.message}"
            } catch (e: IOException) {
                reason = "PC déconnecté"
            } catch (e: Exception) {
                Log.e(TAG, "session interrompue", e)
                reason = "Erreur : ${e.message}"
            }
        }
    }

    /** Closes sockets and waits briefly so the decoder is released before the Surface goes away. */
    fun stop() {
        running = false
        worker.interrupt()
        runCatching { server?.close() }
        runCatching { socket?.close() }
        worker.join(STOP_TIMEOUT_MS)
    }

    private companion object {
        const val TAG = "Receiver"
        const val BIND_RETRY_MS = 2000L
        const val STOP_TIMEOUT_MS = 1000L
    }
}
```

- [ ] **Step 5 : Compiler et relancer les tests**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:assembleDebug :app:testDebugUnitTest; cd ..
```

Attendu : `BUILD SUCCESSFUL`.

- [ ] **Step 6 : Commit**

```powershell
git add android/app/src
git commit -m "feat(android): add loopback server, session loop and UI model"
```

---

### Task 11 : Interface glassmorphism et activité

**Files:**
- Create: `android/app/src/main/java/dev/tabx/client/ui/Glass.kt`
- Create: `android/app/src/main/java/dev/tabx/client/ui/WaitingScreen.kt`
- Create: `android/app/src/main/java/dev/tabx/client/ui/StreamScreen.kt`
- Create: `android/app/src/main/java/dev/tabx/client/ui/TabXApp.kt`
- Modify (remplacement complet): `android/app/src/main/java/dev/tabx/client/MainActivity.kt`

- [ ] **Step 1 : `ui/Glass.kt`**

```kotlin
package dev.tabx.client.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val CardShape = RoundedCornerShape(20.dp)
private val PanelShape = RoundedCornerShape(14.dp)

private fun edgeBrush(top: Float, bottom: Float) =
    Brush.verticalGradient(listOf(Color.White.copy(alpha = top), Color.White.copy(alpha = bottom)))

/** Frosted glass: translucent fill and light edge. Place it over a blurred, colourful background. */
@Composable
fun GlassCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .clip(CardShape)
            .background(Color.White.copy(alpha = 0.10f))
            .border(1.dp, edgeBrush(0.45f, 0.12f), CardShape)
            .padding(24.dp),
        content = content,
    )
}

/** Simulated glass for overlays above the video: no blur (it would force GPU composition and add latency). */
@Composable
fun GlassPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .clip(PanelShape)
            .background(Color(0x8C141428))
            .border(1.dp, edgeBrush(0.45f, 0.15f), PanelShape)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        content = content,
    )
}

@Composable
fun GlassText(
    text: String,
    size: TextUnit = 14.sp,
    alpha: Float = 1f,
    mono: Boolean = false,
    weight: FontWeight = FontWeight.Normal,
    color: Color = Color.White,
) {
    BasicText(
        text = text,
        style = TextStyle(
            color = color.copy(alpha = alpha),
            fontSize = size,
            fontFamily = if (mono) FontFamily.Monospace else FontFamily.Default,
            fontWeight = weight,
        ),
    )
}
```

- [ ] **Step 2 : `ui/WaitingScreen.kt`**

```kotlin
package dev.tabx.client.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.tabx.client.ScreenInfo
import dev.tabx.client.protocol.Protocol

private val Night = Color(0xFF0B0B1A)
private val Violet = Color(0xFF7F77DD)
private val Teal = Color(0xFF1D9E75)
private val Pink = Color(0xFFD4537E)
private val Amber = Color(0xFFFAC775)

@Composable
fun WaitingScreen(reason: String?, screen: ScreenInfo) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        BlobBackground()
        GlassCard(Modifier.fillMaxWidth(0.55f).widthIn(max = 620.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                GlassText("TabX", size = 26.sp, weight = FontWeight.Medium)
                Spacer(Modifier.weight(1f))
                GlassText("protocole v${Protocol.VERSION}", size = 12.sp, alpha = 0.7f)
            }
            Spacer(Modifier.height(18.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                PulsingDot()
                Spacer(Modifier.width(10.dp))
                GlassText("En attente du PC…", size = 16.sp)
            }
            if (reason != null) {
                Spacer(Modifier.height(8.dp))
                GlassText(reason, size = 13.sp, color = Amber)
            }
            Spacer(Modifier.height(18.dp))
            GlassText("Sur le PC :", size = 12.sp, alpha = 0.75f)
            Spacer(Modifier.height(6.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color.Black.copy(alpha = 0.25f))
                    .border(1.dp, Color.White.copy(alpha = 0.15f), RoundedCornerShape(10.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                GlassText("py relay.py --encoder nvenc", size = 13.sp, mono = true)
            }
            Spacer(Modifier.height(16.dp))
            Row {
                GlassText("${screen.width}×${screen.height}", size = 12.sp, alpha = 0.7f)
                Spacer(Modifier.width(20.dp))
                GlassText("127.0.0.1:${Protocol.PORT}", size = 12.sp, alpha = 0.7f)
            }
        }
    }
}

/** Dark background with three slowly drifting colour blobs, blurred (real blur, API 31+). */
@Composable
private fun BlobBackground() {
    val transition = rememberInfiniteTransition(label = "blobs")
    val drift by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(12_000, easing = LinearEasing), RepeatMode.Reverse),
        label = "drift",
    )
    Box(Modifier.fillMaxSize().background(Night)) {
        Box(Modifier.fillMaxSize().blur(80.dp)) {
            Blob(Violet, 520.dp, Alignment.TopStart, x = (-80 + 140 * drift).dp, y = (-60).dp)
            Blob(Teal, 460.dp, Alignment.BottomEnd, x = (60 - 120 * drift).dp, y = 80.dp)
            Blob(Pink, 320.dp, Alignment.Center, x = (120 - 200 * drift).dp, y = (-80 + 60 * drift).dp)
        }
    }
}

@Composable
private fun BoxScope.Blob(color: Color, size: Dp, alignment: Alignment, x: Dp, y: Dp) {
    Box(
        Modifier
            .align(alignment)
            .offset(x, y)
            .size(size)
            .background(color.copy(alpha = 0.85f), CircleShape),
    )
}

@Composable
private fun PulsingDot() {
    val transition = rememberInfiniteTransition(label = "pulse")
    val alpha by transition.animateFloat(
        initialValue = 1f,
        targetValue = 0.25f,
        animationSpec = infiniteRepeatable(tween(800), RepeatMode.Reverse),
        label = "alpha",
    )
    Box(Modifier.size(8.dp).alpha(alpha).background(Color(0xFF5DCAA5), CircleShape))
}
```

- [ ] **Step 3 : `ui/StreamScreen.kt`**

```kotlin
package dev.tabx.client.ui

import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import dev.tabx.client.HudData

/** SurfaceView whose Surface feeds MediaCodec. Lifecycle callbacks drive the Receiver. */
@Composable
fun VideoSurface(modifier: Modifier, onCreated: (Surface) -> Unit, onDestroyed: () -> Unit) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            SurfaceView(context).apply {
                holder.addCallback(object : SurfaceHolder.Callback {
                    override fun surfaceCreated(holder: SurfaceHolder) = onCreated(holder.surface)
                    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}
                    override fun surfaceDestroyed(holder: SurfaceHolder) = onDestroyed()
                })
            }
        },
    )
}

@Composable
fun HudOverlay(hud: HudData, modifier: Modifier = Modifier) {
    GlassPanel(modifier) {
        GlassText("${hud.fps} fps", size = 12.sp, mono = true)
        GlassText("lat %.1f / max %.1f ms".format(hud.avgMs, hud.maxMs), size = 12.sp, mono = true)
        GlassText("p50 ${hud.p50Ms} / p99 ${hud.p99Ms} ms", size = 12.sp, mono = true)
        GlassText(hud.offsetMs?.let { "offset %+.1f ms".format(it) } ?: "offset : synchro…", size = 12.sp, mono = true)
        GlassText(hud.decoder, size = 11.sp, alpha = 0.7f, mono = true)
    }
}

/** Calls [onTap] once each time three or more fingers are down together. */
suspend fun PointerInputScope.detectThreeFingerTap(onTap: () -> Unit) {
    awaitEachGesture {
        awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        var fired = false
        do {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            if (!fired && event.changes.count { it.pressed } >= 3) {
                onTap()
                fired = true
            }
        } while (event.changes.any { it.pressed })
    }
}
```

- [ ] **Step 4 : `ui/TabXApp.kt`**

```kotlin
package dev.tabx.client.ui

import android.view.Surface
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import dev.tabx.client.ConnectionState
import dev.tabx.client.ScreenInfo
import dev.tabx.client.UiModel

/** Root: letterboxed video, waiting screen on top while disconnected, optional HUD while streaming. */
@Composable
fun TabXApp(
    model: UiModel,
    screen: ScreenInfo,
    onSurfaceCreated: (Surface) -> Unit,
    onSurfaceDestroyed: () -> Unit,
) {
    val state = model.state
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .pointerInput(Unit) { detectThreeFingerTap(model::toggleHud) },
        contentAlignment = Alignment.Center,
    ) {
        val videoModifier = if (state is ConnectionState.Streaming) {
            Modifier.aspectRatio(state.width.toFloat() / state.height)
        } else {
            Modifier.fillMaxSize()
        }
        VideoSurface(videoModifier, onSurfaceCreated, onSurfaceDestroyed)

        AnimatedVisibility(
            visible = state is ConnectionState.Waiting,
            enter = fadeIn(tween(400)),
            exit = fadeOut(tween(400)),
        ) {
            WaitingScreen((state as? ConnectionState.Waiting)?.reason, screen)
        }

        val hud = model.hud
        if (model.hudVisible && hud != null && state is ConnectionState.Streaming) {
            HudOverlay(hud, Modifier.align(Alignment.TopEnd).padding(16.dp))
        }
    }
}
```

- [ ] **Step 5 : Remplacer `MainActivity.kt`**

```kotlin
package dev.tabx.client

import android.os.Bundle
import android.view.Surface
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import dev.tabx.client.ui.TabXApp

class MainActivity : ComponentActivity() {
    private val model = UiModel()
    private var receiver: Receiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.setDecorFitsSystemWindows(false)
        val screen = screenInfo()
        setContent { TabXApp(model, screen, ::onSurfaceCreated, ::onSurfaceDestroyed) }
        window.insetsController?.let {
            it.hide(WindowInsets.Type.systemBars())
            it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    /** Physical screen size in landscape orientation. */
    private fun screenInfo(): ScreenInfo {
        val bounds = windowManager.maximumWindowMetrics.bounds
        return ScreenInfo(
            width = maxOf(bounds.width(), bounds.height()),
            height = minOf(bounds.width(), bounds.height()),
            dpi = resources.displayMetrics.densityDpi,
        )
    }

    private fun onSurfaceCreated(surface: Surface) {
        receiver?.stop()
        receiver = Receiver(surface, screenInfo(), model)
    }

    private fun onSurfaceDestroyed() {
        receiver?.stop()
        receiver = null
    }
}
```

- [ ] **Step 6 : Compiler et relancer les tests**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:assembleDebug :app:testDebugUnitTest; cd ..
```

Attendu : `BUILD SUCCESSFUL`.

- [ ] **Step 7 : Commit**

```powershell
git add android/app/src
git commit -m "feat(android): add glassmorphism UI, video surface and HUD"
```

---

### Task 12 : Intégration sur la tablette et README

**Files:**
- Create: `README.md`

- [ ] **Step 1 : Préparer la tablette** (action de l'utilisateur)

Réglages → À propos de la tablette → Informations sur le logiciel → taper 7 fois sur « Numéro de version ». Puis Options de développement → activer « Débogage USB ». Brancher le câble et accepter la demande d'autorisation sur la tablette.

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
```

Attendu : une ligne `<série>	device`.

- [ ] **Step 2 : Installer l'app**

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd android; .\gradlew.bat :app:installDebug; cd ..
```

Attendu : `Installed on 1 device.`. Ouvrir TabX : l'écran d'attente en verre dépoli s'affiche, avec la résolution 2880×1800.

- [ ] **Step 3 : Lancer le relais**

```powershell
cd host-prototype; py relay.py --encoder nvenc; cd ..
```

(sur batterie : `--encoder amf`)

Attendu côté PC : `Tablette connectée : écran 2880x1800, … dpi`, puis `Flux : LxH @ 60 fps`, puis une ligne de stats par seconde. Côté tablette : la carte disparaît en fondu et le bureau du PC s'affiche en letterbox.

- [ ] **Step 4 : Dérouler la checklist des critères de réussite**

| # | Vérification | Résultat attendu |
|---|---|---|
| 1 | Laisser tourner 10 min en bougeant des fenêtres | 60 fps stables dans les stats, aucun artefact cumulé |
| 2 | Tap à 3 doigts → HUD | p50 ≤ 20 ms, p99 ≤ 40 ms (noter les valeurs réelles + le nom du décodeur) |
| 3 | Filmer au téléphone (ralenti si possible) un chronomètre en ms affiché sur le PC et sa copie sur la tablette | Noter l'écart de bout en bout (référence ; ~20 ms dus aux compromis de la phase 1) |
| 4 | Débrancher le câble, rebrancher, relancer le relais | Le flux reprend sans relancer l'app |
| 5 | Ctrl+C sur le relais en plein flux | L'app revient à l'écran d'attente avec « PC déconnecté » |
| 6 | `py -m unittest discover` (dans host-prototype) et `gradlew :app:testDebugUnitTest` | Tout passe |

Si le critère 2 échoue, noter les valeurs : c'est le résultat de mesure attendu de la phase 1 (cf. spec §9).

- [ ] **Step 5 : Écrire `README.md`**

````markdown
# TabX

Tablette Android comme second écran pour Windows, via câble USB-C.
Phase actuelle : 1 (pipeline vidéo, voir `docs/superpowers/specs/2026-10-01-phase1-video-pipeline-design.md`).

## Prérequis

- Windows 11, ffmpeg ≥ 6 (`winget install Gyan.FFmpeg`), Python ≥ 3.10 (`py`)
- Android Studio (SDK + JBR), tablette Android 11+ avec débogage USB activé

## Lancer

1. Installer l'app :
   ```powershell
   $env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
   cd android; .\gradlew.bat :app:installDebug
   ```
2. Ouvrir TabX sur la tablette.
3. Lancer le relais : `cd host-prototype; py relay.py --encoder nvenc` (`amf` sur batterie).
4. Tap à 3 doigts sur la tablette : affiche ou masque le HUD de latence.

## Tests

- Python : `cd host-prototype; py -m unittest discover -v`
- Android : `cd android; .\gradlew.bat :app:testDebugUnitTest`

## Checklist d'intégration (phase 1)

- [ ] 60 fps stables pendant 10 min, sans artefacts cumulés
- [ ] HUD : p50 ≤ 20 ms, p99 ≤ 40 ms (noter les valeurs et le décodeur)
- [ ] Latence de bout en bout filmée : valeur notée
- [ ] Câble débranché/rebranché + relais relancé : le flux reprend sans relancer l'app
- [ ] Relais tué en plein flux : retour à l'écran d'attente avec la raison
- [ ] Tous les tests passent
````

- [ ] **Step 6 : Commit**

```powershell
git add README.md
git commit -m "docs: add README with run instructions and integration checklist"
```

- [ ] **Step 7 : Reporter les mesures**

Ajouter à la fin du README une section `## Mesures phase 1` avec la date, le décodeur, les fps, le p50/p99 et la latence filmée, puis commit `docs: record phase 1 latency measurements`.
