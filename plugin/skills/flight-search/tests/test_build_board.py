import re
import unittest

from scripts.build_board import (NIGHT_LABELS, _airport_section, _candidates,
                                 _caveats_section, _journey_line, _night_pill,
                                 _door_line, _overnight_pills,
                                 _ret_airports,
                                 airport_matrix, date_matrix, origin_matrix,
                                 render)
from scripts.normalize import (BaselineError, apply_ground_cost,
                               apply_night_economics, assert_all_variants_sound)

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


class TestRetAirportsBareString(unittest.TestCase):
    def test_bare_string_wraps_to_single_element_list(self):
        params = {"return_airports": "BER"}
        self.assertEqual(_ret_airports([], params, ["BER", "FRA"]), ["BER"])

    def test_bare_string_does_not_splat_into_characters(self):
        params = {"return_airports": "BER"}
        result = _ret_airports([], params, ["BER", "FRA"])
        self.assertNotIn("B", result)


class TestCaveatsBackfillReason(unittest.TestCase):
    """The backfilled-origins caveat must state the real reason: absence
    from the sweep, or a stop budget the sweep's shared limit cannot
    express. It must never claim the sweep "returned nothing" for an origin
    that the sweep did in fact return rows for.
    """

    def test_does_not_falsely_claim_absence_when_sweep_had_rows(self):
        # BER: 4 sweep rows, plus a backfill row at a wider stop budget.
        trips = [
            {"origin": "BER", "price_basis": "sweep", "max_stops": 1}
            for _ in range(4)
        ] + [{"origin": "BER", "price_basis": "backfill", "max_stops": 2}]
        params = {"origins": [{"code": "BER", "max_stops": 2}]}
        html = _caveats_section(trips, params, ["BER"], {"BER": "ok"})
        item = html.split("Origins backfilled")[1].split("</li>")[0]
        # The old, false, single-cause claim must be gone.
        self.assertNotIn("returned nothing for them", item)
        # BER's own annotation must show it actually had sweep rows.
        self.assertIn("4 sweep fares", item)

    def test_states_the_stop_budget_trigger_for_an_over_budget_origin(self):
        trips = [
            {"origin": "BER", "price_basis": "sweep", "max_stops": 1}
            for _ in range(4)
        ] + [{"origin": "BER", "price_basis": "backfill", "max_stops": 2}]
        params = {"origins": [{"code": "BER", "max_stops": 2}]}
        html = _caveats_section(trips, params, ["BER"], {"BER": "ok"})
        item = html.split("Origins backfilled")[1].split("</li>")[0]
        self.assertIn("4 sweep fares", item)
        self.assertIn("allows 2 stops", item)
        self.assertIn("sweep&#x27;s 1", item)

    def test_absent_origin_still_says_zero_sweep_fares(self):
        trips = [{"origin": "BER", "price_basis": "backfill", "max_stops": 1}]
        params = {"origins": [{"code": "BER", "max_stops": 1}]}
        html = _caveats_section(trips, params, ["BER"], {"BER": "ok"})
        item = html.split("Origins backfilled")[1].split("</li>")[0]
        self.assertIn("0 sweep fare", item)

    def test_no_backfill_at_all_says_so(self):
        trips = [{"origin": "BER", "price_basis": "sweep", "max_stops": 1}]
        params = {"origins": [{"code": "BER", "max_stops": 1}]}
        html = _caveats_section(trips, params, ["BER"], {"BER": "ok"})
        item = html.split("Origins backfilled")[1].split("</li>")[0]
        self.assertIn("No origin needed a backfill search", item)


class TestCoverageHeading(unittest.TestCase):
    """The coverage heading must match its body: neutral when all origins are
    determined, and "not determined" only when some are not.
    """

    def test_coverage_heading_is_neutral_when_all_origins_covered(self):
        trips = [{"origin": "BER", "price_basis": "sweep"}]
        params = {"origins": [{"code": "BER"}]}
        html = _caveats_section(trips, params, ["BER"], {"BER": "ok"})
        self.assertIn("<h3>Coverage</h3>", html)
        self.assertIn("Every origin returned a usable result page", html)
        self.assertNotIn("Coverage not determined", html)

    def test_coverage_heading_names_condition_when_not_all_origins_determined(self):
        trips = [{"origin": "BER", "price_basis": "sweep"}]
        params = {"origins": [{"code": "BER"}]}
        html = _caveats_section(trips, params, ["BER"], {"BER": "not_determined"})
        self.assertIn("<h3>Coverage not determined</h3>", html)
        self.assertIn("BER did not come back with a usable result page", html)
        # The heading must not contradict by also saying coverage is fine.
        self.assertNotIn("<h3>Coverage</h3>", html)

    def test_coverage_lists_multiple_undetermined_origins(self):
        trips = [{"origin": "BER", "price_basis": "sweep"},
                 {"origin": "FRA", "price_basis": "sweep"}]
        params = {"origins": [{"code": "BER"}, {"code": "FRA"}]}
        html = _caveats_section(trips, params, ["BER", "FRA"],
                               {"BER": "not_determined", "FRA": "not_determined"})
        self.assertIn("BER, FRA did not come back", html)
        self.assertIn("them", html)  # plural form


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


GROUND_PARAMS = dict(PARAMS, ground_cost={"BER": [0, 0], "FRA": [70, 130],
                                          "AMS": [60, 120]})


def banded(trips, params=GROUND_PARAMS):
    rows = [dict(t) for t in trips]
    apply_ground_cost(rows, params)
    return rows


class TestDoorToDoorOnThePage(unittest.TestCase):
    def test_the_masthead_carries_a_door_to_door_figure(self):
        html = markup(render(banded(TRIPS), GROUND_PARAMS, COVERAGE))
        self.assertIn("Cheapest door to door", html)

    def test_it_says_so_when_no_ground_cost_was_given(self):
        html = markup(render(TRIPS, PARAMS, COVERAGE))
        self.assertIn("Cheapest door to door", html)
        self.assertIn("no ground costs were given", html)

    def test_a_card_shows_the_band_and_what_the_ground_adds(self):
        html = markup(render(banded(TRIPS), GROUND_PARAMS, COVERAGE))
        self.assertIn("door to door", html)
        self.assertIn("ground", html)

    def rank_rows(self):
        # AMS at 1151 is the cheaper fare; BER at 1200 is the cheaper trip,
        # because AMS carries 120 to 240 EUR of train and BER carries none.
        return banded([dict(TRIPS[0], origin="AMS", ret_airport="AMS"),
                       dict(TRIPS[1], origin="BER", ret_airport="BER",
                            price_eur=1200)])

    def test_the_shortlist_ranks_on_the_band_not_the_fare(self):
        picks = _candidates(self.rank_rows())
        door = [p for p in picks if "cheapest door to door" in p["why"]]
        self.assertEqual(door[0]["trip"]["origin"], "BER")

    def test_the_cheapest_fare_still_gets_its_own_card(self):
        picks = _candidates(self.rank_rows())
        fare = [p for p in picks if "cheapest fare on the board" in p["why"]]
        self.assertEqual(fare[0]["trip"]["origin"], "AMS")

    def test_the_fare_column_is_never_moved_by_ground_cost(self):
        """The fare cell holds the fare. The door figure gets its own
        column beside it, and must never leak into this one."""
        html = markup(render(banded(TRIPS), GROUND_PARAMS, COVERAGE))
        fare_cells = re.findall(r'<td class="b-price">.*?</td>', html)
        self.assertTrue(fare_cells)
        self.assertTrue(any("1151" in cell for cell in fare_cells))
        for cell in fare_cells:
            self.assertNotIn("1271", cell)
            self.assertNotIn("1211", cell)

    def test_the_door_figure_gets_a_column_of_its_own(self):
        html = markup(render(banded(TRIPS), GROUND_PARAMS, COVERAGE))
        self.assertIn('data-sort-key="door"', html)
        self.assertIn(">Door to door<", html)
        door_cells = re.findall(r'<td class="b-door">.*?</td>', html)
        self.assertTrue(any("1271" in cell for cell in door_cells))

    def test_the_table_splits_the_total_into_train_and_bed(self):
        html = markup(render(costed([priced("AMS", 900, dep_time="07:00")]),
                             PRICED_PARAMS, {"AMS": "ok"}))
        cell = re.findall(r'<td class="b-door">.*?</td>', html)[0]
        self.assertIn("1140", cell)
        self.assertIn("+120 train", cell)
        self.assertIn("+120 bed", cell)

    def test_a_trip_with_no_ground_journey_shows_no_breakdown(self):
        html = markup(render(costed([priced("BER", 1050)]), PRICED_PARAMS,
                             {"BER": "ok"}))
        cell = re.findall(r'<td class="b-door">.*?</td>', html)[0]
        self.assertIn("1050", cell)
        self.assertNotIn("door-split", cell)


class TestBorderlineRendering(unittest.TestCase):
    def test_the_pill_names_the_range_rather_than_a_verdict(self):
        pill = _night_pill({"night_verdict": "borderline",
                            "night_saving_eur": 114,
                            "night_saving_hi_eur": 234})
        self.assertIn("114 to 234", pill)
        self.assertIn("pill--borderline", pill)

    def test_borderline_has_its_own_label(self):
        self.assertIn("too close to call", NIGHT_LABELS["borderline"])

    def test_the_caveats_explain_what_decides_a_borderline_row(self):
        rows = banded(TRIPS)
        rows[0]["night_verdict"] = "borderline"
        html = _caveats_section(rows, GROUND_PARAMS, ORIGINS, COVERAGE)
        self.assertIn("Verdicts the ground estimate decides", html)

    def test_no_borderline_rows_means_no_such_caveat(self):
        html = _caveats_section(banded(TRIPS), GROUND_PARAMS, ORIGINS, COVERAGE)
        self.assertNotIn("Verdicts the ground estimate decides", html)


class TestGroundCaveat(unittest.TestCase):
    def test_it_says_the_estimate_is_not_in_the_fare(self):
        html = _caveats_section(banded(TRIPS), GROUND_PARAMS, ORIGINS, COVERAGE)
        self.assertIn("not in the fare", html)

    def test_it_names_the_airports_with_no_ground_cost(self):
        params = dict(PARAMS, ground_cost={"BER": [0, 0], "AMS": [60, 120]})
        html = _caveats_section(banded(TRIPS, params), params, ORIGINS, COVERAGE)
        self.assertIn("No ground cost was given for FRA", html)

    def test_a_run_with_no_ground_costs_gets_no_such_caveat(self):
        html = _caveats_section(TRIPS, PARAMS, ORIGINS, COVERAGE)
        self.assertNotIn("not in the fare", html)


class TestVanishedRows(unittest.TestCase):
    def test_the_caveats_name_rows_that_could_not_be_re_found(self):
        rows = [dict(t) for t in TRIPS]
        rows[2]["expansion_missing"] = True
        html = _caveats_section(rows, PARAMS, ORIGINS, COVERAGE)
        self.assertIn("had vanished by the time we went back", html)

    def test_no_such_caveat_when_every_row_was_reachable(self):
        html = _caveats_section(TRIPS, PARAMS, ORIGINS, COVERAGE)
        self.assertNotIn("had vanished by the time we went back", html)


class TestBaselineGate(unittest.TestCase):
    def rows(self):
        clean = dict(TRIPS[1], legs_expanded=True, night_layover=False)
        return [dict(TRIPS[0]), clean, dict(TRIPS[2])]

    def test_the_board_refuses_a_baseline_an_unexpanded_row_undercuts(self):
        rows = self.rows() + [dict(TRIPS[2], id="t5", price_eur=900)]
        with self.assertRaises(BaselineError):
            render(rows, PARAMS, COVERAGE)

    def test_a_sound_run_renders(self):
        self.assertIn("<title>", render(self.rows(), PARAMS, COVERAGE))


if __name__ == "__main__":
    unittest.main()


class TestCaveatsTripShape(unittest.TestCase):
    TRIPS = [{"origin": "AMS", "price_basis": "sweep", "max_stops": 1,
              "price_eur": 933, "legs_expanded": True}]
    PARAMS = {"origins": [{"code": "AMS", "max_stops": 1}]}

    def test_round_trip_run_says_there_are_no_open_jaws(self):
        html = _caveats_section(self.TRIPS, dict(self.PARAMS, open_jaw=False),
                                ["AMS"], {"AMS": "ok"})
        self.assertIn("No open jaws in this run", html)
        self.assertNotIn("Where the return airport went", html)

    def test_round_trip_caveat_gives_the_reason_and_the_measured_gap(self):
        html = _caveats_section(self.TRIPS, dict(self.PARAMS, open_jaw=False),
                                ["AMS"], {"AMS": "ok"})
        item = html.split("No open jaws in this run")[1].split("</li>")[0]
        self.assertIn("no Cheapest tab", item)
        self.assertIn("1159", item)
        self.assertIn("879", item)

    def test_open_jaw_run_keeps_the_return_airport_caveat(self):
        html = _caveats_section(self.TRIPS, dict(self.PARAMS, open_jaw=True),
                                ["AMS"], {"AMS": "ok"})
        self.assertIn("Where the return airport went", html)
        self.assertNotIn("No open jaws in this run", html)


class TestCaveatsSelfTransfer(unittest.TestCase):
    PARAMS = {"origins": [{"code": "BER", "max_stops": 2}]}

    def test_self_transfer_rows_are_named_and_counted(self):
        trips = [
            {"origin": "BER", "price_basis": "sweep", "max_stops": 2,
             "price_eur": 968, "self_transfer": True, "legs_expanded": True},
            {"origin": "BER", "price_basis": "sweep", "max_stops": 2,
             "price_eur": 939, "self_transfer": False, "legs_expanded": True},
        ]
        html = _caveats_section(trips, self.PARAMS, ["BER"], {"BER": "ok"})
        item = html.split("Self-transfer fares")[1].split("</li>")[0]
        self.assertIn("1 of 2 rows", item)
        self.assertIn("968", item)
        self.assertNotIn("939", item)

    def test_a_board_with_no_self_transfers_says_so(self):
        trips = [{"origin": "BER", "price_basis": "sweep", "max_stops": 2,
                  "price_eur": 939, "self_transfer": False,
                  "legs_expanded": True}]
        html = _caveats_section(trips, self.PARAMS, ["BER"], {"BER": "ok"})
        item = html.split("Self-transfer fares")[1].split("</li>")[0]
        self.assertIn("No row on the board is a self transfer", item)


class TestAirportSectionBlurb(unittest.TestCase):
    """The sparse airport grid has two different causes and they must not be
    described interchangeably: in an open-jaw run the cells are unmeasured,
    in a round-trip run they do not exist."""

    TRIPS = [{"origin": "AMS", "ret_airport": "AMS", "price_eur": 933,
              "price_basis": "sweep", "max_stops": 1, "legs_expanded": True}]

    def test_round_trip_run_does_not_call_empty_cells_unmeasured(self):
        html = _airport_section(self.TRIPS, ["AMS"], ["AMS"], (933, 1774),
                                open_jaw=False)
        self.assertIn("never priced", html)
        self.assertNotIn("unmeasured, not empty", html)

    def test_open_jaw_run_keeps_the_unmeasured_wording(self):
        html = _airport_section(self.TRIPS, ["AMS"], ["AMS"], (933, 1774),
                                open_jaw=True)
        self.assertIn("unmeasured, not empty", html)


PRICED_PARAMS = {
    "dest": "GRU", "currency": "EUR",
    "ground": {
        "BER": {"eur": 0, "hours": 1.0, "home": True},
        "AMS": {"eur": 60, "hours": 7.0, "hotel_eur": 120,
                "first_train": "05:00", "last_train": "19:00"},
    },
}
PRICED_COVERAGE = {"BER": "ok", "AMS": "ok"}


def priced(origin, price, night=False, dep_time="15:00", **kw):
    row = {"origin": origin, "ret_airport": origin, "dest": "GRU",
           "price_eur": price, "dep_date": "2026-12-23",
           "ret_date": "2027-02-09", "dep_time": dep_time,
           "total_duration_min": 780, "legs_expanded": True,
           "night_layover": night, "stops": 1, "carriers": ("KLM",),
           "tfs_url": "https://example/x"}
    row.update(kw)
    return row


def costed(rows, params=PRICED_PARAMS):
    apply_night_economics(rows, params)
    return rows


class TestTheHotelSwitch(unittest.TestCase):
    def rows(self):
        return costed([priced("AMS", 900, dep_time="07:00"),
                       priced("BER", 1050)])

    def test_the_switch_is_offered_when_both_worlds_exist(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        self.assertIn('id="hotel-switch"', html)

    def test_both_shortlists_are_shipped_complete(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        self.assertIn('class="cards v-hotels"', html)
        self.assertIn('class="cards v-no_hotels"', html)

    def test_a_run_with_no_worlds_offers_no_switch(self):
        html = markup(render(TRIPS, PARAMS, COVERAGE))
        self.assertNotIn('id="hotel-switch"', html)

    def test_paying_for_the_bed_changes_the_cheapest_trip(self):
        rows = self.rows()
        with_hotel = _candidates(rows, "hotels")[0]
        without = _candidates(rows, "no_hotels")[0]
        self.assertEqual(with_hotel["trip"]["origin"], "BER")
        self.assertEqual(without["trip"]["origin"], "AMS")

    def test_the_hotel_shows_in_its_price_only_where_it_is_paid(self):
        row = self.rows()[0]
        self.assertIn("120 EUR", _overnight_pills(row, "hotels"))
        self.assertNotIn("120 EUR", _overnight_pills(row, "no_hotels"))

    def test_the_warning_itself_never_depends_on_the_switch(self):
        row = self.rows()[0]
        for variant in ("hotels", "no_hotels"):
            self.assertIn("night before the flight",
                          _overnight_pills(row, variant))


class TestJourneyTimeOnThePage(unittest.TestCase):
    def test_the_shortlist_ranks_duration_from_the_front_door(self):
        rows = costed([
            priced("AMS", 900, dep_time="15:00", total_duration_min=700),
            priced("BER", 1050, total_duration_min=780),
        ])
        picks = _candidates(rows, "hotels")
        shortest = [p for p in picks if "shortest door to door" in p["why"]]
        self.assertEqual(shortest[0]["trip"]["origin"], "BER")

    def test_air_time_is_still_shown_as_air_time(self):
        html = markup(render(costed([priced("BER", 1050)]),
                             PRICED_PARAMS, {"BER": "ok"}))
        self.assertIn("In the air", html)

    def test_the_card_says_when_to_leave_home(self):
        html = markup(render(costed([priced("AMS", 900, dep_time="07:00")]),
                             PRICED_PARAMS, {"AMS": "ok"}))
        self.assertIn("leave home 15:00", html)

    def test_an_unopened_return_says_so_rather_than_showing_nothing(self):
        self.assertIn("the return end has not been opened",
                      _journey_line(costed([priced("BER", 1050)])[0]))

    def test_an_opened_return_gets_a_time_home(self):
        row = costed([priced("BER", 1050, ret_arr_date="2027-02-09",
                             ret_arr_time="10:00", ret_duration_min=800)])[0]
        self.assertIn("back: home", _journey_line(row))


class TestGroundCaveats(unittest.TestCase):
    def caveats(self, rows):
        return _caveats_section(rows, PRICED_PARAMS, ["BER", "AMS"],
                                PRICED_COVERAGE)

    def test_the_assumed_prices_are_printed(self):
        html = self.caveats(costed([priced("AMS", 900, dep_time="07:00")]))
        self.assertIn("AMS 60 EUR and 7h, hotel 120", html)

    def test_unreachable_flights_are_counted(self):
        html = self.caveats(costed([priced("AMS", 900, dep_time="07:00")]))
        self.assertIn("Flights you cannot reach on the day", html)

    def test_unopened_return_ends_are_disclosed(self):
        html = self.caveats(costed([
            priced("AMS", 900, dep_time="07:00"),
            priced("BER", 1050, ret_arr_date="2027-02-09",
                   ret_arr_time="10:00", ret_duration_min=800),
        ]))
        self.assertIn("Return ends nobody opened", html)

    def test_a_run_with_every_return_unopened_makes_no_such_claim(self):
        html = self.caveats(costed([priced("AMS", 900, dep_time="07:00")]))
        self.assertNotIn("Return ends nobody opened", html)


class TestTheGateRunsInBothWorlds(unittest.TestCase):
    def test_a_board_unsound_in_either_world_is_refused(self):
        rows = costed([
            priced("BER", 1050),
            dict(priced("AMS", 900, dep_time="07:00"), legs_expanded=False,
                 night_layover=None),
        ])
        with self.assertRaises(BaselineError):
            render(rows, PRICED_PARAMS, PRICED_COVERAGE)

    def test_the_default_world_is_restored_after_the_gate_refuses(self):
        rows = costed([
            priced("BER", 1050),
            dict(priced("AMS", 900, dep_time="07:00"), legs_expanded=False,
                 night_layover=None),
        ])
        with self.assertRaises(BaselineError):
            assert_all_variants_sound(rows)
        self.assertEqual(rows[0]["door_lo_eur"],
                         rows[0]["variants"]["hotels"]["door_lo_eur"])


class TestTheStylesheetStaysInTheStylesheet(unittest.TestCase):
    """CSS appended after `</style>` renders as a wall of text at the top of
    the page and silently stops applying. It happened once; this notices."""

    def test_no_rule_leaks_into_the_markup(self):
        body = markup(render(costed([priced("AMS", 900, dep_time="07:00"),
                                     priced("BER", 1050)]),
                             PRICED_PARAMS, PRICED_COVERAGE))
        for rule in (".v-no_hotels {", ".switch {", ".card-journey {"):
            self.assertNotIn(rule, body)

    def test_the_hiding_rule_is_actually_present(self):
        html = render(costed([priced("BER", 1050)]), PRICED_PARAMS,
                      {"BER": "ok"})
        style = html.partition("<style>")[2].partition("</style>")[0]
        self.assertIn(".v-no_hotels { display: none; }", style)
        self.assertIn("#hotel-switch:not(:checked) ~ *", style)
        # :has() with .page as its subject asks the browser to re-check a
        # subtree holding every row, and blanked the page. Comments may
        # still name it; rules may not.
        rules = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
        self.assertNotIn(":has(", rules)


LAYOVER_PARAMS = dict(
    PRICED_PARAMS,
    layover_hotel={"min_hours": 8, "default_eur": 90,
                   "eur": {"FCO": 80, "FOR": 40}},
)


def with_layover(code, minutes, **kw):
    row = priced("BER", 1050, night=True, **kw)
    row["layovers"] = [{"code": code, "minutes": minutes}]
    row["layover_windows"] = [{"code": code, "minutes": minutes,
                               "night_flag": True,
                               "start": "2026-12-23T20:00:00",
                               "end": "2026-12-24T10:00:00"}]
    return row


class TestANightInTransitCostsABed(unittest.TestCase):
    def test_a_long_night_layover_carries_a_bed(self):
        rows = costed([with_layover("FCO", 14 * 60), priced("BER", 1200)],
                      LAYOVER_PARAMS)
        self.assertEqual(rows[0]["lay_hotel_eur"], 80)
        self.assertEqual(rows[0]["variants"]["hotels"]["door_lo_eur"], 1130)

    def test_a_short_night_layover_is_spent_in_the_terminal(self):
        rows = costed([with_layover("FOR", 6 * 60 + 45), priced("BER", 1200)],
                      LAYOVER_PARAMS)
        self.assertEqual(rows[0]["lay_hotel_eur"], 0)
        self.assertEqual(rows[0]["variants"]["hotels"]["door_lo_eur"], 1050)

    def test_an_unlisted_airport_falls_back_to_the_default(self):
        rows = costed([with_layover("CMN", 19 * 60), priced("BER", 1200)],
                      LAYOVER_PARAMS)
        self.assertEqual(rows[0]["lay_hotel_eur"], 90)

    def test_no_price_and_no_default_means_no_bed_not_a_free_one(self):
        params = dict(PRICED_PARAMS,
                      layover_hotel={"min_hours": 8, "eur": {"FCO": 80}})
        rows = costed([with_layover("CMN", 19 * 60), priced("BER", 1200)],
                      params)
        self.assertEqual(rows[0]["lay_hotel_eur"], 0)

    def test_the_bed_disappears_when_the_switch_is_off(self):
        rows = costed([with_layover("FCO", 14 * 60), priced("BER", 1200)],
                      LAYOVER_PARAMS)
        self.assertEqual(rows[0]["variants"]["no_hotels"]["door_lo_eur"], 1050)

    def test_a_row_nobody_expanded_gets_no_bed(self):
        row = priced("BER", 1050, night=None)
        row["legs_expanded"] = False
        rows = costed([row, priced("BER", 1200)], LAYOVER_PARAMS)
        self.assertEqual(rows[0]["lay_hotel_eur"], 0)

    def test_the_card_says_where_each_night_is_spent(self):
        rows = costed([with_layover("FCO", 14 * 60), priced("BER", 1200)],
                      LAYOVER_PARAMS)
        line = _door_line(rows[0], LAYOVER_PARAMS)
        self.assertIn("80 of beds", line)
        self.assertIn("a night at FCO in transit", line)


class TestTheBoardCanBeReordered(unittest.TestCase):
    """The two money columns are sortable, and the sort is the reader's.

    Nothing here runs the script: what these assert is that every number a
    click needs is already in the markup, so the browser reorders rows it
    was handed rather than recomputing a fare.
    """

    def rows(self):
        return costed([priced("AMS", 900, dep_time="07:00"),
                       priced("BER", 1050)])

    def board_rows(self, html):
        body = html.partition('<table class="board"')[2]
        return re.findall(r"<tr[^>]*>", body.partition("<tbody>")[2])

    def test_both_money_columns_are_sort_controls(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        head = html.partition('<table class="board"')[2].partition(
            "</thead>")[0]
        self.assertIn('data-sort-key="fare"', head)
        self.assertIn('data-sort-key="door"', head)
        self.assertEqual(head.count("<button"), 2)

    def test_no_other_column_pretends_to_be_sortable(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        head = html.partition('<table class="board"')[2].partition(
            "</thead>")[0]
        self.assertEqual(head.count("data-sort-key"), 2)

    def test_fare_ships_marked_as_the_sorted_column(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        head = html.partition('<table class="board"')[2].partition(
            "</thead>")[0]
        fare = head.partition('data-sort-key="fare"')[0]
        self.assertIn('aria-sort="ascending"', fare.rpartition("<th")[2])
        self.assertEqual(head.count('aria-sort="ascending"'), 1)

    def test_every_row_carries_the_fare_it_sorts_on(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        rows = self.board_rows(html)
        self.assertEqual([r for r in rows if 'data-fare="900"' in r],
                         [rows[0]])
        self.assertIn('data-fare="1050"', rows[1])

    def test_a_row_carries_a_door_figure_for_each_world(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        row = self.board_rows(html)[0]
        # AMS at 07:00 cannot be reached that morning: 900 + 120 of train,
        # and 120 more for the bed once the switch counts it.
        self.assertIn('data-door-no_hotels="1020"', row)
        self.assertIn('data-door-hotels="1140"', row)

    def test_a_fare_nobody_returned_carries_no_sort_key(self):
        rows = costed([priced("BER", 1050)])
        rows.append(dict(priced("AMS", 0), price_eur=None, legs_expanded=False,
                         night_verdict="unknown"))
        html = markup(render(rows, PRICED_PARAMS, PRICED_COVERAGE))
        blank = [r for r in self.board_rows(html) if "data-fare" not in r]
        self.assertEqual(len(blank), 1)
        self.assertNotIn("data-door", blank[0])

    def test_the_script_reads_the_world_the_switch_is_in(self):
        html = render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE)
        script = html.rpartition("<script>")[2]
        self.assertIn('"data-door-" + world', script)
        self.assertIn('box.checked) ? "no_hotels" : "hotels"', script)

    def test_the_blurb_says_the_columns_move(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        self.assertIn("reorders the board when you click its heading", html)


class TestClockTimesInTheTable(unittest.TestCase):
    """When each flight leaves and lands, and what is not known.

    An outbound comes with its times from the search itself; a return only
    has them once somebody opened the itinerary, so the two halves of the
    same row can legitimately disagree about how much is known.
    """

    def rows(self, **kw):
        row = priced("BER", 1050, dep_time="10:05", arr_time="06:10",
                     arr_date="2026-12-24", **kw)
        return costed([row, priced("AMS", 1200, dep_time="09:00")])

    def cells(self, html):
        body = html.partition('<table class="board"')[2].partition(
            "<tbody>")[2]
        return re.findall(r'<td class="b-when">.*?</td>', body)

    def test_the_outbound_carries_both_of_its_times(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        out = self.cells(html)[0]
        self.assertIn("10:05", out)
        self.assertIn("06:10", out)
        self.assertIn("23 Dec", out)

    def test_landing_the_next_day_says_so(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        self.assertIn('<sup class="when-plus">+1</sup>', self.cells(html)[0])

    def test_landing_the_same_day_carries_no_marker(self):
        rows = costed([priced("BER", 1050, dep_time="08:00",
                              arr_time="19:30", arr_date="2026-12-23"),
                       priced("AMS", 1200)])
        html = markup(render(rows, PRICED_PARAMS, PRICED_COVERAGE))
        self.assertNotIn("when-plus", self.cells(html)[0])

    def test_a_return_nobody_opened_says_why_it_is_blank(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        back = self.cells(html)[1]
        self.assertIn("9 Feb", back)
        self.assertIn("times not opened", back)

    def test_a_captured_return_shows_its_times(self):
        rows = self.rows(ret_dep_date="2027-02-09", ret_dep_time="20:40",
                         ret_arr_date="2027-02-10", ret_arr_time="17:05",
                         ret_captured=True)
        html = markup(render(rows, PRICED_PARAMS, PRICED_COVERAGE))
        back = self.cells(html)[1]
        self.assertIn("20:40", back)
        self.assertIn("17:05", back)
        self.assertIn('<sup class="when-plus">+1</sup>', back)
        self.assertNotIn("times not opened", back)

    def test_every_row_gets_both_cells(self):
        html = markup(render(self.rows(), PRICED_PARAMS, PRICED_COVERAGE))
        self.assertEqual(len(self.cells(html)), 4)

    def test_the_caveat_counts_the_returns_that_were_opened(self):
        rows = self.rows(ret_dep_date="2027-02-09", ret_dep_time="20:40",
                         ret_arr_date="2027-02-10", ret_arr_time="17:05")
        html = markup(render(rows, PRICED_PARAMS, PRICED_COVERAGE))
        self.assertIn("the 1 of 2 rows whose return end was actually "
                      "opened", html)

    def test_a_missing_arrival_date_is_not_a_day_earlier(self):
        rows = costed([priced("BER", 1050, dep_time="10:05",
                              arr_time="06:10"),
                       priced("AMS", 1200)])
        html = markup(render(rows, PRICED_PARAMS, PRICED_COVERAGE))
        self.assertNotIn("when-plus", self.cells(html)[0])
