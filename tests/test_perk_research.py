import unittest

from app.core.inventory_lab import encode_vsval
from app.core.perk_research import find_perk_array_candidates


class PerkCandidateTests(unittest.TestCase):
    def fixture(self, count=2):
        refs = [bytes.fromhex("4BE128")] + [i.to_bytes(3, "big") for i in range(1, count)]
        return (encode_vsval(count) + b"".join(ref + b"\x01" for ref in refs)
                + encode_vsval(count) + b"".join(refs))

    def test_bounded_arrays_and_no_mutation(self):
        data = self.fixture()
        before = bytes(data)
        found = find_perk_array_candidates(data, {"4BE128"})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].count_offset, 0)
        self.assertEqual(found[0].end_offset, len(data))
        self.assertEqual(found[0].ranked_entries[0], ("4BE128", 1))
        self.assertEqual(data, before)

    def test_two_byte_counts(self):
        found = find_perk_array_candidates(self.fixture(64), {"4BE128"})
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0].ranked_entries), 64)

    def test_truncated_or_unknown_data_is_not_detected(self):
        data = self.fixture()
        for end in range(len(data)):
            self.assertEqual(find_perk_array_candidates(data[:end], {"4BE128"}), [])
        self.assertEqual(find_perk_array_candidates(data, {"4CB40D"}), [])

    def test_companion_must_match(self):
        self.assertEqual(find_perk_array_candidates(self.fixture()[:-3] + b"\x40\x00\x22", {"4BE128"}), [])

    def test_ambiguity_is_reported_not_silently_selected(self):
        found = find_perk_array_candidates(self.fixture() + b"\xff" * 8 + self.fixture(), {"4BE128"})
        self.assertEqual(len(found), 2)


if __name__ == "__main__":
    unittest.main()
