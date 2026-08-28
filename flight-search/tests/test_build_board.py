import unittest

from scripts.build_board import (NIGHT_LABELS, _airport_section, _candidates,
                                 _caveats_section, _night_pill,
                                 _ret_airports, airport_matrix,
                                 date_matrix, origin_matrix,
                                 render)
from scripts.normalize import BaselineError, apply_ground_cost

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
        html = markup(render(banded(TRIPS), GROUND_PARAMS, COVERAGE))
        self.assertIn("1151", html)
        self.assertNotIn("1271", html.replace("1271 ", ""))


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
