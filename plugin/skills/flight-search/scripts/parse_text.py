"""Parse a Google Flights results page from its visible text.

The aria-label sentences are richer, but they cannot be got off the page:
the JavaScript bridge truncates a returned value at about a thousand
characters, and the accessibility tree clips every label to a hundred. The
page's own text comes back whole, so that is what the run reads.

What the text gives up against the sentences is airport *names* (it carries
IATA codes instead) and the arrival weekday (it carries a +1 / +2 day
offset, which is the same fact counted rather than named). Everything the
board renders survives the trade.

One thing the text adds: "Self transfer" rows, where the two flights are
separate tickets and a missed connection is the passenger's problem. Those
are recorded and flagged rather than silently priced alongside through
fares.
"""

import re
from datetime import datetime, timedelta

from scripts.parse import ParseError, parse_duration_minutes

_TIME = re.compile(r"^(\d{1,2}:\d{2}\s*(?:AM|PM))(?:\+(\d))?$", re.I)
_ROUTE = re.compile(r"^([A-Z]{3})[–\-]([A-Z]{3})$")
_PRICE = re.compile(r"^€\s?([\d,]+)$")
_STOPS = re.compile(r"^(Nonstop|(\d+) stops?)$", re.I)
_DURATION = re.compile(r"^(\d+ hr(?: \d+ min)?|\d+ min)$")
_LAYOVER = re.compile(r"^(\d+ hr(?: \d+ min)?|\d+ min)\s+([A-Z]{3})$")
# Two-stop rows drop the durations and list the stops as bare codes:
# "CDG, FOR". The stop is still real, its length is simply not on the page.
_LAYOVER_CODES = re.compile(r"^([A-Z]{3})(?:,\s*([A-Z]{3}))+$")
_CO2 = re.compile(r"^\d+ kg CO2e$")
_OPERATED = re.compile(r"Operated by .*$")

_SKIP = re.compile(
    r"^(–|round trip|entire trip|Self transfer|View more flights|"
    r"Prices include|Sorted by|Departing flights|Search results|Best|Cheapest|"
    r"from €|No results|.*emissions|Avg emissions|Nonstop|\d+ kg CO2e)",
    re.I,
)


def split_rows(page_text):
    """Cut the page into one chunk of lines per result row.

    A row opens with a departure time on its own line followed by an en
    dash. Nothing else on the page has that shape, which is why the split
    keys off it rather than off a container element.
    """
    lines = [l.strip() for l in page_text.splitlines() if l.strip()]
    starts = [
        i for i in range(len(lines) - 1)
        if _TIME.match(lines[i]) and lines[i + 1] in ("–", "-")
    ]
    return [
        lines[s:starts[n + 1]] if n + 1 < len(starts) else lines[s:]
        for n, s in enumerate(starts)
    ]


def _clock(text):
    return datetime.strptime(text.replace(" ", ""), "%I:%M%p").strftime("%H:%M")


def parse_text_row(chunk, dep_date):
    """Turn one row's lines into a record. Raises rather than guessing."""
    times = [_TIME.match(l) for l in chunk[:4]]
    times = [m for m in times if m]
    if len(times) < 2:
        raise ParseError(f"no departure/arrival pair in: {chunk[:4]!r}")
    dep, arr = times[0], times[1]

    price = route = stops = duration = None
    layovers = []
    carriers = []
    seen_route = False
    for line in chunk:
        m = _PRICE.match(line)
        if m and price is None:
            price = int(m.group(1).replace(",", ""))
            continue
        m = _ROUTE.match(line)
        if m and route is None:
            route, seen_route = (m.group(1), m.group(2)), True
            continue
        m = _STOPS.match(line)
        if m and stops is None:
            stops = 0 if m.group(1).lower() == "nonstop" else int(m.group(2))
            continue
        m = _LAYOVER.match(line)
        if m:
            layovers.append({"minutes": parse_duration_minutes(m.group(1)),
                             "airport_name": m.group(2), "code": m.group(2)})
            continue
        if seen_route and _LAYOVER_CODES.match(line):
            for code in [c.strip() for c in line.split(",")]:
                layovers.append({"minutes": None, "airport_name": code,
                                 "code": code})
            continue
        m = _DURATION.match(line)
        if m and duration is None:
            duration = parse_duration_minutes(m.group(1))
            continue
        if (not seen_route and not _TIME.match(line)
                and not _SKIP.match(line) and not _CO2.match(line)):
            carriers.append(_OPERATED.sub("", line).strip())

    if price is None:
        raise ParseError(f"no price in: {' | '.join(chunk)[:120]!r}")
    if route is None:
        raise ParseError(f"no IATA route in: {' | '.join(chunk)[:120]!r}")
    if duration is None:
        raise ParseError(f"no total duration in: {' | '.join(chunk)[:120]!r}")
    if stops is None:
        raise ParseError(f"no stop count in: {' | '.join(chunk)[:120]!r}")

    carriers = [c for c in ", ".join(carriers).split(", ") if c]
    offset = int(arr.group(2) or 0)
    return {
        "price_eur": price,
        "stops": stops,
        "carriers": tuple(carriers),
        "total_duration_min": duration,
        "origin": route[0],
        "dest": route[1],
        "layovers": tuple(layovers),
        "self_transfer": any(l.lower() == "self transfer" for l in chunk),
        "raw_text": "\n".join(chunk),
        "dep_time": _clock(dep.group(1)),
        "arr_time": _clock(arr.group(1)),
        "dep_date": dep_date,
        "arr_date": (datetime.strptime(dep_date, "%Y-%m-%d").date()
                     + timedelta(days=offset)).isoformat(),
    }


def parse_page_text(page_text, dep_date, strict=True):
    """Parse every row on the page. In strict mode one bad row fails the page."""
    rows = []
    for chunk in split_rows(page_text):
        try:
            rows.append(parse_text_row(chunk, dep_date))
        except ParseError:
            if strict:
                raise
    return rows
