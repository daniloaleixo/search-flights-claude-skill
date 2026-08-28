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
