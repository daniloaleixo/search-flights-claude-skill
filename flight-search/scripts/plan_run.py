"""Turn a trip parameter block into the list of searches a run must visit.

The browser work happens between this module and scripts/ingest.py: this
module says which URLs to open, ingest.py consumes what came back.
"""

from datetime import date, timedelta

from scripts.tfs import Leg, build_url, TRIP_MULTI_CITY, TRIP_ROUND, SEAT_ECONOMY

#: cabin -> tfs seat code. `ticket` and `night_discount.mode` are read
#: nowhere: they stay declarative, documented in SKILL.md, and are not
#: wired to anything here.
CABIN_SEATS = {"economy": SEAT_ECONOMY}


def _seat(params):
    cabin = params.get("cabin", "economy")
    try:
        return CABIN_SEATS[cabin]
    except KeyError:
        raise ValueError(f"unrecognised cabin: {cabin!r}")


def _dates(window):
    start = date.fromisoformat(window[0])
    end = date.fromisoformat(window[1])
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def origin_codes(params):
    return [o["code"] for o in params["origins"]]


def return_airports(params):
    configured = params.get("return_airports", "same_as_origins")
    if configured == "same_as_origins":
        return origin_codes(params)
    if isinstance(configured, str):
        return [configured]
    return list(configured)


def stop_budget(params, origin):
    for o in params["origins"]:
        if o["code"] == origin:
            return o["max_stops"]
    raise KeyError(f"{origin} is not in params['origins']")


def date_pairs(params):
    return [(d, r) for d in _dates(params["dep_window"])
            for r in _dates(params["ret_window"])]


def _search(params, sid, dep, ret, origins, rets, max_stops, trip=TRIP_MULTI_CITY):
    legs = [
        Leg(dep, tuple(origins), (params["dest"],), max_stops=max_stops),
        Leg(ret, (params["dest"],), tuple(rets), max_stops=max_stops),
    ]
    return {
        "id": sid,
        "dep_date": dep,
        "ret_date": ret,
        "origins": list(origins),
        "ret_airports": list(rets),
        "max_stops": max_stops,
        "trip_type": "round_trip" if trip == TRIP_ROUND else "multi_city",
        "url": build_url(
            legs, trip,
            pax=params.get("pax", 1),
            seat=_seat(params),
            max_stops=max_stops,
            curr=params.get("currency", "EUR"),
        ),
    }


def sweep_searches(params):
    """One search per date pair, covering every origin.

    Open jaw (the default): a multi-city search per date pair, all origins
    by all return airports. A search carries a single stop limit, so the
    sweep runs at the minimum budget across origins. Origins allowed more
    stops than that are picked up by backfill_searches, where they are
    searched alone.

    `open_jaw: false`: a round trip carrying several origins returns each
    outbound paired with a return to that same origin, so no separate
    return-airport dimension is needed at all. One round-trip search per
    date pair replaces the multi-city sweep, and `ret_airports` on each
    search equals the origin list rather than the configured return list.
    """
    origins = origin_codes(params)
    max_stops = min(stop_budget(params, o) for o in origins)
    if params.get("open_jaw", True) is False:
        return [
            _search(params, f"sweep-{dep}-{ret}", dep, ret, origins, origins,
                    max_stops, trip=TRIP_ROUND)
            for dep, ret in date_pairs(params)
        ]
    rets = return_airports(params)
    return [
        _search(params, f"sweep-{dep}-{ret}", dep, ret, origins, rets, max_stops)
        for dep, ret in date_pairs(params)
    ]


def origins_needing_backfill(params, rows):
    """Origins that still need their own search after the sweep.

    Two separate reasons put an origin here, and either one is enough:
    it never showed up in `rows` at all (crowded out of a capped result
    list, which is not evidence it is expensive), or it showed up but its
    own stop budget is wider than the sweep's shared limit, so the sweep
    structurally could not have searched it at the stops it is allowed.
    Checking `rows` alone catches the first case but silently drops the
    second: an origin can appear in every capture and still never have had
    its extra stop searched.
    """
    origins = origin_codes(params)
    sweep_limit = min(stop_budget(params, o) for o in origins)
    seen = {r["origin"] for r in rows}
    return [o for o in origins
            if o not in seen or stop_budget(params, o) > sweep_limit]


def backfill_searches(params, missing_origins, best_pairs):
    """Per-origin searches for origins the sweep could not settle.

    `missing_origins` (typically from origins_needing_backfill) mixes two
    distinct reasons, either one sufficient on its own: an origin the
    sweep's capped result list never returned at all, which is not evidence
    it is expensive; or an origin the sweep did return but only at the
    sweep's shared stop limit, because its own budget allows more stops
    than a single sweep search can carry. Either way it gets its own search
    at its own stop budget before the run may say anything about it.
    """
    out = []
    rets = return_airports(params)
    for origin in missing_origins:
        budget = stop_budget(params, origin)
        for dep, ret in best_pairs:
            out.append(_search(
                params, f"backfill-{origin}-{dep}-{ret}",
                dep, ret, [origin], rets, budget,
            ))
    return out
