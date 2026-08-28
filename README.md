# flight-search

A Claude Code skill that compares flights across several departure airports and
a range of dates, then publishes a fare board priced from your front door
rather than from the terminal.

It exists because the cheap number Google Flights shows you is usually not the
cheap number, and because the cheapest fare is often not the cheapest trip.

## What it does

You give it a destination, a set of origin airports, a departure window and a
return window. It drives Google Flights through generated deep links, reads
every result page, and builds a single HTML board.

Every screenshot below is from one real run: Berlin to Sao Paulo, six origins,
five departure dates against four return dates, 462 fares out of 43 page loads.

![The board's masthead: cheapest fare 879 EUR from Frankfurt, cheapest door to
door 939 EUR from Berlin, 462 fares on the board, 105 itineraries
expanded](docs/board-masthead.png)

The two headline numbers are the whole argument. The cheapest fare in the run
is 879 EUR from Frankfurt. The cheapest trip is 939 EUR from Berlin, because
Frankfurt is four and a half hours from the front door and Berlin is one. A
fare-only board would have sent this traveller to the wrong airport.

The checkbox under them switches the board between two worlds, one counting the
hotel a flight forces when it cannot be reached on the day and one not, for a
traveller who has a free bed somewhere. Only the money moves, never the hours.

### Every airport, every date pair

![One grid per departure airport, outbound date down the side and return date
across the top, cheapest fare in each cell, all grids sharing one colour
scale](docs/board-matrices.png)

The view the sweep genuinely supports, so it leads. One grid per departure
airport, outbound date down the side, return date across the top. The grids
share a single colour scale, so a cell means the same fare whichever airport it
sits under, and Munich's flat 882 across four return dates reads at a glance
against Prague's 952 to 1421 spread.

Cells nobody measured say `not determined` rather than sitting empty. An empty
cell reads as cheap; this one reads as unchecked, which is what it is.

### Every fare captured

![The board table sorted cheapest first, showing fare, door-to-door cost, route,
departure and arrival clock times, stops, duration and
carriers](docs/board-table.png)

Every fare, cheapest first, with both money columns sortable. Under each date is
when the flight leaves and when it lands, each on the local clock at its own end,
so a `+1` means the landing is the next day.

The column beside the fare is what the trip costs from your door. Watch the
Munich row: an 882 EUR fare becomes 1001 door to door, `+74 train, +45 bed`,
because that departure is too early to reach by train and the traveller sleeps
near the airport the night before. The fare column never moves. A fare plus
anything else is not a fare, so the ground journey travels beside it instead.

A night layover does not disqualify a trip either. It obliges the trip to be
considerably cheaper, and the night column says whether it is, or says that
nobody checked.

## Two ideas the board is built on

**Never record a price the search did not return.** Date pickers, price
calendars and price graphs are precomputed caches and they go stale. On one
measured query the departure calendar quoted 977 EUR for a search whose own
results list showed 861 EUR. Default result order is not price order either,
and sorting by price is still not enough: the results page carries a Best tab
and a Cheapest tab, and they are two different result sets rather than two
orderings of one. On FRA to GRU at one stop, the Best tab's cheapest row was
1159 EUR and the Cheapest tab's was 879 EUR. Every URL the skill generates
lands on the Cheapest tab, and the ingest step refuses any capture whose page
did not report both "Sorted by price" and a selected tab of "Cheapest".

**The ground journey is compared, never added.** A fare is bought at an
airport; a trip starts at a front door. Every fare on the board is a number
Google returned and nothing is ever added to it. Beside it sits a second
figure: the fare, plus the train at both ends, plus any night the journey
forces. Ranking on fares alone recommended Amsterdam at 933 EUR over Berlin at
939 on the first run, when Amsterdam carried 120 EUR of rail on top and Berlin
carried none.

That second figure also answers a question a fare-only board cannot. Work back
from a departure through check-in and the train; if that lands before the first
train of the day, the flight cannot be reached and the trip carries a hotel. On
the Sao Paulo run, 174 of the 462 fares were unreachable on the day.

## What it handles

### Searching

- **One sweep across the whole grid.** Every origin against every date pair in
  the two windows, in a single search per date pair rather than one per
  airport.
- **Stop budgets per origin.** A sweep search carries one limit, so it runs at
  the lowest budget across your origins and any origin allowed more stops is
  backfilled on its own afterwards. An origin can appear in every capture and
  still need that backfill.
- **The Cheapest tab, or nothing.** Every generated URL lands on it, and ingest
  refuses a capture whose page did not report both "Sorted by price" and a
  selected tab of "Cheapest".
- **Waits for the page to settle.** A results page that is still fetching shows
  prices minutes from final. On one measured page the top fare moved from 1025
  to 982 EUR between the loading state and the settled one.
- **Reads visible page text.** The browser bridge truncates a returned value at
  about a thousand characters, which cannot carry an eleven-row capture, so the
  parser works from the full page text instead.
- **Coverage is tracked.** An origin that never returned a usable page is named
  on the board rather than quietly missing from it.

### Costing

- **Door to door.** The fare, plus the train at both ends, plus any night the
  journey forces. The fare column itself never moves.
- **Reachability.** Work back from the departure through check-in and the
  train; land before the first train of the day and the flight cannot be
  reached, so the trip carries a hotel. The same rule runs in reverse against
  the last train home. On the Sao Paulo run that was 174 of 462 fares.
- **Three kinds of bed.** Before the flight when the outbound is out of reach,
  in transit when a night layover runs long enough to be worth leaving the
  airport for, and after landing when the return misses the last train.
- **Journey time, not air time.** A 13-hour flight from Amsterdam is a 28-hour
  journey from Berlin. The shortlist's fastest candidate ranks on the door to
  door figure, timezone included.
- **Two worlds.** Every trip is priced and judged twice, counting the forced
  hotels and not, for a traveller who has a free bed somewhere. The page ships
  both and switches on a checkbox. Only the money moves; a forced night is a
  night spent whoever paid for the bed.

### Judging

- **Night layovers are detected, not assumed.** Any layover overlapping the
  configured band, 23:00 to 06:00 by default, measured on the local clock at
  the stop.
- **A night layover has to earn itself.** It does not disqualify a trip; it
  obliges the trip to save at least 150 EUR or 20% against the cheapest trip in
  the run with no night layover, whichever is easier to clear. Both figures are
  yours to set.
- **The shortlist is picked by role, not by rank.** A list of the four cheapest
  fares mostly repeats itself. These do not: cheapest door to door, cheapest
  fare on the board, cheapest with no night layover, the night layover that
  pays for itself, and the shortest door to door. The whole shortlist is
  recomputed per world, because the switch can change which trip is cheapest
  and which layover is worth it.
- **Every origin gets looked at.** Expansion puts one look per origin ahead of
  the cheapest-first budget. Without that floor the batch comes off one end of
  the price range, and on the first run Hamburg was never expanded once while
  Berlin got two tries and no clean result. The board would have said least
  about the airports the traveller could most easily use.

### Refusing

The board raises rather than draws when it would otherwise mislead.

- **An unchecked baseline.** Every night verdict is measured against one row,
  the cheapest expanded trip with no night layover. A cheaper row nobody opened
  could be the real baseline and would move every verdict in the same
  direction, so the run stops. On the Sao Paulo re-run it fired and it was
  right: three Berlin itineraries under the baseline had never been opened.
- **A world that does not hold.** The same gate runs in both the hotels and
  no-hotels worlds before the page renders.
- **A half-priced airport.** A non-home airport missing `hotel_eur`,
  `first_train` or `last_train` is refused outright, because a missing
  `last_train` reads an unchecked airport as one you can always get home from.
- **Unknown is never drawn as clean.** A verdict nobody checked, a return end
  nobody opened, a bed nobody priced: each says so. An unpriced bed is unknown,
  not free.
- **The board states its own limits.** A caveats section names the origins that
  needed a backfill and why that makes their fares a different search, which
  numbers are estimates rather than quoted prices, which itineraries could not
  be found again, and what the run never determined.

## Install

```
/plugin marketplace add daniloaleixo/search-flights-claude-skill
/plugin install flight-search@daniloaleixo
```

Or clone it and symlink the skill directly:

```bash
git clone https://github.com/daniloaleixo/search-flights-claude-skill.git
ln -s "$PWD/search-flights-claude-skill/plugin/skills/flight-search" \
      ~/.claude/skills/flight-search
```

Do one or the other, not both, or the skill loads twice.

### Requirements

- Claude Code.
- The Claude in Chrome extension. The skill reads real result pages in a real
  browser; there is no API behind it.
- Python 3.9 or newer. Standard library only, nothing to install.

## Running a search

Copy the example params into your working directory and edit it:

```bash
cp ~/.claude/skills/flight-search/params.example.json params.json
```

Then ask Claude for what you want, in your own words:

> Compare flights to Sao Paulo leaving between 19 and 23 December and coming
> back between 9 and 12 February, from Berlin, Frankfurt, Hamburg, Munich,
> Prague or Amsterdam, using params.json.

Claude runs the sweep, ingests the captures, expands the finalists to read
their layovers, re-checks the shortlist against a live search, and publishes
the board. Expect it to take a while: the first real run was 43 page loads, and
a page that is still fetching shows prices that are minutes from final.

Captures and the board land in `flight-runs/<timestamp>/` under your working
directory. They are your data and never go near the installed skill.

## The params file

The example is a real run, Berlin to Sao Paulo, so its origins and its ground
prices belong to one traveller. Edit them.

| Block | What it sets |
|---|---|
| `dest`, `dep_window`, `ret_window` | Where and when, each window a date range |
| `origins` | Airport codes with a `max_stops` budget each; one may be `"ground": "home"` |
| `ground` | Per airport: train fare, hours from front door to terminal, hotel price, first and last train |
| `ground_timing` | `check_in_hours`, `disembark_hours`, `hotel_arrive_by` |
| `layover_hotel` | `min_hours` before a night layover is worth a bed, and prices per airport |
| `night_layover_window` | The band that makes a layover a night layover, 23:00 to 06:00 by default |
| `night_discount` | What a night layover must save to be worth it: `abs_eur`, `pct`, whichever is easier |

An airport with no `ground` entry gets no door-to-door figure at all rather
than one with a missing end quietly set to zero, and the board says which. A
non-home airport missing `hotel_eur`, `first_train` or `last_train` is refused
outright, because a missing `last_train` reads an unchecked airport as one you
can always get home from.

`references/ground.md` inside the skill explains the model and shows the
Berlin numbers in full.

## What it will not do

**Open jaws cost you the Cheapest tab.** A multi-city results page contains no
tabs at all, so the cheaper result set is unreachable there. A run that wants
honest prices sets `open_jaw: false` and sweeps with round trips. That is a real
trade and the example takes the honest-prices side of it. The board shows you
the cost of that choice rather than hiding it:

![A six by six departure-airport by return-airport matrix with fares on the
diagonal only and every other cell marked not
determined](docs/board-return-matrix.png)

Six of thirty-six cells exist. The off-diagonal ones are not open jaws that came
back expensive; they were never priced at all.

**It is scraping.** The parser reads the page's visible text, which is the most
stable surface Google offers, but Google can still move. A run that returns
zero rows from a page that loaded is a parser problem, not an empty result, and
the skill is written to stop and say so rather than record a blank.

**Some numbers are estimates and are labelled as such.** In the example, the
train fares are real ticket prices. The hotel prices and the eight-hour floor
below which a night layover is not worth a bed are not, and a bed is large
enough to reorder the board.

**A row is not a permalink.** A captured fare is a fact about the moment it was
captured. Fares move between the capture pass and the expansion pass, so the
shortlist is re-checked against a fresh live search before anything is
recommended.

## Layout

```
.claude-plugin/marketplace.json   this repo as a plugin marketplace
plugin/
  .claude-plugin/plugin.json
  skills/flight-search/
    SKILL.md                      the instructions Claude follows
    params.example.json           a real run, to copy and edit
    references/ground.md          the ground journey model
    scripts/                      URL building, parsing, costing, rendering
    tests/                        287 tests, standard library unittest
```

Run the tests from the skill directory:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -t .
```

The golden tests in `tests/test_tfs.py` pin the Google Flights URL encoding
against three links verified on the live site. If those fail, the wire format
moved.

## License

MIT. See [LICENSE](LICENSE).
