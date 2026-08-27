# Getting to each airport from Berlin

This table is mirrored into `params.sao-paulo.json` as the top-level
`ground_notes` object, because `build_board.py` deliberately does not parse
Markdown. Editing the table below means updating that file too, or the two
will drift.

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
