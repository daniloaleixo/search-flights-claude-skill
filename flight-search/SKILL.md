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
on a page whose cheapest row was 1151 EUR.

Sorting by price is not enough either. The results page carries two tabs, Best
and Cheapest, and they are two different result sets rather than two orderings
of one: on FRA-GRU 23 Dec / 12 Feb at one stop, the Best tab's cheapest row was
1159 EUR and the Cheapest tab's was 879 EUR, and the same TAP departure was
1172 EUR on one tab and 1114 EUR on the other. A price-sorted Best page looks
entirely healthy while hiding all of that.

Every generated URL therefore carries `&tfu=EgoIAhAAGAAgAigB`, which lands on
the Cheapest tab, and `ingest.py` refuses any capture whose page did not report
both "Sorted by price" and a selected tab of "Cheapest".

**Multi-city pages have no Cheapest tab at all.** A `trip=3` result page
contains zero `[role="tab"]` elements, so the tfu value is inert there and the
cheaper result set is unreachable. Open jaws are priced as multi-city, so a run
that wants Cheapest-tab fares must set `open_jaw: false` and sweep with
round trips. That is a real trade: open jaws are given up to get honest prices.
`sweep_searches` and `backfill_searches` both switch to `TRIP_ROUND` when
`open_jaw` is false.

## Getting the results off the page

The `javascript_tool` bridge truncates a returned value at about a thousand
characters and `read_page` clips every aria-label to a hundred, so neither can
carry an eleven-row capture. Chrome also blocks a page's second automatic
download, which rules out writing a blob to disk, and Google's CSP blocks
`fetch` and `sendBeacon` to localhost.

What does work is `get_page_text`, which returns the whole page uncapped. So a
capture is two calls: a tiny `javascript_tool` probe returning
`tab=... sort=...` (and polling until the page stops saying "Fetching
results", which takes 20-40 seconds and during which the prices shown are
still moving), then `get_page_text`. `scripts/parse_text.py` reads the text and
`ingest_page_text` applies the same two refusals.

## Running a search

1. Write a params file. Copy `params.sao-paulo.json` and edit the windows,
   origins and stop budgets.

2. Generate the sweep URLs:

       cd flight-search
       python3 -c "import json,sys; from scripts.plan_run import sweep_searches; \
         print(json.dumps(sweep_searches(json.load(open(sys.argv[1])))))" params.sao-paulo.json

3. For each URL: navigate with `mcp__claude-in-chrome__navigate`, poll until
   the page reports "Sorted by price" and has stopped saying "Fetching
   results", then read it with `mcp__claude-in-chrome__get_page_text`. Save
   each capture to `runs/<timestamp>/raw/<search_id>.json` as
   `{url, activeTab, sortedBy, pageText}`. A page still fetching shows prices
   that are minutes from final: on one measured page the top fare moved from
   1025 to 982 EUR between the loading state and the settled one.

   Pace the navigations. The first real run (the Sao Paulo trip) took 43
   captures: 20 sweep loads plus 23 backfill loads. The backfill count varies
   with how many origins need it and how many stops each is allowed, so treat
   43 as a measured data point, not a fixed budget. A page that returns zero
   rows is a blocked or restructured page, not an empty result: stop and say so
   rather than recording it.

4. Ingest, then check coverage:

       python3 -c "from scripts.ingest import merge_captures; ..."
       python3 -c "from scripts.plan_run import origins_needing_backfill; ..."

   Feed the merged rows to `origins_needing_backfill`, not `missing_origins`:
   an origin can appear in every capture and still need a backfill search,
   because the sweep runs at the lowest stop budget across all origins and
   an origin allowed more stops than that never got to use them. Whatever it
   returns goes to `backfill_searches` with the three cheapest date pairs.

5. Expand the finalists. `expansion_targets` gives the batch; for each, click
   the row to reveal per-leg times, collect them, and compute layover windows
   with `layover_windows(legs, window=params.get("night_layover_window", ...))`.
   Pass the params window through explicitly rather than relying on
   `layover_windows`'s default, so a run that configured a different band
   (`night_layover_window` in the params file) actually gets it applied.
   Keep expanding until twelve are expanded and at least three have no night
   layover. If thirty expansions pass without three clean trips, stop and
   report that: a field with no comfortable option at any price is itself the
   finding.

6. Apply `apply_night_economics`, then build the page:

       python3 scripts/build_board.py ../runs/<timestamp> > ../fare-board-sao-paulo.html

   (`build_board.py` reads `trips.json` and `params.json` from the run
   directory, plus `coverage.json` if present.) Publish the result with the
   Artifact tool.

## Parameters that are declarative only

`ticket` and `night_discount.mode` in the params file are not read by any
script. `ticket` documents that every open jaw here is booked as one
multi-city ticket, which is a design decision this skill always follows, not
a switch. `night_discount.mode` documents that the "either" rule (clears the
absolute floor or the percentage, whichever is easier) is the only rule
implemented; `abs_eur` and `pct` are the two fields actually read. Both stay
in the params file as documentation for the next reader, not as inputs.

## Constraints this skill enforces

- Stop budgets are per origin. A sweep search carries one limit, so it runs at
  the minimum across origins and any origin allowed more is backfilled alone.
- A night layover is any layover overlapping 23:00-06:00 local at the stop. It
  does not disqualify a trip; it obliges the trip to save at least 150 EUR or
  20% against the cheapest trip in the run with no night layover.
- `night_verdict: unknown` means nobody checked. Never render it as clean.
- Open jaws are booked as one multi-city ticket, never as two one-ways.
- A row's `tfs_url` is the sweep search page it came from, not a link to that
  itinerary: it encodes every origin and one date pair, not one flight.
  Reopening it reopens the search, and the row has to be found again inside
  the results, not the fare by itself.

## When Google changes

The parsers key off `aria-label` sentences, which are the most stable thing on
the page. If a run returns zero rows from a page that loaded, `extract.js` is
where to look first. Golden tests in `tests/test_tfs.py` pin the URL encoding
against three links verified on the live site; if those fail, the wire format
moved.
