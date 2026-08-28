import json
import os
import unittest

from scripts.build_board import _ground_notes

PARAMS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "params.sao-paulo.json",
)


class TestGroundNotesCoverage(unittest.TestCase):
    def setUp(self):
        with open(PARAMS_PATH) as f:
            self.params = json.load(f)

    def test_every_origin_has_a_non_empty_ground_note(self):
        notes = _ground_notes(self.params)
        for origin in self.params.get("origins") or []:
            code = origin["code"]
            self.assertIn(code, notes, f"{code} missing from merged ground notes")
            self.assertTrue(
                notes[code] and notes[code].strip(),
                f"{code} has an empty ground note",
            )

    def test_ground_notes_wins_over_per_origin_ground_key(self):
        # BER carries both params["ground_notes"]["BER"] and
        # origins[0]["ground"] == "home"; setdefault means the top-level
        # ground_notes entry must be the one that survives the merge.
        notes = _ground_notes(self.params)
        self.assertEqual(notes["BER"], self.params["ground_notes"]["BER"])


if __name__ == "__main__":
    unittest.main()
