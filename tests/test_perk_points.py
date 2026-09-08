import struct
import unittest

from app.core.perk_points import locate_perk_points
from app.core.skyrim_ess import EssParseError
from app.core.inventory_lab import encode_vsval
from app.core.quick_codes import generate_skyrim_quick_code_preset


def sample(points=80, count=6, equipped=b"\0" * 6):
    prefix = b"test" + bytes.fromhex("010000000000") + equipped
    entries = (bytes.fromhex("445474112e1900") + struct.pack("<f", 18.5)) * count
    tail = bytearray(28)
    tail[4] = tail[21] = 1
    return prefix + bytes([points]) + encode_vsval(count) + entries + tail


class PerkPointsTests(unittest.TestCase):
    def test_known_values_and_preserved_neighbors(self):
        for value in (0, 15, 80, 255):
            data = sample(value)
            field = locate_perk_points(data)
            self.assertEqual(field.value, value)
            self.assertEqual(field.offset, 16)
            changed = bytearray(data)
            changed[field.offset] = 15
            self.assertEqual(changed[:field.offset], data[:field.offset])
            self.assertEqual(changed[field.offset + 1:], data[field.offset + 1:])
            self.assertEqual(locate_perk_points(changed).value, 15)

    def test_equipped_refs_and_variable_count(self):
        for count in (1, 5, 64):
            field = locate_perk_points(sample(count=count, equipped=bytes.fromhex("423456000012")))
            self.assertEqual(field.following_count, count)

    def test_reject_unknown_layout(self):
        data = sample()
        for invalid in (data[:-1], data + b"\0", data[:17] + b"\xff" + data[18:]):
            with self.assertRaises(EssParseError):
                locate_perk_points(invalid)

    def test_nonfinite_entries_rejected(self):
        data = bytearray(sample())
        struct.pack_into("<f", data, 25, float("nan"))
        with self.assertRaises(EssParseError):
            locate_perk_points(data)

    def test_quick_code_uses_one_byte(self):
        self.assertTrue(generate_skyrim_quick_code_preset("perk_points", 15).endswith("0800000C 0000000F"))


if __name__ == "__main__":
    unittest.main()
