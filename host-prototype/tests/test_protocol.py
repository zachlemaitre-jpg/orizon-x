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
    "DEVICE_INFO": lambda f: protocol.DeviceInfo(**f),
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


if __name__ == "__main__":
    unittest.main()
