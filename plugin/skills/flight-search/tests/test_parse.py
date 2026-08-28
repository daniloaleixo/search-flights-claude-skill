import json
import pathlib
import unittest

from scripts.parse import (
    ParseError, parse_carriers, parse_duration_minutes, parse_endpoints,
    parse_layovers, parse_price, parse_route, parse_row, parse_stops,
)

FIXTURES = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "rows.json").read_text()
)
TAP, LH_LATAM, NONSTOP, ITA = FIXTURES


class TestPrice(unittest.TestCase):
    def test_one_way_phrasing(self):
        self.assertEqual(parse_price(TAP["aria"]), 977)

    def test_multi_city_total_phrasing(self):
        self.assertEqual(parse_price(LH_LATAM["aria"]), 1161)

    def test_thousands_separator_in_aria_is_absent_but_handled(self):
        self.assertEqual(parse_price("From 1,151 euros total. Nonstop"), 1151)

    def test_missing_price_raises(self):
        with self.assertRaises(ParseError):
            parse_price("Select flight")


class TestStops(unittest.TestCase):
    def test_nonstop_is_zero(self):
        self.assertEqual(parse_stops(NONSTOP["aria"]), 0)

    def test_one_stop(self):
        self.assertEqual(parse_stops(TAP["aria"]), 1)

    def test_two_stops(self):
        self.assertEqual(parse_stops("From 900 euros. 2 stops flight with X."), 2)


class TestCarriers(unittest.TestCase):
    def test_single_carrier(self):
        self.assertEqual(parse_carriers(TAP["aria"]), ("Tap Air Portugal",))

    def test_two_carriers_joined_by_and(self):
        self.assertEqual(parse_carriers(LH_LATAM["aria"]), ("Lufthansa", "LATAM"))

    def test_operated_by_clause_is_not_a_carrier(self):
        self.assertNotIn("Latam Airlines Brasil", parse_carriers(NONSTOP["aria"]))


class TestDuration(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration_minutes("Total duration 30 hr 45 min."), 1845)

    def test_minutes_only(self):
        self.assertEqual(parse_duration_minutes("a 45 min layover"), 45)

    def test_hours_only(self):
        self.assertEqual(parse_duration_minutes("Total duration 12 hr."), 720)


class TestLayovers(unittest.TestCase):
    def test_single_layover(self):
        got = parse_layovers(TAP["aria"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["minutes"], 990)
        self.assertEqual(got[0]["airport_name"], "Humberto Delgado Airport")

    def test_nonstop_has_none(self):
        self.assertEqual(parse_layovers(NONSTOP["aria"]), ())

    def test_two_layovers_are_both_captured(self):
        aria = ("From 800 euros total. 2 stops flight with X. "
                "Layover (1 of 2) is a 2 hr 5 min layover at Alpha Airport in A. "
                "Layover (2 of 2) is a 1 hr 40 min layover at Beta Airport in B.")
        got = parse_layovers(aria)
        self.assertEqual([l["minutes"] for l in got], [125, 100])


class TestRoute(unittest.TestCase):
    def test_en_dash_separator(self):
        self.assertEqual(parse_route(TAP["text"]), ("BER", "GRU"))

    def test_hyphen_separator(self):
        self.assertEqual(parse_route("7:15 AM\n16 hr\nFRA-GRU\n1 stop"), ("FRA", "GRU"))

    def test_missing_route_raises(self):
        with self.assertRaises(ParseError):
            parse_route("7:15 AM – 8:05 PM\nLufthansa")


class TestEndpoints(unittest.TestCase):
    def test_same_day_arrival(self):
        got = parse_endpoints(LH_LATAM["aria"], "2026-12-19")
        self.assertEqual(got["dep_time"], "07:15")
        self.assertEqual(got["arr_time"], "20:05")
        self.assertEqual(got["dep_date"], "2026-12-19")
        self.assertEqual(got["arr_date"], "2026-12-19")

    def test_next_day_arrival(self):
        got = parse_endpoints(TAP["aria"], "2026-12-19")
        self.assertEqual(got["arr_date"], "2026-12-20")

    def test_midnight_hour_converts_correctly(self):
        aria = ("From 1 euros. Nonstop flight with X. Leaves A at 12:30 AM on "
                "Saturday, December 19 and arrives at B at 12:30 PM on "
                "Saturday, December 19. Total duration 12 hr.")
        got = parse_endpoints(aria, "2026-12-19")
        self.assertEqual(got["dep_time"], "00:30")
        self.assertEqual(got["arr_time"], "12:30")

    def test_arrival_across_new_year_rolls_the_year(self):
        aria = ("From 1 euros. Nonstop flight with X. Leaves A at 10:00 PM on "
                "Thursday, December 31 and arrives at B at 6:00 AM on "
                "Friday, January 1. Total duration 8 hr.")
        got = parse_endpoints(aria, "2026-12-31")
        self.assertEqual(got["arr_date"], "2027-01-01")


class TestParseRow(unittest.TestCase):
    def test_assembles_a_complete_record(self):
        row = parse_row(ITA["aria"], ITA["text"], "2026-12-19")
        self.assertEqual(row["price_eur"], 1151)
        self.assertEqual(row["origin"], "AMS")
        self.assertEqual(row["dest"], "GRU")
        self.assertEqual(row["stops"], 1)
        self.assertEqual(row["total_duration_min"], 1725)
        self.assertEqual(row["layovers"][0]["code"], "FCO")
        self.assertEqual(row["carriers"], ("ITA",))

    def test_layover_codes_come_from_row_text(self):
        row = parse_row(TAP["aria"], TAP["text"], "2026-12-19")
        self.assertEqual(row["layovers"][0]["code"], "LIS")
        self.assertEqual(row["layovers"][0]["minutes"], 990)

    def test_nonstop_row_has_no_layovers(self):
        row = parse_row(NONSTOP["aria"], NONSTOP["text"], "2026-12-19")
        self.assertEqual(row["layovers"], ())

    def test_raw_label_is_retained_for_audit(self):
        row = parse_row(TAP["aria"], TAP["text"], "2026-12-19")
        self.assertEqual(row["raw_aria"], TAP["aria"])


if __name__ == "__main__":
    unittest.main()
