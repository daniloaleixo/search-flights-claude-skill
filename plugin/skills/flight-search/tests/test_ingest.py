import copy
import json
import pathlib
import unittest

from scripts.ingest import (
    ResultSetError, SortOrderError, assert_cheapest_tab, assert_price_sorted,
    ingest_capture, merge_captures,
)

CAPTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "capture_sweep.json").read_text()
)
SEARCH = {"id": "sweep-2026-12-19-2027-02-09", "dep_date": "2026-12-19",
          "ret_date": "2027-02-09", "max_stops": 1,
          "url": CAPTURE["url"], "origins": ["AMS", "FRA"],
          "ret_airports": ["BER"]}


class TestSortAssertion(unittest.TestCase):
    def test_price_sorted_page_passes(self):
        assert_price_sorted(CAPTURE)

    def test_top_flights_page_is_rejected(self):
        bad = copy.deepcopy(CAPTURE)
        bad["sortedBy"] = "Sorted by top flights"
        with self.assertRaises(SortOrderError):
            assert_price_sorted(bad)

    def test_missing_sort_line_is_rejected(self):
        bad = copy.deepcopy(CAPTURE)
        bad["sortedBy"] = None
        with self.assertRaises(SortOrderError):
            assert_price_sorted(bad)


class TestResultSetAssertion(unittest.TestCase):
    def test_cheapest_tab_page_passes(self):
        assert_cheapest_tab(CAPTURE)

    def test_best_tab_page_is_rejected_even_when_sorted_by_price(self):
        # The exact shape that produced the first run's board: Best tab,
        # price-sorted, cheapest row 24% above the Cheapest tab's.
        bad = copy.deepcopy(CAPTURE)
        bad["activeTab"] = "Best"
        assert_price_sorted(bad)
        with self.assertRaises(ResultSetError):
            assert_cheapest_tab(bad)

    def test_missing_tab_field_is_rejected(self):
        bad = copy.deepcopy(CAPTURE)
        del bad["activeTab"]
        with self.assertRaises(ResultSetError):
            assert_cheapest_tab(bad)


class TestIngest(unittest.TestCase):
    def test_rows_become_records_tagged_with_their_search(self):
        got = ingest_capture(CAPTURE, SEARCH)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["search_id"], SEARCH["id"])
        self.assertEqual(got[0]["origin"], "AMS")
        self.assertEqual(got[0]["price_eur"], 1151)

    def test_records_carry_the_url_that_produced_them(self):
        got = ingest_capture(CAPTURE, SEARCH)
        self.assertEqual(got[0]["tfs_url"], CAPTURE["url"])

    def test_records_carry_the_date_pair(self):
        got = ingest_capture(CAPTURE, SEARCH)
        self.assertEqual(got[0]["ret_date"], "2027-02-09")

    def test_price_basis_reflects_the_search_kind(self):
        got = ingest_capture(CAPTURE, SEARCH)
        self.assertEqual(got[0]["price_basis"], "sweep")
        backfill = dict(SEARCH, id="backfill-BER-2026-12-19-2027-02-09")
        self.assertEqual(ingest_capture(CAPTURE, backfill)[0]["price_basis"],
                         "backfill")

    def test_unsorted_capture_refuses_to_ingest(self):
        bad = copy.deepcopy(CAPTURE)
        bad["sortedBy"] = "Sorted by top flights"
        with self.assertRaises(SortOrderError):
            ingest_capture(bad, SEARCH)

    def test_best_tab_capture_refuses_to_ingest(self):
        bad = copy.deepcopy(CAPTURE)
        bad["activeTab"] = "Best"
        with self.assertRaises(ResultSetError):
            ingest_capture(bad, SEARCH)

    def test_zero_rows_on_a_loaded_page_raises(self):
        empty = copy.deepcopy(CAPTURE)
        empty["rows"] = []
        empty["rowCount"] = 0
        with self.assertRaises(ValueError):
            ingest_capture(empty, SEARCH)

    def test_an_unparseable_row_is_skipped_when_not_strict(self):
        broken = copy.deepcopy(CAPTURE)
        broken["rows"][0]["text"] = "no route here"
        got = ingest_capture(broken, SEARCH, strict=False)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["origin"], "FRA")

    def test_return_airport_is_unknown_until_expansion(self):
        # A multi-city row describes only leg 1; Google does not commit to the
        # return airport until the itinerary is expanded.
        got = ingest_capture(CAPTURE, SEARCH)
        self.assertIsNone(got[0]["ret_airport"])


class TestMerge(unittest.TestCase):
    def test_merges_across_captures(self):
        got = merge_captures([CAPTURE, CAPTURE], [SEARCH, dict(SEARCH, id="s2")])
        self.assertEqual(len(got), 4)


if __name__ == "__main__":
    unittest.main()


class TestIngestPageText(unittest.TestCase):
    PAGE = (pathlib.Path(__file__).parent / "fixtures"
            / "page_text_round_trip.txt").read_text()

    def capture(self, **over):
        cap = {"url": CAPTURE["url"], "sortedBy": "Sorted by price",
               "activeTab": "Cheapest", "pageText": self.PAGE}
        cap.update(over)
        return cap

    def test_page_text_becomes_records_tagged_with_their_search(self):
        from scripts.ingest import ingest_page_text
        got = ingest_page_text(self.capture(), SEARCH)
        self.assertEqual(len(got), 5)
        self.assertEqual(got[0]["price_eur"], 1047)
        self.assertEqual(got[0]["search_id"], SEARCH["id"])
        self.assertEqual(got[0]["price_basis"], "sweep")

    def test_best_tab_page_text_refuses_to_ingest(self):
        from scripts.ingest import ingest_page_text
        with self.assertRaises(ResultSetError):
            ingest_page_text(self.capture(activeTab="Best"), SEARCH)

    def test_page_text_with_no_rows_raises(self):
        from scripts.ingest import ingest_page_text
        with self.assertRaises(ValueError):
            ingest_page_text(self.capture(pageText="Sorted by price\n"), SEARCH)

    def test_merge_routes_page_text_captures_to_the_text_parser(self):
        got = merge_captures([self.capture()], [SEARCH])
        self.assertEqual(len(got), 5)
