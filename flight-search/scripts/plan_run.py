"""Turn a trip parameter block into the list of searches a run must visit.

The browser work happens between this module and scripts/ingest.py: this
module says which URLs to open, ingest.py consumes what came back.
"""

from datetime import date, timedelta

from scripts.tfs import Leg, build_url, TRIP_MULTI_CITY


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
    return list(configured)


def stop_budget(params, origin):
    for o in params["origins"]:
        if o["code"] == origin:
            return o["max_stops"]
    raise KeyError(f"{origin} is not in params['origins']")


def date_pairs(params):
    return [(d, r) for d in _dates(params["dep_window"])
            for r in _dates(params["ret_window"])]


def _search(params, sid, dep, ret, origins, rets, max_stops):
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
        "url": build_url(
            legs, TRIP_MULTI_CITY,
            pax=params.get("pax", 1),
            max_stops=max_stops,
            curr=params.get("currency", "EUR"),
        ),
    }


def sweep_searches(params):
    """One multi-city search per date pair, all origins by all return airports.

    A search carries a single stop limit, so the sweep runs at the minimum
    budget across origins. Origins allowed more stops than that are picked up
    by backfill_searches, where they are searched alone.
    """
    origins = origin_codes(params)
    rets = return_airports(params)
    max_stops = min(stop_budget(params, o) for o in origins)
    return [
        _search(params, f"sweep-{dep}-{ret}", dep, ret, origins, rets, max_stops)
        for dep, ret in date_pairs(params)
    ]


def backfill_searches(params, missing_origins, best_pairs):
    """Per-origin searches for origins the sweep never returned.

    An origin missing from a capped result list is not evidence it is
    expensive, so each one gets its own search at its own stop budget before
    the run may say anything about it.
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
