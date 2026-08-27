# Flight search skill: design

Date: 2026-08-27
Status: approved for planning

## Problem

The existing artifact in this repo (`fare-board.html`, built from `flights.json`)
was produced by hand-transcribing 18 Google Flights screenshots. That works once.
It does not scale to a search with six origins, and it cannot be re-run when
prices move.

Replace the screenshot step with browser automation against Google Flights, and
package the whole pipeline as a reusable skill.

The driving example, and the first real run:

| | |
|---|---|
| Destination | Sao Paulo (SAO: GRU, CGH, VCP) |
| Outbound window | 19-23 Dec 2026 (5 dates) |
| Return window | 9-12 Feb 2027 (4 dates) |
| Origins, max 2 stops | BER |
| Origins, max 1 stop | FRA, HAM, MUC, PRG, AMS |
| Passengers | 1 adult, economy |
| Trip type | Open jaw allowed: depart from any of the six, return into any of the six |
| Ticket | One multi-city ticket, not two one-ways |
| Currency | EUR, prices are trip totals per person |

Open jaw is what makes this hard. Fixed to the same airport both ways, six
origins across twenty date pairs is 120 searches, and Google's date grid
collapses that to 6. Allowing a different return airport makes it 36 airport
pairs across 20 date pairs, or 720 combinations, and removes the date grid,
because Google offers no grid for multi-city searches. The trick that made the
problem cheap stops working precisely where it is needed.

Returning into Berlin is also not equivalent to returning into Frankfurt. The
return airport is ranked, not merely another variable: BER costs nothing to get
home from and every other airport costs a train.

## Non-goals

- No more than two legs. One outbound, one return. This is an open jaw, not a
  multi-stop tour, and no stopover cities get planned.
- No two-ticket bookings. An open jaw must be purchasable as a single multi-city
  ticket. The sum of two one-way fares is never presented as a price the user
  could pay.
- No booking, no price alerts, no monitoring over time. A run is a snapshot.
- No ground transport pricing. Airport access from Berlin appears as a static
  note per airport, not as a computed surcharge added to fares.
- No third-party flight APIs. Prices must match what Google shows, because a
  price the user cannot pay at checkout is worse than no price.

## Decisions

Each of these was settled during brainstorming. Recorded with the reasoning so a
later reader does not reopen them.

**Never trust a price the search did not return.** Date pickers, price
calendars and price graphs are all precomputed caches, and they go stale. Only a
real search, sorted by price, states what a flight costs. Everything else is a
hint at best and wrong at worst.

Two measurements from the spike, both on live pages:

- The departure calendar quoted 977 EUR for 19 Dec while the results list for
  the identical query showed 861 EUR. 13% high.
- Default result ordering ("Top flights") led with 1161 EUR while the cheapest
  result on the same page was 1151 EUR, sitting further down under "Other
  flights".

So no number reaches the artifact unless a search returned it under an explicit
price sort. Calendars are not used to price, and they are not used to rank
either: a stale calendar that mis-ranks sends the whole funnel down the wrong
branch, which is worse than a stale calendar that misprices.

**Every search URL carries the price sort.** `&tfu=EgYIAhAAGAA` produces "Sorted
by price" on load. Verified against a hand-built `tfs` link. No clicking, and no
search can accidentally be read in default order.

**Deep links, not UI driving.** Google Flights encodes the full query (airports,
dates, cabin, passenger count, stop limit) in a base64 protobuf `tfs=` URL
parameter. Every search becomes a single navigation to a URL that already has
its filters applied. Clicking is reserved for the two things a URL cannot
express: opening the date grid, and expanding an itinerary to see leg times.

The alternative, driving the search form, needs roughly ten interactions per
search against a custom autocomplete widget that is the most fragile part of the
page. The cost of deep links is that `tfs` is undocumented and can change.

**Scrape `aria-label`, not CSS classes.** Google's class names are obfuscated
and rotate. The accessibility labels are stable full sentences:

> From 812 euros round trip total. 1 stop flight with TAP Air Portugal. Leaves
> Berlin Brandenburg Airport at 6:15 PM on Saturday, December 19 and arrives at
> Sao Paulo/Guarulhos International Airport at 10:40 AM on Sunday, December 20.
> Total duration 20 hr 25 min. Layover (1 of 1) is a 8 hr 5 min layover at
> Lisbon Portela Airport in Lisbon.

One regex pass over that yields price, carrier, stop count, both endpoints with
dates and times, total duration, and layover airport and duration. This choice
is what gives the skill a chance of still working on the next trip.

**Ground access is flagged, not priced.** A 40 EUR fare from Prague is not a 40
EUR trip, but inventing a surcharge produces false precision. Each origin card
carries a plain note (approximate travel time and typical cost from Berlin) and
the user does the arithmetic.

**A night layover is a price, not a veto.** A layover is a night layover if its
interval intersects 23:00-06:00 in local time at the layover airport. There is
no grading of how useful a daytime layover might be, and no scoring of night
severity. One boolean.

A night layover does not disqualify a trip. It obliges the trip to be
considerably cheaper, defined as saving at least 150 EUR **or** at least 20%
against the baseline, whichever is easier to clear:

```
qualifies  <=>  baseline_price - trip_price  >=  min(150, 0.20 * baseline_price)
```

The absolute floor binds on expensive fares and the percentage binds on cheap
ones, so the rule behaves sensibly whether the field sits at 400 EUR or 1200.

**The baseline is the cheapest trip in the run with no night layover, in any
direction, from any origin.** That is the true opportunity cost: what it costs
to sleep in a bed instead. A per-origin baseline was rejected because it flatters
night options departing from expensive airports, which is the opposite of
useful.

Night trips that fail the test are not deleted. They render muted with the
shortfall stated, so the user can see what was passed on and disagree.

**Open jaw on a single ticket.** Any of the six European airports out, any of
the six back. Booked as one multi-city ticket, which prices near a round trip
and well under two one-ways, and which leaves the airline owing a rebooking when
a connection breaks. Two separate one-ways were rejected: cheaper occasionally,
unprotected always.

**Discovery may be approximate; every price shown as final must be bookable.**
One-way scans are how open-jaw candidates get found and ranked. They are not how
they get priced. A number in the artifact is either confirmed by a search the
user could book from, or it is labelled an estimate and never ranked against a
confirmed one.

**Outbound-first for the return direction.** See "The round-trip asymmetry".

## Architecture

One search shape does nearly all the work. A multi-city query accepts several
airports in **both** legs, so a single load covers all 36 airport pairs for one
date pair, at real bookable prices, sorted by price.

That leaves dates as the only dimension needing enumeration, and there are 20 of
them.

| Stage | What | Loads | Prices are |
|---|---|---|---|
| 1. Sweep | One multi-city search per date pair, all six origins in leg 1 and all six return airports in leg 2, price-sorted | 20 | bookable |
| 2. Backfill | Per-origin searches for any origin the sweep never returned, on the three best date pairs | 0-9 | bookable |
| 3. Expand | Per-leg times for the finalists, producing the night-layover flag | 12+ | n/a |

Roughly 32 to 41 loads for 720 combinations, and **every price in the run is one
a search returned.** There is no indicative tier and no calendar anywhere in the
pipeline.

### Why the backfill stage exists

The sweep returns a capped list. Measured on 19 Dec / 9 Feb at one stop: 13
results, drawn only from FRA, AMS, MUC and PRG. Berlin and Hamburg did not
appear at all, and not because they had no flights. They were crowded out by
cheaper airports.

A capped list is fine for finding the cheap frontier and useless for the
question "is Munich ever worth it", which needs a number for every origin
including the losers. Absence in a capped list is not evidence of expense.

So stage 2 runs a per-origin search for each origin the sweep never returned,
restricted to the three best date pairs. Usually one or two origins qualify, so
the stage costs 0 to 9 loads. Every origin ends the run with a real price
attached or an explicit "no result under these constraints".

### The stop-budget asymmetry

BER may use two stops, the other five only one. A single sweep search carries one
stop limit, so the two cannot be expressed together.

Resolution: the sweep runs at one stop, which is correct for five of the six
origins. BER's two-stop allowance is handled in stage 2, where BER is searched on
its own and can carry its own limit. This also means BER is likely to need
backfilling regardless of crowding, which is fine, since it is the one origin
with a different rule and the one the user lives in.

### The round-trip asymmetry

A Google Flights round-trip search does not return round trips. It returns
outbound options, each labelled with a round-trip total that means "this
outbound, paired with the cheapest return available". The return itinerary is
unknown until an outbound is selected and a second page loads.

So the night-layover flag is cheap in one direction only. The chosen handling:

1. Characterize every outbound fully in stage 3: legs, layovers, night flag.
2. Take the trip total as the price, unmodified. It is a real quoted total, it
   is simply a total whose second leg has not been examined.
3. Expand return itineraries only for the 3-5 finalists the user is choosing
   between.

Full expansion of both directions for every candidate was rejected on cost,
roughly 5-10x the browser work on a page that rate-limits.

The artifact must state, per row, whether return legs were expanded or the price
is Google's cheapest-compatible-return figure. Not marking this would repeat the
mistake the previous artifact caught in its own data, where one fare looked
cheapest only because a filter had not been applied to that search.

## Data model

Written to `runs/<timestamp>/`. Raw scrapes are kept so the artifact can be
rebuilt without re-scraping, and so two runs can be compared.

```
runs/2026-08-27T14-05/
  params.json         the trip definition this run was given
  raw/<search_id>.json   unparsed scrape payloads, one per navigation
  sweep.json          stage 1 output, all date pairs, all airport pairs returned
  backfill.json       stage 2 output, plus which origins needed it and why
  trips.json          stages 1 + 2 merged, every price a search returned
  itineraries.json    normalized, with legs where stage 3 expanded them
  fare-board.html     the artifact
```

**search**

```json
{
  "id": "ber-sao-20261219-20270209",
  "origin": "BER", "dest": "SAO",
  "dep_date": "2026-12-19", "ret_date": "2027-02-09",
  "max_stops": 2, "cabin": "economy", "pax": 1, "currency": "EUR",
  "tfs_url": "https://www.google.com/travel/flights?tfs=...",
  "scraped_at": "2026-08-27T14:06:11Z"
}
```

Storing `tfs_url` makes every row in the artifact reproducible. A user who
doubts a price can open the exact search that produced it.

**trip**

A trip is what the user buys: one outbound itinerary, one return itinerary, one
price. Open jaw made this its own record, because an itinerary no longer implies
its counterpart.

```json
{
  "id": "ams-gru-ber-20261219-20270209",
  "route_kind": "open_jaw",
  "out_origin": "AMS", "ret_dest": "BER", "dest": "SAO",
  "dep_date": "2026-12-19", "ret_date": "2027-02-09",
  "price_total": 734, "currency": "EUR",
  "price_basis": "bookable_multicity",
  "ticket": "single",
  "outbound_id": "tp-ams-lis-gru-20261219",
  "inbound_id": "ib-gru-mad-ber-20270209",
  "search_id": "mc-ams-sao-ber-20261219-20270209",
  "night_layover": true,
  "night_saving_eur": 186,
  "night_saving_pct": 20.2,
  "night_verdict": "justified"
}
```

The three night fields are computed after the whole run finishes, not during
scraping, because the baseline is not known until every finalist has been
expanded. `night_verdict` takes four values:

| Value | Meaning |
|---|---|
| `clean` | No night layover in either direction |
| `justified` | Night layover, clears 150 EUR or 20% against the baseline |
| `not_justified` | Night layover, does not clear it. Shown muted with the shortfall |
| `unknown` | Legs never expanded, so night status was never determined |

`unknown` is not a synonym for `clean` and the artifact must never render it as
one. A trip whose legs were not expanded is a trip nobody has checked.

`route_kind` is `round_trip` when `out_origin` equals `ret_dest`, `open_jaw`
otherwise. `price_basis` is the field the artifact depends on for honesty and
takes exactly three values:

| Value | Source | May be shown as a final price |
|---|---|---|
| `sweep` | Stage 1 multi-city sweep, price-sorted |
| `backfill` | Stage 2 per-origin search, price-sorted |

Both come from a search run under an explicit price sort, so both may be shown
as fares. There is deliberately no third value. An earlier draft carried an
`indicative_oneway` tier fed by calendar scans; dropping calendars removed the
need for it. Any future change that reintroduces an estimated price must add a
value here and a rule barring it from recommendations.

**itinerary**

```json
{
  "id": "tp-ber-lis-gru-20261219",
  "search_id": "ber-sao-20261219-20270209",
  "direction": "out",
  "price_total": 812, "currency": "EUR",
  "price_basis": "cheapest_compatible_return",
  "carriers": ["TP"], "stops": 1,
  "total_duration_min": 1225,
  "legs": [
    {"from": "BER", "to": "LIS", "dep_local": "2026-12-19T18:15",
     "arr_local": "2026-12-19T20:50", "carrier": "TP", "flight_no": "TP539",
     "duration_min": 215},
    {"from": "LIS", "to": "GRU", "dep_local": "2026-12-20T04:55",
     "arr_local": "2026-12-20T10:40", "carrier": "TP", "flight_no": "TP087",
     "duration_min": 525}
  ],
  "layovers": [
    {"airport": "LIS", "start_local": "2026-12-19T20:50",
     "end_local": "2026-12-20T04:55", "duration_min": 485,
     "night_flag": true}
  ],
  "night_layover": true,
  "separate_tickets": false,
  "self_transfer": false,
  "legs_expanded": true
}
```

Leg durations are wall-clock across time zones, not local subtraction: BER
departs 17:15Z and LIS arrives 20:50Z, so leg one is 215 minutes despite the
clock showing 2h35. The three components (215 + 485 + 525) sum to
`total_duration_min`, and a normalizer that cannot make them sum should reject
the row rather than store it.

`legs` and `layovers` are nested arrays rather than the flat `dt`/`at`/`al`
columns used in `flights.json`. Flat columns cannot express a two-stop
itinerary. `legs_expanded` records whether stage 3 ran on this row; when false,
`legs`, `layovers` and `night_layover` are absent rather than guessed.

## Artifact

The previous artifact solved a pairing problem, two tickets meeting in Recife,
so it was built around pairs. This one answers a different question: which
airport to leave from, which airport to come back into, and on which dates. It
is built around that and inherits nothing from the old page beyond the
departure-board vernacular.

**A 6x6 airport matrix, out by back.** Rows are the departure airport, columns
the return airport, cells the cheapest trip found. The diagonal is the
conventional round trip; everything off it is an open jaw. This is the headline
because it is the question the user cannot currently answer at all, and one look
settles it: whether AMS out and BER back beats leaving and returning from
Berlin.

Confirmed and estimated prices must be distinguishable without reading a legend
entry twice. Every price in the run came from a search, so the distinction the
artifact must carry is not estimated against real but expanded against
unexpanded: a trip whose legs were never examined has an unknown night status
and must not read as a clean one.

The BER return column gets called out, because it is the only one with no train
home attached.

**A 5x4 date grid for the leading candidates.** Outbound date by return date,
for the two or three airport pairs still in contention after the matrix. Twenty
cells each, and it answers whether shifting a day is worth anything.

**A card per candidate.** Cheapest fare, its date pair, stop count, total
duration, night flag, and the airport access note from `references/ground.md`
for both ends, since an open jaw has two ground problems rather than one.

**The board.** Every trip, filterable by departure airport, return airport, stop
count, duration and night verdict, sorted by price. Layover chips show airport
and duration, marked when the layover intersects 23:00-06:00 local.

Night trips carry their economics inline rather than as a footnote: a
`justified` trip reads as saving a stated amount against the best comfortable
option, and a `not_justified` trip renders muted with its shortfall stated, so
what was passed on stays visible and arguable. The baseline trip itself is
labelled, because every one of those numbers is relative to it and a reader
should be able to see which row is doing the anchoring.

**Caveats block.** Which rows are estimates, self-transfer connections, whether
the stop limit was applied to a given search, and which rows have expanded
return legs. The previous artifact earned its keep by catching that its own
cheapest fare was cheapest only because a filter had been missed. The same
discipline applies here, and open jaw gives it more to catch.

Load `artifact-design` and `dataviz` before building. The matrix needs a proper
sequential palette that still reads when half its cells are muted, and airline
brand colours stay reserved for encoding carriers rather than decoration.

## Skill layout

`~/.claude/skills/flight-search/`

| File | Job |
|---|---|
| `SKILL.md` | Trigger conditions, the five stages, known failure modes |
| `scripts/tfs.py` | Query definition to Google Flights deep link, round trip, one way and multi-city |
| `scripts/extract.js` | The `aria-label` scraper, injected via `javascript_tool` |
| `scripts/normalize.py` | Raw scrapes to `itineraries.json` |
| `scripts/build_board.py` | `itineraries.json` to the artifact |
| `references/ground.md` | Airport access notes, as editable data |

Parameters are the trip, not this trip. Origins carry a per-origin stop budget,
which turns the BER-gets-2-stops rule from a special case into an input:

```json
{
  "dest": "SAO",
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
  "pax": 1, "cabin": "economy", "currency": "EUR",
  "night_layover_window": ["23:00", "06:00"],
  "night_discount": {"abs_eur": 150, "pct": 20, "mode": "either"}
}
```

`return_airports` defaults to the origin list but is separately settable, since
a trip can be flexible on one end and fixed on the other. `open_jaw: false`
restores same-airport round trips, which collapses the sweep to one search per
date pair with a single origin list and no return-airport dimension. Worth
keeping for trips that do not need open jaw.

## Risks

**Resolved by the spike: `tfs` expresses the stop limit**, multi-city links work,
multi-airport works on both legs, and `tfu` sets the price sort. The no-clicking
engine stands. Field numbers are recorded under "The wire format".

**A stale cache read as a fare.** The single easiest mistake for an
implementation to make, because a calendar cell looks exactly like a price and
is 13% wrong. There is no calendar in the pipeline and there must not be one. If
a future optimization proposes reading a price graph or date grid to save loads,
that is this risk returning.

**A default-sorted page read as cheapest.** Equally easy, equally invisible.
Every generated URL carries `&tfu=EgYIAhAAGAA`, and the scraper should assert
the page says "Sorted by price" before recording anything from it. A page that
does not say so has been served in an order nobody asked for.

**The sweep silently under-covers.** It returns a capped list, so an origin can
vanish for being expensive rather than for being unavailable. Stage 2 exists for
this, and it only works if stage 1 records which origins it actually saw. An
origin that appears in no result and gets no backfill must be reported as "not
determined", never as absent or expensive.

**`tfs` multi-city encoding is a different shape.** Round-trip and one-way
queries differ mostly in a flag. Multi-city carries a repeated leg structure, so
`tfs.py` has genuinely two things to get right rather than one.

**Google changes the page.** The whole design rests on `aria-label` grammar,
`data-iso` attributes and two opaque URL parameters. The `aria-label` sentences
are the most stable of these and the parsers should key off them. A run that
parses zero results from a page that loaded must fail loudly rather than record
an empty result set.

**Rate limiting.** A full run is 32 to 41 navigations. Pace them, and treat an
empty results list as a possible block rather than as "no flights found". A run
that silently records zero results is worse than one that fails loudly.

**Locale drift.** The browser session is German. Force `hl=en&gl=de&curr=EUR` so
the `aria-label` regexes parse English strings and prices come back in euros.

## Spike results, 2026-08-27

All five questions answered against the live site with a hand-rolled encoder and
no protobuf library. Nothing in the architecture had to change.

| # | Question | Answer |
|---|---|---|
| 1 | Multi-city `tfs` link works? | Yes. AMS-GRU out, GRU-BER back rendered as Multi-city, priced at 1353 EUR |
| 2 | Several airports in one leg's field? | **Yes.** All six return airports accepted in one search |
| 3 | Stop limit honoured in the URL? | Yes. Page shows "All filters (1), 1 stop or fewer" |
| 4 | `aria-label` scrapeable, same grammar both modes? | Yes, one grammar. One way says "From 977 euros.", multi-city says "From 1353 euros total." |
| 5 | Date window in one load? | Better than hoped. See below |

### The wire format

`tfs` is a base64url-encoded protobuf, no padding. Field numbers, confirmed
working:

```
Airport    { name = 2 (string, IATA), type = 3 (varint, 1) }
FlightData { date = 2 (string, YYYY-MM-DD), max_stops = 5 (varint),
             from = 13 (repeated Airport), to = 14 (repeated Airport) }
Info       { data = 3 (repeated FlightData), max_stops = 5 (varint),
             passengers = 8 (repeated varint, 1 = adult),
             seat = 9 (varint, 1 = economy), trip = 19 (varint) }
trip: 1 = round trip, 2 = one way, 3 = multi city
```

Appending `&hl=en&gl=de&curr=EUR` produced English labels and euro prices with no
consent interstitial. Roughly forty lines of varint writing, no dependency.

### Multi-airport legs, and what they buy

The multi-city return field accepted all six airports and rendered them as
`Amsterdam AMS · Berlin BER · Frankfurt am Main FRA · Hamburg HAM · Munich MUC ·
Prague PRG`. Stage 1 therefore prices every return airport for a date pair in
one load rather than six.

The same query priced at 1276 EUR against 1353 EUR when the return was pinned to
BER alone. Open jaw paid for itself on the first search anyone ran.

### The date calendar, and a caveat that matters

Clicking a one-way search's departure field opens a calendar carrying 97 priced
cells spanning 2026-08-27 to 2027-01-31, each tagged `data-iso` with its exact
date. Stage 1 reads a whole five-month window per origin in one load, not the
five days the spec asked for. Dates parse from the attribute, so no month
boundary has to be inferred.

The caveat: for 19 Dec the calendar said 977 EUR while the results list for the
same query said 861 EUR. **Calendar prices are not the cheapest bookable fare.**
They track a representative fare, and they run high. This is confirmation of the
design rather than a problem for it. The gap is real, it reached 13% on the one
case measured, and it is why calendars were removed from the pipeline entirely
rather than kept as a cheap ranking hint.

Also measured in passing: 19 Dec at 977 EUR against 20-22 Dec at 821. Departing
one day later saves about 156 EUR before any other variable moves.

### Multi-city has no price calendar

1095 date cells in the multi-city picker, zero of them priced. Return dates
cannot be scanned and must be enumerated, one search per return date. Combined
with dropping calendars, this is why stage 1 enumerates all 20 date pairs
directly rather than trying to narrow them first.

### Revised cost

| Stage | Loads | Note |
|---|---|---|
| 1. Outbound scan | 6 | One per origin. Whole window per load |
| 2. Return probe | 6 | One per return airport |
| 4. Deepen | 16-32 | Candidates x return dates. All six return airports per load |
| 3. Expand | 12+ | Stops on the clean-baseline condition |

Roughly 32 to 41 loads against 720 combinations. Stage 1 is fixed at 20 by the
size of the date windows, so the only variable stages are backfill and expansion,
both driven by what the sweep actually returns.

## Success criteria

- One invocation with the parameter block above produces `trips.json`,
  `itineraries.json` and a published artifact.
- Every itinerary row carries the `tfs_url` that produced it, and opening that
  URL shows the same flight at the same price.
- Three rows spot-checked by hand against a fresh Google Flights search match on
  price, carrier, stop count and times.
- Running the skill for a different trip requires changing only the parameter
  block, no code edits.
- Rows without expanded legs are visibly marked as such in the artifact, never
  shown with a guessed night flag.
- No price in the artifact came from a calendar, a price graph, or a
  default-sorted page. Every recorded page asserted "Sorted by price" first.
- Every origin in the parameter block ends the run with either a real price or an
  explicit "not determined". None is shown as expensive on the strength of having
  been missing from a capped list.
- Every open jaw presented as an option has a multi-city price its `tfs_url`
  reproduces.
- Setting `open_jaw: false` produces a cheaper same-airport run without code
  changes.
- Every trip marked `justified` has its saving recomputable by hand from the
  baseline row shown in the artifact, and the baseline row is identifiable.
- No trip with `night_verdict: unknown` is displayed as though it were `clean`.
- If fewer than three clean trips were found, the artifact says so rather than
  computing a baseline from too few.
