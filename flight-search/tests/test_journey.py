import unittest

from scripts.journey import (
    apply_journey, ground_spec, hotel_cost, outbound_plan, return_plan, timing,
)

PARAMS = {
    "ground": {
        "BER": {"eur": 0, "hours": 1.0, "home": True},
        "HAM": {"eur": 37, "hours": 2.5, "hotel_eur": 80,
                "first_train": "05:00", "last_train": "22:00"},
        "AMS": {"eur": 60, "hours": 7.0, "hotel_eur": 120,
                "first_train": "05:00", "last_train": "19:00"},
    },
}

SPEC = ground_spec(PARAMS)
CLOCKS = timing(PARAMS)


def trip(**kw):
    base = {"origin": "AMS", "ret_airport": "AMS", "dest": "GRU",
            "dep_date": "2026-12-23", "dep_time": "07:00",
            "total_duration_min": 780}
    base.update(kw)
    return base


class TestGroundSpec(unittest.TestCase):
    def test_an_airport_with_a_train_must_declare_its_last_one(self):
        params = {"ground": {"FRA": {"eur": 37, "hours": 4.5,
                                     "hotel_eur": 90, "first_train": "05:00"}}}
        with self.assertRaises(ValueError) as caught:
            ground_spec(params)
        self.assertIn("last_train", str(caught.exception))

    def test_home_needs_no_train_times(self):
        spec = ground_spec({"ground": {"BER": {"eur": 0, "hours": 1.0,
                                               "home": True}}})
        self.assertTrue(spec["BER"]["home"])


class TestOutboundFeasibility(unittest.TestCase):
    def test_a_morning_amsterdam_departure_costs_the_night_before(self):
        plan = outbound_plan(trip(dep_time="07:00"), SPEC, CLOCKS)
        self.assertTrue(plan["overnight"])
        self.assertEqual(plan["hotel_eur"], 120)

    def test_the_afternoon_is_reachable_on_the_day(self):
        plan = outbound_plan(trip(dep_time="15:00"), SPEC, CLOCKS)
        self.assertFalse(plan["overnight"])
        self.assertEqual(plan["hotel_eur"], 0)
        self.assertEqual(plan["home_dep"], "2026-12-23T05:30:00")

    def test_the_earliest_reachable_amsterdam_flight_is_half_past_two(self):
        self.assertFalse(
            outbound_plan(trip(dep_time="14:30"), SPEC, CLOCKS)["overnight"])
        self.assertTrue(
            outbound_plan(trip(dep_time="14:29"), SPEC, CLOCKS)["overnight"])

    def test_home_is_never_out_of_reach(self):
        plan = outbound_plan(
            trip(origin="BER", ret_airport="BER", dep_time="06:00"),
            SPEC, CLOCKS)
        self.assertFalse(plan["overnight"])
        self.assertEqual(plan["home_dep"], "2026-12-23T02:30:00")

    def test_a_forced_night_leaves_home_the_previous_afternoon(self):
        plan = outbound_plan(trip(dep_time="07:00"), SPEC, CLOCKS)
        self.assertEqual(plan["home_dep"], "2026-12-22T15:00:00")

    def test_an_origin_with_no_ground_entry_is_unknown_not_reachable(self):
        self.assertIsNone(outbound_plan(trip(origin="PRG"), SPEC, CLOCKS))


class TestOutboundDuration(unittest.TestCase):
    def test_the_journey_counts_the_train_and_the_waiting(self):
        plan = outbound_plan(
            trip(origin="HAM", dep_time="15:00", total_duration_min=780),
            SPEC, CLOCKS)
        self.assertEqual(plan["door_min"], 300 + 780)

    def test_a_forced_night_is_inside_the_journey_time(self):
        plan = outbound_plan(trip(dep_time="07:00"), SPEC, CLOCKS)
        self.assertEqual(plan["door_min"], 960 + 780)

    def test_a_row_with_no_flight_duration_has_no_journey_time(self):
        plan = outbound_plan(
            trip(dep_time="15:00", total_duration_min=None), SPEC, CLOCKS)
        self.assertIsNone(plan["door_min"])


class TestReturnEnd(unittest.TestCase):
    def test_a_return_nobody_captured_is_unknown(self):
        self.assertIsNone(return_plan(trip(), SPEC, CLOCKS))

    def test_a_late_landing_costs_a_night(self):
        plan = return_plan(
            trip(ret_arr_date="2027-02-09", ret_arr_time="21:00"),
            SPEC, CLOCKS)
        self.assertTrue(plan["overnight"])
        self.assertEqual(plan["hotel_eur"], 120)
        self.assertEqual(plan["home_arr"], "2027-02-10T12:00:00")

    def test_an_afternoon_landing_gets_you_home(self):
        plan = return_plan(
            trip(ret_arr_date="2027-02-09", ret_arr_time="10:00"),
            SPEC, CLOCKS)
        self.assertFalse(plan["overnight"])
        self.assertEqual(plan["home_arr"], "2027-02-09T18:30:00")

    def test_landing_home_is_never_a_night(self):
        plan = return_plan(
            trip(origin="BER", ret_airport="BER",
                 ret_arr_date="2027-02-09", ret_arr_time="23:40"),
            SPEC, CLOCKS)
        self.assertFalse(plan["overnight"])

    def test_the_return_journey_counts_the_train_home(self):
        plan = return_plan(
            trip(ret_arr_date="2027-02-09", ret_arr_time="10:00",
                 ret_duration_min=800), SPEC, CLOCKS)
        self.assertEqual(plan["door_min"], 800 + 510)


class TestApplyJourney(unittest.TestCase):
    def test_both_ends_are_attached(self):
        rows = [trip(dep_time="07:00", ret_arr_date="2027-02-09",
                     ret_arr_time="21:00", ret_duration_min=800)]
        apply_journey(rows, PARAMS)
        row = rows[0]
        self.assertTrue(row["out_overnight"])
        self.assertTrue(row["ret_overnight"])
        self.assertEqual(hotel_cost(row), 240)
        self.assertEqual(row["journey_min"],
                         row["out_door_min"] + row["ret_door_min"])

    def test_an_unchecked_return_leaves_the_total_unknown(self):
        rows = [trip(dep_time="15:00")]
        apply_journey(rows, PARAMS)
        self.assertIsNone(rows[0]["journey_min"])
        self.assertIsNone(rows[0]["ret_overnight"])
        self.assertEqual(hotel_cost(rows[0]), 0)

    def test_an_unchecked_end_is_never_charged_for_a_hotel(self):
        rows = [trip(dep_time="07:00")]
        apply_journey(rows, PARAMS)
        self.assertEqual(hotel_cost(rows[0]), 120)


if __name__ == "__main__":
    unittest.main()
