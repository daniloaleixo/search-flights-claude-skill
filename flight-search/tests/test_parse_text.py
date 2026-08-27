import pathlib
import unittest

from scripts.parse import ParseError
from scripts.parse_text import parse_page_text, parse_text_row, split_rows

PAGE = (pathlib.Path(__file__).parent / "fixtures"
        / "page_text_round_trip.txt").read_text()


class TestSplitRows(unittest.TestCase):
    def test_finds_every_result_row_and_no_page_furniture(self):
        self.assertEqual(len(split_rows(PAGE)), 5)

    def test_a_row_starts_at_its_departure_time(self):
        self.assertEqual(split_rows(PAGE)[0][0], "5:55 PM")

    def test_the_tab_strip_and_price_badge_are_not_rows(self):
        # "from €1,047" sits above the list and is the Cheapest tab's badge,
        # not a fare anyone can book.
        self.assertNotIn("from €1,047", [c[0] for c in split_rows(PAGE)])


class TestParseTextRow(unittest.TestCase):
    def setUp(self):
        self.rows = parse_page_text(PAGE, "2026-12-19")

    def test_one_stop_row_reads_every_field(self):
        r = self.rows[0]
        self.assertEqual(r["price_eur"], 1047)
        self.assertEqual(r["stops"], 1)
        self.assertEqual(r["carriers"], ("ITA",))
        self.assertEqual(r["total_duration_min"], 28 * 60 + 45)
        self.assertEqual((r["origin"], r["dest"]), ("AMS", "GRU"))
        self.assertEqual(r["dep_time"], "17:55")
        self.assertEqual(r["arr_time"], "18:40")

    def test_layover_carries_minutes_and_code(self):
        self.assertEqual(self.rows[0]["layovers"],
                         ({"minutes": 865, "airport_name": "FCO",
                           "code": "FCO"},))

    def test_day_offset_becomes_a_real_arrival_date(self):
        self.assertEqual(self.rows[0]["arr_date"], "2026-12-20")

    def test_same_day_arrival_keeps_the_departure_date(self):
        same_day = [r for r in self.rows if r["price_eur"] == 1108][0]
        self.assertEqual(same_day["arr_date"], "2026-12-19")

    def test_nonstop_row_has_no_layovers(self):
        nonstop = [r for r in self.rows if r["price_eur"] == 1207][0]
        self.assertEqual(nonstop["stops"], 0)
        self.assertEqual(nonstop["layovers"], ())
        self.assertEqual(nonstop["total_duration_min"], 12 * 60 + 15)

    def test_operated_by_suffix_is_stripped_from_carriers(self):
        nonstop = [r for r in self.rows if r["price_eur"] == 1207][0]
        self.assertEqual(nonstop["carriers"], ("LATAM",))

    def test_two_carriers_split_into_two(self):
        r = [r for r in self.rows if r["price_eur"] == 1108][0]
        self.assertEqual(r["carriers"], ("Lufthansa", "LATAM"))

    def test_self_transfer_rows_are_flagged(self):
        flagged = [r for r in self.rows if r["self_transfer"]]
        self.assertEqual([r["price_eur"] for r in flagged], [1621])

    def test_through_fares_are_not_flagged(self):
        self.assertFalse(self.rows[0]["self_transfer"])

    def test_a_row_missing_its_price_raises(self):
        with self.assertRaises(ParseError):
            parse_text_row(["5:55 PM", "–", "6:40 PM", "ITA", "28 hr 45 min",
                            "AMS–GRU", "1 stop"], "2026-12-19")

    def test_a_row_missing_its_route_raises(self):
        with self.assertRaises(ParseError):
            parse_text_row(["5:55 PM", "–", "6:40 PM", "ITA", "28 hr 45 min",
                            "1 stop", "€1,047"], "2026-12-19")


if __name__ == "__main__":
    unittest.main()
