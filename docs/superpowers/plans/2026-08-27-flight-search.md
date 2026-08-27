# Flight Search Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable `flight-search` skill that drives Google Flights through generated deep links, scrapes price-sorted results, and publishes a comparison artifact for multi-origin open-jaw trips.

**Architecture:** A thin browser layer collects raw strings and does no interpretation; everything else is pure Python with unit tests. `tfs.py` generates search URLs with filters and sort baked in, `extract.js` collects `aria-label` and row text verbatim, `parse.py` turns those strings into records, `normalize.py` applies night-layover economics, `build_board.py` renders the artifact. Claude drives navigation via MCP browser tools between the URL generator and the ingester.

**Tech Stack:** Python 3.13 standard library only (no pip installs, `unittest` for tests), plain JavaScript injected via `mcp__claude-in-chrome__javascript_tool`, git for version control.

**Spec:** `docs/superpowers/specs/2026-08-27-flight-search-design.md`

## Global Constraints

- **Zero runtime dependencies.** No pip installs. Protobuf is hand-encoded; tests use `unittest` from the standard library.
- **Every generated URL carries `&tfu=EgYIAhAAGAA`** (price sort) and `&hl=en&gl=de&curr=EUR`.
- **No price may come from a calendar, date picker, or price graph.** Only price-sorted search results.
- **Refuse to record any page whose text does not contain "Sorted by price".** This is an assertion, not a warning.
- Night layover window: `23:00`-`06:00`, evaluated in **local time at the layover airport**.
- Night discount test: `baseline_price - trip_price >= min(150, 0.20 * baseline_price)`, EUR.
- Stop budgets: `BER` max 2 stops; `FRA`, `HAM`, `MUC`, `PRG`, `AMS` max 1 stop.
- Trip windows: outbound `2026-12-19`..`2026-12-23`, return `2027-02-09`..`2027-02-12`, destination `GRU`, 1 adult, economy.
- `night_verdict: unknown` is never rendered as `clean`.
- Skill is developed at `flight-search/` inside this repo and symlinked into `~/.claude/skills/`, so edits stay under version control.

---

### Task 1: Repository scaffolding and the `tfs` URL builder

The URL builder is first because everything downstream needs URLs, and because the spike produced three URLs verified against the live site. Those become golden tests: if the encoder reproduces them byte for byte, the wire format is correct.

**Files:**
- Create: `.gitignore`
- Create: `flight-search/scripts/__init__.py` (empty)
- Create: `flight-search/scripts/tfs.py`
- Test: `flight-search/tests/test_tfs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Leg(date: str, origins: tuple[str,...], dests: tuple[str,...], max_stops: int|None)`; `encode_tfs(legs, trip, pax=1, seat=1, max_stops=None) -> str`; `build_url(legs, trip, *, pax=1, seat=1, max_stops=None, sort_by_price=True, hl="en", gl="de", curr="EUR") -> str`; constants `TRIP_ROUND=1`, `TRIP_ONE_WAY=2`, `TRIP_MULTI_CITY=3`, `SEAT_ECONOMY=1`, `SORT_BY_PRICE="EgYIAhAAGAA"`.

- [ ] **Step 1: Initialise the repository**

```bash
cd /home/danilo/Documents/danilo/Flight
git init
printf 'runs/\n__pycache__/\n*.pyc\n' > .gitignore
mkdir -p flight-search/scripts flight-search/tests/fixtures flight-search/references
touch flight-search/scripts/__init__.py
git add -A && git commit -m "chore: initialise flight search repo"
```

- [ ] **Step 2: Write the failing golden-URL test**

These three `tfs` values were generated during the spike and confirmed to render the intended search on google.com/travel/flights. Do not edit them to match your encoder; make your encoder match them.

Create `flight-search/tests/test_tfs.py`:

```python
import unittest
from scripts.tfs import (
    Leg, build_url, encode_tfs,
    TRIP_ONE_WAY, TRIP_MULTI_CITY, SORT_BY_PRICE,
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

    def test_url_carries_price_sort_by_default(self):
        url = build_url(self.legs, TRIP_ONE_WAY, max_stops=1)
        self.assertIn("tfu=" + SORT_BY_PRICE, url)

    def test_url_carries_locale_and_currency(self):
        url = build_url(self.legs, TRIP_ONE_WAY, max_stops=1)
        self.assertIn("hl=en", url)
        self.assertIn("gl=de", url)
        self.assertIn("curr=EUR", url)

    def test_sort_can_be_disabled_explicitly(self):
        url = build_url(self.legs, TRIP_ONE_WAY, sort_by_price=False)
        self.assertNotIn("tfu=", url)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd flight-search && python3 -m unittest discover -s tests -t . -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.tfs'`

- [ ] **Step 4: Write the encoder**

Field numbers are from the spec's "The wire format" section. Field emission order matters: changing it changes the bytes and breaks the golden tests.

Create `flight-search/scripts/tfs.py`:

```python
"""Google Flights `tfs=` deep link builder.

The `tfs` query parameter is an undocumented base64url-encoded protobuf.
Field numbers below were confirmed against the live site on 2026-08-27 and
are pinned by golden tests in tests/test_tfs.py.

    Airport    { name = 2 (string, IATA), type = 3 (varint, always 1) }
    FlightData { date = 2 (string YYYY-MM-DD), max_stops = 5 (varint),
                 from = 13 (repeated Airport), to = 14 (repeated Airport) }
    Info       { data = 3 (repeated FlightData), max_stops = 5 (varint),
                 passengers = 8 (repeated varint), seat = 9 (varint),
                 trip = 19 (varint) }

No third-party protobuf library: the subset needed here is two wire types.
"""

import base64
from dataclasses import dataclass

TRIP_ROUND = 1
TRIP_ONE_WAY = 2
TRIP_MULTI_CITY = 3

SEAT_ECONOMY = 1
PASSENGER_ADULT = 1

# &tfu= value that renders "Sorted by price". Verified against a hand-built
# tfs link; without it Google serves "Top flights" order, which is not price
# order and led with a fare 10 EUR above the cheapest on the measured page.
SORT_BY_PRICE = "EgYIAhAAGAA"

BASE = "https://www.google.com/travel/flights"

WIRE_VARINT = 0
WIRE_LEN = 2


@dataclass(frozen=True)
class Leg:
    """One flight leg. `origins` and `dests` may each hold several airports."""

    date: str
    origins: tuple
    dests: tuple
    max_stops: int = None


def _varint(n):
    out = b""
    while True:
        chunk = n & 0x7F
        n >>= 7
        out += bytes([chunk | (0x80 if n else 0)])
        if not n:
            return out


def _tag(field_no, wire):
    return _varint((field_no << 3) | wire)


def _varint_field(field_no, value):
    return _tag(field_no, WIRE_VARINT) + _varint(value)


def _len_field(field_no, payload):
    return _tag(field_no, WIRE_LEN) + _varint(len(payload)) + payload


def _str_field(field_no, text):
    return _len_field(field_no, text.encode("utf-8"))


def _airport(code):
    return _str_field(2, code) + _varint_field(3, 1)


def _leg(leg):
    payload = _str_field(2, leg.date)
    for code in leg.origins:
        payload += _len_field(13, _airport(code))
    for code in leg.dests:
        payload += _len_field(14, _airport(code))
    if leg.max_stops is not None:
        payload += _varint_field(5, leg.max_stops)
    return payload


def encode_tfs(legs, trip, pax=1, seat=SEAT_ECONOMY, max_stops=None):
    payload = b""
    for leg in legs:
        payload += _len_field(3, _leg(leg))
    if max_stops is not None:
        payload += _varint_field(5, max_stops)
    for _ in range(pax):
        payload += _varint_field(8, PASSENGER_ADULT)
    payload += _varint_field(9, seat)
    payload += _varint_field(19, trip)
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def build_url(legs, trip, *, pax=1, seat=SEAT_ECONOMY, max_stops=None,
              sort_by_price=True, hl="en", gl="de", curr="EUR"):
    parts = ["tfs=" + encode_tfs(legs, trip, pax, seat, max_stops)]
    if sort_by_price:
        parts.append("tfu=" + SORT_BY_PRICE)
    parts += [f"hl={hl}", f"gl={gl}", f"curr={curr}"]
    return BASE + "?" + "&".join(parts)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd flight-search && python3 -m unittest discover -s tests -t . -v`
Expected: PASS, 7 tests

- [ ] **Step 6: Commit**

```bash
git add flight-search/scripts/tfs.py flight-search/scripts/__init__.py flight-search/tests/test_tfs.py
git commit -m "feat: add Google Flights tfs deep link builder"
```

---

### Task 2: Run planner, turning trip parameters into a sweep URL list

**Files:**
- Create: `flight-search/scripts/plan_run.py`
- Create: `flight-search/params.sao-paulo.json`
- Test: `flight-search/tests/test_plan_run.py`

**Interfaces:**
- Consumes: `Leg`, `build_url`, `TRIP_MULTI_CITY` from `scripts.tfs`.
- Produces: `date_pairs(params) -> list[tuple[str, str]]`; `sweep_searches(params) -> list[dict]` where each dict is `{"id": str, "dep_date": str, "ret_date": str, "origins": list[str], "ret_airports": list[str], "max_stops": int, "url": str}`; `backfill_searches(params, missing_origins, best_pairs) -> list[dict]`; `stop_budget(params, origin) -> int`.

- [ ] **Step 1: Write the failing test**

Create `flight-search/tests/test_plan_run.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd flight-search && python3 -m unittest tests.test_plan_run -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.plan_run'`

- [ ] **Step 3: Write the planner**

Create `flight-search/scripts/plan_run.py`:

```python
"""Turn a trip parameter block into the list of searches a run must visit.

The browser work happens between this module and scripts/ingest.py: this
module says which URLs to open, ingest.py consumes what came back.
"""

from datetime import date, timedelta

from scripts.tfs import Leg, build_url, TRIP_MULTI_CITY


def _dates(window):
    start = date.fromisoformat(window[0])
    end = date.fromisoformat(window[1])
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def origin_codes(params):
    return [o["code"] for o in params["origins"]]


def return_airports(params):
    configured = params.get("return_airports", "same_as_origins")
    if configured == "same_as_origins":
        return origin_codes(params)
    return list(configured)


def stop_budget(params, origin):
    for o in params["origins"]:
        if o["code"] == origin:
            return o["max_stops"]
    raise KeyError(f"{origin} is not in params['origins']")


def date_pairs(params):
    return [(d, r) for d in _dates(params["dep_window"])
            for r in _dates(params["ret_window"])]


def _search(params, sid, dep, ret, origins, rets, max_stops):
    legs = [
        Leg(dep, tuple(origins), (params["dest"],), max_stops=max_stops),
        Leg(ret, (params["dest"],), tuple(rets), max_stops=max_stops),
    ]
    return {
        "id": sid,
        "dep_date": dep,
        "ret_date": ret,
        "origins": list(origins),
        "ret_airports": list(rets),
        "max_stops": max_stops,
        "url": build_url(
            legs, TRIP_MULTI_CITY,
            pax=params.get("pax", 1),
            max_stops=max_stops,
            curr=params.get("currency", "EUR"),
        ),
    }


def sweep_searches(params):
    """One multi-city search per date pair, all origins by all return airports.

    A search carries a single stop limit, so the sweep runs at the minimum
    budget across origins. Origins allowed more stops than that are picked up
    by backfill_searches, where they are searched alone.
    """
    origins = origin_codes(params)
    rets = return_airports(params)
    max_stops = min(stop_budget(params, o) for o in origins)
    return [
        _search(params, f"sweep-{dep}-{ret}", dep, ret, origins, rets, max_stops)
        for dep, ret in date_pairs(params)
    ]


def backfill_searches(params, missing_origins, best_pairs):
    """Per-origin searches for origins the sweep never returned.

    An origin missing from a capped result list is not evidence it is
    expensive, so each one gets its own search at its own stop budget before
    the run may say anything about it.
    """
    out = []
    rets = return_airports(params)
    for origin in missing_origins:
        budget = stop_budget(params, origin)
        for dep, ret in best_pairs:
            out.append(_search(
                params, f"backfill-{origin}-{dep}-{ret}",
                dep, ret, [origin], rets, budget,
            ))
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd flight-search && python3 -m unittest tests.test_plan_run -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Write the trip parameter file**

Create `flight-search/params.sao-paulo.json`:

```json
{
  "dest": "GRU",
  "origins": [
    {"code": "BER", "max_stops": 2, "ground": "home"},
    {"code": "FRA", "max_stops": 1},
    {"code": "HAM", "max_stops": 1},
    {"code": "MUC", "max_stops": 1},
    {"code": "PRG", "max_stops": 1},
    {"code": "AMS", "max_stops": 1}
  ],
  "return_airports": "same_as_origins",
  "open_jaw": true,
  "ticket": "single",
  "dep_window": ["2026-12-19", "2026-12-23"],
  "ret_window": ["2027-02-09", "2027-02-12"],
  "pax": 1,
  "cabin": "economy",
  "currency": "EUR",
  "night_layover_window": ["23:00", "06:00"],
  "night_discount": {"abs_eur": 150, "pct": 20, "mode": "either"}
}
```

- [ ] **Step 6: Commit**

```bash
git add flight-search/scripts/plan_run.py flight-search/tests/test_plan_run.py flight-search/params.sao-paulo.json
git commit -m "feat: add run planner for sweep and backfill searches"
```

---

### Task 3: Parse result rows from `aria-label` and row text

Google's class names are obfuscated and rotate; the accessibility sentences do not. Everything structural is read from `aria-label`, and the IATA codes (which the sentences give only as full airport names) come from the row's own visible text.

**Files:**
- Create: `flight-search/scripts/parse.py`
- Create: `flight-search/tests/fixtures/rows.json`
- Test: `flight-search/tests/test_parse.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_price(aria) -> int`; `parse_stops(aria) -> int`; `parse_carriers(aria) -> tuple[str,...]`; `parse_duration_minutes(text) -> int`; `parse_layovers(aria) -> tuple[dict,...]` each `{"minutes": int, "airport_name": str}`; `parse_route(row_text) -> tuple[str, str]`; `parse_endpoints(aria, dep_date) -> dict` with keys `dep_time`, `arr_time`, `dep_date`, `arr_date`; `parse_row(aria, row_text, dep_date) -> dict`; exception `ParseError`.

- [ ] **Step 1: Save real captured rows as a fixture**

These four strings were captured from live pages during the spike. They are the parser's contract.

Create `flight-search/tests/fixtures/rows.json`:

```json
[
  {
    "aria": "From 977 euros. 1 stop flight with Tap Air Portugal. Leaves Berlin Brandenburg Airport at 5:10 PM on Saturday, December 19 and arrives at São Paulo/Guarulhos–Governor André Franco Montoro International Airport at 7:55 PM on Sunday, December 20. Total duration 30 hr 45 min.  Layover (1 of 1) is a 16 hr 30 min layover at Humberto Delgado Airport in Lisbon. Select flight",
    "text": "5:10 PM – 7:55 PM+1\nTap Air Portugal\n30 hr 45 min\nBER–GRU\n1 stop\n16 hr 30 min LIS\n623 kg CO2e\n€977"
  },
  {
    "aria": "From 1161 euros total. 1 stop flight with Lufthansa and LATAM. Operated by Latam Airlines Brasil. Leaves Frankfurt Airport at 7:15 AM on Saturday, December 19 and arrives at São Paulo/Guarulhos–Governor André Franco Montoro International Airport at 8:05 PM on Saturday, December 19. Total duration 16 hr 50 min.  Layover (1 of 1) is a 4 hr 15 min layover at Lisbon Portela Airport in Lisbon. Select flight",
    "text": "7:15 AM – 8:05 PM\nLufthansa, LATAM\n16 hr 50 min\nFRA–GRU\n1 stop\n4 hr 15 min LIS\n623 kg CO2e\n€1,161"
  },
  {
    "aria": "From 1271 euros total. Nonstop flight with LATAM. Operated by Latam Airlines Brasil. Leaves Frankfurt Airport at 8:50 PM on Saturday, December 19 and arrives at São Paulo/Guarulhos–Governor André Franco Montoro International Airport at 5:05 AM on Sunday, December 20. Total duration 12 hr 15 min. Select flight",
    "text": "8:50 PM – 5:05 AM+1\nLATAM\n12 hr 15 min\nFRA–GRU\nNonstop\n564 kg CO2e\n€1,271"
  },
  {
    "aria": "From 1151 euros total. 1 stop flight with ITA. Leaves Amsterdam Airport Schiphol at 5:55 PM on Saturday, December 19 and arrives at São Paulo/Guarulhos–Governor André Franco Montoro International Airport at 6:40 PM on Sunday, December 20. Total duration 28 hr 45 min.  Layover (1 of 1) is a 14 hr 25 min layover at Leonardo da Vinci International Airport in Rome. Select flight",
    "text": "5:55 PM – 6:40 PM+1\nITA\n28 hr 45 min\nAMS–GRU\n1 stop\n14 hr 25 min FCO\n694 kg CO2e\n€1,151"
  }
]
```

- [ ] **Step 2: Write the failing test**

Create `flight-search/tests/test_parse.py`:

```python
import json
import pathlib
import unittest

from scripts.parse import (
    ParseError, parse_carriers, parse_duration_minutes, parse_endpoints,
    parse_layovers, parse_price, parse_route, parse_row, parse_stops,
)

FIXTURES = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "rows.json").read_text()
)
TAP, LH_LATAM, NONSTOP, ITA = FIXTURES


class TestPrice(unittest.TestCase):
    def test_one_way_phrasing(self):
        self.assertEqual(parse_price(TAP["aria"]), 977)

    def test_multi_city_total_phrasing(self):
        self.assertEqual(parse_price(LH_LATAM["aria"]), 1161)

    def test_thousands_separator_in_aria_is_absent_but_handled(self):
        self.assertEqual(parse_price("From 1,151 euros total. Nonstop"), 1151)

    def test_missing_price_raises(self):
        with self.assertRaises(ParseError):
            parse_price("Select flight")


class TestStops(unittest.TestCase):
    def test_nonstop_is_zero(self):
        self.assertEqual(parse_stops(NONSTOP["aria"]), 0)

    def test_one_stop(self):
        self.assertEqual(parse_stops(TAP["aria"]), 1)

    def test_two_stops(self):
        self.assertEqual(parse_stops("From 900 euros. 2 stops flight with X."), 2)


class TestCarriers(unittest.TestCase):
    def test_single_carrier(self):
        self.assertEqual(parse_carriers(TAP["aria"]), ("Tap Air Portugal",))

    def test_two_carriers_joined_by_and(self):
        self.assertEqual(parse_carriers(LH_LATAM["aria"]), ("Lufthansa", "LATAM"))

    def test_operated_by_clause_is_not_a_carrier(self):
        self.assertNotIn("Latam Airlines Brasil", parse_carriers(NONSTOP["aria"]))


class TestDuration(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration_minutes("Total duration 30 hr 45 min."), 1845)

    def test_minutes_only(self):
        self.assertEqual(parse_duration_minutes("a 45 min layover"), 45)

    def test_hours_only(self):
        self.assertEqual(parse_duration_minutes("Total duration 12 hr."), 720)


class TestLayovers(unittest.TestCase):
    def test_single_layover(self):
        got = parse_layovers(TAP["aria"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["minutes"], 990)
        self.assertEqual(got[0]["airport_name"], "Humberto Delgado Airport")

    def test_nonstop_has_none(self):
        self.assertEqual(parse_layovers(NONSTOP["aria"]), ())

    def test_two_layovers_are_both_captured(self):
        aria = ("From 800 euros total. 2 stops flight with X. "
                "Layover (1 of 2) is a 2 hr 5 min layover at Alpha Airport in A. "
                "Layover (2 of 2) is a 1 hr 40 min layover at Beta Airport in B.")
        got = parse_layovers(aria)
        self.assertEqual([l["minutes"] for l in got], [125, 100])


class TestRoute(unittest.TestCase):
    def test_en_dash_separator(self):
        self.assertEqual(parse_route(TAP["text"]), ("BER", "GRU"))

    def test_hyphen_separator(self):
        self.assertEqual(parse_route("7:15 AM\n16 hr\nFRA-GRU\n1 stop"), ("FRA", "GRU"))

    def test_missing_route_raises(self):
        with self.assertRaises(ParseError):
            parse_route("7:15 AM – 8:05 PM\nLufthansa")


class TestEndpoints(unittest.TestCase):
    def test_same_day_arrival(self):
        got = parse_endpoints(LH_LATAM["aria"], "2026-12-19")
        self.assertEqual(got["dep_time"], "07:15")
        self.assertEqual(got["arr_time"], "20:05")
        self.assertEqual(got["dep_date"], "2026-12-19")
        self.assertEqual(got["arr_date"], "2026-12-19")

    def test_next_day_arrival(self):
        got = parse_endpoints(TAP["aria"], "2026-12-19")
        self.assertEqual(got["arr_date"], "2026-12-20")

    def test_midnight_hour_converts_correctly(self):
        aria = ("From 1 euros. Nonstop flight with X. Leaves A at 12:30 AM on "
                "Saturday, December 19 and arrives at B at 12:30 PM on "
                "Saturday, December 19. Total duration 12 hr.")
        got = parse_endpoints(aria, "2026-12-19")
        self.assertEqual(got["dep_time"], "00:30")
        self.assertEqual(got["arr_time"], "12:30")

    def test_arrival_across_new_year_rolls_the_year(self):
        aria = ("From 1 euros. Nonstop flight with X. Leaves A at 10:00 PM on "
                "Thursday, December 31 and arrives at B at 6:00 AM on "
                "Friday, January 1. Total duration 8 hr.")
        got = parse_endpoints(aria, "2026-12-31")
        self.assertEqual(got["arr_date"], "2027-01-01")


class TestParseRow(unittest.TestCase):
    def test_assembles_a_complete_record(self):
        row = parse_row(ITA["aria"], ITA["text"], "2026-12-19")
        self.assertEqual(row["price_eur"], 1151)
        self.assertEqual(row["origin"], "AMS")
        self.assertEqual(row["dest"], "GRU")
        self.assertEqual(row["stops"], 1)
        self.assertEqual(row["total_duration_min"], 1725)
        self.assertEqual(row["layovers"][0]["code"], "FCO")
        self.assertEqual(row["carriers"], ("ITA",))

    def test_layover_codes_come_from_row_text(self):
        row = parse_row(TAP["aria"], TAP["text"], "2026-12-19")
        self.assertEqual(row["layovers"][0]["code"], "LIS")
        self.assertEqual(row["layovers"][0]["minutes"], 990)

    def test_nonstop_row_has_no_layovers(self):
        row = parse_row(NONSTOP["aria"], NONSTOP["text"], "2026-12-19")
        self.assertEqual(row["layovers"], ())

    def test_raw_label_is_retained_for_audit(self):
        row = parse_row(TAP["aria"], TAP["text"], "2026-12-19")
        self.assertEqual(row["raw_aria"], TAP["aria"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd flight-search && python3 -m unittest tests.test_parse -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.parse'`

- [ ] **Step 4: Write the parser**

Create `flight-search/scripts/parse.py`:

```python
"""Turn Google Flights result rows into records.

Two sources per row, each used for what it is good at:

  aria-label  full sentences, stable across releases. Price, stops, carriers,
              clock times, weekday-and-month dates, layover durations.
  row text    the visible cells. IATA codes, which the sentences give only as
              full airport names ("Humberto Delgado Airport").

Nothing here touches the DOM. The browser layer collects strings and this
module interprets them, so every rule below is unit-testable offline.
"""

import re
from datetime import date, datetime, timedelta

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

_PRICE = re.compile(r"From\s+([\d,]+)\s+euros", re.I)
_STOPS = re.compile(r"\b(Nonstop|(\d+)\s+stops?)\s+flight", re.I)
_CARRIERS = re.compile(r"flight with\s+(.+?)\.\s", re.I)
_HR = re.compile(r"(\d+)\s*hr", re.I)
_MIN = re.compile(r"(\d+)\s*min", re.I)
_TOTAL_DURATION = re.compile(r"Total duration\s+([\d\s a-z]+?)\.", re.I)
_LAYOVER = re.compile(
    r"Layover \(\d+ of \d+\) is an?\s+(.+?)\s+layover at\s+(.+?)\s+in\s+[^.]+\.",
    re.I)
_ROUTE = re.compile(r"\b([A-Z]{3})\s*[–—-]\s*([A-Z]{3})\b")
_LAYOVER_CODE = re.compile(r"\b(?:\d+\s*hr\s*)?(?:\d+\s*min\s*)\b([A-Z]{3})\b")
_ENDPOINTS = re.compile(
    r"Leaves\s+(.+?)\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)\s+on\s+\w+day,\s+"
    r"(\w+)\s+(\d{1,2})\s+and arrives at\s+(.+?)\s+at\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s+on\s+\w+day,\s+(\w+)\s+(\d{1,2})",
    re.I)


class ParseError(ValueError):
    """A row did not match the expected grammar."""


def parse_price(aria):
    m = _PRICE.search(aria)
    if not m:
        raise ParseError(f"no price in: {aria[:80]!r}")
    return int(m.group(1).replace(",", ""))


def parse_stops(aria):
    m = _STOPS.search(aria)
    if not m:
        raise ParseError(f"no stop count in: {aria[:80]!r}")
    return 0 if m.group(2) is None else int(m.group(2))


def parse_carriers(aria):
    m = _CARRIERS.search(aria)
    if not m:
        raise ParseError(f"no carriers in: {aria[:80]!r}")
    blob = m.group(1)
    parts = re.split(r",\s*|\s+and\s+", blob)
    return tuple(p.strip() for p in parts if p.strip())


def parse_duration_minutes(text):
    """Minutes from "30 hr 45 min", "12 hr", or "45 min".

    Two separate patterns rather than one with optional halves: a single
    all-optional pattern matches the empty string at position 0 and every
    call raises.
    """
    hours = _HR.search(text)
    minutes = _MIN.search(text)
    if not hours and not minutes:
        raise ParseError(f"no duration in: {text[:80]!r}")
    return int(hours.group(1) if hours else 0) * 60 + \
        int(minutes.group(1) if minutes else 0)


def parse_total_duration_minutes(aria):
    m = _TOTAL_DURATION.search(aria)
    if not m:
        raise ParseError(f"no total duration in: {aria[:80]!r}")
    return parse_duration_minutes(m.group(1))


def parse_layovers(aria):
    return tuple(
        {"minutes": parse_duration_minutes(dur), "airport_name": name.strip()}
        for dur, name in _LAYOVER.findall(aria)
    )


def parse_route(row_text):
    m = _ROUTE.search(row_text)
    if not m:
        raise ParseError(f"no IATA route in: {row_text[:80]!r}")
    return m.group(1), m.group(2)


def parse_layover_codes(row_text):
    route = _ROUTE.search(row_text)
    endpoints = {route.group(1), route.group(2)} if route else set()
    return tuple(c for c in _LAYOVER_CODE.findall(row_text) if c not in endpoints)


def _to_24h(clock):
    return datetime.strptime(clock.replace(" ", ""), "%I:%M%p").strftime("%H:%M")


def _resolve(month_name, day, not_before):
    """Pick the year that puts month/day on or after `not_before`.

    Google omits the year. A December departure arriving in January belongs to
    the following year, and guessing wrong silently shifts a whole itinerary.
    """
    month = MONTHS[month_name.capitalize()]
    for year in (not_before.year, not_before.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= not_before:
            return candidate
    raise ParseError(f"cannot place {month_name} {day} after {not_before}")


def parse_endpoints(aria, dep_date):
    m = _ENDPOINTS.search(aria)
    if not m:
        raise ParseError(f"no endpoints in: {aria[:80]!r}")
    dep_from, dep_clock, dep_month, dep_day, arr_to, arr_clock, arr_month, arr_day = \
        m.groups()
    ref = date.fromisoformat(dep_date)
    resolved_dep = _resolve(dep_month, int(dep_day), ref - timedelta(days=1))
    resolved_arr = _resolve(arr_month, int(arr_day), resolved_dep)
    return {
        "dep_airport_name": dep_from.strip(),
        "arr_airport_name": arr_to.strip(),
        "dep_time": _to_24h(dep_clock),
        "arr_time": _to_24h(arr_clock),
        "dep_date": resolved_dep.isoformat(),
        "arr_date": resolved_arr.isoformat(),
    }


def parse_row(aria, row_text, dep_date):
    """Assemble one result row. Raises ParseError rather than guessing."""
    endpoints = parse_endpoints(aria, dep_date)
    origin, dest = parse_route(row_text)
    durations = parse_layovers(aria)
    codes = parse_layover_codes(row_text)
    layovers = tuple(
        {"minutes": d["minutes"],
         "airport_name": d["airport_name"],
         "code": codes[i] if i < len(codes) else None}
        for i, d in enumerate(durations)
    )
    return {
        "price_eur": parse_price(aria),
        "stops": parse_stops(aria),
        "carriers": parse_carriers(aria),
        "total_duration_min": parse_total_duration_minutes(aria),
        "origin": origin,
        "dest": dest,
        "layovers": layovers,
        "raw_aria": aria,
        "raw_text": row_text,
        **endpoints,
    }
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd flight-search && python3 -m unittest tests.test_parse -v`
Expected: PASS, 27 tests

- [ ] **Step 6: Commit**

```bash
git add flight-search/scripts/parse.py flight-search/tests/test_parse.py flight-search/tests/fixtures/rows.json
git commit -m "feat: parse Google Flights rows from aria-label and row text"
```

---

### Task 4: Night-layover economics and coverage checks

This is where the spec's judgment rules live. All of it is arithmetic over records from Task 3, so all of it is testable without a browser.

**Files:**
- Create: `flight-search/scripts/normalize.py`
- Test: `flight-search/tests/test_normalize.py`

**Interfaces:**
- Consumes: nothing at runtime; operates on dicts shaped like `parse_row` output plus a `legs` list from expansion.
- Produces: `layover_windows(legs) -> list[dict]` each `{"code","start","end","minutes"}` with ISO datetime strings; `is_night_layover(start_iso, end_iso, window=("23:00","06:00")) -> bool`; `night_baseline(trips) -> dict|None`; `night_verdict(trip, baseline, abs_eur=150, pct=20) -> str`; `apply_night_economics(trips, params) -> list[dict]`; `missing_origins(rows, expected) -> list[str]`; `expansion_targets(trips, want=12, want_clean=3) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `flight-search/tests/test_normalize.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd flight-search && python3 -m unittest tests.test_normalize -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.normalize'`

- [ ] **Step 3: Write the module**

Create `flight-search/scripts/normalize.py`:

```python
"""Night-layover economics, coverage checks, and expansion selection.

A night layover does not disqualify a trip; it obliges the trip to be
considerably cheaper. "Considerably" is a saving of at least 150 EUR or at
least 20% against the cheapest trip in the run that has no night layover.
The absolute floor binds on expensive fares, the percentage on cheap ones.
"""

from datetime import datetime, time, timedelta

NIGHT_START = time(23, 0)
NIGHT_END = time(6, 0)
DEFAULT_ABS_EUR = 150
DEFAULT_PCT = 20


def layover_windows(legs):
    """Clock windows between consecutive legs, in local time at the stop."""
    out = []
    for first, second in zip(legs, legs[1:]):
        start = datetime.fromisoformat(first["arr_local"])
        end = datetime.fromisoformat(second["dep_local"])
        out.append({
            "code": first["to"],
            "start": first["arr_local"],
            "end": second["dep_local"],
            "minutes": int((end - start).total_seconds() // 60),
        })
    return out


def is_night_layover(start_iso, end_iso, window=(NIGHT_START, NIGHT_END)):
    """True if the layover overlaps 23:00-06:00 on any night it spans.

    Touching an endpoint does not count: a layover ending exactly at 23:00
    has spent no time in the band.
    """
    night_start, night_end = window
    if isinstance(night_start, str):
        night_start = time.fromisoformat(night_start)
    if isinstance(night_end, str):
        night_end = time.fromisoformat(night_end)

    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)

    day = start.date() - timedelta(days=1)
    while day <= end.date():
        band_start = datetime.combine(day, night_start)
        band_end = datetime.combine(day + timedelta(days=1), night_end)
        if start < band_end and end > band_start:
            return True
        day += timedelta(days=1)
    return False


def night_baseline(trips):
    """Cheapest trip with no night layover whose legs were actually examined.

    Unexpanded trips are excluded: their night status is unknown, and an
    unknown is not a clean.
    """
    clean = [t for t in trips
             if t.get("legs_expanded") and t.get("night_layover") is False]
    return min(clean, key=lambda t: t["price_eur"], default=None)


def night_verdict(trip, baseline, abs_eur=DEFAULT_ABS_EUR, pct=DEFAULT_PCT):
    if not trip.get("legs_expanded") or trip.get("night_layover") is None:
        return "unknown"
    if trip["night_layover"] is False:
        return "clean"
    if baseline is None:
        return "unknown"
    threshold = min(abs_eur, baseline["price_eur"] * pct / 100)
    saving = baseline["price_eur"] - trip["price_eur"]
    return "justified" if saving >= threshold else "not_justified"


def apply_night_economics(trips, params):
    discount = params.get("night_discount") or {}
    abs_eur = discount.get("abs_eur", DEFAULT_ABS_EUR)
    pct = discount.get("pct", DEFAULT_PCT)
    baseline = night_baseline(trips)

    for trip in trips:
        verdict = night_verdict(trip, baseline, abs_eur, pct)
        trip["night_verdict"] = verdict
        trip["is_baseline"] = bool(baseline and trip is baseline)
        if verdict in ("justified", "not_justified"):
            saving = baseline["price_eur"] - trip["price_eur"]
            trip["night_saving_eur"] = saving
            trip["night_saving_pct"] = round(
                saving * 100 / baseline["price_eur"], 1)
        else:
            trip["night_saving_eur"] = None
            trip["night_saving_pct"] = None
    return trips


def missing_origins(rows, expected):
    """Origins the sweep never returned.

    Absence from a capped result list is not evidence of expense, so these
    need their own searches before the run may say anything about them.
    """
    seen = {r["origin"] for r in rows}
    return [code for code in expected if code not in seen]


def expansion_targets(trips, want=12, want_clean=3):
    """The next batch of trips to expand, cheapest first.

    Expansion stops on a condition rather than a count: keep going until
    `want` trips are expanded and at least `want_clean` of them turned out to
    have no night layover. Night status is only known after expanding, so the
    caller loops, calling this again after each batch until it returns [].
    """
    expanded = [t for t in trips if t.get("legs_expanded")]
    clean = [t for t in expanded if t.get("night_layover") is False]
    if len(expanded) >= want and len(clean) >= want_clean:
        return []
    pending = sorted(
        (t for t in trips if not t.get("legs_expanded")),
        key=lambda t: t["price_eur"])
    if len(expanded) < want:
        return pending[:want - len(expanded)]
    return pending[:want_clean - len(clean)]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd flight-search && python3 -m unittest tests.test_normalize -v`
Expected: PASS, 27 tests

- [ ] **Step 5: Run the whole suite**

Run: `cd flight-search && python3 -m unittest discover -s tests -t . -v`
Expected: PASS, 75 tests

- [ ] **Step 6: Commit**

```bash
git add flight-search/scripts/normalize.py flight-search/tests/test_normalize.py
git commit -m "feat: add night-layover economics and coverage checks"
```

---

### Task 5: Browser collector and the sorted-page assertion

The collector interprets nothing. It gathers strings and two facts about the page, so that when Google changes its markup only this file breaks, and it breaks visibly.

**Files:**
- Create: `flight-search/scripts/extract.js`
- Create: `flight-search/scripts/ingest.py`
- Test: `flight-search/tests/test_ingest.py`
- Test: `flight-search/tests/fixtures/capture_sweep.json`

**Interfaces:**
- Consumes: `parse_row`, `ParseError` from `scripts.parse`; `missing_origins` from `scripts.normalize`.
- Produces: `SortOrderError`; `assert_price_sorted(capture) -> None`; `ingest_capture(capture, search) -> list[dict]`; `merge_captures(captures, searches) -> list[dict]`.

- [ ] **Step 1: Write the collector**

Create `flight-search/scripts/extract.js`:

```javascript
// Collected verbatim, interpreted nowhere. Paste into javascript_tool.
//
// Returns every result row's aria-label and visible text plus two page facts
// the ingester asserts on. If Google restructures its markup this file is the
// only thing that breaks, and it breaks loudly by returning zero rows.
(() => {
  const bodyText = document.body.innerText;
  const rows = [...document.querySelectorAll('li')]
    .map((li) => {
      const labelled = li.querySelector('[aria-label]');
      const aria = labelled && labelled.getAttribute('aria-label');
      if (!aria || !/^From /.test(aria)) return null;
      return {
        aria,
        text: li.innerText.replace(/ /g, ' ').trim(),
      };
    })
    .filter(Boolean);

  return {
    url: location.href,
    title: document.title,
    sortedBy: (bodyText.match(/Sorted by[^\n]*/) || [null])[0],
    filters: (bodyText.match(/All filters \(\d+\)/) || [null])[0],
    legFields: [...document.querySelectorAll('input')]
      .map((i) => i.value)
      .filter(Boolean),
    rowCount: rows.length,
    rows,
  };
})()
```

- [ ] **Step 2: Write the failing test**

Create `flight-search/tests/fixtures/capture_sweep.json`:

```json
{
  "url": "https://www.google.com/travel/flights?tfs=X&tfu=EgYIAhAAGAA&hl=en&gl=de&curr=EUR",
  "title": "Berlin and 5 more to São Paulo | Google Flights",
  "sortedBy": "Sorted by price",
  "filters": "All filters (1)",
  "legFields": ["Sat, Dec 19", "Tue, Feb 9"],
  "rowCount": 2,
  "rows": [
    {
      "aria": "From 1151 euros total. 1 stop flight with ITA. Leaves Amsterdam Airport Schiphol at 5:55 PM on Saturday, December 19 and arrives at São Paulo/Guarulhos–Governor André Franco Montoro International Airport at 6:40 PM on Sunday, December 20. Total duration 28 hr 45 min.  Layover (1 of 1) is a 14 hr 25 min layover at Leonardo da Vinci International Airport in Rome. Select flight",
      "text": "5:55 PM – 6:40 PM+1\nITA\n28 hr 45 min\nAMS–GRU\n1 stop\n14 hr 25 min FCO\n694 kg CO2e\n€1,151"
    },
    {
      "aria": "From 1161 euros total. 1 stop flight with Lufthansa and LATAM. Operated by Latam Airlines Brasil. Leaves Frankfurt Airport at 7:15 AM on Saturday, December 19 and arrives at São Paulo/Guarulhos–Governor André Franco Montoro International Airport at 8:05 PM on Saturday, December 19. Total duration 16 hr 50 min.  Layover (1 of 1) is a 4 hr 15 min layover at Lisbon Portela Airport in Lisbon. Select flight",
      "text": "7:15 AM – 8:05 PM\nLufthansa, LATAM\n16 hr 50 min\nFRA–GRU\n1 stop\n4 hr 15 min LIS\n623 kg CO2e\n€1,161"
    }
  ]
}
```

Create `flight-search/tests/test_ingest.py`:

```python
import copy
import json
import pathlib
import unittest

from scripts.ingest import (
    SortOrderError, assert_price_sorted, ingest_capture, merge_captures,
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

    def test_zero_rows_on_a_loaded_page_raises(self):
        empty = copy.deepcopy(CAPTURE)
        empty["rows"] = []
        empty["rowCount"] = 0
        with self.assertRaises(ValueError):
            ingest_capture(empty, SEARCH)

    def test_an_unparseable_row_does_not_silently_vanish(self):
        broken = copy.deepcopy(CAPTURE)
        broken["rows"][0]["text"] = "no route here"
        got = ingest_capture(broken, SEARCH, strict=False)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["origin"], "FRA")


class TestMerge(unittest.TestCase):
    def test_merges_across_captures(self):
        got = merge_captures([CAPTURE, CAPTURE], [SEARCH, dict(SEARCH, id="s2")])
        self.assertEqual(len(got), 4)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd flight-search && python3 -m unittest tests.test_ingest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.ingest'`

- [ ] **Step 4: Write the ingester**

Create `flight-search/scripts/ingest.py`:

```python
"""Consume browser captures and turn them into records.

Two refusals live here, and they are refusals rather than warnings because
both failure modes are invisible in the output they corrupt:

  * A page not sorted by price. Google's default "Top flights" order is not
    price order; on a measured page it led with a fare 10 EUR above the
    cheapest row on that same page.
  * A loaded page with zero parsed rows. That is a blocked or restructured
    page, and recording it as "no flights found" would quietly understate
    an origin for the rest of the run.
"""

from scripts.parse import ParseError, parse_row

PRICE_SORTED = "Sorted by price"


class SortOrderError(RuntimeError):
    """The captured page was not sorted by price."""


def assert_price_sorted(capture):
    sorted_by = capture.get("sortedBy")
    if sorted_by != PRICE_SORTED:
        raise SortOrderError(
            f"page reported {sorted_by!r}, expected {PRICE_SORTED!r}: "
            f"{capture.get('url', '')[:90]}"
        )


def _price_basis(search):
    return "backfill" if search["id"].startswith("backfill-") else "sweep"


def ingest_capture(capture, search, strict=True):
    assert_price_sorted(capture)
    if not capture.get("rows"):
        raise ValueError(
            f"page loaded with zero result rows: {capture.get('url', '')[:90]}"
        )

    records = []
    for row in capture["rows"]:
        try:
            record = parse_row(row["aria"], row["text"], search["dep_date"])
        except ParseError:
            if strict:
                raise
            continue
        record.update({
            "search_id": search["id"],
            "tfs_url": capture["url"],
            "dep_date_searched": search["dep_date"],
            "ret_date": search["ret_date"],
            "max_stops": search["max_stops"],
            "price_basis": _price_basis(search),
            "legs_expanded": False,
            "night_layover": None,
        })
        records.append(record)
    return records


def merge_captures(captures, searches):
    out = []
    for capture, search in zip(captures, searches):
        out.extend(ingest_capture(capture, search))
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd flight-search && python3 -m unittest tests.test_ingest -v`
Expected: PASS, 11 tests

- [ ] **Step 6: Commit**

```bash
git add flight-search/scripts/extract.js flight-search/scripts/ingest.py flight-search/tests/test_ingest.py flight-search/tests/fixtures/capture_sweep.json
git commit -m "feat: add browser collector and capture ingester"
```

---

### Task 6: The artifact builder

**Files:**
- Create: `flight-search/scripts/build_board.py`
- Test: `flight-search/tests/test_build_board.py`

**Interfaces:**
- Consumes: trip records carrying `origin`, `ret_airport`, `price_eur`, `night_verdict`, `legs_expanded`.
- Produces: `airport_matrix(trips, origins, ret_airports) -> dict[(str,str), dict|None]`; `date_matrix(trips, dep_dates, ret_dates) -> dict`; `render(trips, params, coverage) -> str`.

- [ ] **Step 1: Load the design skills**

Before writing any markup, invoke the `artifact-design` skill, then the `dataviz` skill. The matrix needs a sequential palette that still reads when half its cells are muted, and airline brand colours must stay reserved for encoding carriers rather than decoration.

- [ ] **Step 2: Write the failing test**

Create `flight-search/tests/test_build_board.py`:

```python
import unittest

from scripts.build_board import airport_matrix, date_matrix, render

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
        self.assertIn("not checked", self.html.lower())

    def test_origin_without_coverage_is_reported_as_not_determined(self):
        self.assertIn("not determined", self.html.lower())

    def test_justified_night_trip_states_its_saving(self):
        self.assertIn("200", self.html)

    def test_no_doctype_or_body_wrapper(self):
        # The Artifact tool supplies the skeleton; the file is page content.
        self.assertNotIn("<!doctype", self.html.lower())
        self.assertNotIn("<body", self.html.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd flight-search && python3 -m unittest tests.test_build_board -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.build_board'`

- [ ] **Step 4: Write the builder**

Write `flight-search/scripts/build_board.py` implementing the three functions above. It must produce, in this order:

1. A 6x6 airport matrix, departure airport by return airport, cheapest trip per cell. The diagonal is the conventional round trip. Cells with no trip render as empty, not as zero.
2. A per-origin coverage strip. Any origin whose `coverage` entry is not `ok` renders the words "not determined" rather than a price.
3. A 5x4 date grid for the two or three leading airport pairs.
4. A card per candidate carrying price, date pair, stops, duration, night verdict and the ground note from `references/ground.md` for both ends.
5. The board: every trip, sorted by price, with layover chips. `night_verdict == "unknown"` renders the words "not checked" and must not use the styling that `clean` uses.
6. A caveats block listing which origins were backfilled, which rows are unexpanded, and the stop limit each search ran under.

Follow the theming rules from `artifact-design`: define the full light palette on bare `:root`, redefine tokens under `@media (prefers-color-scheme: dark)` guarded as `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. Give `body` an explicit token background. Emit page content only, with no `<!doctype>`, `<html>`, `<head>` or `<body>` tags, since the Artifact tool wraps the file at publish time.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd flight-search && python3 -m unittest tests.test_build_board -v`
Expected: PASS, 11 tests

- [ ] **Step 6: Commit**

```bash
git add flight-search/scripts/build_board.py flight-search/tests/test_build_board.py
git commit -m "feat: render the fare board artifact"
```

---

### Task 7: Skill packaging and ground-access notes

**Files:**
- Create: `flight-search/SKILL.md`
- Create: `flight-search/references/ground.md`

**Interfaces:**
- Consumes: every script from Tasks 1-6.
- Produces: the skill itself, symlinked to `~/.claude/skills/flight-search`.

- [ ] **Step 1: Write the ground-access notes**

These are data, not prose, so they can be corrected without touching code. Times and costs are approximate and are shown to the reader as such; nothing computes with them.

Create `flight-search/references/ground.md`:

```markdown
# Getting to each airport from Berlin

Shown on each origin card. Never added to a fare: a fare plus an estimate is
not a price. The reader does the arithmetic.

| Airport | From Berlin | Rough cost | Note |
|---|---|---|---|
| BER | home | none | The only airport with no journey attached |
| HAM | ~2h by ICE | 30-80 EUR | Shortest hop of the five |
| FRA | ~4h by ICE | 70-130 EUR | Frequent, and the largest long-haul choice |
| PRG | ~4.5h by bus or train | 30-60 EUR | Cheapest to reach, slowest to recover from if a leg slips |
| MUC | ~4.5h by ICE | 70-140 EUR | |
| AMS | ~6.5h by ICE | 60-120 EUR | Longest journey; consider the night before |

Returning into an airport other than BER carries the same journey in reverse,
after a long-haul flight. Worth weighing more heavily on the return than on the
outbound.
```

- [ ] **Step 2: Write the skill definition**

Create `flight-search/SKILL.md`:

```markdown
---
name: flight-search
description: Search Google Flights across several origin airports and flexible dates, including open-jaw trips, and publish a comparison artifact. Use when the user wants flights compared across multiple departure or return airports, across a date range, or wants to know which airport and date combination is cheapest.
---

Drive Google Flights through generated deep links, scrape price-sorted results,
and publish a fare board.

## The rule that governs everything

**Never record a price the search did not return.** Date pickers, price
calendars and price graphs are precomputed caches and they go stale. On
2026-08-27 the departure calendar quoted 977 EUR for a query whose own results
list showed 861 EUR.

Default result order is also not price order. "Top flights" led with 1161 EUR
on a page whose cheapest row was 1151 EUR. Every generated URL carries
`&tfu=EgYIAhAAGAA`, and `ingest.py` refuses any capture whose page did not
report "Sorted by price".

## Running a search

1. Write a params file. Copy `params.sao-paulo.json` and edit the windows,
   origins and stop budgets.

2. Generate the sweep URLs:

       cd flight-search
       python3 -c "import json,sys; from scripts.plan_run import sweep_searches; \
         print(json.dumps(sweep_searches(json.load(open(sys.argv[1])))))" params.sao-paulo.json

3. For each URL: navigate with `mcp__claude-in-chrome__navigate`, wait about
   three seconds for results to render, then run `scripts/extract.js` through
   `mcp__claude-in-chrome__javascript_tool`. Save each capture to
   `runs/<timestamp>/raw/<search_id>.json`.

   Pace the navigations. A full run is 32 to 41 loads. A page that returns zero
   rows is a blocked or restructured page, not an empty result: stop and say so
   rather than recording it.

4. Ingest, then check coverage:

       python3 -c "from scripts.ingest import merge_captures; ..."
       python3 -c "from scripts.normalize import missing_origins; ..."

   Any origin the sweep never returned goes to `backfill_searches` with the
   three cheapest date pairs. An origin missing from a capped list is not
   evidence it is expensive.

5. Expand the finalists. `expansion_targets` gives the batch; for each, click
   the row to reveal per-leg times, collect them, and compute layover windows
   with `layover_windows` and `is_night_layover`. Keep expanding until twelve
   are expanded and at least three have no night layover. If thirty expansions
   pass without three clean trips, stop and report that: a field with no
   comfortable option at any price is itself the finding.

6. Apply `apply_night_economics`, build with `build_board.py`, publish with the
   Artifact tool.

## Constraints this skill enforces

- Stop budgets are per origin. A sweep search carries one limit, so it runs at
  the minimum across origins and any origin allowed more is backfilled alone.
- A night layover is any layover overlapping 23:00-06:00 local at the stop. It
  does not disqualify a trip; it obliges the trip to save at least 150 EUR or
  20% against the cheapest trip in the run with no night layover.
- `night_verdict: unknown` means nobody checked. Never render it as clean.
- Open jaws are booked as one multi-city ticket, never as two one-ways.

## When Google changes

The parsers key off `aria-label` sentences, which are the most stable thing on
the page. If a run returns zero rows from a page that loaded, `extract.js` is
where to look first. Golden tests in `tests/test_tfs.py` pin the URL encoding
against three links verified on the live site; if those fail, the wire format
moved.
```

- [ ] **Step 3: Install the skill**

A symlink, so edits stay under version control in this repo.

```bash
ln -sfn /home/danilo/Documents/danilo/Flight/flight-search ~/.claude/skills/flight-search
ls -l ~/.claude/skills/flight-search
```

Expected: the symlink resolves to the repo directory.

- [ ] **Step 4: Verify the skill file parses**

```bash
head -4 ~/.claude/skills/flight-search/SKILL.md
```

Expected: valid YAML frontmatter with `name: flight-search`.

- [ ] **Step 5: Commit**

```bash
git add flight-search/SKILL.md flight-search/references/ground.md
git commit -m "feat: package flight-search skill with ground access notes"
```

---

### Task 8: Live end-to-end run for the São Paulo trip

The first real use, and the only test that can catch a wrong assumption about the live site.

**Files:**
- Create: `runs/<timestamp>/` (gitignored)
- Modify: `flight-search/scripts/extract.js` if the live page disagrees with the fixture

**Interfaces:**
- Consumes: everything.
- Produces: a published artifact URL.

- [ ] **Step 1: Confirm the full suite passes**

Run: `cd flight-search && python3 -m unittest discover -s tests -t . -v`
Expected: PASS, 97 tests

- [ ] **Step 2: Run one sweep search end to end**

Generate the first sweep URL, navigate, run `extract.js`, and ingest that single capture. Confirm the page reported "Sorted by price", that rows parsed, and that `parse_row` did not raise on any of them.

If any row fails to parse, add it to `tests/fixtures/rows.json`, write a failing test for it, fix `parse.py`, and commit before continuing. Do not add `strict=False` to get past it.

- [ ] **Step 3: Run the remaining 19 sweep searches**

Pace them. Save each capture to `runs/<timestamp>/raw/`. Stop and report if any page returns zero rows.

- [ ] **Step 4: Check coverage and backfill**

Run `missing_origins` against the merged rows and the six origins. BER is expected to need backfilling, both because it carries a different stop budget and because it did not appear in the spike's sweep. Run `backfill_searches` for whatever is missing across the three cheapest date pairs.

- [ ] **Step 5: Expand finalists**

Expand in price order until twelve are done and three are clean. Record per-leg times and compute night flags.

- [ ] **Step 6: Build and publish**

```bash
cd flight-search && python3 scripts/build_board.py ../runs/<timestamp> > ../fare-board-sao-paulo.html
```

Publish with the Artifact tool. Use a new file path, not `fare-board.html`, so the existing Recife artifact keeps its URL.

- [ ] **Step 7: Verify three rows by hand**

Pick three rows spanning different origins. Open each row's `tfs_url` and confirm the price, carrier, stop count and times match. Any mismatch is a bug in the parser, not a rounding difference.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: first live flight search run for Sao Paulo"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: wire format and sort parameter to Task 1; sweep, backfill and stop-budget asymmetry to Task 2; `aria-label` grammar to Task 3; night economics, baseline and the clean-baseline stopping rule to Task 4; the two refusals to Task 5; the artifact including the 6x6 matrix, coverage strip and caveats to Task 6; skill packaging and ground notes to Task 7; the success criteria to Task 8.

Two spec items are deliberately deferred rather than dropped. The round-trip asymmetry (return legs known only after a click) is handled by Task 8 step 5 expanding finalists; no separate module is needed because `layover_windows` already works on whatever legs it is given. The `open_jaw: false` cheaper path is exercised by `sweep_searches` reading `return_airports`, and is covered by the parameter file rather than by a dedicated task.

**Type consistency.** `night_layover` is a tri-state (`True`, `False`, `None`) throughout, with `None` meaning unexpanded; `night_verdict` is the string derived from it. `price_eur` is an int in every module. Layover records carry `minutes`, `airport_name` and `code` from `parse_row` onward, and `code`, `start`, `end`, `minutes` from `layover_windows`, which are different shapes for different stages and are never mixed: parsed layovers have durations only, expanded ones have clock windows.

**Known gap.** `parse_layover_codes` pairs codes to durations positionally. On a two-stop itinerary whose row text orders codes differently from the `aria-label` sentences, the codes could be swapped. The parser sets `code: None` rather than guessing when counts disagree. Task 8 step 2 is the check: if a two-stop row appears in the live run, verify its codes by hand before trusting them.
