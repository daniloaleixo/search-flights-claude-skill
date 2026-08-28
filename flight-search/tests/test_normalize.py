import unittest

from scripts.normalize import (
    BaselineError, apply_ground_cost, apply_night_economics,
    assert_baseline_sound, cost_band, door_to_door, expansion_targets,
    ground_band, is_night_layover, layover_windows, missing_origins,
    night_baseline, night_saving_band, night_verdict,
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


PARAMS = {"ground_cost": {"BER": [0, 0], "AMS": [60, 120], "FRA": [70, 130]}}


def trip(origin, price, **extra):
    row = {"origin": origin, "price_eur": price}
    row.update(extra)
    return row


class TestGroundBand(unittest.TestCase):
    def test_reads_the_params_block(self):
        self.assertEqual(ground_band(PARAMS)["AMS"], (60, 120))

    def test_absent_block_is_empty_not_zero(self):
        self.assertEqual(ground_band({}), {})

    def test_an_inverted_band_is_a_typo_and_raises(self):
        with self.assertRaises(ValueError):
            ground_band({"ground_cost": {"AMS": [120, 60]}})


class TestDoorToDoor(unittest.TestCase):
    def setUp(self):
        self.bands = ground_band(PARAMS)

    def test_a_round_trip_pays_the_same_journey_twice(self):
        row = trip("AMS", 933, ret_airport="AMS")
        self.assertEqual(door_to_door(row, self.bands), (1053, 1173))

    def test_an_open_jaw_pays_each_end_once(self):
        row = trip("AMS", 933, ret_airport="BER")
        self.assertEqual(door_to_door(row, self.bands), (993, 1053))

    def test_the_airport_with_no_journey_adds_nothing(self):
        row = trip("BER", 939, ret_airport="BER")
        self.assertEqual(door_to_door(row, self.bands), (939, 939))

    def test_an_end_with_no_band_yields_no_figure_rather_than_a_zero(self):
        row = trip("AMS", 933, ret_airport="MUC")
        self.assertEqual(door_to_door(row, self.bands), (None, None))

    def test_a_row_with_no_fare_yields_no_figure(self):
        self.assertEqual(
            door_to_door({"origin": "BER", "price_eur": None}, self.bands),
            (None, None))


class TestCostBand(unittest.TestCase):
    def test_falls_back_to_the_bare_fare_as_a_point(self):
        self.assertEqual(cost_band({"price_eur": 500}), (500, 500))

    def test_uses_the_attached_band_when_there_is_one(self):
        rows = apply_ground_cost([trip("AMS", 933, ret_airport="AMS")], PARAMS)
        self.assertEqual(cost_band(rows[0]), (1053, 1173))


class TestBaselineRanksDoorToDoor(unittest.TestCase):
    def test_the_cheaper_fare_loses_to_the_cheaper_journey(self):
        # AMS 933 is the cheaper fare; FRA 1000 is the cheaper trip once the
        # train at both ends is counted, 1140 against 1053 low end... the
        # baseline must be the one with the lower band, not the lower fare.
        rows = [trip("AMS", 933, ret_airport="AMS", legs_expanded=True,
                     night_layover=False),
                trip("BER", 940, ret_airport="BER", legs_expanded=True,
                     night_layover=False)]
        apply_ground_cost(rows, PARAMS)
        self.assertEqual(night_baseline(rows)["origin"], "BER")

    def test_without_ground_costs_it_is_the_cheaper_fare(self):
        rows = [trip("AMS", 933, legs_expanded=True, night_layover=False),
                trip("BER", 940, legs_expanded=True, night_layover=False)]
        self.assertEqual(night_baseline(rows)["origin"], "AMS")


class TestBorderlineVerdict(unittest.TestCase):
    def setUp(self):
        self.base = trip("AMS", 933, ret_airport="AMS", legs_expanded=True,
                         night_layover=False)
        self.night = trip("BER", 939, ret_airport="BER", legs_expanded=True,
                          night_layover=True)
        apply_ground_cost([self.base, self.night], PARAMS)

    def test_the_saving_is_a_band_not_a_number(self):
        self.assertEqual(night_saving_band(self.night, self.base), (114, 234))

    def test_straddling_the_bar_is_too_close_to_call(self):
        self.assertEqual(night_verdict(self.night, self.base), "borderline")

    def test_clearing_the_bar_at_both_ends_is_justified(self):
        cheap = trip("BER", 700, ret_airport="BER", legs_expanded=True,
                     night_layover=True)
        apply_ground_cost([cheap], PARAMS)
        self.assertEqual(night_verdict(cheap, self.base), "justified")

    def test_missing_the_bar_at_both_ends_is_not_justified(self):
        dear = trip("BER", 1100, ret_airport="BER", legs_expanded=True,
                    night_layover=True)
        apply_ground_cost([dear], PARAMS)
        self.assertEqual(night_verdict(dear, self.base), "not_justified")

    def test_borderline_cannot_happen_without_ground_costs(self):
        base = trip("AMS", 933, legs_expanded=True, night_layover=False)
        night = trip("BER", 939, legs_expanded=True, night_layover=True)
        self.assertEqual(night_verdict(night, base), "not_justified")

    def test_economics_records_both_ends_of_the_saving(self):
        rows = [self.base, self.night]
        apply_night_economics(rows, dict(PARAMS, night_discount={
            "abs_eur": 150, "pct": 20}))
        self.assertEqual(self.night["night_verdict"], "borderline")
        self.assertEqual(self.night["night_saving_eur"], 114)
        self.assertEqual(self.night["night_saving_hi_eur"], 234)


class TestBaselineAssertion(unittest.TestCase):
    def test_an_unexpanded_row_under_the_baseline_is_refused(self):
        rows = [trip("AMS", 933, legs_expanded=True, night_layover=False),
                trip("FRA", 800)]
        with self.assertRaises(BaselineError) as caught:
            assert_baseline_sound(rows)
        self.assertIn("800", str(caught.exception))

    def test_a_run_whose_cheapest_rows_were_all_expanded_passes(self):
        rows = [trip("AMS", 933, legs_expanded=True, night_layover=False),
                trip("FRA", 1200)]
        assert_baseline_sound(rows)

    def test_a_row_that_vanished_from_the_results_is_exempt(self):
        rows = [trip("AMS", 933, legs_expanded=True, night_layover=False),
                trip("FRA", 800, expansion_missing=True)]
        assert_baseline_sound(rows)

    def test_no_baseline_yet_is_not_an_error(self):
        assert_baseline_sound([trip("FRA", 800)])

    def test_it_compares_door_to_door_not_fares(self):
        # AMS 933 baseline is 1053 door to door; a 1000 EUR Berlin fare is
        # under that even though its fare is higher.
        rows = [trip("AMS", 933, ret_airport="AMS", legs_expanded=True,
                     night_layover=False),
                trip("BER", 1000, ret_airport="BER")]
        apply_ground_cost(rows, PARAMS)
        with self.assertRaises(BaselineError):
            assert_baseline_sound(rows)


class TestExpansionCoversEveryOrigin(unittest.TestCase):
    def rows(self):
        out = []
        for origin, base in (("FRA", 100), ("AMS", 200), ("HAM", 900)):
            for i in range(6):
                out.append(trip(origin, base + i, dep_time=f"0{i}:00",
                                arr_time="20:00"))
        return out

    def test_the_dearest_origin_is_in_the_first_batch(self):
        got = expansion_targets(self.rows(), want=3, want_clean=0)
        self.assertIn("HAM", {t["origin"] for t in got})

    def test_it_still_fills_the_budget_cheapest_first(self):
        got = expansion_targets(self.rows(), want=6, want_clean=0)
        self.assertEqual(len(got), 6)

    def test_an_origin_with_no_clean_result_keeps_getting_tries(self):
        rows = self.rows()
        for row in rows:
            if row["origin"] == "FRA" and row["dep_time"] < "02:00":
                row["legs_expanded"] = True
                row["night_layover"] = True
        got = expansion_targets(rows, want=3, want_clean=0)
        self.assertIn("FRA", {t["origin"] for t in got})

    def test_it_gives_up_on_an_origin_after_max_per_origin_tries(self):
        rows = self.rows()
        for row in rows:
            if row["origin"] == "FRA":
                row["legs_expanded"] = True
                row["night_layover"] = True
        got = expansion_targets(rows, want=3, want_clean=0, max_per_origin=6)
        self.assertNotIn("FRA", {t["origin"] for t in got})

    def test_an_origin_with_a_clean_result_stops_being_starved(self):
        rows = self.rows()
        for row in rows:
            if row["origin"] == "FRA":
                row["legs_expanded"] = True
                row["night_layover"] = row["price_eur"] != 100
        got = expansion_targets(rows, want=3, want_clean=0)
        self.assertNotIn("FRA", {t["origin"] for t in got})


if __name__ == "__main__":
    unittest.main()
