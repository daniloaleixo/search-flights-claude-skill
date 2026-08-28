# Getting to each airport from Berlin

A fare is bought at an airport. A trip starts at a front door. For five of the
six origins here that gap is a train, and the train decides three things the
fare cannot show: what it costs, how long it takes, and whether the flight can
be reached on the day at all.

## The table

| Airport | Train, one way | Door to terminal | Bed near the airport | First train | Last train home |
|---|---|---|---|---|---|
| BER | home | 1h | none | any | any |
| HAM | 37 EUR | 2.5h | 80 EUR | 05:00 | 22:00 |
| FRA | 37 EUR | 4.5h | 90 EUR | 05:00 | 20:00 |
| PRG | 29 EUR | 5h | 60 EUR | 05:00 | 19:00 |
| MUC | 37 EUR | 5h | 95 EUR | 05:00 | 20:00 |
| AMS | 60 EUR | 7h | 120 EUR | 05:00 | 19:00 |

These are real ticket prices, not estimates. That distinction runs through the
whole model: a price is a point, so every comparison below settles instead of
straddling a range.

The table is mirrored into the params file twice, and `build_board.py`
deliberately does not parse Markdown, so editing it here means editing both:

- `ground`, the numeric block every calculation reads. One entry per airport:
  `eur`, `hours`, `hotel_eur`, `first_train`, `last_train`, and `home: true`
  for the airport with no journey attached.
- `ground_notes`, the prose the board prints under each candidate.

`ground_spec` refuses a non-home airport missing `hotel_eur`, `first_train` or
`last_train`. A missing `last_train` would silently turn "nobody checked" into
"you can always get home", which is the one failure this model must not have.

The older shape, `ground_cost`, held a `[low, high]` estimate per airport and
is still read when no `ground` block is present, so a run written before the
prices were looked up still works. Nothing else here applies to it: with a band
instead of a price there is no journey time, no feasibility, and no bed.

## Whether the flight can be reached at all

Work backwards from the departure. Be at the terminal `check_in_hours` before
it, which means leaving home that much plus the journey earlier. If that lands
before the first train, the flight cannot be reached on the day: the traveller
goes the evening before and pays for a bed.

At 2.5 hours of check-in and a 05:00 first train, that is the earliest flight
each airport can sell you without a hotel:

    HAM 10:00   FRA 12:00   PRG 12:30   MUC 12:30   AMS 14:30

The return end is the same rule in reverse. Land, spend `disembark_hours`
clearing the airport, and catch a train; miss the last one and it is another
bed. At 1.5 hours that is the latest landing each airport allows:

    HAM 20:30   FRA 18:30   PRG 17:30   MUC 17:30   AMS 17:30

BER is exempt at both ends. On the Sao Paulo run, 174 of 462 fares depart too
early to reach by train that morning, which is more than a third of the board.

When a night is forced, the home departure is derived from `hotel_arrive_by`
(22:00 by default) minus the journey, so a longer trip starts earlier rather
than every airport being pinned to one invented hour.

## Three kinds of bed

1. **Before the flight**, when the outbound is unreachable on the day.
   Priced per airport from `hotel_eur`.
2. **In transit**, when a layover is both a night layover and long enough to
   be worth leaving the airport for. `layover_hotel` carries `min_hours`
   (8 by default), a price per airport in `eur`, and a `default_eur` for
   everywhere else. 37 of the 462 rows carry one.
3. **After landing**, when the return lands too late for the last train home.

The train fares are the traveller's own numbers. The bed prices and the
eight-hour floor are not: they are estimates standing in until someone checks
them, which the board says in its caveats. Confirm them when setting up a run,
because a bed is large enough to reorder the board. Frankfurt at 879 EUR is
the cheapest fare on it and drops three places once its Lisbon night is
counted.

An airport with no price and no default contributes nothing, because an
unpriced bed is unknown, not free. A layover under the floor stays a hard night
in a terminal, which the night verdict already judges; pricing a hotel for a
four-hour wait would overstate every short night on the board.

## Never added to a fare, always added to a comparison

A fare plus anything else is not a fare, so the fare column never moves: every
number in it is one Google returned. The journey travels beside it as
`door_lo_eur` and `door_hi_eur`, and the beds inside that as `door_hotel_eur`.

That figure is what every comparison reads, and it changes the answer. Ranking
on fares alone put Amsterdam at 933 EUR ahead of Berlin at 939 on the first
Sao Paulo run, when Amsterdam carried 120 EUR of rail and fourteen hours of it
and Berlin carried none. The cheapest fare on the board is now Frankfurt at
879, and it is the third cheapest trip:

| Origin | Fare | Door to door, beds counted |
|---|---|---|
| BER | 939 | 939 |
| MUC | 882 | 1001 |
| FRA | 879 | 1023 |
| AMS | 933 | 1053 |
| HAM | 997 | 1071 |
| PRG | 952 | 1130 |

Real prices also moved the ranking against the old estimates. Frankfurt was
carried at 70 to 130 EUR each way when the ticket is 37, which is a different
airport entirely.

## The two worlds

The traveller may have a free bed, so the board is priced and judged twice:
once counting the forced nights (`hotels`) and once not (`no_hotels`). Both are
computed by `apply_night_economics` and stored under `trip["variants"]`, and
the page ships both and shows one, on a checkbox.

The switch moves the baseline as well as the totals. The night-layover bar is
measured against the cheapest clean trip, and counting beds can change which
trip that is, so a layover can be justified in one world and not in the other.
Both readings are true; that is why the board carries both rather than picking.
`assert_all_variants_sound` runs the baseline gate in every world before the
page renders.

Time never toggles. A forced night is a night spent whoever paid for the bed,
so `journey_min` and the door-to-door durations are computed once and shared.
