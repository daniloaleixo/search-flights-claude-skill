"""The journey either side of the flight: whether it fits in the day, and how long it takes.

A fare is bought at an airport, but the trip starts at a front door. For five
of the six origins here that gap is a train, and the train has two
consequences the fare cannot show.

The first is that an early flight may be unreachable. Leaving Berlin for a
07:00 departure from Amsterdam means being at Schiphol by 04:30, which means a
train at 21:30 the evening before, which means a hotel. The airport that
looked 60 EUR away is 60 EUR and a night away.

The second is duration. A 13-hour flight from Amsterdam is a 28-hour journey
from Berlin, and ranking on air time alone hides every hour of it.

Everything here is arithmetic on the params file's `ground` block and the
trip's own departure and arrival times. Nothing is inferred from a fare.
"""

from datetime import datetime, time, timedelta

#: Hours at the airport before a long-haul departure, and hours to clear the
#: airport on arrival with checked bags. Overridable per params file under
#: `ground_timing`.
DEFAULT_CHECK_IN_HOURS = 2.5
DEFAULT_DISEMBARK_HOURS = 1.5

#: When a flight is unreachable on the day, the traveller goes the evening
#: before and wants to be at the hotel by this time. The home departure is
#: then this, minus the journey, which makes a long journey start earlier
#: instead of pinning every airport to one invented hour.
DEFAULT_HOTEL_ARRIVE_BY = "22:00"


def _time(value):
    return time.fromisoformat(value) if isinstance(value, str) else value


def _delta(hours):
    return timedelta(hours=float(hours))


def ground_spec(params):
    """Per-airport ground journey: cost, duration, hotel, and train times.

    Read from the `ground` block, which mirrors the table in
    references/ground.md. An airport marked `home` has no train attached and
    is never unreachable; every other airport must declare the four fields
    the feasibility test needs, because a missing `last_train` silently
    turns "we never checked" into "you can always get home".
    """
    out = {}
    for code, entry in (params.get("ground") or {}).items():
        home = bool(entry.get("home"))
        spec = {
            "eur": entry["eur"],
            "hours": float(entry["hours"]),
            "home": home,
            "hotel_eur": entry.get("hotel_eur", 0),
            "first_train": _time(entry.get("first_train") or "00:00"),
            "last_train": _time(entry.get("last_train") or "23:59"),
        }
        if not home:
            for field in ("hotel_eur", "first_train", "last_train"):
                if entry.get(field) is None:
                    raise ValueError(
                        f"ground[{code!r}] has no {field}: an airport with a "
                        f"train attached needs one, or the feasibility test "
                        f"reads an unchecked airport as always reachable")
        out[code] = spec
    return out


def timing(params):
    block = params.get("ground_timing") or {}
    return {
        "check_in": _delta(block.get("check_in_hours", DEFAULT_CHECK_IN_HOURS)),
        "disembark": _delta(
            block.get("disembark_hours", DEFAULT_DISEMBARK_HOURS)),
        "hotel_arrive_by": _time(
            block.get("hotel_arrive_by", DEFAULT_HOTEL_ARRIVE_BY)),
    }


def _stamp(date_iso, clock):
    if not date_iso or not clock:
        return None
    return datetime.combine(
        datetime.fromisoformat(date_iso).date(), _time(clock))


def outbound_plan(trip, spec, clocks):
    """When the traveller leaves home, and whether a night goes with it.

    Returns None when the arithmetic cannot be done: an origin with no
    `ground` entry, or a row whose departure was never captured. None means
    unknown, and unknown is never rendered as reachable.
    """
    entry = spec.get(trip.get("origin"))
    depart = _stamp(trip.get("dep_date"), trip.get("dep_time"))
    if entry is None or depart is None:
        return None

    at_terminal = depart - clocks["check_in"]
    leave_home = at_terminal - _delta(entry["hours"])
    first_train = datetime.combine(depart.date(), entry["first_train"])
    overnight = not entry["home"] and leave_home < first_train

    if overnight:
        arrive_by = datetime.combine(
            depart.date() - timedelta(days=1), clocks["hotel_arrive_by"])
        leave_home = arrive_by - _delta(entry["hours"])

    plan = {
        "overnight": overnight,
        "home_dep": leave_home.isoformat(),
        "hotel_eur": entry["hotel_eur"] if overnight else 0,
        "door_min": None,
    }
    flight = trip.get("total_duration_min")
    if flight is not None:
        ground = int((depart - leave_home).total_seconds() // 60)
        plan["door_min"] = ground + flight
    return plan


def return_plan(trip, spec, clocks):
    """When the traveller gets home, and whether a night goes with that.

    Returns None whenever the return arrival was never captured, which is
    the usual case: a search result row describes the outbound only. The
    return end of a trip is unknown until someone opens it, and this says so
    rather than assuming the last train was waiting.
    """
    entry = spec.get(trip.get("ret_airport") or trip.get("origin"))
    landing = _stamp(trip.get("ret_arr_date"), trip.get("ret_arr_time"))
    if entry is None or landing is None:
        return None

    ready = landing + clocks["disembark"]
    last_train = datetime.combine(ready.date(), entry["last_train"])
    overnight = not entry["home"] and ready > last_train

    if overnight:
        home_arr = (datetime.combine(ready.date() + timedelta(days=1),
                                     entry["first_train"])
                    + _delta(entry["hours"]))
    else:
        home_arr = ready + _delta(entry["hours"])

    plan = {
        "overnight": overnight,
        "home_arr": home_arr.isoformat(),
        "hotel_eur": entry["hotel_eur"] if overnight else 0,
        "door_min": None,
    }
    flight = trip.get("ret_duration_min")
    if flight is not None:
        ground = int((home_arr - landing).total_seconds() // 60)
        plan["door_min"] = ground + flight
    return plan


#: A layover shorter than this is spent in the terminal. Leaving the
#: airport, finding a bed and coming back is not worth it below it, and
#: pricing a hotel for a four-hour wait would overstate every short night.
DEFAULT_LAYOVER_MIN_HOURS = 8


def layover_beds(trip, params):
    """Nights a layover forces on you, and what a bed costs at each.

    Only layovers already flagged as night layovers count, and only those
    long enough to be worth leaving the airport for. An airport with no
    price and no default contributes nothing rather than a guess: an
    unpriced bed is unknown, not free.

    A trip nobody expanded has no layover windows and so gets no beds,
    which is correct. Its night status is unknown too.
    """
    block = params.get("layover_hotel") or {}
    prices = block.get("eur") or {}
    default = block.get("default_eur")
    floor = block.get("min_hours", DEFAULT_LAYOVER_MIN_HOURS) * 60
    out = []
    for window in trip.get("layover_windows") or ():
        if not window.get("night_flag"):
            continue
        minutes = window.get("minutes") or 0
        if minutes < floor:
            continue
        price = prices.get(window.get("code"), default)
        if price is None:
            continue
        out.append({"code": window.get("code"), "eur": price,
                    "minutes": minutes})
    return out


def hotel_cost(trip):
    """What the forced nights cost: both ends, plus any night in transit.

    An unchecked end contributes nothing rather than a guess. It is disclosed
    separately, on the board, as an end nobody looked at.
    """
    return ((trip.get("out_hotel_eur") or 0)
            + (trip.get("ret_hotel_eur") or 0)
            + (trip.get("lay_hotel_eur") or 0))


def apply_journey(trips, params):
    """Attach both ends of the ground journey to every trip."""
    spec = ground_spec(params)
    clocks = timing(params)
    for trip in trips:
        out = outbound_plan(trip, spec, clocks)
        back = return_plan(trip, spec, clocks)
        trip["out_overnight"] = None if out is None else out["overnight"]
        trip["out_home_dep"] = None if out is None else out["home_dep"]
        trip["out_door_min"] = None if out is None else out["door_min"]
        trip["out_hotel_eur"] = None if out is None else out["hotel_eur"]
        trip["ret_overnight"] = None if back is None else back["overnight"]
        trip["ret_home_arr"] = None if back is None else back["home_arr"]
        trip["ret_door_min"] = None if back is None else back["door_min"]
        trip["ret_hotel_eur"] = None if back is None else back["hotel_eur"]
        beds = layover_beds(trip, params)
        trip["lay_beds"] = beds
        trip["lay_hotel_eur"] = sum(b["eur"] for b in beds)
        legs = (trip["out_door_min"], trip["ret_door_min"])
        trip["journey_min"] = (None if None in legs else sum(legs))
    return trips
