import unittest
from dance_code_belle import AudioPhrase, HighLevelSequence, AUDIO, SEQUENCES
from dance_code_belle.catalog import resolve
from dance_code_belle import protocol as p


class PacketTests(unittest.TestCase):
    def test_known_csharp_audio_vectors(self):
        # Independent expectations from C# enum positions and BitConverter encoding.
        self.assertEqual(p.play_audio("eP001"), bytes.fromhex("10 00 00"))
        self.assertEqual(p.play_audio("eP008"), bytes.fromhex("10 06 00"))
        self.assertEqual(p.play_audio(256), bytes.fromhex("10 00 01"))
        self.assertEqual(p.play_audio(AudioPhrase.eP008), p.play_audio("eP008"))

    def test_high_level_vectors(self):
        self.assertEqual(p.play_sequence("eHLS_Wake_1"), bytes.fromhex("17 02 00 00"))
        self.assertEqual(p.play_sequence(256), bytes.fromhex("17 02 00 01"))

    def test_complete_zero_based_catalogs(self):
        self.assertEqual(len(AUDIO), 421)
        self.assertEqual(len(SEQUENCES), 454)
        self.assertEqual([e.id for e in AUDIO.values()], list(range(421)))
        self.assertEqual([e.id for e in SEQUENCES.values()], list(range(454)))
        self.assertAlmostEqual(AUDIO["eP001"].duration, 1.623)

    def test_namespaces_and_invalid_ids(self):
        for bad in (-1, 421, 65535, "eP007", "001"):
            with self.assertRaises(ValueError):
                p.play_audio(bad)
        for bad in (True, 1.5, HighLevelSequence.eHLS_Wake_1):
            with self.assertRaises(TypeError):
                p.play_audio(bad)
        with self.assertRaises(TypeError):
            p.play_sequence(AudioPhrase.eP001)
        with self.assertRaises(TypeError):
            AUDIO["invented"] = resolve("eP001")

    def test_volume_bounds(self):
        self.assertEqual(p.set_volume(5), bytes.fromhex("23 05"))
        for bad in (-1, 6, True, 2.5):
            with self.assertRaises(ValueError):
                p.set_volume(bad)

    def test_completion_and_input_notifications(self):
        audio = p.parse_notification(bytes.fromhex("10 00 01"))
        self.assertEqual(audio.value, 256)
        seq = p.parse_notification(bytes.fromhex("17 02 01 01"))
        self.assertEqual((seq.sequence_type, seq.value), (2, 257))
        self.assertEqual(p.parse_notification(bytes.fromhex("20 01 80")).value, 32769)
        self.assertEqual(p.parse_notification(bytes.fromhex("ee 12")).value, None)

    def test_malformed_notifications(self):
        for data in (b"", b"\x10\x00", b"\x17\x02\x00", b"\x20\x00", b"\x22", b"\x50"):
            with self.assertRaises(ValueError):
                p.parse_notification(data)
