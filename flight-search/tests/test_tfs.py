import unittest
from scripts.tfs import (
    Leg, build_url, encode_tfs,
    TRIP_ONE_WAY, TRIP_MULTI_CITY, CHEAPEST_TAB,
)

SIX = ("BER", "FRA", "HAM", "MUC", "PRG", "AMS")

ONE_WAY_BER_GRU = (
    "GiASCjIwMjYtMTItMTlqBxIDQkVSGAFyBxIDR1JVGAEoASgBQAFIAZgBAg"
)
MULTI_AMS_GRU_BER = (
    "GiASCjIwMjYtMTItMTlqBxIDQU1TGAFyBxIDR1JVGAEoARogEgoyMDI3LTAyLTA5"
    "agcSA0dSVRgBcgcSA0JFUhgBKAEoAUABSAGYAQM"
)
SWEEP_SIX_BY_SIX = (
    "Gk0SCjIwMjYtMTItMTlqBxIDQkVSGAFqBxIDRlJBGAFqBxIDSEFNGAFqBxIDTVVDGAFq"
    "BxIDUFJHGAFqBxIDQU1TGAFyBxIDR1JVGAEoARpNEgoyMDI3LTAyLTA5agcSA0dSVRgB"
    "cgcSA0JFUhgBcgcSA0ZSQRgBcgcSA0hBTRgBcgcSA01VQxgBcgcSA1BSRxgBcgcSA0FN"
    "UxgBKAEoAUABSAGYAQM"
)


class TestEncodeTfs(unittest.TestCase):
    def test_one_way_single_airport(self):
        legs = [Leg("2026-12-19", ("BER",), ("GRU",), max_stops=1)]
        self.assertEqual(
            encode_tfs(legs, TRIP_ONE_WAY, max_stops=1), ONE_WAY_BER_GRU
        )

    def test_multi_city_open_jaw(self):
        legs = [
            Leg("2026-12-19", ("AMS",), ("GRU",), max_stops=1),
            Leg("2027-02-09", ("GRU",), ("BER",), max_stops=1),
        ]
        self.assertEqual(
            encode_tfs(legs, TRIP_MULTI_CITY, max_stops=1), MULTI_AMS_GRU_BER
        )

    def test_sweep_six_origins_six_returns(self):
        legs = [
            Leg("2026-12-19", SIX, ("GRU",), max_stops=1),
            Leg("2027-02-09", ("GRU",), SIX, max_stops=1),
        ]
        self.assertEqual(
            encode_tfs(legs, TRIP_MULTI_CITY, max_stops=1), SWEEP_SIX_BY_SIX
        )

    def test_encoding_has_no_base64_padding(self):
        legs = [Leg("2026-12-19", ("BER",), ("GRU",))]
        self.assertNotIn("=", encode_tfs(legs, TRIP_ONE_WAY))


class TestBuildUrl(unittest.TestCase):
    def setUp(self):
        self.legs = [Leg("2026-12-19", ("BER",), ("GRU",), max_stops=1)]

    def test_url_lands_on_the_cheapest_tab_by_default(self):
        url = build_url(self.legs, TRIP_ONE_WAY, max_stops=1)
        self.assertIn("tfu=" + CHEAPEST_TAB, url)

    def test_cheapest_tab_value_is_not_the_best_tab_price_sort(self):
        # "EgYIAhAAGAA" sorts the Best set by price and leaves the cheaper
        # result set unreached. Pinning the distinction so it cannot regress.
        self.assertNotEqual(CHEAPEST_TAB, "EgYIAhAAGAA")
        self.assertEqual(CHEAPEST_TAB, "EgoIAhAAGAAgAigB")

    def test_url_carries_locale_and_currency(self):
        url = build_url(self.legs, TRIP_ONE_WAY, max_stops=1)
        self.assertIn("hl=en", url)
        self.assertIn("gl=de", url)
        self.assertIn("curr=EUR", url)

    def test_tab_selection_can_be_disabled_explicitly(self):
        url = build_url(self.legs, TRIP_ONE_WAY, cheapest_tab=False)
        self.assertNotIn("tfu=", url)


if __name__ == "__main__":
    unittest.main()
