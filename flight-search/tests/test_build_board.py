import unittest

from scripts.build_board import airport_matrix, date_matrix, origin_matrix, render

ORIGINS = ["BER", "FRA", "AMS"]
RETS = ["BER", "FRA", "AMS"]

TRIPS = [
    {"id": "t1", "origin": "AMS", "ret_airport": "BER", "price_eur": 1151,
     "dep_date": "2026-12-19", "ret_date": "2027-02-09",
     "night_verdict": "justified", "legs_expanded": True,
     "night_saving_eur": 200, "stops": 1, "total_duration_min": 1725,
     "carriers": ("ITA",), "tfs_url": "https://example/1"},
    {"id": "t2", "origin": "FRA", "ret_airport": "FRA", "price_eur": 1161,
     "dep_date": "2026-12-19", "ret_date": "2027-02-09",
     "night_verdict": "clean", "legs_expanded": True,
     "night_saving_eur": None, "stops": 1, "total_duration_min": 1010,
     "carriers": ("Lufthansa", "LATAM"), "tfs_url": "https://example/2"},
    {"id": "t3", "origin": "AMS", "ret_airport": "BER", "price_eur": 1400,
     "dep_date": "2026-12-20", "ret_date": "2027-02-09",
     "night_verdict": "unknown", "legs_expanded": False,
     "night_saving_eur": None, "stops": 1, "total_duration_min": 1800,
     "carriers": ("KLM",), "tfs_url": "https://example/3"},
]
COVERAGE = {"BER": "not_determined", "FRA": "ok", "AMS": "ok"}
PARAMS = {"dest": "GRU", "currency": "EUR"}

DATE_PAIRS = [("2026-12-19", "2027-02-09"), ("2026-12-20", "2027-02-09")]

# A second AMS fare in a cell that already has one, so "cheapest wins" is
# a claim the fixture can actually test.
DEARER_AMS = {"id": "t4", "origin": "AMS", "ret_airport": None,
              "price_eur": 1290, "dep_date": "2026-12-19",
              "ret_date": "2027-02-09", "night_verdict": "unknown",
              "legs_expanded": False, "night_saving_eur": None, "stops": 2,
              "total_duration_min": 1900, "carriers": ("TAP",),
              "tfs_url": "https://example/4"}


class TestOriginMatrix(unittest.TestCase):
    def test_cell_holds_the_cheapest_trip_for_that_combination(self):
        m = origin_matrix(TRIPS + [DEARER_AMS], ORIGINS, DATE_PAIRS)
        self.assertEqual(m[("AMS", ("2026-12-19", "2027-02-09"))]["id"], "t1")

    def test_combinations_with_no_trip_are_none(self):
        m = origin_matrix(TRIPS, ORIGINS, DATE_PAIRS)
        self.assertIsNone(m[("BER", ("2026-12-19", "2027-02-09"))])
        self.assertIsNone(m[("FRA", ("2026-12-20", "2027-02-09"))])

    def test_every_combination_has_a_key(self):
        m = origin_matrix(TRIPS, ORIGINS, DATE_PAIRS)
        self.assertEqual(len(m), 6)

    def test_a_trip_with_no_return_airport_still_lands_in_a_cell(self):
        # This is the whole point of the view: the sweep knows the origin
        # and the dates long before it knows the return airport.
        m = origin_matrix([DEARER_AMS], ORIGINS, DATE_PAIRS)
        self.assertEqual(m[("AMS", ("2026-12-19", "2027-02-09"))]["id"], "t4")


class TestAirportMatrix(unittest.TestCase):
    def test_cell_holds_the_cheapest_trip_for_that_pair(self):
        m = airport_matrix(TRIPS, ORIGINS, RETS)
        self.assertEqual(m[("AMS", "BER")]["price_eur"], 1151)

    def test_pairs_with_no_trip_are_none(self):
        m = airport_matrix(TRIPS, ORIGINS, RETS)
        self.assertIsNone(m[("BER", "AMS")])

    def test_diagonal_is_the_same_airport_round_trip(self):
        m = airport_matrix(TRIPS, ORIGINS, RETS)
        self.assertEqual(m[("FRA", "FRA")]["id"], "t2")

    def test_every_pair_has_a_key(self):
        m = airport_matrix(TRIPS, ORIGINS, RETS)
        self.assertEqual(len(m), 9)


class TestDateMatrix(unittest.TestCase):
    def test_cheapest_per_date_pair(self):
        m = date_matrix(TRIPS, ["2026-12-19", "2026-12-20"], ["2027-02-09"])
        self.assertEqual(m[("2026-12-19", "2027-02-09")]["price_eur"], 1151)
        self.assertEqual(m[("2026-12-20", "2027-02-09")]["price_eur"], 1400)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.html = render(TRIPS, PARAMS, COVERAGE)

    def test_output_has_a_title(self):
        self.assertIn("<title>", self.html)

    def test_every_trip_appears(self):
        for trip in TRIPS:
            self.assertIn(str(trip["price_eur"]), self.html)

    def test_unknown_night_status_is_labelled_not_shown_as_clean(self):
        self.assertIn("not checked", self.html.lower())

    def test_origin_without_coverage_is_reported_as_not_determined(self):
        self.assertIn("not determined", self.html.lower())

    def test_justified_night_trip_states_its_saving(self):
        self.assertIn("200", self.html)

    def test_no_doctype_or_body_wrapper(self):
        # The Artifact tool supplies the skeleton; the file is page content.
        self.assertNotIn("<!doctype", self.html.lower())
        self.assertNotIn("<body", self.html.lower())


if __name__ == "__main__":
    unittest.main()
