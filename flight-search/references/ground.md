# Getting to each airport from Berlin

This table is mirrored into `params.sao-paulo.json` twice: as the prose
`ground_notes` object, which is what the board prints, and as the numeric
`ground_cost` object, which is what the arithmetic reads. `build_board.py`
deliberately does not parse Markdown, so editing the table below means
updating both, or the three will drift.

| Airport | From Berlin | Rough cost, one way | Note |
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

## Never added to a fare, always added to a comparison

A fare plus an estimate is not a price, so the fare column never moves: every
number in it is one Google returned. The estimate travels beside it instead, as
`door_lo_eur` and `door_hi_eur`, the fare plus the ground journey at both ends
at its cheapest and its dearest.

That band is what every comparison reads. Ranking on fares alone put Amsterdam
at 933 EUR ahead of Berlin at 939 on the first Sao Paulo run, when Amsterdam
carried 120 to 240 EUR of rail on top and thirteen hours of it, and Berlin
carried none. Door to door, Berlin was between 114 and 234 EUR cheaper than
Amsterdam's best case, and the board had recommended the other one.

An airport with no entry in `ground_cost` gets no band and no door-to-door
figure at all. A band with one end missing is not a band, and filling the gap
with a zero would quietly claim the journey is free.
