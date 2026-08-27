import unittest

from scripts.normalize import (
    apply_night_economics, expansion_targets, is_night_layover,
    layover_windows, missing_origins, night_baseline, night_verdict,
)


def leg(frm, to, dep, arr):
    return {"from": frm, "to": to, "dep_local": dep, "arr_local": arr}


class TestLayoverWindows(unittest.TestCase):
    def test_single_layover_window_between_two_legs(self):
        legs = [leg("BER", "LIS", "2026-12-19T18:15", "2026-12-19T20:50"),
                leg("LIS", "GRU", "2026-12-20T04:55", "2026-12-20T10:40")]
        got = layover_windows(legs)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["code"], "LIS")
        self.assertEqual(got[0]["minutes"], 485)

    def test_nonstop_has_no_windows(self):
        self.assertEqual(layover_windows([leg("BER", "GRU", "a", "b")]), [])

    def test_two_stops_produce_two_windows(self):
        legs = [leg("BER", "FRA", "2026-12-19T08:00", "2026-12-19T09:00"),
                leg("FRA", "LIS", "2026-12-19T11:00", "2026-12-19T13:00"),
                leg("LIS", "GRU", "2026-12-19T16:00", "2026-12-20T00:00")]
        self.assertEqual([w["code"] for w in layover_windows(legs)], ["FRA", "LIS"])

    def test_night_flag_uses_the_default_band(self):
        legs = [leg("BER", "LIS", "2026-12-19T18:15", "2026-12-19T20:50"),
                leg("LIS", "GRU", "2026-12-20T04:55", "2026-12-20T10:40")]
        self.assertTrue(layover_windows(legs)[0]["night_flag"])

    def test_night_flag_respects_a_configured_window(self):
        # A daytime layover is not flagged under the default 23:00-06:00
        # band, but is flagged once a custom band covering daytime hours
        # (params["night_layover_window"]) is passed through explicitly.
        legs = [leg("BER", "FRA", "2026-12-19T07:00", "2026-12-19T09:00"),
                leg("FRA", "GRU", "2026-12-19T16:00", "2026-12-19T20:00")]
        self.assertFalse(layover_windows(legs)[0]["night_flag"])
        from datetime import time
        daytime = (time(8, 0), time(17, 0))
        self.assertTrue(layover_windows(legs, window=daytime)[0]["night_flag"])


class TestIsNightLayover(unittest.TestCase):
    def test_layover_spanning_midnight_is_night(self):
        self.assertTrue(
            is_night_layover("2026-12-19T20:50", "2026-12-20T04:55"))

    def test_daytime_layover_is_not_night(self):
        self.assertFalse(
            is_night_layover("2026-12-19T09:00", "2026-12-19T16:00"))

    def test_layover_ending_exactly_at_23_00_is_not_night(self):
        self.assertFalse(
            is_night_layover("2026-12-19T18:00", "2026-12-19T23:00"))

    def test_layover_starting_exactly_at_06_00_is_not_night(self):
        self.assertFalse(
            is_night_layover("2026-12-20T06:00", "2026-12-20T11:00"))

    def test_layover_clipping_one_minute_of_the_band_is_night(self):
        self.assertTrue(
            is_night_layover("2026-12-19T22:00", "2026-12-19T23:01"))

    def test_very_long_layover_covering_a_whole_day_is_night(self):
        self.assertTrue(
            is_night_layover("2026-12-19T08:00", "2026-12-21T08:00"))


class TestBaselineAndVerdict(unittest.TestCase):
    def setUp(self):
        self.trips = [
            {"id": "a", "price_eur": 700, "night_layover": True,
             "legs_expanded": True},
            {"id": "b", "price_eur": 900, "night_layover": False,
             "legs_expanded": True},
            {"id": "c", "price_eur": 850, "night_layover": False,
             "legs_expanded": True},
            {"id": "d", "price_eur": 600, "night_layover": None,
             "legs_expanded": False},
        ]

    def test_baseline_is_cheapest_expanded_clean_trip(self):
        self.assertEqual(night_baseline(self.trips)["id"], "c")

    def test_unexpanded_trips_cannot_be_the_baseline(self):
        self.assertNotEqual(night_baseline(self.trips)["id"], "d")

    def test_baseline_is_none_when_no_clean_trip_exists(self):
        self.assertIsNone(night_baseline([self.trips[0]]))

    def test_clean_trip_is_verdict_clean(self):
        self.assertEqual(night_verdict(self.trips[1], self.trips[2]), "clean")

    def test_unexpanded_trip_is_verdict_unknown(self):
        self.assertEqual(night_verdict(self.trips[3], self.trips[2]), "unknown")

    def test_night_trip_clearing_the_absolute_floor_is_justified(self):
        baseline = {"price_eur": 850, "night_layover": False, "legs_expanded": True}
        trip = {"price_eur": 700, "night_layover": True, "legs_expanded": True}
        self.assertEqual(night_verdict(trip, baseline), "justified")

    def test_night_trip_one_euro_short_is_not_justified(self):
        baseline = {"price_eur": 850, "night_layover": False, "legs_expanded": True}
        trip = {"price_eur": 701, "night_layover": True, "legs_expanded": True}
        self.assertEqual(night_verdict(trip, baseline), "not_justified")

    def test_percentage_binds_on_cheap_fares(self):
        # 20% of 400 is 80, which is easier to clear than the 150 floor.
        baseline = {"price_eur": 400, "night_layover": False, "legs_expanded": True}
        trip = {"price_eur": 315, "night_layover": True, "legs_expanded": True}
        self.assertEqual(night_verdict(trip, baseline), "justified")

    def test_verdict_is_unknown_when_there_is_no_baseline(self):
        trip = {"price_eur": 700, "night_layover": True, "legs_expanded": True}
        self.assertEqual(night_verdict(trip, None), "unknown")


class TestApplyNightEconomics(unittest.TestCase):
    def test_saving_fields_are_attached(self):
        trips = [
            {"id": "cheap_night", "price_eur": 700, "night_layover": True,
             "legs_expanded": True},
            {"id": "clean", "price_eur": 900, "night_layover": False,
             "legs_expanded": True},
        ]
        out = {t["id"]: t for t in apply_night_economics(trips, {})}
        self.assertEqual(out["cheap_night"]["night_saving_eur"], 200)
        self.assertEqual(out["cheap_night"]["night_verdict"], "justified")
        self.assertTrue(out["clean"]["is_baseline"])

    def test_clean_trips_get_no_saving(self):
        trips = [{"id": "clean", "price_eur": 900, "night_layover": False,
                  "legs_expanded": True}]
        out = apply_night_economics(trips, {})
        self.assertIsNone(out[0]["night_saving_eur"])


class TestCoverage(unittest.TestCase):
    def test_origins_absent_from_rows_are_reported(self):
        rows = [{"origin": "FRA"}, {"origin": "AMS"}, {"origin": "FRA"}]
        got = missing_origins(rows, ["BER", "FRA", "HAM", "MUC", "PRG", "AMS"])
        self.assertEqual(got, ["BER", "HAM", "MUC", "PRG"])

    def test_nothing_missing_returns_empty(self):
        self.assertEqual(missing_origins([{"origin": "BER"}], ["BER"]), [])


class TestExpansionTargets(unittest.TestCase):
    def test_first_batch_is_the_cheapest_want(self):
        trips = [{"id": str(i), "price_eur": 100 + i} for i in range(30)]
        self.assertEqual(len(expansion_targets(trips, want=12, want_clean=3)), 12)

    def test_returns_them_in_ascending_price_order(self):
        trips = [{"id": "b", "price_eur": 200}, {"id": "a", "price_eur": 100}]
        got = expansion_targets(trips, want=2, want_clean=0)
        self.assertEqual([t["id"] for t in got], ["a", "b"])

    def test_never_returns_more_than_exists(self):
        trips = [{"id": "a", "price_eur": 100}]
        self.assertEqual(len(expansion_targets(trips, want=12, want_clean=3)), 1)

    def test_nothing_left_once_both_conditions_are_met(self):
        trips = [{"id": str(i), "price_eur": 100 + i, "legs_expanded": True,
                  "night_layover": i % 2 == 1} for i in range(12)]
        self.assertEqual(expansion_targets(trips, want=12, want_clean=3), [])

    def test_keeps_going_when_the_clean_baseline_is_short(self):
        # Twelve expanded but every one a night layover: no baseline exists,
        # so the run must keep expanding rather than report an uncomputable
        # comparison.
        trips = [{"id": str(i), "price_eur": 100 + i, "legs_expanded": True,
                  "night_layover": True} for i in range(12)]
        trips.append({"id": "x", "price_eur": 500})
        self.assertEqual(len(expansion_targets(trips, want=12, want_clean=3)), 1)


if __name__ == "__main__":
    unittest.main()
