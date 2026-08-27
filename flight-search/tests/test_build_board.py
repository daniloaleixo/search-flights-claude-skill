import unittest

from scripts.build_board import (NIGHT_LABELS, airport_matrix,
                                 date_matrix, origin_matrix,
                                 render)

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


CLEAN_TRIP = TRIPS[1]
UNKNOWN_TRIP = TRIPS[2]


def markup(html):
    """The page with its stylesheet cut out.

    Every class the page can ever wear is named in the <style> block, so
    asserting a class is absent from the whole document proves nothing.
    These assertions have to run against the markup alone.
    """
    head, _, rest = html.partition("<style>")
    _, _, tail = rest.partition("</style>")
    return head + tail


def coverage_row(html, code):
    """One origin's row out of the coverage strip."""
    for chunk in html.split('<li class="cover">')[1:]:
        row = chunk.split("</li>")[0]
        if f">{code}<" in row:
            return row
    raise AssertionError(f"no coverage row for {code}")


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
        # Rendered alone, so nothing else on the page can supply the words
        # or the class: the unknown verdict has to produce both itself, and
        # must not reach for any of the styling a clean verdict earns.
        body = markup(render([UNKNOWN_TRIP], PARAMS, {"AMS": "ok"}))
        self.assertIn("not checked", body.lower())
        self.assertIn("pill--unknown", body)
        self.assertNotIn("pill--clean", body)
        self.assertNotIn(NIGHT_LABELS["clean"], body)

    def test_clean_night_status_is_not_labelled_not_checked(self):
        body = markup(render([CLEAN_TRIP], PARAMS, {"FRA": "ok"}))
        self.assertIn("pill--clean", body)
        self.assertIn(NIGHT_LABELS["clean"], body)
        self.assertNotIn("pill--unknown", body)
        self.assertNotIn("not checked", body.lower())

    def test_a_mixed_board_keeps_the_two_verdicts_apart(self):
        body = markup(self.html)
        self.assertIn("pill--clean", body)
        self.assertIn("pill--unknown", body)

    def test_origin_without_coverage_is_reported_as_not_determined(self):
        # Assert on the coverage row itself. "not determined" appears in the
        # ramp legend on every page ever rendered, so finding it anywhere in
        # the document would not prove the coverage strip did its job.
        #
        # BER is given a fare here on purpose. Without one the row would say
        # "not determined" whatever the coverage logic did, and the test
        # would pass for the wrong reason. With one, the only way the price
        # stays hidden is if coverage actually wins.
        ber_fare = dict(UNKNOWN_TRIP, origin="BER", price_eur=999)
        body = markup(render(TRIPS + [ber_fare], PARAMS, COVERAGE))
        row = coverage_row(body, "BER")
        self.assertIn("cover-nd", row)
        self.assertIn("not determined", row.lower())
        self.assertNotIn("cover-price", row)
        self.assertNotIn("999", row)

    def test_origin_with_coverage_is_reported_as_a_price(self):
        body = markup(self.html)
        fra = coverage_row(body, "FRA")
        self.assertIn("cover-price", fra)
        self.assertIn("1161", fra)
        self.assertNotIn("cover-nd", fra)

    def test_justified_night_trip_states_its_saving(self):
        self.assertIn("200", self.html)

    def test_no_doctype_or_body_wrapper(self):
        # The Artifact tool supplies the skeleton; the file is page content.
        self.assertNotIn("<!doctype", self.html.lower())
        self.assertNotIn("<body", self.html.lower())


if __name__ == "__main__":
    unittest.main()
