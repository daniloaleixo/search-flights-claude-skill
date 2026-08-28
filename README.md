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

The board carries every fare it captured, cheapest first, with the fare and the
door-to-door cost sortable, each flight's departure and arrival times on the
local clock at each end, and a shortlist of candidates with the reasoning
attached. A worked run from Berlin to Sao Paulo across six origins produced 462
rows from 43 page captures.

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
honest prices sets `open_jaw: false` and sweeps with round trips. That is a
real trade and the example takes the honest-prices side of it.

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
