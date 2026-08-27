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
