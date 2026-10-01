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

    def test_handles_short_reads(self):
        class OneByteStream(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 1) if size and size > 0 else size)
        stream = OneByteStream(bytes.fromhex(self.PING_HEX))
        self.assertEqual(protocol.read_message(stream), protocol.Ping(123456789))


if __name__ == "__main__":
    unittest.main()
