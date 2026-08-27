import json
import unittest
from scripts.plan_run import (
    date_pairs, sweep_searches, backfill_searches, stop_budget,
    origins_needing_backfill, return_airports, _seat,
)
from scripts.tfs import SEAT_ECONOMY

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

    def test_every_url_lands_on_the_cheapest_tab(self):
        for s in sweep_searches(PARAMS):
            self.assertIn("tfu=EgoIAhAAGAAgAigB", s["url"])

    def test_ids_are_unique_and_stable(self):
        ids = [s["id"] for s in sweep_searches(PARAMS)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sweep_searches(PARAMS)[0]["id"], ids[0])


class TestOriginsNeedingBackfill(unittest.TestCase):
    def test_absent_origin_qualifies(self):
        rows = [{"origin": "FRA"}, {"origin": "MUC"}, {"origin": "PRG"},
                {"origin": "AMS"}, {"origin": "HAM"}]
        self.assertIn("BER", origins_needing_backfill(PARAMS, rows))

    def test_present_origin_with_higher_budget_qualifies(self):
        # BER appears in every row but its budget (2) exceeds the sweep's
        # shared limit (1), so its extra stop was never searched.
        rows = [{"origin": code} for code in
                ("BER", "FRA", "HAM", "MUC", "PRG", "AMS")]
        self.assertIn("BER", origins_needing_backfill(PARAMS, rows))

    def test_present_origin_at_sweep_limit_does_not_qualify(self):
        rows = [{"origin": code} for code in
                ("BER", "FRA", "HAM", "MUC", "PRG", "AMS")]
        self.assertNotIn("FRA", origins_needing_backfill(PARAMS, rows))

    def test_no_duplicates_when_an_origin_meets_both_conditions(self):
        # BER is both absent and over budget: still listed once.
        rows = [{"origin": "FRA"}, {"origin": "MUC"}, {"origin": "PRG"},
                {"origin": "AMS"}, {"origin": "HAM"}]
        result = origins_needing_backfill(PARAMS, rows)
        self.assertEqual(result.count("BER"), 1)


class TestReturnAirportsBareString(unittest.TestCase):
    def test_bare_string_wraps_to_single_element_list(self):
        params = dict(PARAMS, return_airports="BER")
        self.assertEqual(return_airports(params), ["BER"])

    def test_bare_string_does_not_splat_into_characters(self):
        params = dict(PARAMS, return_airports="BER")
        result = return_airports(params)
        self.assertNotIn("B", result)
        self.assertNotIn("E", result)


class TestCabinSeat(unittest.TestCase):
    def test_economy_maps_to_seat_economy(self):
        self.assertEqual(_seat(PARAMS), SEAT_ECONOMY)

    def test_default_cabin_is_economy(self):
        params = dict(PARAMS)
        params.pop("cabin", None)
        self.assertEqual(_seat(params), SEAT_ECONOMY)

    def test_unrecognised_cabin_raises(self):
        params = dict(PARAMS, cabin="business")
        with self.assertRaises(ValueError):
            _seat(params)


class TestOpenJawFalse(unittest.TestCase):
    def setUp(self):
        self.params = dict(PARAMS, open_jaw=False)

    def test_still_one_search_per_date_pair(self):
        self.assertEqual(len(sweep_searches(self.params)), 20)

    def test_trip_type_is_round_trip_not_multi_city(self):
        for s in sweep_searches(self.params):
            self.assertEqual(s["trip_type"], "round_trip")

    def test_ret_airports_equals_the_origin_list(self):
        origins = [o["code"] for o in self.params["origins"]]
        for s in sweep_searches(self.params):
            self.assertEqual(s["ret_airports"], origins)

    def test_open_jaw_true_is_unchanged(self):
        true_params = dict(PARAMS, open_jaw=True)
        for s in sweep_searches(true_params):
            self.assertEqual(s["trip_type"], "multi_city")
            self.assertEqual(len(s["ret_airports"]), 6)

    def test_open_jaw_absent_is_unchanged(self):
        absent_params = {k: v for k, v in PARAMS.items() if k != "open_jaw"}
        for s in sweep_searches(absent_params):
            self.assertEqual(s["trip_type"], "multi_city")
            self.assertEqual(len(s["ret_airports"]), 6)


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
