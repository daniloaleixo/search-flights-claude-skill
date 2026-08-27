import json
import unittest
from scripts.plan_run import (
    date_pairs, sweep_searches, backfill_searches, stop_budget,
)

PARAMS = {
    "dest": "GRU",
    "origins": [
        {"code": "BER", "max_stops": 2},
        {"code": "FRA", "max_stops": 1},
        {"code": "HAM", "max_stops": 1},
        {"code": "MUC", "max_stops": 1},
        {"code": "PRG", "max_stops": 1},
        {"code": "AMS", "max_stops": 1},
    ],
    "return_airports": "same_as_origins",
    "open_jaw": True,
    "dep_window": ["2026-12-19", "2026-12-23"],
    "ret_window": ["2027-02-09", "2027-02-12"],
    "pax": 1,
    "cabin": "economy",
    "currency": "EUR",
}


class TestDatePairs(unittest.TestCase):
    def test_produces_full_cross_product(self):
        pairs = date_pairs(PARAMS)
        self.assertEqual(len(pairs), 20)

    def test_first_and_last_pair(self):
        pairs = date_pairs(PARAMS)
        self.assertEqual(pairs[0], ("2026-12-19", "2027-02-09"))
        self.assertEqual(pairs[-1], ("2026-12-23", "2027-02-12"))

    def test_windows_are_inclusive_on_both_ends(self):
        deps = {p[0] for p in date_pairs(PARAMS)}
        self.assertIn("2026-12-19", deps)
        self.assertIn("2026-12-23", deps)


class TestStopBudget(unittest.TestCase):
    def test_berlin_gets_two_stops(self):
        self.assertEqual(stop_budget(PARAMS, "BER"), 2)

    def test_others_get_one_stop(self):
        self.assertEqual(stop_budget(PARAMS, "MUC"), 1)


class TestSweepSearches(unittest.TestCase):
    def test_one_search_per_date_pair(self):
        self.assertEqual(len(sweep_searches(PARAMS)), 20)

    def test_sweep_runs_at_the_lowest_common_stop_budget(self):
        # BER allows 2 but the other five allow 1; a single search carries one
        # limit, so the sweep must use 1 and leave BER to backfill.
        for s in sweep_searches(PARAMS):
            self.assertEqual(s["max_stops"], 1)

    def test_every_search_carries_all_origins_and_all_return_airports(self):
        s = sweep_searches(PARAMS)[0]
        self.assertEqual(len(s["origins"]), 6)
        self.assertEqual(len(s["ret_airports"]), 6)

    def test_every_url_is_price_sorted(self):
        for s in sweep_searches(PARAMS):
            self.assertIn("tfu=EgYIAhAAGAA", s["url"])

    def test_ids_are_unique_and_stable(self):
        ids = [s["id"] for s in sweep_searches(PARAMS)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sweep_searches(PARAMS)[0]["id"], ids[0])


class TestBackfillSearches(unittest.TestCase):
    def test_one_search_per_missing_origin_per_pair(self):
        pairs = [("2026-12-20", "2027-02-09"), ("2026-12-21", "2027-02-10")]
        out = backfill_searches(PARAMS, ["BER", "HAM"], pairs)
        self.assertEqual(len(out), 4)

    def test_backfill_uses_that_origins_own_stop_budget(self):
        pairs = [("2026-12-20", "2027-02-09")]
        by_origin = {s["origins"][0]: s for s in
                     backfill_searches(PARAMS, ["BER", "HAM"], pairs)}
        self.assertEqual(by_origin["BER"]["max_stops"], 2)
        self.assertEqual(by_origin["HAM"]["max_stops"], 1)

    def test_backfill_keeps_all_return_airports(self):
        pairs = [("2026-12-20", "2027-02-09")]
        out = backfill_searches(PARAMS, ["BER"], pairs)
        self.assertEqual(len(out[0]["ret_airports"]), 6)

    def test_no_missing_origins_means_no_searches(self):
        self.assertEqual(backfill_searches(PARAMS, [], [("a", "b")]), [])


if __name__ == "__main__":
    unittest.main()
