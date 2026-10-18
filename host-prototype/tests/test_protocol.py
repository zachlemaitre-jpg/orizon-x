import io
import json
import unittest
from pathlib import Path

import protocol

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "protocol" / "test-vectors.json").read_text(encoding="utf-8")
)

EXPECTED_TABLET_MESSAGES = {
    "HELLO": lambda f: protocol.Hello(**f),
    "PING": lambda f: protocol.Ping(**f),
    "KEYFRAME_REQ": lambda f: protocol.KeyframeRequest(),
    "STATS": lambda f: protocol.Stats(**f),
    "INPUT": lambda f: protocol.Input(f["device"], tuple(protocol.Contact(**c) for c in f["contacts"])),
    "DEVICE_INFO": lambda f: protocol.DeviceInfo(
        **({**f, "video": protocol.VideoCaps(**f["video"])} if "video" in f else f)),
    "ACTION": lambda f: protocol.Action(f),
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
    if vector["type"] == "ACTIONS_STATE":
        return protocol.encode_actions_state(f["state"])
    if vector["type"] == "MEDIA_ARTWORK":
        return protocol.encode_media_artwork(f["id"], bytes.fromhex(f["data"]))
    if vector["type"] == "FRAME_STATE":
        return protocol.encode_frame_state(
            f["epoch"], f["status"], f["folder"], f["interval_s"], f["fit"], f["paused"])
    if vector["type"] == "FRAME_FILE":
        return protocol.encode_frame_file(
            f["epoch"], f["id"], f["kind"], f["total"], f["offset"], bytes.fromhex(f["data"]))
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

    def test_rejects_input_with_wrong_size(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000003" "010100")))

    def test_rejects_input_from_unknown_device(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000002" "0300")))

    def test_rejects_more_than_one_pen_contact(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000016" "0202" + "00" * 20)))

    def test_pen_out_of_range_is_an_empty_input(self):
        message = protocol.read_message(io.BytesIO(bytes.fromhex("8500000000000002" "0200")))
        self.assertEqual(message, protocol.Input(protocol.DEVICE_PEN, ()))

    def test_rejects_oversized_payload(self):
        header = bytes.fromhex("82000000") + (protocol.MAX_PAYLOAD + 1).to_bytes(4, "big")
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(header))

    def test_rejects_keyframe_request_with_payload(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(io.BytesIO(bytes.fromhex("8300000000000001" "00")))

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

    def test_handles_short_reads(self):
        class OneByteStream(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 1) if size and size > 0 else size)
        stream = OneByteStream(bytes.fromhex(self.PING_HEX))
        self.assertEqual(protocol.read_message(stream), protocol.Ping(123456789))


def _json_frame(msg_type: int, payload: bytes) -> io.BytesIO:
    return io.BytesIO(bytes([msg_type, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload)


class DeviceInfoTest(unittest.TestCase):
    GOOD = {"role": "actions", "kind": "phone", "name": "Pixel 8", "app": "0.5.0"}

    def decode(self, payload: bytes):
        return protocol.read_message(_json_frame(protocol.DEVICE_INFO, payload))

    def test_constants(self):
        self.assertEqual((protocol.ACTIONS_STATE, protocol.DEVICE_INFO, protocol.ACTION), (0x04, 0x86, 0x87))
        self.assertEqual(protocol.MAX_JSON, 65536)

    def test_decodes_utf8_fields(self):
        info = self.decode(json.dumps({**self.GOOD, "name": "Téléphone"}, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(info, protocol.DeviceInfo("actions", "phone", "Téléphone", "0.5.0"))

    def test_decodes_escaped_unicode(self):
        info = self.decode(json.dumps({**self.GOOD, "name": "Téléphone"}).encode("ascii"))
        self.assertEqual(info.name, "Téléphone")

    def test_ignores_unknown_extra_fields(self):
        info = self.decode(json.dumps({**self.GOOD, "future": 1}).encode("utf-8"))
        self.assertEqual(info, protocol.DeviceInfo("actions", "phone", "Pixel 8", "0.5.0"))

    def test_rejects_invalid_json(self):
        with self.assertRaises(protocol.ProtocolError):
            self.decode(b"{not json")

    def test_rejects_empty_payload(self):
        with self.assertRaises(protocol.ProtocolError):
            self.decode(b"")

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(protocol.ProtocolError):
            self.decode(b'{"role":"\xff","kind":"phone","name":"x","app":"y"}')

    def test_rejects_non_object(self):
        for payload in (b"[]", b'"actions"', b"42", b"null"):
            with self.subTest(payload=payload), self.assertRaises(protocol.ProtocolError):
                self.decode(payload)

    def test_rejects_missing_or_non_string_field(self):
        for key in self.GOOD:
            missing = {k: v for k, v in self.GOOD.items() if k != key}
            wrong = {**self.GOOD, key: 3}
            for bad in (missing, wrong):
                with self.subTest(key=key, bad=bad), self.assertRaises(protocol.ProtocolError):
                    self.decode(json.dumps(bad).encode("utf-8"))

    def test_rejects_non_finite_numbers(self):
        with self.assertRaises(protocol.ProtocolError):
            self.decode(b'{"role":"actions","kind":"phone","name":"x","app":"y","n":NaN}')

    def test_rejects_payload_over_64_kib(self):
        pad = "x" * protocol.MAX_JSON
        with self.assertRaises(protocol.ProtocolError):
            self.decode(json.dumps({**self.GOOD, "name": pad}).encode("utf-8"))

    def test_accepts_payload_of_exactly_64_kib(self):
        base = json.dumps({**self.GOOD, "name": ""}, separators=(",", ":")).encode("utf-8")
        name = "x" * (protocol.MAX_JSON - len(base))
        payload = json.dumps({**self.GOOD, "name": name}, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(payload), protocol.MAX_JSON)
        self.assertEqual(self.decode(payload).name, name)

    def test_lang_defaults_to_french(self):
        self.assertEqual(self.decode(json.dumps(self.GOOD).encode("utf-8")).lang, "fr")
        self.assertEqual(protocol.DeviceInfo("actions", "phone", "x", "1").lang, "fr")

    def test_decodes_the_device_language(self):
        for lang in ("en", "fr"):
            with self.subTest(lang):
                info = self.decode(json.dumps({**self.GOOD, "lang": lang}).encode("utf-8"))
                self.assertEqual(info.lang, lang)

    def test_unknown_or_malformed_lang_is_french_not_an_error(self):
        for bad in ("de", "EN", "", " en", None, 3, True, ["en"], {"en": 1}):
            with self.subTest(bad=bad):
                info = self.decode(json.dumps({**self.GOOD, "lang": bad}).encode("utf-8"))
                self.assertEqual(info.lang, "fr")
                self.assertEqual(info.role, "actions")

    def test_video_is_absent_by_default(self):
        self.assertIsNone(self.decode(json.dumps(self.GOOD).encode("utf-8")).video)
        self.assertIsNone(protocol.DeviceInfo("actions", "phone", "x", "1").video)

    def test_decodes_the_video_capabilities(self):
        info = self.decode(json.dumps({**self.GOOD, "video": {"width": 2160, "height": 1350, "fps": 60}}).encode())
        self.assertEqual(info.video, protocol.VideoCaps(2160, 1350, 60))
        self.assertEqual(info.role, "actions")

    def test_invalid_video_is_ignored_not_an_error(self):
        bad_values = [
            None, 3, "2880x1800", [], {},
            {"width": 2880, "height": 1800},  # fps manquant
            {"width": 2880, "fps": 60},  # hauteur manquante
            {"height": 1800, "fps": 60},
            {"width": "2880", "height": 1800, "fps": 60},
            {"width": 2880.5, "height": 1800, "fps": 60},
            {"width": 2880, "height": 1800, "fps": 59.9},
            {"width": True, "height": 1800, "fps": 60},
            {"width": 2880, "height": 1800, "fps": True},
            {"width": 0, "height": 1800, "fps": 60},
            {"width": 2880, "height": -1, "fps": 60},
            {"width": 2880, "height": 1800, "fps": 0},
            {"width": 2880, "height": 1800, "fps": 1000},
            {"width": 100000, "height": 1800, "fps": 60},
            {"width": 2880, "height": 100000, "fps": 60},
            {"width": None, "height": 1800, "fps": 60},
        ]
        for video in bad_values:
            with self.subTest(video=video):
                info = self.decode(json.dumps({**self.GOOD, "video": video}).encode("utf-8"))
                self.assertIsNone(info.video)
                self.assertEqual(info.name, "Pixel 8")

    def test_video_extra_fields_are_ignored(self):
        info = self.decode(json.dumps(
            {**self.GOOD, "video": {"width": 1920, "height": 1200, "fps": 30, "codec": "avc"}}).encode())
        self.assertEqual(info.video, protocol.VideoCaps(1920, 1200, 30))


class ActionTest(unittest.TestCase):
    def decode(self, payload: bytes):
        return protocol.read_message(_json_frame(protocol.ACTION, payload))

    def test_decodes_all_fields(self):
        action = self.decode(b'{"id":"usb.eject","drive":"E:"}')
        self.assertEqual(action, protocol.Action({"id": "usb.eject", "drive": "E:"}))
        self.assertEqual(action.fields["drive"], "E:")

    def test_decodes_value_types(self):
        self.assertEqual(self.decode(b'{"id":"volume.set","value":0.5}').fields["value"], 0.5)
        self.assertIs(self.decode(b'{"id":"wifi.set","value":true}').fields["value"], True)

    def test_unknown_id_is_still_decoded(self):
        self.assertEqual(self.decode(b'{"id":"future.thing"}').fields["id"], "future.thing")

    def test_rejects_missing_or_non_string_id(self):
        for payload in (b"{}", b'{"id":3}', b'{"id":null}', b'{"value":1}'):
            with self.subTest(payload=payload), self.assertRaises(protocol.ProtocolError):
                self.decode(payload)

    def test_rejects_invalid_json_and_non_objects(self):
        for payload in (b"", b"{", b"[]", b'"volume.set"', b"7"):
            with self.subTest(payload=payload), self.assertRaises(protocol.ProtocolError):
                self.decode(payload)

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(protocol.ProtocolError):
            self.decode(b'{"id":"\xff"}')

    def test_rejects_payload_over_64_kib(self):
        payload = json.dumps({"id": "volume.set", "pad": "x" * protocol.MAX_JSON}).encode("utf-8")
        with self.assertRaises(protocol.ProtocolError):
            self.decode(payload)


class EncodeActionsStateTest(unittest.TestCase):
    def test_frame_is_compact_utf8_json(self):
        frame = protocol.encode_actions_state({"v": 1, "wifi": {"ssid": "Café", "on": True}})
        payload = '{"v":1,"wifi":{"ssid":"Café","on":true}}'.encode("utf-8")
        self.assertEqual(frame, bytes([0x04, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload)

    def test_header_matches_payload_length(self):
        frame = protocol.encode_actions_state({"v": 1})
        self.assertEqual(protocol.HEADER.unpack_from(frame), (0x04, 0, 0, len(frame) - 8))

    def test_accepts_exactly_64_kib(self):
        base = len(json.dumps({"v": 1, "p": ""}, separators=(",", ":")))
        frame = protocol.encode_actions_state({"v": 1, "p": "x" * (protocol.MAX_JSON - base)})
        self.assertEqual(len(frame) - 8, protocol.MAX_JSON)

    def test_rejects_over_64_kib(self):
        base = len(json.dumps({"v": 1, "p": ""}, separators=(",", ":")))
        with self.assertRaises(ValueError):
            protocol.encode_actions_state({"v": 1, "p": "x" * (protocol.MAX_JSON - base + 1)})

    def test_rejects_non_serialisable_state(self):
        with self.assertRaises(ValueError):
            protocol.encode_actions_state({"v": 1, "bad": {1, 2}})

    def test_rejects_non_finite_floats(self):
        with self.assertRaises(ValueError):
            protocol.encode_actions_state({"v": 1, "x": float("nan")})


class EncodeMediaArtworkTest(unittest.TestCase):
    ID = "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"

    def test_constants(self):
        self.assertEqual(protocol.MEDIA_ARTWORK, 0x05)
        self.assertEqual(protocol.MAX_ARTWORK, 512 * 1024)

    def test_layout_is_id_length_then_ascii_id_then_image(self):
        image = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        frame = protocol.encode_media_artwork(self.ID, image)
        payload = bytes([40]) + self.ID.encode("ascii") + image
        self.assertEqual(frame, bytes([0x05, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload)

    def test_header_matches_payload_length(self):
        frame = protocol.encode_media_artwork("x", b"\xff\xd8\xff")
        self.assertEqual(protocol.HEADER.unpack_from(frame), (0x05, 0, 0, 1 + 1 + 3))
        self.assertEqual(frame[8:], b"\x01x\xff\xd8\xff")

    def test_accepts_a_whole_payload_of_exactly_512_kib(self):
        image = b"\x00" * (protocol.MAX_ARTWORK - 1 - 40)
        frame = protocol.encode_media_artwork(self.ID, image)
        self.assertEqual(len(frame) - 8, protocol.MAX_ARTWORK)

    def test_rejects_a_whole_payload_over_512_kib(self):
        with self.assertRaises(ValueError):
            protocol.encode_media_artwork(self.ID, b"\x00" * (protocol.MAX_ARTWORK - 1 - 40 + 1))

    def test_max_image_size_helper(self):
        self.assertEqual(protocol.max_artwork_image(self.ID), protocol.MAX_ARTWORK - 41)

    def test_rejects_an_empty_image(self):
        with self.assertRaises(ValueError):
            protocol.encode_media_artwork(self.ID, b"")

    def test_accepts_a_255_byte_id(self):
        frame = protocol.encode_media_artwork("i" * 255, b"img")
        self.assertEqual(frame[8], 255)
        self.assertEqual(frame[9:9 + 255], b"i" * 255)
        self.assertEqual(frame[9 + 255:], b"img")

    def test_rejects_an_id_over_255_bytes(self):
        with self.assertRaises(ValueError):
            protocol.encode_media_artwork("i" * 256, b"img")

    def test_rejects_an_empty_id(self):
        with self.assertRaises(ValueError):
            protocol.encode_media_artwork("", b"img")

    def test_rejects_a_non_ascii_id(self):
        with self.assertRaises(ValueError):
            protocol.encode_media_artwork("café", b"img")

    def test_rejects_a_non_str_id(self):
        with self.assertRaises(ValueError):
            protocol.encode_media_artwork(b"abc", b"img")

    def test_accepts_bytearray_and_memoryview_images(self):
        expected = protocol.encode_media_artwork("id", b"abc")
        self.assertEqual(protocol.encode_media_artwork("id", bytearray(b"abc")), expected)
        self.assertEqual(protocol.encode_media_artwork("id", memoryview(b"abc")), expected)

    def test_vector_media_artwork_small_is_present(self):
        names = [v["name"] for v in VECTORS["pc_to_tablet"] if v["type"] == "MEDIA_ARTWORK"]
        self.assertIn("media_artwork_small", names)

    def test_pc_side_reader_skips_it_as_an_unknown_type(self):
        # 0x05 is PC -> device: the PC-side reader of tablet messages ignores it like any unknown type.
        stream = io.BytesIO(protocol.encode_media_artwork(self.ID, b"img") + protocol.HEADER.pack(0x82, 0, 0, 8)
                            + (7).to_bytes(8, "big"))
        self.assertEqual(protocol.read_message(stream), protocol.Ping(7))


class EncodeFrameStateTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((protocol.FRAME_STATE, protocol.FRAME_FILE), (0x06, 0x07))
        self.assertEqual(protocol.MAX_FRAME_CHUNK, 1024 * 1024)

    def test_frame_is_compact_json_in_the_documented_key_order(self):
        frame = protocol.encode_frame_state(3, "ok", "Café", 30, "fit", True)
        payload = '{"epoch":3,"status":"ok","folder":"Café","interval_s":30,"fit":"fit","paused":true}'.encode("utf-8")
        self.assertEqual(frame, bytes([0x06, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload)

    def test_no_folder_is_json_null(self):
        frame = protocol.encode_frame_state(1, "no_folder", None, 5, "crop", False)
        self.assertIn(b'"folder":null', frame)

    def test_accepts_every_status_and_fit(self):
        for status in ("ok", "no_folder", "empty", "unreadable"):
            for fit in ("crop", "fit"):
                with self.subTest(status=status, fit=fit):
                    protocol.encode_frame_state(0, status, None, 30, fit, False)

    def test_accepts_the_largest_epoch(self):
        self.assertIn(b'"epoch":4294967295', protocol.encode_frame_state(0xFFFFFFFF, "ok", "x", 30, "crop", False))

    def test_rejects_invalid_fields(self):
        good = dict(epoch=1, status="ok", folder="x", interval_s=30, fit="crop", paused=False)
        bad_values = {
            "epoch": (-1, 0x1_0000_0000, 1.5, "1", True, None),
            "status": ("bogus", "OK", "", None, 1),
            "folder": (3, b"x", ["x"]),
            "interval_s": (0, -5, 2.5, "30", True, None),
            "fit": ("stretch", "Crop", "", None, 1),
            "paused": (0, 1, "false", None),
        }
        for key, values in bad_values.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    protocol.encode_frame_state(**{**good, key: value})

    def test_rejects_over_64_kib(self):
        base = len(protocol.encode_frame_state(1, "ok", "", 30, "crop", False)) - 8
        folder = "x" * (protocol.MAX_JSON - base)
        self.assertEqual(len(protocol.encode_frame_state(1, "ok", folder, 30, "crop", False)) - 8, protocol.MAX_JSON)
        with self.assertRaises(ValueError):
            protocol.encode_frame_state(1, "ok", folder + "x", 30, "crop", False)

    def test_vectors_are_present(self):
        names = {v["name"] for v in VECTORS["pc_to_tablet"] if v["type"] == "FRAME_STATE"}
        self.assertEqual(names, {"frame_state_ok", "frame_state_no_folder"})


class EncodeFrameFileTest(unittest.TestCase):
    def test_layout_is_big_endian_epoch_id_kind_total_offset_then_data(self):
        frame = protocol.encode_frame_file(0x01020304, 0x0A0B0C0D, 2, 0x1122334455667788, 0x0102, b"\xaa\xbb")
        payload = (bytes.fromhex("01020304" "0a0b0c0d" "02" "1122334455667788" "0000000000000102") + b"\xaa\xbb")
        self.assertEqual(len(payload), 25 + 2)
        self.assertEqual(frame, bytes([0x07, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload)

    def test_accepts_a_chunk_of_exactly_1_mib(self):
        data = b"\x00" * protocol.MAX_FRAME_CHUNK
        frame = protocol.encode_frame_file(1, 1, 2, protocol.MAX_FRAME_CHUNK, 0, data)
        self.assertEqual(len(frame) - 8, 25 + protocol.MAX_FRAME_CHUNK)

    def test_accepts_a_chunk_that_ends_exactly_at_total(self):
        protocol.encode_frame_file(1, 1, 1, 10, 9, b"x")

    def test_accepts_bytearray_and_memoryview_data(self):
        expected = protocol.encode_frame_file(1, 1, 1, 3, 0, b"abc")
        self.assertEqual(protocol.encode_frame_file(1, 1, 1, 3, 0, bytearray(b"abc")), expected)
        self.assertEqual(protocol.encode_frame_file(1, 1, 1, 3, 0, memoryview(b"abc")), expected)

    def test_rejects_empty_data(self):
        with self.assertRaises(ValueError):
            protocol.encode_frame_file(1, 1, 1, 10, 0, b"")

    def test_rejects_data_over_1_mib(self):
        with self.assertRaises(ValueError):
            protocol.encode_frame_file(1, 1, 1, 2 * 1024 * 1024, 0, b"\x00" * (protocol.MAX_FRAME_CHUNK + 1))

    def test_rejects_a_chunk_running_past_total(self):
        for total, offset, data in ((10, 6, b"12345"), (4, 0, b"12345"), (0, 0, b"x"), (10, 10, b"x")):
            with self.subTest(total=total, offset=offset), self.assertRaises(ValueError):
                protocol.encode_frame_file(1, 1, 1, total, offset, data)

    def test_rejects_an_unknown_kind(self):
        for kind in (0, 3, 255, -1, True, "1", None):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                protocol.encode_frame_file(1, 1, kind, 10, 0, b"x")

    def test_rejects_out_of_range_numbers(self):
        for args in ((-1, 1, 1, 10, 0), (0x1_0000_0000, 1, 1, 10, 0), (1, -1, 1, 10, 0), (1, 0x1_0000_0000, 1, 10, 0),
                     (1, 1, 1, 2 ** 64, 0), (1, 1, 1, 10, -1), (1, 1, 1, 10.0, 0), (1.0, 1, 1, 10, 0), (True, 1, 1, 10, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                protocol.encode_frame_file(*args, b"x")

    def test_vectors_are_present(self):
        names = {v["name"] for v in VECTORS["pc_to_tablet"] if v["type"] == "FRAME_FILE"}
        self.assertEqual(names, {"frame_file_first_chunk", "frame_file_last_chunk"})

    def test_pc_side_reader_skips_both_as_unknown_types(self):
        stream = io.BytesIO(protocol.encode_frame_state(1, "ok", "x", 30, "crop", False)
                            + protocol.encode_frame_file(1, 1, 1, 1, 0, b"x")
                            + protocol.HEADER.pack(0x82, 0, 0, 8) + (7).to_bytes(8, "big"))
        self.assertEqual(protocol.read_message(stream), protocol.Ping(7))


class DeviceInfoFrameRoleTest(unittest.TestCase):
    def test_the_frame_role_is_decoded_as_is(self):
        payload = b'{"role":"frame","kind":"tablet","name":"Tab","app":"0.8.0","lang":"en"}'
        info = protocol.read_message(_json_frame(protocol.DEVICE_INFO, payload))
        self.assertEqual(info, protocol.DeviceInfo("frame", "tablet", "Tab", "0.8.0", None, "en"))


if __name__ == "__main__":
    unittest.main()
