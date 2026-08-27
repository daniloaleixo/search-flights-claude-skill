"""Google Flights `tfs=` deep link builder.

The `tfs` query parameter is an undocumented base64url-encoded protobuf.
Field numbers below were confirmed against the live site on 2026-08-27 and
are pinned by golden tests in tests/test_tfs.py.

    Airport    { name = 2 (string, IATA), type = 3 (varint, always 1) }
    FlightData { date = 2 (string YYYY-MM-DD), max_stops = 5 (varint),
                 from = 13 (repeated Airport), to = 14 (repeated Airport) }
    Info       { data = 3 (repeated FlightData), max_stops = 5 (varint),
                 passengers = 8 (repeated varint), seat = 9 (varint),
                 trip = 19 (varint) }

No third-party protobuf library: the subset needed here is two wire types.
"""

import base64
from dataclasses import dataclass

TRIP_ROUND = 1
TRIP_ONE_WAY = 2
TRIP_MULTI_CITY = 3

SEAT_ECONOMY = 1
PASSENGER_ADULT = 1

# &tfu= value that lands on the "Cheapest" tab. Google's results page carries
# two tabs, and they are two different result sets, not two orderings of one
# set: on FRA-GRU 23 Dec / 12 Feb, 1 stop, the Best tab's cheapest row was
# 1159 EUR and the Cheapest tab's was 879 EUR — the same page, 24% apart. The
# earlier constant "EgYIAhAAGAA" only sorted the Best set by price, which is
# why every page it captured reported "Sorted by price" while still hiding the
# cheaper set. Captured from the live URL after clicking the tab, 2026-08-27.
CHEAPEST_TAB = "EgoIAhAAGAAgAigB"

BASE = "https://www.google.com/travel/flights"

WIRE_VARINT = 0
WIRE_LEN = 2


@dataclass(frozen=True)
class Leg:
    """One flight leg. `origins` and `dests` may each hold several airports."""

    date: str
    origins: tuple
    dests: tuple
    max_stops: int = None


def _varint(n):
    out = b""
    while True:
        chunk = n & 0x7F
        n >>= 7
        out += bytes([chunk | (0x80 if n else 0)])
        if not n:
            return out


def _tag(field_no, wire):
    return _varint((field_no << 3) | wire)


def _varint_field(field_no, value):
    return _tag(field_no, WIRE_VARINT) + _varint(value)


def _len_field(field_no, payload):
    return _tag(field_no, WIRE_LEN) + _varint(len(payload)) + payload


def _str_field(field_no, text):
    return _len_field(field_no, text.encode("utf-8"))


def _airport(code):
    return _str_field(2, code) + _varint_field(3, 1)


def _leg(leg):
    payload = _str_field(2, leg.date)
    for code in leg.origins:
        payload += _len_field(13, _airport(code))
    for code in leg.dests:
        payload += _len_field(14, _airport(code))
    if leg.max_stops is not None:
        payload += _varint_field(5, leg.max_stops)
    return payload


def encode_tfs(legs, trip, pax=1, seat=SEAT_ECONOMY, max_stops=None):
    payload = b""
    for leg in legs:
        payload += _len_field(3, _leg(leg))
    if max_stops is not None:
        payload += _varint_field(5, max_stops)
    for _ in range(pax):
        payload += _varint_field(8, PASSENGER_ADULT)
    payload += _varint_field(9, seat)
    payload += _varint_field(19, trip)
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def build_url(legs, trip, *, pax=1, seat=SEAT_ECONOMY, max_stops=None,
              cheapest_tab=True, hl="en", gl="de", curr="EUR"):
    parts = ["tfs=" + encode_tfs(legs, trip, pax, seat, max_stops)]
    if cheapest_tab:
        parts.append("tfu=" + CHEAPEST_TAB)
    parts += [f"hl={hl}", f"gl={gl}", f"curr={curr}"]
    return BASE + "?" + "&".join(parts)
