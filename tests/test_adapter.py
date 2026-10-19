import gzip
import json
import os
import unittest

from helpers import ROOT
from adapters import espn_nfl as E

FIX = os.path.join(ROOT, "tests", "fixtures", "game_401872656.json.gz")


class Adapter(unittest.TestCase):
    def setUp(self):
        with gzip.open(FIX, "rt") as f:
            self.raw = json.load(f)

    def test_real_game_parses_and_adds_up(self):
        p = E.parse_game(self.raw)          # NE at SEA, week 1 2026, 13-10
        self.assertEqual(p["problems"], [])
        self.assertTrue(p["final"])
        self.assertEqual(sorted(p["teams"]), ["NE", "SEA"])
        maye = p["lines"]["4431452"]
        self.assertEqual((maye["pass_yd"], maye["pass_td"], maye["int"], maye["rush_yd"]), (178, 1, 3, 47))
        jsn = p["lines"]["4430878"]
        self.assertEqual((jsn["rec"], jsn["rec_yd"], jsn["rec_td"]), (8, 122, 1))

    def test_tampered_box_score_is_caught(self):
        for tm in self.raw["boxscore"]["players"]:
            for cat in tm["statistics"]:
                if cat["name"] == "receiving":
                    cat["athletes"][0]["stats"][1] = str(int(cat["athletes"][0]["stats"][1]) + 40)
        self.assertTrue(E.parse_game(self.raw)["problems"])

    def test_two_point_conversions(self):
        texts = [("Jayden Daniels 26 Yd Rush (Jayden Daniels Pass to Terry McLaurin for Two-Point Conversion)",
                  [("Jayden Daniels", "Terry McLaurin")], []),
                 ("Chris Olave 21 Yd pass from Tyler Shough (Travis Etienne Jr. Run for Two-Point Conversion)",
                  [], ["Travis Etienne Jr."]),
                 ("Chuba Hubbard 1 Yd Rush (Two-Point Pass Conversion Failed)", [], [])]
        for text, passes, runs in texts:
            self.assertEqual([m.groups() for m in E.TWO_PT_PASS.finditer(text)], passes)
            self.assertEqual([m.group(1) for m in E.TWO_PT_RUN.finditer(text)], runs)
        self.assertEqual(E._name_key("Travis Etienne Jr."), E._name_key("Travis Etienne Jr"))


if __name__ == "__main__":
    unittest.main()
