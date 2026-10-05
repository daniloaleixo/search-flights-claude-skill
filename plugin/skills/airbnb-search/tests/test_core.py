import os
import unittest

from scripts.geo import blocks, distance_to_lines, load_lines
from scripts.ingest_dump import expand_info, parse_dump
from scripts.merge import evaluate, info_numbers, money, parse_sqm, rating

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIO = load_lines(os.path.join(SKILL, "references", "rio_beachfront.json"))


class Geo(unittest.TestCase):
    def test_beachfront_hotel_is_on_the_beach(self):
        # Copacabana Palace faces Av. Atlantica.
        self.assertLess(distance_to_lines(-22.9671, -43.1787, RIO), 80)

    def test_listing_that_says_400m_measures_about_400m(self):
        # Listing 923015698827356839, "400 meters from the beach".
        self.assertAlmostEqual(distance_to_lines(-22.9833, -43.1972, RIO), 400, delta=60)

    def test_blocks_round(self):
        self.assertEqual(blocks(557, 130), 4)
        self.assertEqual(blocks(40, 130), 0)


class Parsing(unittest.TestCase):
    def test_money_and_rating(self):
        self.assertEqual(money("€1,234"), 1234.0)
        self.assertEqual(rating("4.84 (56)"), (4.84, 56))
        self.assertEqual(rating("New"), (None, 0))

    def test_info_roundtrip(self):
        info = expand_info("3br,3 doublebd,2.5ba")
        self.assertEqual(info_numbers(info), {"bedrooms": 3.0, "beds": 3.0, "baths": 2.5})

    def test_sqm_thousands(self):
        self.assertEqual(parse_sqm("It is 1,500 m2 on 3 floors"), 1500)
        self.assertEqual(parse_sqm("Elegant apartment of 110m2 with"), 110)
        self.assertIsNone(parse_sqm("900m from the beach"))

    def test_dump_joins_names_with_newlines(self):
        text = ("#LISTINGS 1\n1|ipa|Apt@Leme|Apt Leme RJ\none block|3br,7bd,2ba||-22.96|-43.17||FC\n"
                "#PRICES 1\n1|A|1200|1500|ipa\n#END")
        rows = parse_dump(text, {"A": ("2026-12-22", "2026-12-27")})
        self.assertEqual(rows[0]["name"], "Apt Leme RJ one block")
        self.assertEqual(rows[0]["title"], "Apartment in Leme")
        self.assertEqual(rows[0]["pm"], "Free cancellation")


class Evaluate(unittest.TestCase):
    PARAMS = {
        "must_have": [
            {"key": "parking", "kind": "amenity", "patterns": ["parking on premises"], "search_filtered": True},
            {"key": "guests", "kind": "min_guests", "value": 5},
            {"key": "beach", "kind": "max_blocks", "value": 4, "slack_m": 80},
        ],
        "nice_to_have": [{"key": "br3", "kind": "min_bedrooms", "value": 3, "weight": 1}],
    }

    def listing(self, **kw):
        base = {"beach_m": 300, "_block_m": 130, "bedrooms": 3, "name": "", "badges": "", "pm": ""}
        base.update(kw)
        return base

    def test_unread_listing_is_unknown_not_failed(self):
        L = self.listing()
        evaluate(L, self.PARAMS)
        self.assertIsNone(L["must"]["guests"])
        self.assertTrue(L["must_ok"])
        self.assertFalse(L["must_confirmed"])

    def test_detail_page_overrides_search_filter(self):
        L = self.listing(detail={"cap": 6, "amen": ["Wifi", "Paid parking off premises"]})
        evaluate(L, self.PARAMS)
        self.assertFalse(L["must"]["parking"])
        self.assertFalse(L["must_ok"])

    def test_beach_slack(self):
        L = self.listing(beach_m=595, detail={"cap": 5, "amen": ["Free parking on premises"]})
        evaluate(L, self.PARAMS)
        self.assertTrue(L["must"]["beach"])
        L = self.listing(beach_m=610, detail={"cap": 5, "amen": ["Free parking on premises"]})
        evaluate(L, self.PARAMS)
        self.assertFalse(L["must"]["beach"])


if __name__ == "__main__":
    unittest.main()
